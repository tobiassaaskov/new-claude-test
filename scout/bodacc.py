"""Official French business notices (BODACC): hotel companies in insolvency proceedings or selling their business.

Uses DILA's free open-data API (no key). These are signals for the team to follow up, not listings."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from typing import Any, Callable

from .store import is_http_url

API_URL = "https://bodacc-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/annonces-commerciales/records"
FAMILIES = {"Procédures collectives": "insolvency", "Ventes et cessions": "sale"}
# "hôtel", "hotel", "hôtellerie"... but not "hôtel de ville" (town hall) in an address or name.
HOTEL_PATTERN = re.compile(r"\bh[oô]tel(?!\s+de\s+ville)\w*", re.IGNORECASE)
PAGE_SIZE = 100
MAX_ROWS = 1000
TIMEOUT_SECONDS = 30

Fetch = Callable[[str], dict[str, Any]]


class QueryRejected(Exception):
    """The API rejected the query syntax (HTTP 400)."""


def _http_get_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "HotelDealScout/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        if error.code == 400:
            raise QueryRejected(error.read().decode("utf-8", "replace")[:300]) from error
        raise


def _where(since: date, full_text: bool) -> str:
    families = " OR ".join(f'familleavis_lib = "{label}"' for label in FAMILIES)
    clause = f"dateparution >= date'{since.isoformat()}' AND ({families})"
    # A bare string literal is an Opendatasoft full-text search across the record.
    return f'{clause} AND "hotel"' if full_text else clause


def _query(fetch: Fetch, where: str, max_rows: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for offset in range(0, max_rows, PAGE_SIZE):
        params = {"where": where, "order_by": "dateparution desc", "limit": PAGE_SIZE, "offset": offset}
        page = fetch(f"{API_URL}?{urllib.parse.urlencode(params)}")
        results = page.get("results") or []
        rows.extend(results)
        if len(results) < PAGE_SIZE:
            break
    return rows


def _parse_json_field(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _values_for(obj: Any, key_part: str) -> list[str]:
    """All string values under keys containing key_part, anywhere in a nested structure."""
    found: list[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key_part in key.lower() and isinstance(value, str):
                found.append(value)
            else:
                found.extend(_values_for(value, key_part))
    elif isinstance(obj, list):
        for item in obj:
            found.extend(_values_for(item, key_part))
    return found


def to_signal(record: dict[str, Any]) -> dict[str, Any] | None:
    """Convert one BODACC record into a dashboard signal, or None if it isn't about a hotel business."""
    family = record.get("familleavis_lib") or ""
    activities = _values_for(_parse_json_field(record.get("listeetablissements")), "activite")
    company = str(record.get("commercant") or "")
    if not (any(HOTEL_PATTERN.search(a) for a in activities) or HOTEL_PATTERN.search(company)):
        return None
    record_id = record.get("id") or "-".join(
        str(record.get(k) or "") for k in ("publicationavis", "parution", "numeroannonce")
    ).strip("-")
    if not record_id:
        return None
    judgment = _parse_json_field(record.get("jugement"))
    natures = _values_for(judgment, "nature") if isinstance(judgment, (dict, list)) else []
    url = record.get("url_complete")
    return {
        "id": str(record_id),
        "date": record.get("dateparution"),
        "kind": FAMILIES.get(family, "other"),
        "family": family,
        "notice": record.get("typeavis_lib") or "",
        "company": company[:120],
        "town": str(record.get("ville") or "")[:80],
        "postcode": str(record.get("cp") or ""),
        "departement": str(record.get("departement_nom_officiel") or record.get("numerodepartement") or ""),
        "activity": "; ".join(dict.fromkeys(a.strip() for a in activities if a.strip()))[:300],
        "judgment": "; ".join(natures)[:300],
        "url": url if isinstance(url, str) and is_http_url(url) else None,
    }


def fetch_signals(today: date, days_back: int, fetch: Fetch = _http_get_json) -> tuple[list[dict[str, Any]], str]:
    """Returns hotel-related notices from the last days_back days and a note on how they were found."""
    since = today - timedelta(days=days_back)
    try:
        rows = _query(fetch, _where(since, full_text=True), max_rows=MAX_ROWS)
        note = "full-text query"
    except QueryRejected:
        # Fall back to filtering locally if the API doesn't accept the full-text clause.
        rows = _query(fetch, _where(since, full_text=False), max_rows=MAX_ROWS)
        note = f"date and category query, filtered locally ({len(rows)} notices scanned)"
    signals = [s for s in (to_signal(r) for r in rows) if s]
    unique = list({s["id"]: s for s in signals}.values())
    return unique, note

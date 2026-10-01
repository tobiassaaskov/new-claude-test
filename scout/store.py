"""Reads and writes the JSON files in data/ that the dashboard displays."""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit

TRACKING_PARAM = re.compile(r"^(utm_.*|fbclid|gclid|mc_cid|mc_eid|xtor)$", re.IGNORECASE)
ID_PATTERN = re.compile(r"^HDS-(\d+)$")

STRONG_MATCH_SCORE = 80
POSSIBLE_SCORE = 50
KEEP_RUNS = 90
KEEP_SIGNAL_DAYS = 90


def dedupe_key(url: str) -> str:
    """Host, path and meaningful query of a URL, so that tracking parameters,
    'www.', the scheme and a trailing slash don't create duplicates."""
    parts = urlsplit(url.strip())
    host = parts.netloc.lower().removeprefix("www.")
    path = parts.path.rstrip("/") or "/"
    query = urlencode(
        sorted((k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not TRACKING_PARAM.match(k))
    )
    return f"{host}{path}" + (f"?{query}" if query else "")


def is_http_url(url: str) -> bool:
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(parts.netloc)


def verdict_for(score: int | None, asking_price_eur: float | None, budget_eur: int) -> str:
    if score is None:
        return "unassessed"
    if asking_price_eur is not None and asking_price_eur > budget_eur:
        return "over_budget"
    if score >= STRONG_MATCH_SCORE:
        return "strong_match"
    if score >= POSSIBLE_SCORE:
        return "possible"
    return "no_match"


def _load(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _save(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class Store:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.opportunities_file = _load(data_dir / "opportunities.json", {"opportunities": []})
        self.signals_file = _load(data_dir / "signals.json", {"signals": []})
        self.runs_file = _load(data_dir / "runs.json", {"runs": []})

    # --- opportunities -------------------------------------------------

    @property
    def opportunities(self) -> list[dict[str, Any]]:
        return self.opportunities_file["opportunities"]

    def find(self, url: str) -> dict[str, Any] | None:
        key = dedupe_key(url)
        return next((o for o in self.opportunities if o["key"] == key), None)

    def known_urls(self, limit: int = 150) -> list[str]:
        """Most recently seen URLs first, so the explorer can skip what we already have."""
        recent = sorted(self.opportunities, key=lambda o: o["last_seen"], reverse=True)
        return [o["url"] for o in recent[:limit]]

    def _next_id(self) -> str:
        numbers = [int(m.group(1)) for o in self.opportunities if (m := ID_PATTERN.match(o["id"]))]
        return f"HDS-{max(numbers, default=0) + 1:04d}"

    def add_candidate(self, candidate: dict[str, Any], today: date, found_via: str) -> tuple[dict[str, Any], bool]:
        """Insert a newly found listing, or mark an existing one as seen again.
        Returns the opportunity and whether it is new."""
        existing = self.find(candidate["url"])
        if existing:
            if existing["last_seen"] != today.isoformat():
                existing["times_seen"] += 1
            existing["last_seen"] = today.isoformat()
            return existing, False
        opportunity = {
            "id": self._next_id(),
            "url": candidate["url"],
            "key": dedupe_key(candidate["url"]),
            "title": candidate.get("title") or candidate["url"],
            "source": candidate.get("source") or urlsplit(candidate["url"]).netloc.removeprefix("www."),
            "location": candidate.get("location") or "",
            "asking_price_text": candidate.get("asking_price_text") or "",
            "why_found": candidate.get("why") or "",
            "found_via": found_via,
            "first_seen": today.isoformat(),
            "last_seen": today.isoformat(),
            "times_seen": 1,
            "assessment": None,
            "verdict": "unassessed",
            "score": None,
            "price_per_key_eur": None,
            "team": None,
        }
        self.opportunities.append(opportunity)
        return opportunity, True

    def apply_assessment(self, opportunity: dict[str, Any], assessment: dict[str, Any], budget_eur: int) -> None:
        opportunity["assessment"] = assessment
        opportunity["score"] = assessment["score"]
        price, keys = assessment.get("asking_price_eur"), assessment.get("keys")
        opportunity["price_per_key_eur"] = round(price / keys) if price and keys else None
        opportunity["verdict"] = verdict_for(assessment["score"], price, budget_eur)
        if assessment.get("title_en"):
            opportunity["title"] = assessment["title_en"]

    def apply_team_status(self, statuses: dict[str, dict[str, Any]]) -> None:
        for opportunity in self.opportunities:
            opportunity["team"] = statuses.get(opportunity["id"])

    # --- signals -------------------------------------------------------

    @property
    def signals(self) -> list[dict[str, Any]]:
        return self.signals_file["signals"]

    def add_signals(self, signals: list[dict[str, Any]], today: date) -> int:
        """Add BODACC notices not seen before and drop old ones. Returns how many were new."""
        known = {s["id"] for s in self.signals}
        new = [dict(s, first_seen=today.isoformat()) for s in signals if s["id"] not in known]
        cutoff = (today - timedelta(days=KEEP_SIGNAL_DAYS)).isoformat()
        kept = [s for s in self.signals + new if (s.get("date") or s["first_seen"]) >= cutoff]
        self.signals_file["signals"] = sorted(kept, key=lambda s: s.get("date") or "", reverse=True)
        return len(new)

    # --- runs and saving -------------------------------------------------

    def add_run(self, run: dict[str, Any]) -> None:
        self.runs_file["runs"] = ([run] + self.runs_file["runs"])[:KEEP_RUNS]

    def save(self, *, updated_at: str, repository: str | None, budget_eur: int, brief_version: str) -> None:
        self.opportunities_file.update(
            updated_at=updated_at, repository=repository, budget_eur=budget_eur, brief_version=brief_version
        )
        self.opportunities_file["opportunities"] = sorted(
            self.opportunities, key=lambda o: (o["score"] is not None, o["score"] or 0, o["first_seen"]), reverse=True
        )
        self.signals_file["updated_at"] = updated_at
        _save(self.data_dir / "opportunities.json", self.opportunities_file)
        _save(self.data_dir / "signals.json", self.signals_file)
        _save(self.data_dir / "runs.json", self.runs_file)

"""Team status from GitHub issues.

Each opportunity has an ID such as HDS-0007. The team discusses it in an issue whose title contains
"[HDS-0007]", and sets its status with a label such as "status: shortlist". Only people with triage
access can add labels, so random visitors can comment but can't change a status."""

from __future__ import annotations

import json
import re
import urllib.request
from typing import Any, Callable

ID_IN_TITLE = re.compile(r"\[(HDS-\d{4,})\]")
MAX_PAGES = 10

Fetch = Callable[[str], list[dict[str, Any]]]


def _github_get(token: str) -> Fetch:
    def fetch(url: str) -> list[dict[str, Any]]:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "HotelDealScout/1.0",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))

    return fetch


def status_from_labels(labels: list[dict[str, Any]]) -> str | None:
    for label in labels:
        name = str(label.get("name") or "").strip()
        if name.lower().startswith("status:"):
            return name.split(":", 1)[1].strip().lower() or None
    return None


def team_statuses(issues: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Map opportunity IDs to their team status, discussion link and comment count."""
    statuses: dict[str, dict[str, Any]] = {}
    for issue in sorted(issues, key=lambda i: i.get("updated_at") or ""):
        if "pull_request" in issue:
            continue
        for opportunity_id in ID_IN_TITLE.findall(issue.get("title") or ""):
            status = status_from_labels(issue.get("labels") or [])
            if status is None and issue.get("state") == "closed":
                status = "closed"
            statuses[opportunity_id] = {
                "status": status or "discussing",
                "issue_url": issue.get("html_url"),
                "comments": int(issue.get("comments") or 0),
            }
    return statuses


def fetch_team_statuses(repository: str, token: str, fetch: Fetch | None = None) -> dict[str, dict[str, Any]]:
    fetch = fetch or _github_get(token)
    issues: list[dict[str, Any]] = []
    for page in range(1, MAX_PAGES + 1):
        batch = fetch(f"https://api.github.com/repos/{repository}/issues?state=all&per_page=100&page={page}")
        issues.extend(batch)
        if len(batch) < 100:
            break
    return team_statuses(issues)

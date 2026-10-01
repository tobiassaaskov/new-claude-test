"""Loads config/settings.toml and config/brief.md."""

from __future__ import annotations

import hashlib
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    country: str
    budget_eur: int
    max_web_searches: int
    max_web_fetches: int
    max_candidates: int
    max_new_assessments: int
    max_reassessments: int
    blocked_fetch_domains: tuple[str, ...]
    focus_regions: tuple[str, ...]
    model: str
    effort: str
    bodacc_enabled: bool
    bodacc_days_back: int
    brief: str
    data_dir: Path

    @property
    def brief_version(self) -> str:
        """Short fingerprint of the brief, stored with every assessment."""
        return hashlib.sha256(self.brief.encode("utf-8")).hexdigest()[:8]


def load_settings(root: Path = ROOT) -> Settings:
    raw = tomllib.loads((root / "config" / "settings.toml").read_text(encoding="utf-8"))
    search, model, bodacc = raw["search"], raw["model"], raw.get("bodacc", {})
    return Settings(
        country=search["country"],
        budget_eur=int(search["budget_eur"]),
        max_web_searches=int(search["max_web_searches"]),
        max_web_fetches=int(search["max_web_fetches"]),
        max_candidates=int(search["max_candidates"]),
        max_new_assessments=int(search["max_new_assessments"]),
        max_reassessments=int(search["max_reassessments"]),
        blocked_fetch_domains=tuple(search.get("blocked_fetch_domains", [])),
        focus_regions=tuple(search.get("focus_regions", [])),
        model=model["name"],
        effort=model.get("effort", "medium"),
        bodacc_enabled=bool(bodacc.get("enabled", False)),
        bodacc_days_back=int(bodacc.get("days_back", 4)),
        brief=(root / "config" / "brief.md").read_text(encoding="utf-8"),
        data_dir=root / "data",
    )

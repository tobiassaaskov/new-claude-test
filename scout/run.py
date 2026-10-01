"""One daily run: search, assess, collect signals, sync team statuses, save."""

from __future__ import annotations

import argparse
import os
from datetime import date, datetime, timezone
from typing import Any

import anthropic

from . import assessor, bodacc, explorer, issues, llm
from .settings import Settings, load_settings
from .store import Store

# Errors that will repeat on every call, so there's no point continuing with Claude in this run.
FATAL_API_ERRORS = (
    anthropic.AuthenticationError,
    anthropic.PermissionDeniedError,
    anthropic.NotFoundError,
    anthropic.BadRequestError,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _warn(message: str) -> None:
    # Shown as an annotation on the GitHub Actions run.
    print(f"::warning::{message}", flush=True)


def _describe(error: Exception) -> str:
    return f"{type(error).__name__}: {str(error)[:300]}"


def _assessment_queue(store: Store, settings: Settings, new: list[dict[str, Any]], reassess: bool) -> list[dict[str, Any]]:
    pending = [o for o in store.opportunities if o["assessment"] is None and o not in new]
    queue = (new + pending)[: settings.max_new_assessments]
    if reassess:
        outdated = [
            o for o in store.opportunities
            if o["assessment"] is not None and o["assessment"].get("brief_version") != settings.brief_version
        ]
        queue += outdated[: settings.max_reassessments]
    return queue


def _run_claude(store: Store, settings: Settings, today: date, reassess: bool, log: dict[str, Any]) -> bool:
    """Explorer and assessor. Returns False if a fatal API error means the run should be marked failed."""
    client = llm.make_client()
    usage = llm.Usage()
    new: list[dict[str, Any]] = []
    ok = True
    try:
        result = explorer.explore(client, settings, store.known_urls(), today, usage)
        log["candidates_found"] = len(result.candidates)
        log["explorer_notes"] = result.notes
        for candidate in result.candidates:
            opportunity, is_new = store.add_candidate(candidate, today, found_via="explorer")
            if is_new:
                new.append(opportunity)
    except FATAL_API_ERRORS as error:
        log["errors"].append(f"Explorer: {_describe(error)}")
        log["usage"] = usage.as_dict()
        return False
    except (anthropic.APIError, RuntimeError) as error:
        log["errors"].append(f"Explorer: {_describe(error)}")
    log["new_opportunities"] = [o["id"] for o in new]

    assessed = 0
    for opportunity in _assessment_queue(store, settings, new, reassess):
        try:
            assessment = assessor.assess(client, settings, opportunity, usage)
        except FATAL_API_ERRORS as error:
            log["errors"].append(f"Assessing {opportunity['id']}: {_describe(error)}")
            ok = False
            break
        except (anthropic.APIError, RuntimeError) as error:
            log["errors"].append(f"Assessing {opportunity['id']}: {_describe(error)}")
            continue
        if assessment is None:
            log["errors"].append(f"Assessing {opportunity['id']}: Claude did not return an assessment")
            continue
        store.apply_assessment(opportunity, assessment, settings.budget_eur)
        assessed += 1
    log["assessed"] = assessed
    log["usage"] = usage.as_dict()
    return ok


def _write_step_summary(store: Store, log: dict[str, Any]) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    strong = [o for o in store.opportunities if o["verdict"] == "strong_match"]
    lines = [
        "## Hotel Deal Scout",
        "",
        f"- New listings found: {len(log.get('new_opportunities', []))}",
        f"- Listings assessed: {log.get('assessed', 0)}",
        f"- Strong matches in total: {len(strong)}",
        f"- New BODACC signals: {log.get('signals_new', 0)}",
        f"- Estimated Claude cost: ${log.get('usage', {}).get('estimated_cost_usd', 0):.2f}",
    ]
    if log["errors"]:
        lines += ["", "### Problems", ""] + [f"- {e}" for e in log["errors"]]
    with open(path, "a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scout", description="Daily hotel deal scout.")
    parser.add_argument("--reassess", action="store_true", help="Re-assess listings scored with an older brief.")
    parser.add_argument("--skip-claude", action="store_true", help="Don't call Claude (signals and statuses only).")
    parser.add_argument("--skip-bodacc", action="store_true", help="Don't fetch BODACC notices.")
    args = parser.parse_args(argv)

    settings = load_settings()
    today = datetime.now(timezone.utc).date()
    store = Store(settings.data_dir)
    log: dict[str, Any] = {"started_at": _now(), "brief_version": settings.brief_version, "errors": []}
    ok = True

    if args.skip_claude:
        pass
    elif not os.environ.get("ANTHROPIC_API_KEY"):
        log["errors"].append(
            "ANTHROPIC_API_KEY is not set, so Claude did not search. Add it under Settings > Secrets and variables > Actions."
        )
    else:
        ok = _run_claude(store, settings, today, args.reassess, log)

    if settings.bodacc_enabled and not args.skip_bodacc:
        try:
            signals, note = bodacc.fetch_signals(today, settings.bodacc_days_back)
            log["signals_new"] = store.add_signals(signals, today)
            log["bodacc_note"] = note
        except Exception as error:  # an outage at DILA shouldn't stop the run
            log["errors"].append(f"BODACC: {_describe(error)}")

    repository, token = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_TOKEN")
    if repository and token:
        try:
            store.apply_team_status(issues.fetch_team_statuses(repository, token))
        except Exception as error:
            log["errors"].append(f"GitHub issues: {_describe(error)}")

    log["finished_at"] = _now()
    store.add_run(log)
    store.save(
        updated_at=log["finished_at"],
        repository=repository,
        budget_eur=settings.budget_eur,
        brief_version=settings.brief_version,
    )
    _write_step_summary(store, log)
    for error in log["errors"]:
        _warn(error)
    print(
        f"Done: {len(log.get('new_opportunities', []))} new, {log.get('assessed', 0)} assessed, "
        f"{log.get('signals_new', 0)} new signals, ~${log.get('usage', {}).get('estimated_cost_usd', 0):.2f}."
    )
    return 0 if ok else 1

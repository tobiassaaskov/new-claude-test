import json

import anthropic
import httpx2
import pytest
from fakes import FakeClient, message, tool_call, usage

from scout import run
from scout.settings import load_settings

CANDIDATES = {
    "candidates": [
        {
            "url": f"https://broker.example/hotel-{n}",
            "title": f"Hotel {n}",
            "source": "Example Brokers",
            "location": "Lyon",
            "asking_price_text": price,
            "why": "Fits the brief.",
        }
        for n, price in ((1, "9 000 000 €"), (2, "32 000 000 €"))
    ],
    "notes": "",
}


def assessment(score, price):
    return {
        "title_en": "Hotel", "listing_status": "for_sale", "page_was_read": True, "in_france": True,
        "asset_type": "hotel", "deal_type": "walls_and_business", "commune": "Lyon", "departement": "Rhône",
        "region": "Auvergne-Rhône-Alpes", "keys": 60, "stars": 3, "asking_price_eur": price,
        "price_on_request": False, "revenue_eur": None, "ebitda_eur": None, "figures_year": None, "broker": None,
        "summary_en": "A hotel.", "score": score, "reasons": [], "red_flags": [], "missing_information": [],
        "questions_for_broker": [], "evidence_quotes": [],
    }


def scripted_claude(params):
    tool_names = {tool["name"] for tool in params["tools"]}
    if "submit_candidates" in tool_names:
        return message(tool_call("submit_candidates", CANDIDATES), usage_obj=usage(searches=12))
    if "hotel-1" in params["messages"][0]["content"]:
        return message(tool_call("submit_assessment", assessment(84, 9_000_000)))
    return message(tool_call("submit_assessment", assessment(90, 32_000_000)))


@pytest.fixture
def isolated(project, monkeypatch):
    monkeypatch.setattr(run, "load_settings", lambda: load_settings(project))
    monkeypatch.setattr(run.bodacc, "fetch_signals", lambda today, days: ([{"id": "S1", "date": "2026-09-30", "kind": "sale"}], "test"))
    for name in ("GITHUB_REPOSITORY", "GITHUB_TOKEN", "GITHUB_STEP_SUMMARY"):
        monkeypatch.delenv(name, raising=False)
    return project


def read(project, name):
    return json.loads((project / "data" / f"{name}.json").read_text(encoding="utf-8"))


def test_full_run_finds_assesses_and_saves(isolated, monkeypatch):
    client = FakeClient(scripted_claude)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(run.llm, "make_client", lambda: client)

    assert run.main([]) == 0

    opportunities = {o["url"]: o for o in read(isolated, "opportunities")["opportunities"]}
    assert opportunities["https://broker.example/hotel-1"]["verdict"] == "strong_match"
    assert opportunities["https://broker.example/hotel-2"]["verdict"] == "over_budget"
    assert read(isolated, "signals")["signals"][0]["id"] == "S1"
    last_run = read(isolated, "runs")["runs"][0]
    assert last_run["assessed"] == 2 and last_run["errors"] == []
    assert last_run["usage"]["web_searches"] == 12

    # A second run sees the same listings again: nothing new to assess.
    assert run.main([]) == 0
    assert read(isolated, "runs")["runs"][0]["assessed"] == 0
    assert len(read(isolated, "opportunities")["opportunities"]) == 2


def test_missing_api_key_still_saves_signals(isolated, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert run.main([]) == 0
    last_run = read(isolated, "runs")["runs"][0]
    assert "ANTHROPIC_API_KEY" in last_run["errors"][0]
    assert read(isolated, "signals")["signals"]


def test_invalid_key_fails_the_run(isolated, monkeypatch):
    response = httpx2.Response(401, request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"))
    error = anthropic.AuthenticationError("invalid x-api-key", response=response, body=None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "bad-key")
    monkeypatch.setattr(run.llm, "make_client", lambda: FakeClient([error]))

    assert run.main([]) == 1
    assert "AuthenticationError" in read(isolated, "runs")["runs"][0]["errors"][0]


def test_reassess_picks_up_a_changed_brief(isolated, monkeypatch):
    client = FakeClient(scripted_claude)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(run.llm, "make_client", lambda: client)
    run.main([])

    brief = isolated / "config" / "brief.md"
    brief.write_text(brief.read_text(encoding="utf-8") + "\n- Prefer coastal hotels.\n", encoding="utf-8")
    run.main(["--reassess"])
    assert read(isolated, "runs")["runs"][0]["assessed"] == 2

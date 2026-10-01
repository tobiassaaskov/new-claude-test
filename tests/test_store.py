import json
from datetime import date

from scout.store import Store, dedupe_key, is_http_url, verdict_for

TODAY = date(2026, 10, 1)


def test_dedupe_key_ignores_scheme_www_trailing_slash_and_tracking():
    assert dedupe_key("https://www.Example.com/hotel/123/?utm_source=news&ref=7") == dedupe_key(
        "http://example.com/hotel/123?ref=7"
    )
    assert dedupe_key("https://example.com/a?x=1") != dedupe_key("https://example.com/a?x=2")


def test_is_http_url():
    assert is_http_url("https://example.com/x")
    assert not is_http_url("javascript:alert(1)")
    assert not is_http_url("example.com/no-scheme")


def test_verdict_bands_and_budget():
    assert verdict_for(None, None, 25_000_000) == "unassessed"
    assert verdict_for(85, 10_000_000, 25_000_000) == "strong_match"
    assert verdict_for(80, None, 25_000_000) == "strong_match"
    assert verdict_for(79, None, 25_000_000) == "possible"
    assert verdict_for(50, None, 25_000_000) == "possible"
    assert verdict_for(49, None, 25_000_000) == "no_match"
    assert verdict_for(95, 26_000_000, 25_000_000) == "over_budget"


def test_add_candidate_assigns_ids_and_tracks_sightings(tmp_path):
    store = Store(tmp_path)
    first, is_new = store.add_candidate({"url": "https://broker.fr/hotel-1"}, TODAY, "explorer")
    second, _ = store.add_candidate({"url": "https://broker.fr/hotel-2", "title": "Hotel 2"}, TODAY, "explorer")
    assert is_new and first["id"] == "HDS-0001" and second["id"] == "HDS-0002"
    assert first["source"] == "broker.fr"

    again, is_new = store.add_candidate({"url": "https://www.broker.fr/hotel-1/"}, TODAY, "explorer")
    assert not is_new and again is first and first["times_seen"] == 1  # same day counts once

    store.add_candidate({"url": "https://broker.fr/hotel-1"}, date(2026, 10, 2), "explorer")
    assert first["times_seen"] == 2 and first["last_seen"] == "2026-10-02"
    assert store.known_urls(limit=1) == ["https://broker.fr/hotel-1"]


def test_apply_assessment_sets_score_verdict_and_price_per_key(tmp_path):
    store = Store(tmp_path)
    opportunity, _ = store.add_candidate({"url": "https://broker.fr/h"}, TODAY, "explorer")
    store.apply_assessment(
        opportunity, {"score": 83, "asking_price_eur": 14_500_000.0, "keys": 48, "title_en": "4-star hotel, Bordeaux"}, 25_000_000
    )
    assert opportunity["verdict"] == "strong_match"
    assert opportunity["price_per_key_eur"] == 302083
    assert opportunity["title"] == "4-star hotel, Bordeaux"


def test_signals_are_deduplicated_and_old_ones_dropped(tmp_path):
    store = Store(tmp_path)
    assert store.add_signals([{"id": "A1", "date": "2026-09-30"}, {"id": "A2", "date": "2026-05-01"}], TODAY) == 2
    assert store.add_signals([{"id": "A1", "date": "2026-09-30"}], TODAY) == 0
    assert [s["id"] for s in store.signals] == ["A1"]  # A2 is older than 90 days


def test_save_writes_sorted_files(tmp_path):
    store = Store(tmp_path)
    low, _ = store.add_candidate({"url": "https://a.fr/1"}, TODAY, "explorer")
    high, _ = store.add_candidate({"url": "https://a.fr/2"}, TODAY, "explorer")
    store.add_candidate({"url": "https://a.fr/3"}, TODAY, "explorer")
    store.apply_assessment(low, {"score": 40}, 25_000_000)
    store.apply_assessment(high, {"score": 90}, 25_000_000)
    store.add_run({"started_at": "x"})
    store.save(updated_at="2026-10-01T05:20:00+00:00", repository="me/repo", budget_eur=25_000_000, brief_version="abc")

    saved = json.loads((tmp_path / "opportunities.json").read_text(encoding="utf-8"))
    assert [o["id"] for o in saved["opportunities"]] == ["HDS-0002", "HDS-0001", "HDS-0003"]
    assert saved["repository"] == "me/repo" and saved["budget_eur"] == 25_000_000
    assert json.loads((tmp_path / "runs.json").read_text(encoding="utf-8"))["runs"] == [{"started_at": "x"}]

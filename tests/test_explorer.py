from datetime import date

from fakes import FakeClient, message, text, tool_call, usage

from scout import explorer, llm

TODAY = date(2026, 10, 1)

CANDIDATES = {
    "candidates": [
        {
            "url": "https://www.msimond.fr/acheter/hotellerie/hotel-example",
            "title": "3-star hotel, 42 rooms, Annecy",
            "source": "Michel Simond",
            "location": "Annecy (74)",
            "asking_price_text": "6 900 000 €",
            "why": "Walls and business in a year-round destination.",
        },
        {"url": "not a url", "title": "x", "source": "x", "location": "x", "asking_price_text": "x", "why": "x"},
    ],
    "notes": "One broker site was slow.",
}


def test_request_uses_settings_brief_and_known_urls(settings):
    request = explorer.build_request(settings, ["https://known.example/hotel"], TODAY)
    tools = {tool["name"]: tool for tool in request["tools"]}
    assert tools["web_search"]["type"] == "web_search_20260318"
    assert tools["web_search"]["max_uses"] == settings.max_web_searches
    assert tools["web_search"]["user_location"]["country"] == "FR"
    assert tools["web_fetch"]["blocked_domains"] == ["leboncoin.fr", "seloger.com"]
    assert "submit_candidates" in tools
    assert "Investment brief" in request["system"]
    assert "https://known.example/hotel" in request["messages"][0]["content"]
    assert request["model"] == "claude-opus-5-5"
    assert request["fallbacks"] == "default" and llm.FALLBACK_BETA in request["betas"]


def test_focus_region_rotates_daily(settings):
    regions = {explorer.focus_region(settings, date.fromordinal(TODAY.toordinal() + i)) for i in range(9)}
    assert regions == set(settings.focus_regions)


def test_clean_candidates_drops_bad_urls_and_duplicates():
    duplicate = {"candidates": [CANDIDATES["candidates"][0]], "notes": ""}
    candidates, notes = explorer.clean_candidates([CANDIDATES, duplicate], limit=10)
    assert [c["url"] for c in candidates] == ["https://www.msimond.fr/acheter/hotellerie/hotel-example"]
    assert notes == "One broker site was slow."


def test_explore_resumes_a_paused_turn(settings):
    paused = message(text(""), stop_reason="pause_turn", usage_obj=usage(searches=5))
    final = message(tool_call("submit_candidates", CANDIDATES), usage_obj=usage(searches=3))
    client = FakeClient([paused, final])
    spend = llm.Usage()

    result = explorer.explore(client, settings, [], TODAY, spend)

    assert len(result.candidates) == 1
    assert len(client.calls) == 2
    resumed = client.calls[1]["messages"]
    assert resumed[-1] == {"role": "assistant", "content": paused.content}  # paused turn sent back unchanged
    assert spend.web_searches == 8 and spend.requests == 2


def test_explore_asks_once_more_when_no_tool_call(settings):
    client = FakeClient([message(text("Here is what I found..."), stop_reason="end_turn"), message(tool_call("submit_candidates", CANDIDATES))])
    result = explorer.explore(client, settings, [], TODAY, llm.Usage())
    assert len(result.candidates) == 1
    nudge = client.calls[1]["messages"][-1]
    assert nudge["role"] == "user" and "submit_candidates" in nudge["content"]


def test_usage_cost_estimate():
    spend = llm.Usage()
    spend.add(usage(input_tokens=1_000_000, output_tokens=100_000, searches=10))
    assert spend.estimated_cost_usd == round(4.0 + 2.0 + 0.10, 4)

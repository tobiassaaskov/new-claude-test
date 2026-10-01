from fakes import FakeClient, message, tool_call

from scout import assessor, llm

GOOD_REPORT = {
    "title_en": "4-star hotel, 48 rooms, Bordeaux",
    "listing_status": "for_sale",
    "page_was_read": True,
    "in_france": True,
    "asset_type": "hotel",
    "deal_type": "walls_and_business",
    "commune": "Bordeaux",
    "departement": "Gironde (33)",
    "region": "Nouvelle-Aquitaine",
    "keys": 48,
    "stars": 4,
    "asking_price_eur": 14_500_000,
    "price_on_request": False,
    "revenue_eur": 4_100_000,
    "ebitda_eur": 1_300_000,
    "figures_year": 2025,
    "broker": "Example Hotel Brokers",
    "summary_en": "Well-located four-star hotel sold with its walls.",
    "score": 86,
    "reasons": ["Walls and business", "Year-round city demand"],
    "red_flags": ["Rooms need refurbishment"],
    "missing_information": ["Capex estimate"],
    "questions_for_broker": ["Why is the owner selling?"],
    "evidence_quotes": ["Hôtel 4* de 48 chambres, murs et fonds"],
}

OPPORTUNITY = {"id": "HDS-0001", "url": "https://broker.example/hotel", "title": "Hotel", "source": "broker"}


def test_tool_schema_requires_every_field():
    schema = assessor.SUBMIT_ASSESSMENT_TOOL["input_schema"]
    assert set(schema["required"]) == set(schema["properties"])
    assert schema["additionalProperties"] is False


def test_clean_assessment_coerces_bad_values():
    cleaned = assessor.clean_assessment(
        {
            "score": 140,
            "keys": "48",
            "stars": 7,
            "deal_type": "something else",
            "asking_price_eur": -5,
            "ebitda_eur": -200_000,
            "reasons": ["  fine  ", "", 3],
            "commune": "   ",
        }
    )
    assert cleaned["score"] == 100
    assert cleaned["keys"] is None and cleaned["stars"] is None
    assert cleaned["deal_type"] == "unknown"
    assert cleaned["asking_price_eur"] is None
    assert cleaned["ebitda_eur"] == -200_000  # a loss is a real figure
    assert cleaned["reasons"] == ["fine", "3"]
    assert cleaned["commune"] is None
    assert cleaned["in_france"] is True and cleaned["page_was_read"] is False


def test_assess_returns_cleaned_report_with_provenance(settings):
    client = FakeClient([message(tool_call("submit_assessment", GOOD_REPORT))])
    result = assessor.assess(client, settings, OPPORTUNITY, llm.Usage())
    assert result["score"] == 86 and result["keys"] == 48
    assert result["brief_version"] == settings.brief_version
    assert result["model"] == "claude-opus-5-5"
    request = client.calls[0]
    assert request["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "https://broker.example/hotel" in request["messages"][0]["content"]


def test_hotel_outside_france_scores_zero(settings):
    client = FakeClient([message(tool_call("submit_assessment", dict(GOOD_REPORT, in_france=False)))])
    assert assessor.assess(client, settings, OPPORTUNITY, llm.Usage())["score"] == 0


def test_refusal_returns_none(settings):
    client = FakeClient([message(stop_reason="refusal")])
    assert assessor.assess(client, settings, OPPORTUNITY, llm.Usage()) is None
    assert len(client.calls) == 1  # no nudge after a refusal

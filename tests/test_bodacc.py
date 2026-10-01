import json
from datetime import date
from urllib.parse import parse_qs, urlsplit

import pytest

from scout import bodacc

HOTEL_SALE = {
    "id": "B202609301234",
    "dateparution": "2026-09-30",
    "familleavis_lib": "Ventes et cessions",
    "typeavis_lib": "Avis initial",
    "commercant": "SARL LES TERRASSES",
    "ville": "Annecy",
    "cp": "74000",
    "departement_nom_officiel": "Haute-Savoie",
    "listeetablissements": json.dumps(
        {"etablissement": {"activite": "Hôtel-restaurant, bar", "adresse": {"ville": "Annecy"}}}
    ),
    "url_complete": "https://www.bodacc.fr/annonce/detail-annonce/B/20260930/1234",
}

TOWN_HALL_BAKERY = {
    "id": "A202609300001",
    "dateparution": "2026-09-30",
    "familleavis_lib": "Procédures collectives",
    "commercant": "BOULANGERIE DE LA PLACE",
    "listeetablissements": json.dumps(
        {"etablissement": {"activite": "Boulangerie", "adresse": "Place de l'Hôtel de Ville"}}
    ),
}

HOTEL_INSOLVENCY = {
    "id": "A202609300002",
    "dateparution": "2026-09-29",
    "familleavis_lib": "Procédures collectives",
    "commercant": "HOTEL DU PORT SAS",
    "jugement": json.dumps({"nature": "Jugement d'ouverture d'une procédure de redressement judiciaire"}),
}


def test_hotel_sale_becomes_signal():
    signal = bodacc.to_signal(HOTEL_SALE)
    assert signal["kind"] == "sale"
    assert signal["activity"] == "Hôtel-restaurant, bar"
    assert signal["url"].startswith("https://www.bodacc.fr/")


def test_town_hall_address_is_not_a_hotel():
    assert bodacc.to_signal(TOWN_HALL_BAKERY) is None


def test_company_name_and_judgment_are_used():
    signal = bodacc.to_signal(HOTEL_INSOLVENCY)
    assert signal["kind"] == "insolvency"
    assert "redressement judiciaire" in signal["judgment"]
    assert signal["url"] is None


def test_falls_back_to_local_filtering_when_full_text_is_rejected():
    requests = []

    def fake_fetch(url):
        requests.append(parse_qs(urlsplit(url).query))
        if '"hotel"' in requests[-1]["where"][0]:
            raise bodacc.QueryRejected("bad syntax")
        return {"results": [HOTEL_SALE, TOWN_HALL_BAKERY, HOTEL_INSOLVENCY]}

    signals, note = bodacc.fetch_signals(date(2026, 10, 1), 4, fetch=fake_fetch)
    assert {s["id"] for s in signals} == {"B202609301234", "A202609300002"}
    assert "filtered locally" in note
    assert "dateparution >= date'2026-09-27'" in requests[-1]["where"][0]


def test_pages_until_a_short_page(monkeypatch):
    pages = [{"results": [HOTEL_SALE] * bodacc.PAGE_SIZE}, {"results": [HOTEL_INSOLVENCY]}]
    signals, _ = bodacc.fetch_signals(date(2026, 10, 1), 4, fetch=lambda url: pages.pop(0))
    assert len(signals) == 2 and not pages


def test_other_http_errors_propagate():
    def failing(url):
        raise OSError("network down")

    with pytest.raises(OSError):
        bodacc.fetch_signals(date(2026, 10, 1), 4, fetch=failing)

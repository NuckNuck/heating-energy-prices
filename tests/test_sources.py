"""Contract-Tests der Parser (`sources.py`) gegen echte Beispieldateien der Quellen.

Vertrag (Docstrings in `sources.py`): Jeder Parser liefert einen `PriceReading` mit Preis und Stand oder wirft
`SourceError`, wenn der erwartete Wert fehlt; es wird nie geschätzt.
"""

from datetime import date
import json

import pytest

from custom_components.heating_energy_prices.sources import (
    DEPI_REGIONS, SourceError, district_heating_mean, district_heating_network, eurostat_gas_url, latest_archive_file,
    parse_depi, parse_district_heating_table, parse_eurostat, parse_oil_bulletin)

from .conftest import fixture_bytes, fixture_text

OIL_BULLETIN = "oil_bulletin.xlsx"
EUROSTAT_GAS_DE = "eurostat_gas_de.json"
DEPI_PAGE = "depi.html"
ARCHIVE_PAGE = "district_heating_archive.html"
DISTRICT_HEATING_TABLE = "district_heating.xlsx"
OIL_BULLETIN_STICHTAG = date(2026, 11, 2)  # Zelle A2 der Beispieldatei


# --- Oil Bulletin ---------------------------------------------------------------------------------------------------

def test_covered_country_returns_heating_oil_price_with_stichtag():
    reading = parse_oil_bulletin(fixture_bytes(OIL_BULLETIN), "DE")
    assert reading.value > 0
    assert reading.as_of == OIL_BULLETIN_STICHTAG


def test_country_without_heating_oil_value_raises_source_error():
    with pytest.raises(SourceError):
        parse_oil_bulletin(fixture_bytes(OIL_BULLETIN), "NL")


def test_country_outside_bulletin_raises_source_error():
    with pytest.raises(SourceError):
        parse_oil_bulletin(fixture_bytes(OIL_BULLETIN), "CH")


def test_unreadable_bulletin_raises_source_error():
    with pytest.raises(SourceError):
        parse_oil_bulletin(b"kein xlsx", "DE")


# --- Eurostat -------------------------------------------------------------------------------------------------------

def test_eurostat_response_returns_latest_half_year_with_end_date():
    reading = parse_eurostat(fixture_bytes(EUROSTAT_GAS_DE))
    assert reading.extra["period"] == "2026-S1"
    assert reading.as_of == date(2026, 6, 30)
    assert 0 < reading.value < 1  # €/kWh


def test_eurostat_latest_period_missing_falls_back_to_previous_half_year():
    doc = json.loads(fixture_bytes(EUROSTAT_GAS_DE))
    doc["value"].pop(str(max(doc["dimension"]["time"]["category"]["index"].values())))
    reading = parse_eurostat(json.dumps(doc).encode())
    assert reading.extra["period"] == "2025-S2"
    assert reading.as_of == date(2025, 12, 31)


def test_eurostat_response_without_values_raises_source_error():
    doc = json.loads(fixture_bytes(EUROSTAT_GAS_DE)) | {"value": {}}
    with pytest.raises(SourceError):
        parse_eurostat(json.dumps(doc).encode())


def test_eurostat_response_with_several_countries_raises_source_error():
    doc = json.loads(fixture_bytes(EUROSTAT_GAS_DE))
    doc["size"][doc["id"].index("geo")] = 2
    with pytest.raises(SourceError):
        parse_eurostat(json.dumps(doc).encode())


def test_unreadable_eurostat_response_raises_source_error():
    with pytest.raises(SourceError):
        parse_eurostat(b"<html>")


@pytest.mark.parametrize(("country", "geo"), [("DE", "geo=DE&"), ("GR", "geo=EL&"), ("GB", "geo=UK&")])
def test_eurostat_url_uses_eurostat_country_code(country, geo):
    assert geo in eurostat_gas_url(country)


# --- DEPI -----------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("region", DEPI_REGIONS)
def test_each_depi_region_returns_six_tonne_price_with_month(region):
    reading = parse_depi(fixture_text(DEPI_PAGE), region)
    assert 100 < reading.value < 1000  # €/t
    assert reading.as_of == date(2026, 10, 1)


def test_unknown_depi_region_raises_source_error():
    with pytest.raises(SourceError):
        parse_depi(fixture_text(DEPI_PAGE), "west")


@pytest.mark.parametrize("region", DEPI_REGIONS)
def test_depi_page_without_tables_raises_source_error(region):
    with pytest.raises(SourceError):
        parse_depi("<html><p>Wartungsarbeiten</p></html>", region)


# --- waermepreise.info ----------------------------------------------------------------------------------------------

def test_archive_returns_newest_xlsx_and_its_stichtag():
    url, stichtag = latest_archive_file(fixture_text(ARCHIVE_PAGE))
    assert url.endswith(".xlsx")
    assert stichtag == date(2026, 10, 1)


def test_archive_without_xlsx_links_raises_source_error():
    with pytest.raises(SourceError):
        latest_archive_file("<p>Stichtag 01.03.2026: <a href=\"x.csv\">csv</a></p>")


def test_table_returns_networks_with_company_and_price():
    networks = parse_district_heating_table(fixture_bytes(DISTRICT_HEATING_TABLE))
    priced = [n for n in networks if n.price is not None]
    assert priced
    assert all(n.company for n in priced)
    # Der Preisstand kommt aus der Tabelle; drei Netze der Beispieldatei haben keinen und bleiben ohne Stand.
    assert any(n.as_of is not None for n in priced)


def test_table_without_expected_columns_raises_source_error():
    with pytest.raises(SourceError):
        parse_district_heating_table(fixture_bytes(OIL_BULLETIN))


def test_unreadable_table_raises_source_error():
    with pytest.raises(SourceError):
        parse_district_heating_table(b"")


def test_mean_is_unweighted_average_over_priced_networks():
    networks = parse_district_heating_table(fixture_bytes(DISTRICT_HEATING_TABLE))
    prices = [n.price for n in networks if n.price is not None]
    reading = district_heating_mean(networks, date(2026, 10, 1))
    assert reading.value == pytest.approx(sum(prices) / len(prices), abs=0.005)
    assert reading.extra == {"sample_size": len(prices), "weighting": "unweighted"}
    assert reading.as_of == date(2026, 10, 1)


def test_mean_without_prices_raises_source_error():
    with pytest.raises(SourceError):
        district_heating_mean([], None)


def test_selected_network_returns_its_price_and_price_date():
    networks = parse_district_heating_table(fixture_bytes(DISTRICT_HEATING_TABLE))
    chosen = next(n for n in networks if n.price is not None)
    reading = district_heating_network(networks, chosen.key)
    assert (reading.value, reading.as_of) == (chosen.price, chosen.as_of)
    assert reading.extra["company"] == chosen.company


def test_network_missing_from_table_raises_source_error():
    networks = parse_district_heating_table(fixture_bytes(DISTRICT_HEATING_TABLE))
    with pytest.raises(SourceError):
        district_heating_network(networks, "Nirgendwo|Nirgendwo|Niemand|Nichts")

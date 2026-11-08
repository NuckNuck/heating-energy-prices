"""Contract-Tests der Preis-Sensoren gegen den Vertrag aus Spezifikation 7.3 des Wärmepumpen-Audits.

Vertrag: state = Preis brutto in einer erlaubten Einheit; Pflichtattribut `heating_system`; `source`, `source_kind`,
`as_of` (ISO-Datum) und `includes_fixed_charges`; ein Sensor je gewählter Quelle; scheitert der Abruf, ist der Sensor
unavailable (kein geschätzter oder alter Wert).
"""

from datetime import date

import pytest

from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant

from custom_components.heating_energy_prices.sources import DEPI_URL, OIL_BULLETIN_URL

from .helpers import entity_id, mock_sources, setup_entry

AUDIT_UNITS = {"€/kWh", "ct/kWh", "€/MWh", "€/L", "ct/L", "€/100 L", "€/1000 L", "€/kg", "€/t"}

EXPECTED = {
    # Quelle: (heating_system, source_kind, includes_fixed_charges)
    "oil_bulletin": ("heating_oil", "official", False),
    "eurostat_gas": ("natural_gas", "official", True),
    "depi_pellets": ("wood_pellets", "association", False),
    "district_heating_mean": ("district_heating", "association", True),
}


@pytest.mark.parametrize("source", EXPECTED)
async def test_selected_source_creates_sensor_fulfilling_audit_contract(hass: HomeAssistant, aioclient_mock,
                                                                         source):
    mock_sources(aioclient_mock)
    entry = await setup_entry(hass)
    state = hass.states.get(entity_id(hass, "sensor", f"{entry.entry_id}_{source}"))
    system, kind, fixed = EXPECTED[source]
    assert float(state.state) > 0
    assert state.attributes["unit_of_measurement"] in AUDIT_UNITS
    assert state.attributes["heating_system"] == system
    assert state.attributes["source_kind"] == kind
    assert state.attributes["includes_fixed_charges"] is fixed
    assert state.attributes["source"]
    date.fromisoformat(state.attributes["as_of"])


async def test_unselected_source_creates_no_sensor(hass: HomeAssistant, aioclient_mock):
    mock_sources(aioclient_mock)
    entry = await setup_entry(hass, sources=["oil_bulletin"])
    assert entity_id(hass, "sensor", f"{entry.entry_id}_eurostat_gas") is None


async def test_source_not_covering_country_creates_no_sensor(hass: HomeAssistant, aioclient_mock):
    mock_sources(aioclient_mock)
    entry = await setup_entry(hass, country="AT", sources=["depi_pellets", "oil_bulletin"])
    assert entity_id(hass, "sensor", f"{entry.entry_id}_depi_pellets") is None


async def test_failed_download_makes_sensor_unavailable(hass: HomeAssistant, aioclient_mock):
    mock_sources(aioclient_mock, failing={OIL_BULLETIN_URL})
    entry = await setup_entry(hass)
    assert hass.states.get(entity_id(hass, "sensor", f"{entry.entry_id}_oil_bulletin")).state == STATE_UNAVAILABLE


async def test_unparsable_source_makes_sensor_unavailable(hass: HomeAssistant, aioclient_mock):
    aioclient_mock.get(DEPI_URL, text="<html><p>Wartungsarbeiten</p></html>")
    entry = await setup_entry(hass, sources=["depi_pellets"])
    assert hass.states.get(entity_id(hass, "sensor", f"{entry.entry_id}_depi_pellets")).state == STATE_UNAVAILABLE


async def test_depi_region_selects_regional_price(hass: HomeAssistant, aioclient_mock):
    mock_sources(aioclient_mock)
    entry = await setup_entry(hass, sources=["depi_pellets"], depi_region="south")
    state = hass.states.get(entity_id(hass, "sensor", f"{entry.entry_id}_depi_pellets"))
    assert float(state.state) == 466.81  # Spalte Süd, 6 t, Oktober 2026 der Beispielseite


async def test_district_heating_mean_names_sample_size_and_weighting(hass: HomeAssistant, aioclient_mock):
    mock_sources(aioclient_mock)
    entry = await setup_entry(hass, sources=["district_heating_mean"])
    state = hass.states.get(entity_id(hass, "sensor", f"{entry.entry_id}_district_heating_mean"))
    assert state.attributes["weighting"] == "unweighted"
    assert state.attributes["sample_size"] > 0


async def test_eurostat_sensor_names_period(hass: HomeAssistant, aioclient_mock):
    mock_sources(aioclient_mock)
    entry = await setup_entry(hass, sources=["eurostat_gas"])
    state = hass.states.get(entity_id(hass, "sensor", f"{entry.entry_id}_eurostat_gas"))
    assert state.attributes["period"] == "2026-S1"


async def test_unloading_entry_removes_sensor_states(hass: HomeAssistant, aioclient_mock):
    mock_sources(aioclient_mock)
    entry = await setup_entry(hass, sources=["oil_bulletin"])
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert hass.states.get(entity_id(hass, "sensor", f"{entry.entry_id}_oil_bulletin")).state == STATE_UNAVAILABLE

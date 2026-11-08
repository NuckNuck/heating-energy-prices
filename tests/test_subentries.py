"""Contract-Tests der Untereinträge „Fernwärmenetz“ und „Eigener Preis“.

Vertrag Fernwärmenetz: Auswahl Bundesland → Stadt → Teilnetz aus der jüngsten Tabelle von waermepreise.info; der
Sensor zeigt den EFH-Mischpreis dieses Netzes (inkl. Grundpreis); fehlt das Netz später, ist er unavailable.
Vertrag Eigener Preis: Name und System, dann Einheit und optional Grundpreis; der Preis wird in einer number-Entität
eingetragen, der Sensor trägt ihn mit `source_kind` local, `as_of` = Tag der Eingabe und `annual_base_fee`;
Wert und Stand überstehen einen Neustart.
"""

from datetime import date

from homeassistant import config_entries
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, State
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import mock_restore_cache

from custom_components.heating_energy_prices.sources import DISTRICT_HEATING_ARCHIVE_URL, parse_district_heating_table

from .conftest import fixture_bytes
from .helpers import entity_id, mock_sources, setup_entry

NETWORKS = [n for n in parse_district_heating_table(fixture_bytes("district_heating.xlsx")) if n.price is not None]
CHOSEN = NETWORKS[0]
NETWORK_SUBENTRY = {"subentry_type": "district_heating_network", "data": {"network_key": CHOSEN.key},
                    "title": "Fernwärme Testnetz", "unique_id": CHOSEN.key, "subentry_id": "net1"}
OIL_QUOTE = {"subentry_type": "custom_price", "title": "Heizöl Angebot", "subentry_id": "own1", "unique_id": None,
             "data": {"heating_system": "heating_oil", "unit": "€/100 L", "annual_base_fee": 0.0}}
GAS_CONTRACT = {"subentry_type": "custom_price", "title": "Gasvertrag", "subentry_id": "own2", "unique_id": None,
                "data": {"heating_system": "natural_gas", "unit": "ct/kWh", "annual_base_fee": 180.0}}
KNOWN_PRICE = 98.5


async def _start(hass: HomeAssistant, entry, subentry_type: str):
    return await hass.config_entries.subentries.async_init((entry.entry_id, subentry_type),
                                                           context={"source": config_entries.SOURCE_USER})


async def _configure(hass: HomeAssistant, result, data: dict):
    return await hass.config_entries.subentries.async_configure(result["flow_id"], data)


# --- Fernwärmenetz --------------------------------------------------------------------------------------------------

async def test_choosing_state_city_and_network_creates_subentry(hass: HomeAssistant, aioclient_mock):
    mock_sources(aioclient_mock)
    entry = await setup_entry(hass, sources=["oil_bulletin"])
    result = await _start(hass, entry, "district_heating_network")
    result = await _configure(hass, result, {"state": CHOSEN.state})
    result = await _configure(hass, result, {"city": CHOSEN.city})
    result = await _configure(hass, result, {"network_key": CHOSEN.key})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"network_key": CHOSEN.key}


async def test_network_already_chosen_aborts(hass: HomeAssistant, aioclient_mock):
    mock_sources(aioclient_mock)
    entry = await setup_entry(hass, [NETWORK_SUBENTRY], sources=["oil_bulletin"])
    result = await _start(hass, entry, "district_heating_network")
    result = await _configure(hass, result, {"state": CHOSEN.state})
    result = await _configure(hass, result, {"city": CHOSEN.city})
    result = await _configure(hass, result, {"network_key": CHOSEN.key})
    assert result["reason"] == "already_configured"


async def test_unreachable_list_aborts_network_flow(hass: HomeAssistant, aioclient_mock):
    mock_sources(aioclient_mock, failing={DISTRICT_HEATING_ARCHIVE_URL})
    entry = await setup_entry(hass, sources=["oil_bulletin"])
    result = await _start(hass, entry, "district_heating_network")
    assert result["reason"] == "cannot_connect"


async def test_network_sensor_shows_price_of_chosen_network(hass: HomeAssistant, aioclient_mock):
    mock_sources(aioclient_mock)
    await setup_entry(hass, [NETWORK_SUBENTRY], sources=[])
    state = hass.states.get(entity_id(hass, "sensor", "net1_price"))
    assert float(state.state) == CHOSEN.price
    assert state.attributes["heating_system"] == "district_heating"
    assert state.attributes["includes_fixed_charges"] is True
    assert state.attributes["company"] == CHOSEN.company


async def test_network_missing_from_table_makes_sensor_unavailable(hass: HomeAssistant, aioclient_mock):
    mock_sources(aioclient_mock)
    gone = NETWORK_SUBENTRY | {"data": {"network_key": "Nirgendwo|Nirgendwo|Niemand|Nichts"}, "unique_id": "gone"}
    await setup_entry(hass, [gone], sources=[])
    assert hass.states.get(entity_id(hass, "sensor", "net1_price")).state == STATE_UNAVAILABLE


# --- Eigener Preis --------------------------------------------------------------------------------------------------

async def test_custom_price_flow_creates_subentry_with_unit_and_base_fee(hass: HomeAssistant, aioclient_mock):
    mock_sources(aioclient_mock)
    entry = await setup_entry(hass, sources=["oil_bulletin"])
    result = await _start(hass, entry, "custom_price")
    result = await _configure(hass, result, {"name": "Gasvertrag alt", "heating_system": "natural_gas"})
    result = await _configure(hass, result, {"unit": "ct/kWh", "annual_base_fee": 180})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert (result["title"], result["data"]) == (
        "Gasvertrag alt", {"heating_system": "natural_gas", "unit": "ct/kWh", "annual_base_fee": 180})


async def test_custom_price_units_match_heating_system(hass: HomeAssistant, aioclient_mock):
    mock_sources(aioclient_mock)
    entry = await setup_entry(hass, sources=["oil_bulletin"])
    result = await _start(hass, entry, "custom_price")
    result = await _configure(hass, result, {"name": "Pellets", "heating_system": "wood_pellets"})
    field = next(k for k in result["data_schema"].schema if str(k) == "unit")
    assert set(result["data_schema"].schema[field].config["options"]) == {"€/t", "€/kg", "ct/kWh", "€/kWh", "€/MWh"}


async def test_new_custom_price_sensor_has_no_value_until_entered(hass: HomeAssistant, aioclient_mock):
    mock_sources(aioclient_mock)
    await setup_entry(hass, [OIL_QUOTE], sources=[])
    state = hass.states.get(entity_id(hass, "sensor", "own1_price"))
    assert state.state == STATE_UNKNOWN
    assert state.attributes["heating_system"] == "heating_oil"


async def test_entered_price_appears_at_sensor_with_entry_date(hass: HomeAssistant, aioclient_mock):
    mock_sources(aioclient_mock)
    await setup_entry(hass, [GAS_CONTRACT], sources=[])
    await hass.services.async_call("number", "set_value", {"entity_id": entity_id(hass, "number", "own2_input"),
                                                          "value": 9.8}, blocking=True)
    state = hass.states.get(entity_id(hass, "sensor", "own2_price"))
    assert float(state.state) == 9.8
    assert state.attributes["unit_of_measurement"] == "ct/kWh"
    assert state.attributes["source_kind"] == "local"
    assert state.attributes["as_of"] == dt_util.now().date().isoformat()
    assert state.attributes["annual_base_fee"] == 180.0
    assert state.attributes["includes_fixed_charges"] is False


async def test_custom_price_without_base_fee_has_no_base_fee_attribute(hass: HomeAssistant, aioclient_mock):
    mock_sources(aioclient_mock)
    no_fee = OIL_QUOTE | {"data": {"heating_system": "heating_oil", "unit": "€/100 L"}}
    await setup_entry(hass, [no_fee], sources=[])
    assert "annual_base_fee" not in hass.states.get(entity_id(hass, "sensor", "own1_price")).attributes


async def test_entered_price_and_date_survive_restart(hass: HomeAssistant, aioclient_mock):
    mock_sources(aioclient_mock)
    mock_restore_cache(hass, [State("number.heizol_angebot_price", str(KNOWN_PRICE), {"as_of": "2026-09-01"})])
    await setup_entry(hass, [OIL_QUOTE], sources=[])
    state = hass.states.get(entity_id(hass, "sensor", "own1_price"))
    assert float(state.state) == KNOWN_PRICE
    assert date.fromisoformat(state.attributes["as_of"]) == date(2026, 9, 1)


async def test_reconfigure_changes_unit_and_keeps_system(hass: HomeAssistant, aioclient_mock):
    mock_sources(aioclient_mock)
    entry = await setup_entry(hass, [OIL_QUOTE], sources=[])
    result = await entry.start_subentry_reconfigure_flow(hass, "own1")
    result = await _configure(hass, result, {"unit": "€/L"})
    await hass.async_block_till_done()
    assert result["reason"] == "reconfigure_successful"
    assert dict(entry.subentries["own1"].data) == {"heating_system": "heating_oil", "unit": "€/L"}

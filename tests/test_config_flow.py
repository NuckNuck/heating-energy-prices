"""Contract-Tests der Einrichtung und der Optionen.

Vertrag: Land (Vorgabe aus HA) und ein Abfrageintervall, dann Auswahl unter den Quellen, die das Land abdecken;
eine Einrichtung je HA; Länder ohne Quelle werden mit Fehler abgewiesen; Optionen ändern Land, Intervall und Quellen.
"""

import pytest

from homeassistant import config_entries
from homeassistant.data_entry_flow import UnknownHandler
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.heating_energy_prices.const import DOMAIN

from .helpers import ALL_DE_SOURCES, mock_sources, setup_entry


def _source_options(result) -> list[str]:
    field = next(k for k in result["data_schema"].schema if str(k) == "sources")
    return result["data_schema"].schema[field].config["options"]


def _fields(result) -> set[str]:
    return {str(k) for k in result["data_schema"].schema}


async def test_user_flow_creates_entry_with_chosen_sources(hass: HomeAssistant, aioclient_mock):
    mock_sources(aioclient_mock)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"],
                                                            {"country": "DE", "update_interval_hours": 12})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"sources": ["oil_bulletin"], "depi_region": "germany"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"] == {"country": "DE", "update_interval_hours": 12, "sources": ["oil_bulletin"],
                                 "depi_region": "germany"}


async def test_country_defaults_to_home_assistant_country(hass: HomeAssistant):
    hass.config.country = "AT"
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    field = next(k for k in result["data_schema"].schema if str(k) == "country")
    assert field.default() == "AT"


async def test_sources_step_offers_only_sources_covering_country(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"],
                                                            {"country": "AT", "update_interval_hours": 24})
    assert _source_options(result) == ["oil_bulletin", "eurostat_gas"]
    assert "depi_region" not in _fields(result)


async def test_german_setup_offers_all_sources_and_pellet_region(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"],
                                                            {"country": "DE", "update_interval_hours": 24})
    assert _source_options(result) == ALL_DE_SOURCES
    assert "depi_region" in _fields(result)


async def test_country_without_sources_shows_error(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"],
                                                            {"country": "US", "update_interval_hours": 24})
    assert result["errors"] == {"country": "no_sources"}


async def test_second_setup_aborts(hass: HomeAssistant, aioclient_mock):
    mock_sources(aioclient_mock)
    await setup_entry(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["reason"] == "already_configured"


async def test_options_change_interval_and_sources(hass: HomeAssistant, aioclient_mock):
    mock_sources(aioclient_mock)
    entry = await setup_entry(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"],
                                                               {"country": "DE", "update_interval_hours": 6})
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"sources": ["eurostat_gas"], "depi_region": "central"})
    await hass.async_block_till_done()
    assert entry.options == {"country": "DE", "update_interval_hours": 6, "sources": ["eurostat_gas"],
                             "depi_region": "central"}


async def test_options_reject_country_without_sources(hass: HomeAssistant, aioclient_mock):
    mock_sources(aioclient_mock)
    entry = await setup_entry(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"],
                                                               {"country": "US", "update_interval_hours": 24})
    assert result["errors"] == {"country": "no_sources"}


async def test_district_heating_network_offered_only_for_germany(hass: HomeAssistant, aioclient_mock):
    mock_sources(aioclient_mock)
    entry = await setup_entry(hass, country="AT", sources=["oil_bulletin"])
    with pytest.raises(UnknownHandler):
        await hass.config_entries.subentries.async_init((entry.entry_id, "district_heating_network"),
                                                        context={"source": config_entries.SOURCE_USER})

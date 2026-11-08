"""Hilfen für HA-Tests: Abrufe der Quellen mit den Beispieldateien beantworten, Eintrag einrichten."""

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.heating_energy_prices.const import DOMAIN
from custom_components.heating_energy_prices.sources import (DEPI_URL, DISTRICT_HEATING_ARCHIVE_URL,
                                                              OIL_BULLETIN_URL, eurostat_gas_url, latest_archive_file)

from .conftest import fixture_bytes, fixture_text

ALL_DE_SOURCES = ["oil_bulletin", "eurostat_gas", "depi_pellets", "district_heating_mean"]


def mock_sources(aioclient_mock: AiohttpClientMocker, failing: set[str] = frozenset()) -> None:
    """Alle Quellen für Deutschland; Adressen in `failing` antworten mit HTTP 500."""
    table_url, _ = latest_archive_file(fixture_text("district_heating_archive.html"))
    answers = {
        OIL_BULLETIN_URL: fixture_bytes("oil_bulletin.xlsx"),
        eurostat_gas_url("DE"): fixture_bytes("eurostat_gas_de.json"),
        DEPI_URL: fixture_bytes("depi.html"),
        DISTRICT_HEATING_ARCHIVE_URL: fixture_bytes("district_heating_archive.html"),
        table_url: fixture_bytes("district_heating.xlsx"),
    }
    for url, content in answers.items():
        if url in failing:
            aioclient_mock.get(url, status=500)
        else:
            aioclient_mock.get(url, content=content)


def options(**overrides: Any) -> dict[str, Any]:
    return {"country": "DE", "update_interval_hours": 24, "sources": ALL_DE_SOURCES, "depi_region": "germany"} \
        | overrides


async def setup_entry(hass: HomeAssistant, subentries: list[dict] | None = None, **overrides: Any) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, title="Heizenergiepreise", data={}, options=options(**overrides),
                            unique_id=DOMAIN, subentries_data=subentries or [])
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def entity_id(hass: HomeAssistant, domain: str, unique_id: str) -> str | None:
    return er.async_get(hass).async_get_entity_id(domain, DOMAIN, unique_id)

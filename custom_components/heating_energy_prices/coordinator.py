"""Abruf der Quellen. Ein Coordinator je Quelle; Fehler machen den Sensor unavailable, es wird nichts geschätzt."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
import logging

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (CONF_DEPI_REGION, CONF_UPDATE_INTERVAL_HOURS, DEFAULT_UPDATE_INTERVAL_HOURS, SOURCE_DEPI_PELLETS,
                    SOURCE_EUROSTAT_GAS, SOURCE_OIL_BULLETIN)
from .sources import (DEPI_URL, DISTRICT_HEATING_ARCHIVE_URL, OIL_BULLETIN_URL, DistrictHeatingNetwork, PriceReading,
                      SourceError, eurostat_gas_url, latest_archive_file, parse_depi, parse_district_heating_table,
                      parse_eurostat, parse_oil_bulletin)

_LOGGER = logging.getLogger(__name__)
_TIMEOUT = aiohttp.ClientTimeout(total=60)


async def async_download(hass: HomeAssistant, url: str) -> bytes:
    """Rohdaten einer Adresse; Netz- und HTTP-Fehler werden zu `SourceError`."""
    session = async_get_clientsession(hass)
    try:
        async with session.get(url, timeout=_TIMEOUT) as response:
            response.raise_for_status()
            return await response.read()
    except (aiohttp.ClientError, TimeoutError) as err:
        raise SourceError(f"Abruf von {url} fehlgeschlagen: {err}") from err


@dataclass(frozen=True)
class DistrictHeatingTable:
    """Jüngste Tabelle der Preistransparenzplattform."""

    networks: list[DistrictHeatingNetwork] = field(default_factory=list)
    stichtag: date | None = None


async def async_fetch_district_heating(hass: HomeAssistant) -> DistrictHeatingTable:
    """Download-Archiv lesen, jüngste XLSX laden und auswerten."""
    html = (await async_download(hass, DISTRICT_HEATING_ARCHIVE_URL)).decode("utf-8", errors="replace")
    url, stichtag = latest_archive_file(html)
    data = await async_download(hass, url)
    networks = await hass.async_add_executor_job(parse_district_heating_table, data)
    return DistrictHeatingTable(networks, stichtag)


def update_interval(entry: ConfigEntry) -> timedelta:
    return timedelta(hours=float(entry.options.get(CONF_UPDATE_INTERVAL_HOURS, DEFAULT_UPDATE_INTERVAL_HOURS)))


class SourceCoordinator[T](DataUpdateCoordinator[T]):
    """Ruft eine Quelle im eingestellten Intervall ab."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, name: str,
                 fetch: Callable[[], Awaitable[T]]) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=name, update_interval=update_interval(entry))
        self._fetch = fetch

    async def _async_update_data(self) -> T:
        try:
            return await self._fetch()
        except SourceError as err:
            raise UpdateFailed(str(err)) from err


def price_fetcher(hass: HomeAssistant, entry: ConfigEntry, source: str,
                  country: str) -> Callable[[], Awaitable[PriceReading]]:
    """Abruf + Auswertung für eine Preisquelle mit genau einem Wert."""

    async def oil() -> PriceReading:
        data = await async_download(hass, OIL_BULLETIN_URL)
        return await hass.async_add_executor_job(parse_oil_bulletin, data, country)

    async def gas() -> PriceReading:
        return parse_eurostat(await async_download(hass, eurostat_gas_url(country)))

    async def pellets() -> PriceReading:
        html = (await async_download(hass, DEPI_URL)).decode("utf-8", errors="replace")
        return parse_depi(html, entry.options.get(CONF_DEPI_REGION, "germany"))

    return {SOURCE_OIL_BULLETIN: oil, SOURCE_EUROSTAT_GAS: gas, SOURCE_DEPI_PELLETS: pellets}[source]

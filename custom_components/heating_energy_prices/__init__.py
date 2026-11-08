"""Heizenergiepreise: Brennstoffpreise anderer Heizsysteme als Sensoren für Wärmekosten-Vergleiche."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback

from .const import (CONF_COUNTRY, CONF_SOURCES, SOURCE_DISTRICT_HEATING_MEAN, SUBENTRY_CUSTOM_PRICE,
                    SUBENTRY_DISTRICT_HEATING_NETWORK, sources_for_country)
from .coordinator import SourceCoordinator, async_fetch_district_heating, price_fetcher

PLATFORMS = [Platform.SENSOR, Platform.NUMBER]


class CustomPriceStore:
    """Von Hand eingetragener Preis eines Untereintrags; die number-Entität schreibt, der Sensor liest."""

    def __init__(self) -> None:
        self.value: float | None = None
        self.as_of: date | None = None
        self._listeners: list[Callable[[], None]] = []

    @callback
    def set(self, value: float | None, as_of: date | None) -> None:
        self.value, self.as_of = value, as_of
        for listener in list(self._listeners):
            listener()

    @callback
    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)


@dataclass
class RuntimeData:
    country: str
    price_coordinators: dict[str, SourceCoordinator] = field(default_factory=dict)
    district_heating: SourceCoordinator | None = None
    custom_prices: dict[str, CustomPriceStore] = field(default_factory=dict)


type HeatingPricesConfigEntry = ConfigEntry[RuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: HeatingPricesConfigEntry) -> bool:
    country = entry.options.get(CONF_COUNTRY) or entry.data.get(CONF_COUNTRY) or hass.config.country or ""
    available = sources_for_country(country)
    selected = [s for s in entry.options.get(CONF_SOURCES, []) if s in available]
    runtime = RuntimeData(country)
    for source in selected:
        if source == SOURCE_DISTRICT_HEATING_MEAN:
            continue
        runtime.price_coordinators[source] = SourceCoordinator(
            hass, entry, f"{entry.title} {source}", price_fetcher(hass, entry, source, country))
    networks = [s for s in entry.subentries.values() if s.subentry_type == SUBENTRY_DISTRICT_HEATING_NETWORK]
    if SOURCE_DISTRICT_HEATING_MEAN in selected or networks:
        runtime.district_heating = SourceCoordinator(
            hass, entry, f"{entry.title} district_heating", lambda: async_fetch_district_heating(hass))
    for sub in entry.subentries.values():
        if sub.subentry_type == SUBENTRY_CUSTOM_PRICE:
            runtime.custom_prices[sub.subentry_id] = CustomPriceStore()
    # Ein Fehler beim ersten Abruf hält die Einrichtung nicht auf: Der Sensor ist dann unavailable.
    for coordinator in [*runtime.price_coordinators.values(), runtime.district_heating]:
        if coordinator is not None:
            await coordinator.async_refresh()
    entry.runtime_data = runtime
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: HeatingPricesConfigEntry) -> None:
    """Optionen oder Untereinträge geändert → neu einrichten."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: HeatingPricesConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

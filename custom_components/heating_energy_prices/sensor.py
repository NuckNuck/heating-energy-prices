"""Preis-Sensoren nach dem Vertrag des Luft-Wasser-Wärmepumpen-Audits (Spezifikation 7.3).

state = Brennstoffpreis brutto in einer vom Audit verstandenen Einheit; Pflichtattribut `heating_system`, dazu
`source`, `source_kind`, `as_of` und `includes_fixed_charges` (Preis enthält Grundpreis und Messkosten).
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import CustomPriceStore, HeatingPricesConfigEntry
from .const import (ATTR_ANNUAL_BASE_FEE, ATTR_AS_OF, ATTR_HEATING_SYSTEM, ATTR_INCLUDES_FIXED_CHARGES, ATTR_SOURCE,
                    ATTR_SOURCE_KIND, CONF_ANNUAL_BASE_FEE, CONF_HEATING_SYSTEM, CONF_NETWORK_KEY, CONF_UNIT,
                    DISTRICT_HEATING, DISTRICT_HEATING_SOURCE, DOMAIN, SOURCE_DISTRICT_HEATING_MEAN, SOURCES,
                    SUBENTRY_CUSTOM_PRICE, SUBENTRY_DISTRICT_HEATING_NETWORK)
from .coordinator import SourceCoordinator
from .sources import PriceReading, SourceError, district_heating_mean, district_heating_network

CUSTOM_PRICE_SOURCE = "Eigener Eintrag"


def entry_device(entry: HeatingPricesConfigEntry) -> DeviceInfo:
    return DeviceInfo(identifiers={(DOMAIN, entry.entry_id)}, name=entry.title, manufacturer="NuckNuck",
                      model="Heizenergiepreise", entry_type=DeviceEntryType.SERVICE)


def subentry_device(subentry_id: str, title: str) -> DeviceInfo:
    return DeviceInfo(identifiers={(DOMAIN, subentry_id)}, name=title, manufacturer="NuckNuck",
                      model="Heizenergiepreise", entry_type=DeviceEntryType.SERVICE)


def contract_attributes(system: str, source: str, kind: str, reading: PriceReading | None,
                        fixed_charges: bool) -> dict[str, Any]:
    attrs: dict[str, Any] = {ATTR_HEATING_SYSTEM: system, ATTR_SOURCE: source, ATTR_SOURCE_KIND: kind,
                             ATTR_INCLUDES_FIXED_CHARGES: fixed_charges}
    if reading is not None:
        if reading.as_of is not None:
            attrs[ATTR_AS_OF] = reading.as_of.isoformat()
        attrs.update(reading.extra)
    return attrs


async def async_setup_entry(hass: HomeAssistant, entry: HeatingPricesConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    runtime = entry.runtime_data
    entities: list[SensorEntity] = [SourcePriceSensor(entry, key, coordinator)
                                    for key, coordinator in runtime.price_coordinators.items()]
    if runtime.district_heating is not None and SOURCE_DISTRICT_HEATING_MEAN in entry.options.get("sources", []):
        entities.append(DistrictHeatingMeanSensor(entry, runtime.district_heating))
    async_add_entities(entities)
    for sub in entry.subentries.values():
        if sub.subentry_type == SUBENTRY_DISTRICT_HEATING_NETWORK and runtime.district_heating is not None:
            async_add_entities([DistrictHeatingNetworkSensor(runtime.district_heating, sub.subentry_id, sub.title,
                                                             sub.data[CONF_NETWORK_KEY])],
                               config_subentry_id=sub.subentry_id)
        elif sub.subentry_type == SUBENTRY_CUSTOM_PRICE:
            async_add_entities([CustomPriceSensor(runtime.custom_prices[sub.subentry_id], sub.subentry_id, sub.title,
                                                  dict(sub.data))], config_subentry_id=sub.subentry_id)


class _PriceSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2


class SourcePriceSensor(CoordinatorEntity[SourceCoordinator[PriceReading]], _PriceSensor):
    """Ein Sensor je Quelle mit genau einem Wert (Oil Bulletin, Eurostat, DEPI)."""

    def __init__(self, entry: HeatingPricesConfigEntry, source: str, coordinator: SourceCoordinator) -> None:
        super().__init__(coordinator)
        self._spec = SOURCES[source]
        self._attr_unique_id = f"{entry.entry_id}_{source}"
        self._attr_translation_key = source
        self._attr_native_unit_of_measurement = self._spec["unit"]
        self._attr_device_info = entry_device(entry)
        if self._spec["unit"] == "€/kWh":
            self._attr_suggested_display_precision = 4

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.value if self.coordinator.data else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return contract_attributes(self._spec["system"], self._spec["source"], self._spec["kind"],
                                   self.coordinator.data, self._spec["fixed_charges"])


class _DistrictHeatingSensor(CoordinatorEntity[SourceCoordinator], _PriceSensor):
    """Gemeinsame Grundlage: Wert wird aus der Tabelle der Preistransparenzplattform abgeleitet."""

    _attr_native_unit_of_measurement = "ct/kWh"
    _reading: PriceReading | None = None

    def _derive(self) -> PriceReading:
        raise NotImplementedError

    def _update_reading(self) -> None:
        try:
            self._reading = self._derive() if self.coordinator.data else None
        except SourceError:
            self._reading = None

    @callback
    def _handle_coordinator_update(self) -> None:
        self._update_reading()
        super()._handle_coordinator_update()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._update_reading()

    @property
    def available(self) -> bool:
        return super().available and self._reading is not None

    @property
    def native_value(self) -> float | None:
        return self._reading.value if self._reading else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return contract_attributes(DISTRICT_HEATING, DISTRICT_HEATING_SOURCE, "association", self._reading, True)


class DistrictHeatingMeanSensor(_DistrictHeatingSensor):
    """Bundesmittel (ungewichtet) der EFH-Mischpreise aller Teilnetze."""

    _attr_translation_key = SOURCE_DISTRICT_HEATING_MEAN

    def __init__(self, entry: HeatingPricesConfigEntry, coordinator: SourceCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{SOURCE_DISTRICT_HEATING_MEAN}"
        self._attr_device_info = entry_device(entry)

    def _derive(self) -> PriceReading:
        table = self.coordinator.data
        return district_heating_mean(table.networks, table.stichtag)


class DistrictHeatingNetworkSensor(_DistrictHeatingSensor):
    """EFH-Mischpreis des vom Nutzer gewählten Fernwärmenetzes."""

    _attr_name = None

    def __init__(self, coordinator: SourceCoordinator, subentry_id: str, title: str, key: str) -> None:
        super().__init__(coordinator)
        self._key = key
        self._attr_unique_id = f"{subentry_id}_price"
        self._attr_device_info = subentry_device(subentry_id, title)

    def _derive(self) -> PriceReading:
        return district_heating_network(self.coordinator.data.networks, self._key)


class CustomPriceSensor(_PriceSensor):
    """Von Hand eingetragener Vergleichspreis; der Wert kommt aus der number-Entität desselben Untereintrags."""

    _attr_name = None
    _attr_should_poll = False

    def __init__(self, store: CustomPriceStore, subentry_id: str, title: str, data: dict[str, Any]) -> None:
        self._store = store
        self._data = data
        self._attr_unique_id = f"{subentry_id}_price"
        self._attr_native_unit_of_measurement = data[CONF_UNIT]
        self._attr_device_info = subentry_device(subentry_id, title)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._store.add_listener(self.async_write_ha_state))

    @property
    def native_value(self) -> float | None:
        return self._store.value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        reading = None if self._store.value is None else PriceReading(self._store.value, self._store.as_of)
        # Der eingetragene Preis ist der Arbeitspreis; ein Grundpreis steht getrennt in `annual_base_fee`.
        attrs = contract_attributes(self._data[CONF_HEATING_SYSTEM], CUSTOM_PRICE_SOURCE, "local", reading, False)
        if self._data.get(CONF_ANNUAL_BASE_FEE) is not None:
            attrs[ATTR_ANNUAL_BASE_FEE] = float(self._data[CONF_ANNUAL_BASE_FEE])
        return attrs

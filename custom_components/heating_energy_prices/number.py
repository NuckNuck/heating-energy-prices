"""Eingabefeld für einen von Hand eingetragenen Vergleichspreis (Untereintrag „Eigener Preis“)."""

from __future__ import annotations

from datetime import date
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from . import CustomPriceStore, HeatingPricesConfigEntry
from .const import ATTR_AS_OF, CONF_UNIT, SUBENTRY_CUSTOM_PRICE
from .sensor import subentry_device


async def async_setup_entry(hass: HomeAssistant, entry: HeatingPricesConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    for sub in entry.subentries.values():
        if sub.subentry_type == SUBENTRY_CUSTOM_PRICE:
            async_add_entities([CustomPriceNumber(entry.runtime_data.custom_prices[sub.subentry_id], sub.subentry_id,
                                                  sub.title, sub.data[CONF_UNIT])],
                               config_subentry_id=sub.subentry_id)


class CustomPriceNumber(NumberEntity, RestoreEntity):
    """Preis eintragen; Stand ist der Tag der letzten Eingabe. Wert und Stand überstehen einen Neustart."""

    _attr_has_entity_name = True
    _attr_translation_key = "custom_price"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0
    _attr_native_max_value = 100000
    _attr_native_step = 0.0001
    _attr_should_poll = False

    def __init__(self, store: CustomPriceStore, subentry_id: str, title: str, unit: str) -> None:
        self._store = store
        self._attr_unique_id = f"{subentry_id}_input"
        self._attr_native_unit_of_measurement = unit
        self._attr_device_info = subentry_device(subentry_id, title)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is None:
            return
        try:
            value = float(last.state)
        except ValueError:
            return
        as_of = last.attributes.get(ATTR_AS_OF)
        self._store.set(value, date.fromisoformat(as_of) if isinstance(as_of, str) else None)

    @property
    def native_value(self) -> float | None:
        return self._store.value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {ATTR_AS_OF: self._store.as_of.isoformat()} if self._store.as_of else {}

    async def async_set_native_value(self, value: float) -> None:
        self._store.set(value, dt_util.now().date())
        self.async_write_ha_state()

"""Einrichtung: Land und Intervall, dann Quellen. Untereinträge „Fernwärmenetz“ und „Eigener Preis“."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (ConfigEntry, ConfigFlow, ConfigFlowResult, ConfigSubentryFlow,
                                          OptionsFlow as BaseOptionsFlow, SubentryFlowResult)
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (CONF_ANNUAL_BASE_FEE, CONF_CITY, CONF_COUNTRY, CONF_DEPI_REGION, CONF_HEATING_SYSTEM, CONF_NAME,
                    CONF_NETWORK_KEY, CONF_SOURCES, CONF_STATE, CONF_UNIT, CONF_UPDATE_INTERVAL_HOURS,
                    CUSTOM_PRICE_SYSTEMS, DEFAULT_UPDATE_INTERVAL_HOURS, DOMAIN, MAX_UPDATE_INTERVAL_HOURS,
                    MIN_UPDATE_INTERVAL_HOURS, SOURCE_DEPI_PELLETS, SUBENTRY_CUSTOM_PRICE,
                    SUBENTRY_DISTRICT_HEATING_NETWORK, UNITS_BY_SYSTEM, sources_for_country)
from .coordinator import async_fetch_district_heating
from .sources import DEPI_REGIONS, DistrictHeatingNetwork, SourceError

TITLE = "Heizenergiepreise"


def _country_schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema({
        vol.Required(CONF_COUNTRY, default=defaults.get(CONF_COUNTRY) or vol.UNDEFINED): selector.CountrySelector(),
        vol.Required(CONF_UPDATE_INTERVAL_HOURS,
                     default=defaults.get(CONF_UPDATE_INTERVAL_HOURS, DEFAULT_UPDATE_INTERVAL_HOURS)):
            selector.NumberSelector(selector.NumberSelectorConfig(
                min=MIN_UPDATE_INTERVAL_HOURS, max=MAX_UPDATE_INTERVAL_HOURS, step=1, unit_of_measurement="h",
                mode=selector.NumberSelectorMode.BOX)),
    })


def _sources_schema(country: str, defaults: dict[str, Any]) -> vol.Schema:
    available = sources_for_country(country)
    selected = [s for s in defaults.get(CONF_SOURCES, available) if s in available]
    schema: dict[Any, Any] = {
        vol.Required(CONF_SOURCES, default=selected): selector.SelectSelector(selector.SelectSelectorConfig(
            options=available, multiple=True, mode=selector.SelectSelectorMode.LIST, translation_key="source")),
    }
    if SOURCE_DEPI_PELLETS in available:
        schema[vol.Required(CONF_DEPI_REGION, default=defaults.get(CONF_DEPI_REGION, "germany"))] = \
            selector.SelectSelector(selector.SelectSelectorConfig(options=list(DEPI_REGIONS),
                                                                  translation_key="depi_region"))
    return vol.Schema(schema)


def _clean(user_input: dict[str, Any]) -> dict[str, Any]:
    out = dict(user_input)
    out[CONF_UPDATE_INTERVAL_HOURS] = int(out[CONF_UPDATE_INTERVAL_HOURS])
    return out


class HeatingEnergyPricesConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._options: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        errors: dict[str, str] = {}
        if user_input is not None:
            if sources_for_country(user_input[CONF_COUNTRY]):
                self._options = _clean(user_input)
                return await self.async_step_sources()
            errors[CONF_COUNTRY] = "no_sources"
        defaults = user_input or {CONF_COUNTRY: self.hass.config.country}
        return self.async_show_form(step_id="user", data_schema=_country_schema(defaults), errors=errors)

    async def async_step_sources(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title=TITLE, data={}, options=self._options | user_input)
        return self.async_show_form(step_id="sources",
                                    data_schema=_sources_schema(self._options[CONF_COUNTRY], {}))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return OptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(cls, config_entry: ConfigEntry) -> dict[str, type[ConfigSubentryFlow]]:
        types: dict[str, type[ConfigSubentryFlow]] = {SUBENTRY_CUSTOM_PRICE: CustomPriceSubentryFlow}
        if config_entry.options.get(CONF_COUNTRY) == "DE":
            types[SUBENTRY_DISTRICT_HEATING_NETWORK] = DistrictHeatingNetworkSubentryFlow
        return types


class OptionsFlow(BaseOptionsFlow):
    """Land, Intervall und Quellen nachträglich ändern (das Neuladen übernimmt der Update-Listener)."""

    def __init__(self) -> None:
        self._options: dict[str, Any] = {}

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if sources_for_country(user_input[CONF_COUNTRY]):
                self._options = dict(self.config_entry.options) | _clean(user_input)
                return await self.async_step_sources()
            errors[CONF_COUNTRY] = "no_sources"
        defaults = user_input or dict(self.config_entry.options)
        return self.async_show_form(step_id="init", data_schema=_country_schema(defaults), errors=errors)

    async def async_step_sources(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=self._options | user_input)
        return self.async_show_form(step_id="sources",
                                    data_schema=_sources_schema(self._options[CONF_COUNTRY], self._options))


def _select(options: list[str] | list[selector.SelectOptionDict]) -> selector.SelectSelector:
    return selector.SelectSelector(selector.SelectSelectorConfig(options=options,
                                                                 mode=selector.SelectSelectorMode.DROPDOWN))


class DistrictHeatingNetworkSubentryFlow(ConfigSubentryFlow):
    """Eigenes Fernwärmenetz aus der Liste der Preistransparenzplattform wählen: Bundesland → Stadt → Teilnetz."""

    def __init__(self) -> None:
        self._networks: list[DistrictHeatingNetwork] = []
        self._state = ""
        self._city = ""

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        if not self._networks:
            try:
                self._networks = [n for n in (await async_fetch_district_heating(self.hass)).networks
                                  if n.price is not None]
            except SourceError:
                return self.async_abort(reason="cannot_connect")
        if user_input is not None:
            self._state = user_input[CONF_STATE]
            return await self.async_step_city()
        states = sorted({n.state for n in self._networks if n.state})
        return self.async_show_form(step_id="user", data_schema=vol.Schema({vol.Required(CONF_STATE): _select(states)}))

    async def async_step_city(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        if user_input is not None:
            self._city = user_input[CONF_CITY]
            return await self.async_step_network()
        cities = sorted({n.city for n in self._networks if n.state == self._state})
        return self.async_show_form(step_id="city", data_schema=vol.Schema({vol.Required(CONF_CITY): _select(cities)}),
                                    description_placeholders={"state": self._state})

    async def async_step_network(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        candidates = {n.key: n for n in self._networks if n.state == self._state and n.city == self._city}
        if user_input is not None:
            network = candidates[user_input[CONF_NETWORK_KEY]]
            for sub in self._get_entry().subentries.values():
                if sub.unique_id == network.key:
                    return self.async_abort(reason="already_configured")
            return self.async_create_entry(title=f"Fernwärme {network.city} {network.network}".strip(),
                                           data={CONF_NETWORK_KEY: network.key}, unique_id=network.key)
        options = [selector.SelectOptionDict(value=key, label=f"{n.company} – {n.network} ({n.price:.2f} ct/kWh)")
                   for key, n in sorted(candidates.items(), key=lambda item: (item[1].company, item[1].network))]
        return self.async_show_form(step_id="network",
                                    data_schema=vol.Schema({vol.Required(CONF_NETWORK_KEY): _select(options)}),
                                    description_placeholders={"city": self._city})


class CustomPriceSubentryFlow(ConfigSubentryFlow):
    """Eigener Vergleichspreis: Name und System, dann Einheit und optional ein Grundpreis."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        if user_input is not None:
            self._data = dict(user_input)
            return await self.async_step_details()
        return self.async_show_form(step_id="user", data_schema=vol.Schema({
            vol.Required(CONF_NAME): selector.TextSelector(),
            vol.Required(CONF_HEATING_SYSTEM): selector.SelectSelector(selector.SelectSelectorConfig(
                options=CUSTOM_PRICE_SYSTEMS, translation_key="heating_system")),
        }))

    async def async_step_details(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        if user_input is not None:
            data = self._data | user_input
            return self.async_create_entry(title=data.pop(CONF_NAME), data=data)
        return self.async_show_form(step_id="details", data_schema=self._details_schema(self._data))

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        subentry = self._get_reconfigure_subentry()
        if user_input is not None:
            data = {CONF_HEATING_SYSTEM: subentry.data[CONF_HEATING_SYSTEM]} | user_input
            return self.async_update_and_abort(self._get_entry(), subentry, data=data)
        return self.async_show_form(step_id="reconfigure", data_schema=self._details_schema(dict(subentry.data)))

    @staticmethod
    def _details_schema(data: dict[str, Any]) -> vol.Schema:
        units = UNITS_BY_SYSTEM[data[CONF_HEATING_SYSTEM]]
        base_fee = data.get(CONF_ANNUAL_BASE_FEE)
        return vol.Schema({
            vol.Required(CONF_UNIT, default=data.get(CONF_UNIT, units[0])): _select(units),
            vol.Optional(CONF_ANNUAL_BASE_FEE, description={"suggested_value": base_fee}):
                selector.NumberSelector(selector.NumberSelectorConfig(
                    min=0, max=10000, step=0.01, unit_of_measurement="€/a", mode=selector.NumberSelectorMode.BOX)),
        })

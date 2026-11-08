"""Konstanten der Integration Heizenergiepreise."""

from __future__ import annotations

from .sources import EUROSTAT_GAS_COUNTRIES, OIL_BULLETIN_COUNTRIES

DOMAIN = "heating_energy_prices"

CONF_COUNTRY = "country"
CONF_UPDATE_INTERVAL_HOURS = "update_interval_hours"
CONF_SOURCES = "sources"
CONF_DEPI_REGION = "depi_region"
DEFAULT_UPDATE_INTERVAL_HOURS = 24
MIN_UPDATE_INTERVAL_HOURS = 1
MAX_UPDATE_INTERVAL_HOURS = 24 * 7

# Quellen (ein Sensor je Quelle)
SOURCE_OIL_BULLETIN = "oil_bulletin"
SOURCE_EUROSTAT_GAS = "eurostat_gas"
SOURCE_DEPI_PELLETS = "depi_pellets"
SOURCE_DISTRICT_HEATING_MEAN = "district_heating_mean"

# Untereinträge
SUBENTRY_DISTRICT_HEATING_NETWORK = "district_heating_network"
SUBENTRY_CUSTOM_PRICE = "custom_price"
CONF_NETWORK_KEY = "network_key"
CONF_STATE = "state"
CONF_CITY = "city"
CONF_NAME = "name"
CONF_HEATING_SYSTEM = "heating_system"
CONF_UNIT = "unit"
CONF_ANNUAL_BASE_FEE = "annual_base_fee"

# Vertrag der Preis-Sensoren (Spezifikation 7.3 des Luft-Wasser-Wärmepumpen-Audits)
ATTR_HEATING_SYSTEM = "heating_system"
ATTR_SOURCE = "source"
ATTR_SOURCE_KIND = "source_kind"
ATTR_AS_OF = "as_of"
ATTR_INCLUDES_FIXED_CHARGES = "includes_fixed_charges"
ATTR_ANNUAL_BASE_FEE = "annual_base_fee"

HEATING_OIL = "heating_oil"
NATURAL_GAS = "natural_gas"
WOOD_PELLETS = "wood_pellets"
DISTRICT_HEATING = "district_heating"

# Einheiten je System, wie sie das Audit versteht
_ENERGY_UNITS = ["ct/kWh", "€/kWh", "€/MWh"]
UNITS_BY_SYSTEM: dict[str, list[str]] = {
    HEATING_OIL: ["ct/L", "€/L", "€/100 L", "€/1000 L", *_ENERGY_UNITS],
    NATURAL_GAS: list(_ENERGY_UNITS),
    WOOD_PELLETS: ["€/t", "€/kg", *_ENERGY_UNITS],
    DISTRICT_HEATING: list(_ENERGY_UNITS),
}
# Direktstrom fehlt bewusst: Das Audit rechnet ihn aus dem eigenen Haushaltsstrompreis.
CUSTOM_PRICE_SYSTEMS = list(UNITS_BY_SYSTEM)

# Je Quelle: System, Art, Einheit, Quellenangabe, Fixanteile enthalten?, abgedeckte Länder
SOURCES: dict[str, dict] = {
    SOURCE_OIL_BULLETIN: {
        "system": HEATING_OIL, "kind": "official", "unit": "€/1000 L", "fixed_charges": False,
        "source": "EU Weekly Oil Bulletin (Europäische Kommission)", "countries": frozenset(OIL_BULLETIN_COUNTRIES),
    },
    SOURCE_EUROSTAT_GAS: {
        "system": NATURAL_GAS, "kind": "official", "unit": "€/kWh", "fixed_charges": True,
        "source": "Eurostat nrg_pc_202, Haushalte Band D2", "countries": EUROSTAT_GAS_COUNTRIES,
    },
    SOURCE_DEPI_PELLETS: {
        "system": WOOD_PELLETS, "kind": "association", "unit": "€/t", "fixed_charges": False,
        "source": "Deutsches Pelletinstitut GmbH (DEPI)", "countries": frozenset({"DE"}),
    },
    SOURCE_DISTRICT_HEATING_MEAN: {
        "system": DISTRICT_HEATING, "kind": "association", "unit": "ct/kWh", "fixed_charges": True,
        "source": "waermepreise.info (AGFW, BDEW, VKU)", "countries": frozenset({"DE"}),
    },
}
DISTRICT_HEATING_SOURCE = SOURCES[SOURCE_DISTRICT_HEATING_MEAN]["source"]


def sources_for_country(country: str | None) -> list[str]:
    """Quellen, die ein Land abdecken, in fester Reihenfolge."""
    return [key for key, spec in SOURCES.items() if country in spec["countries"]]

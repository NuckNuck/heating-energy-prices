"""Preisquellen: Abruf-Adressen, Länderabdeckung und Parser. Ohne Home-Assistant-Abhängigkeit.

Jeder Parser bekommt die Rohdaten einer Quelle und liefert einen `PriceReading` (Preis, Stand, Zusatzangaben) oder
wirft `SourceError`, wenn der erwartete Wert fehlt. Werte werden nie geschätzt oder aus älteren Abrufen ergänzt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from html.parser import HTMLParser
import json
import re
import statistics

from .xlsx import XlsxError, excel_date, read_rows


class SourceError(ValueError):
    """Die Quelle liefert den erwarteten Wert nicht (Format geändert, Land fehlt, Seite leer …)."""


@dataclass(frozen=True)
class PriceReading:
    """Ein Preis mit Stand. `extra` landet als zusätzliche Attribute am Sensor."""

    value: float
    as_of: date | None
    extra: dict = field(default_factory=dict)


# --- EU Weekly Oil Bulletin -----------------------------------------------------------------------------------------

OIL_BULLETIN_URL = "https://energy.ec.europa.eu/document/download/264c2d0f-f161-4ea3-a777-78faae59bea0_en"

# Ländernamen in der Datei (englisch) je ISO-3166-Code. BG, NL und SK melden kein Heizöl.
OIL_BULLETIN_COUNTRIES = {
    "AT": "Austria", "BE": "Belgium", "HR": "Croatia", "CY": "Cyprus", "CZ": "Czechia", "DK": "Denmark",
    "EE": "Estonia", "FI": "Finland", "FR": "France", "DE": "Germany", "GR": "Greece", "HU": "Hungary",
    "IE": "Ireland", "IT": "Italy", "LV": "Latvia", "LT": "Lithuania", "LU": "Luxembourg", "MT": "Malta",
    "PL": "Poland", "PT": "Portugal", "RO": "Romania", "SI": "Slovenia", "ES": "Spain", "SE": "Sweden",
}


def parse_oil_bulletin(data: bytes, country: str) -> PriceReading:
    """Heizölpreis mit Steuern in €/1000 L für ein Land; Stand = Stichtag in Zelle A2."""
    name = OIL_BULLETIN_COUNTRIES.get(country)
    if name is None:
        raise SourceError(f"Oil Bulletin deckt {country} nicht ab")
    try:
        rows = read_rows(data)
    except XlsxError as err:
        raise SourceError(f"Oil Bulletin nicht lesbar: {err}") from err
    if len(rows) < 3:
        raise SourceError("Oil Bulletin ohne Datenzeilen")
    column = next((col for col, text in rows[0].items() if "heating gas oil" in text.lower()), None)
    if column is None:
        raise SourceError("Oil Bulletin ohne Spalte Heizöl")
    for row in rows[2:]:
        if row.get("A", "").strip() == name:
            value = _number(row.get(column))
            if value is None:
                raise SourceError(f"Oil Bulletin ohne Heizölpreis für {country}")
            return PriceReading(round(value, 2), excel_date(rows[1].get("A")))
    raise SourceError(f"Oil Bulletin ohne Zeile für {country}")


# --- Eurostat nrg_pc_202 (Erdgas, Haushalte) -----------------------------------------------------------------------

# Eurostat weicht bei Griechenland und dem Vereinigten Königreich vom ISO-Code ab.
_EUROSTAT_GEO = {"GR": "EL", "GB": "UK"}
EUROSTAT_GAS_COUNTRIES = frozenset({
    "BE", "BG", "CZ", "DK", "DE", "EE", "IE", "GR", "ES", "FR", "HR", "IT", "LV", "LT", "LU", "HU", "NL", "AT", "PL",
    "PT", "RO", "SI", "SK", "FI", "SE", "LI", "GB", "BA", "MD", "MK", "GE", "AL", "RS", "TR", "UA",
})


def eurostat_gas_url(country: str) -> str:
    """Abfrage Band D2 (20–200 GJ), alle Steuern und Abgaben, EUR/kWh, die letzten zwei Halbjahre."""
    geo = _EUROSTAT_GEO.get(country, country)
    return ("https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/nrg_pc_202?format=JSON&lang=en"
            f"&geo={geo}&nrg_cons=GJ20-199&tax=I_TAX&currency=EUR&unit=KWH&lastTimePeriod=2")


def parse_eurostat(data: bytes) -> PriceReading:
    """Jüngster vorhandene Halbjahreswert aus einer JSON-stat-Antwort mit genau einem Wert je Zeitraum.

    Stand = letzter Tag des Halbjahres; die Periode (z. B. „2026-S1“) steht zusätzlich als `period`.
    """
    try:
        doc = json.loads(data)
        ids, sizes, values = doc["id"], doc["size"], doc.get("value", {})
        periods = doc["dimension"]["time"]["category"]["index"]
    except (ValueError, KeyError, TypeError) as err:
        raise SourceError(f"Eurostat-Antwort nicht lesbar: {err}") from err
    if any(size != 1 for dim, size in zip(ids, sizes) if dim != "time"):
        raise SourceError("Eurostat-Antwort mit mehreren Werten je Zeitraum")
    stride = 1
    for dim, size in reversed(list(zip(ids, sizes))):
        if dim == "time":
            break
        stride *= size
    if isinstance(values, list):
        values = {str(i): v for i, v in enumerate(values) if v is not None}
    for period, index in sorted(periods.items(), key=lambda item: item[1], reverse=True):
        value = values.get(str(index * stride))
        if value is not None:
            return PriceReading(float(value), _half_year_end(period), {"period": period})
    raise SourceError("Eurostat-Antwort ohne Wert")


def _half_year_end(period: str) -> date | None:
    match = re.fullmatch(r"(\d{4})-S([12])", period)
    if not match:
        return None
    year = int(match.group(1))
    return date(year, 6, 30) if match.group(2) == "1" else date(year, 12, 31)


# --- DEPI (Holzpellets) -------------------------------------------------------------------------------------------

DEPI_URL = "https://www.depi.de/pelletpreis-wirtschaftlichkeit/"
DEPI_REGIONS = ("germany", "north_east", "central", "south")
_DEPI_REGION_HEADERS = {"north_east": "Nord/Ost", "central": "Mitte", "south": "Süd"}
_MONTHS = {name: i + 1 for i, name in enumerate(
    ("Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November",
     "Dezember"))}


class _TableParser(HTMLParser):
    """Sammelt alle Tabellen als Liste von Zeilen mit Zelltexten."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._depth = 0
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "table":
            self._depth += 1
            if self._depth == 1:
                self.tables.append([])
        elif self._depth == 1 and tag == "tr":
            self._row = []
        elif self._depth == 1 and tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "table":
            self._depth = max(0, self._depth - 1)
        elif self._depth == 1 and tag in ("td", "th") and self._row is not None and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif self._depth == 1 and tag == "tr" and self._row is not None:
            self.tables[-1].append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)


def _tables(html: str) -> list[list[list[str]]]:
    parser = _TableParser()
    parser.feed(html)
    return parser.tables


def _number(text: str | None) -> float | None:
    """Zahl aus Text; deutsches Komma oder Punkt, Tausenderpunkt bei Komma-Dezimalen."""
    if text is None:
        return None
    match = re.search(r"-?\d[\d.]*,\d+|-?\d+(?:\.\d+)?", text.replace("\xa0", " "))
    if not match:
        return None
    raw = match.group(0)
    return float(raw.replace(".", "").replace(",", ".") if "," in raw else raw)


def _month(label: str) -> date | None:
    match = re.search(r"([A-Za-zäöüÄÖÜ]+)\s+(\d{4})", label)
    if not match or match.group(1) not in _MONTHS:
        return None
    return date(int(match.group(2)), _MONTHS[match.group(1)], 1)


def parse_depi(html: str, region: str = "germany") -> PriceReading:
    """Pelletpreis bei 6 t Liefermenge in €/t (inkl. MwSt.); Stand = Erhebungsmonat (Monatserster).

    `germany` nimmt den Bundesdurchschnitt, sonst die Spalte der Region im jüngsten Monat der 6-t-Gruppe.
    """
    if region not in DEPI_REGIONS:
        raise SourceError(f"Unbekannte DEPI-Region {region}")
    tables = _tables(html)
    if region == "germany":
        for table in tables:
            month = _month(table[0][0]) if table and table[0] else None
            for row in table[1:]:
                if len(row) >= 2 and row[0].startswith("Pelletpreis 6 Tonnen"):
                    value = _number(row[1])
                    if value is not None:
                        return PriceReading(value, month)
        raise SourceError("DEPI-Seite ohne 6-t-Preis")
    header = _DEPI_REGION_HEADERS[region]
    for table in tables:
        if not table or header not in table[0]:
            continue
        column = table[0].index(header)
        group, latest = None, None
        for row in table[1:]:
            if row and re.fullmatch(r"\d+ t", row[0]):
                group = row[0]
            elif group == "6 t" and len(row) > column and _number(row[column]) is not None:
                latest = (_number(row[column]), _month(row[0]))
        if latest is not None:
            return PriceReading(latest[0], latest[1])
    raise SourceError(f"DEPI-Seite ohne 6-t-Preis für Region {region}")


# --- waermepreise.info (Fernwärme) --------------------------------------------------------------------------------

DISTRICT_HEATING_ARCHIVE_URL = "https://www.waermepreise.info/download-archiv/"
_ARCHIVE_LINK = re.compile(
    r"Stichtag\s+(\d{1,2})\.(\d{1,2})\.(\d{4})\s*:?\s*(?:</strong>\s*)?<a[^>]*href=\"([^\"]+\.xlsx)\"", re.I)
_COLUMNS = {"state": "Bundesland", "city": "Stadt", "company": "Unternehmen", "network": "Teilnetz",
            "price": "EFH in ct/kWh (brutto)", "as_of": "Preisstand"}


@dataclass(frozen=True)
class DistrictHeatingNetwork:
    """Ein Teilnetz der Preistransparenzplattform mit Mischpreis Einfamilienhaus (ct/kWh, brutto)."""

    state: str
    city: str
    company: str
    network: str
    price: float | None
    as_of: date | None

    @property
    def key(self) -> str:
        """Stabile Kennung über Stichtage hinweg."""
        return "|".join((self.state, self.city, self.company, self.network))


def latest_archive_file(html: str) -> tuple[str, date]:
    """Adresse und Stichtag der jüngsten XLSX im Download-Archiv (CSV-Ausgaben werden übergangen)."""
    links = [(date(int(y), int(m), int(d)), url) for d, m, y, url in _ARCHIVE_LINK.findall(html)]
    if not links:
        raise SourceError("Download-Archiv ohne XLSX-Link")
    stichtag, url = max(links)
    return url, stichtag


def parse_district_heating_table(data: bytes) -> list[DistrictHeatingNetwork]:
    """Alle Teilnetze der Tabelle; Spalten werden über die Kopfzeile gefunden."""
    try:
        rows = read_rows(data)
    except XlsxError as err:
        raise SourceError(f"Fernwärme-Tabelle nicht lesbar: {err}") from err
    if not rows:
        raise SourceError("Fernwärme-Tabelle leer")
    header = {text.strip(): col for col, text in rows[0].items()}
    missing = [name for name in _COLUMNS.values() if name not in header]
    if missing:
        raise SourceError(f"Fernwärme-Tabelle ohne Spalten {missing}")
    col = {key: header[name] for key, name in _COLUMNS.items()}
    networks = []
    for row in rows[1:]:
        if not row.get(col["company"]):
            continue
        price = _number(row.get(col["price"]))
        networks.append(DistrictHeatingNetwork(
            state=row.get(col["state"], "").strip(), city=row.get(col["city"], "").strip(),
            company=row.get(col["company"], "").strip(), network=row.get(col["network"], "").strip(),
            price=price if price is not None and price > 0 else None, as_of=excel_date(row.get(col["as_of"]))))
    if not networks:
        raise SourceError("Fernwärme-Tabelle ohne Teilnetze")
    return networks


def district_heating_mean(networks: list[DistrictHeatingNetwork], stichtag: date | None) -> PriceReading:
    """Ungewichteter Mittelwert der EFH-Mischpreise aller Teilnetze mit Preis."""
    prices = [n.price for n in networks if n.price is not None]
    if not prices:
        raise SourceError("Fernwärme-Tabelle ohne Preise")
    return PriceReading(round(statistics.fmean(prices), 2), stichtag,
                        {"sample_size": len(prices), "weighting": "unweighted"})


def district_heating_network(networks: list[DistrictHeatingNetwork], key: str) -> PriceReading:
    """Preis eines Teilnetzes; Stand = dessen Preisstand."""
    for network in networks:
        if network.key == key:
            if network.price is None:
                raise SourceError(f"Teilnetz {key} ohne Preis")
            return PriceReading(network.price, network.as_of,
                                {"company": network.company, "network": network.network, "city": network.city})
    raise SourceError(f"Teilnetz {key} nicht mehr in der Tabelle")

"""Minimaler XLSX-Leser ohne Zusatzpakete (zipfile + ElementTree).

Liest das erste Tabellenblatt als Liste von Zeilen; jede Zeile ist ein dict Spaltenbuchstabe → Zellwert (Text oder
Zahl als Text). Formeln werden nicht ausgewertet, es zählt der gespeicherte Wert.
"""

from __future__ import annotations

from datetime import date, timedelta
import io
import re
import xml.etree.ElementTree as ET
import zipfile

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_EXCEL_EPOCH = date(1899, 12, 30)


class XlsxError(ValueError):
    """Die Datei ist kein lesbares XLSX."""


def _column(ref: str) -> str:
    match = re.match(r"[A-Z]+", ref or "")
    return match.group(0) if match else ""


def _first_sheet_path(archive: zipfile.ZipFile) -> str:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    sheet = next(workbook.iter(f"{_NS}sheet"), None)
    if sheet is None:
        raise XlsxError("Arbeitsmappe ohne Tabellenblatt")
    rel_id = sheet.get(f"{_REL_NS}id")
    rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    for rel in rels:
        if rel.get("Id") == rel_id:
            target = rel.get("Target", "").lstrip("/")
            return target if target.startswith("xl/") else f"xl/{target}"
    raise XlsxError("Tabellenblatt nicht gefunden")


def read_rows(data: bytes) -> list[dict[str, str]]:
    """Zeilen des ersten Tabellenblatts; leere Zellen fehlen im dict."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            for item in ET.fromstring(archive.read("xl/sharedStrings.xml")).findall(f"{_NS}si"):
                shared.append("".join(t.text or "" for t in item.iter(f"{_NS}t")))
        sheet = ET.fromstring(archive.read(_first_sheet_path(archive)))
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as err:
        raise XlsxError(str(err)) from err
    rows: list[dict[str, str]] = []
    for row in sheet.iter(f"{_NS}row"):
        cells: dict[str, str] = {}
        for cell in row.findall(f"{_NS}c"):
            kind = cell.get("t")
            if kind == "inlineStr":
                value = "".join(t.text or "" for t in cell.iter(f"{_NS}t"))
            else:
                node = cell.find(f"{_NS}v")
                if node is None or node.text is None:
                    continue
                value = shared[int(node.text)] if kind == "s" else node.text
            if value.strip():
                cells[_column(cell.get("r", ""))] = value
        rows.append(cells)
    return rows


def excel_date(value: str | None) -> date | None:
    """Excel-Seriennummer (z. B. „46328“) als Datum; None, wenn der Wert keine Zahl ist."""
    try:
        return _EXCEL_EPOCH + timedelta(days=int(float(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None

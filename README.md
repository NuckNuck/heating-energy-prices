# Heizenergiepreise für Home Assistant

Diese Integration stellt Brennstoffpreise anderer Heizsysteme als Sensoren bereit: Heizöl, Erdgas, Holzpellets und
Fernwärme. Sie ist für Wärmekosten-Vergleiche gedacht, zum Beispiel im
[Luft-Wasser-Wärmepumpen-Audit](https://github.com/NuckNuck/air-water-heatpump-audit). Das Audit erkennt die
Sensoren selbst und zeigt sie im Kosten-Zeitstrahl als gestrichelte Vergleichslinien.

Die Preise kommen ausschließlich aus amtlichen Quellen und von Verbänden. Kommerzielle Preisportale sind bewusst nicht
eingebunden: Ihre Nutzungsbedingungen verbieten den automatisierten Abruf.

## Quellen

| Sensor | System | Quelle | Art | Takt | Einheit | Länder |
|---|---|---|---|---|---|---|
| Heizöl (EU Weekly Oil Bulletin) | Heizöl | Europäische Kommission, Preise mit Steuern | amtlich | wöchentlich | €/1000 L | EU außer BG, NL, SK |
| Erdgas (Eurostat) | Erdgas | Eurostat `nrg_pc_202`, Haushalte Band D2 (20–200 GJ/a), alle Steuern und Abgaben | amtlich | halbjährlich | €/kWh | EU und weitere europäische Länder |
| Holzpellets (DEPI) | Holzpellets | Deutsches Pelletinstitut, 6 t, inkl. MwSt. | Verband | monatlich | €/t | Deutschland |
| Fernwärme (Bundesmittel waermepreise.info) | Fernwärme | Preistransparenzplattform von AGFW, BDEW und VKU, Mischpreis Einfamilienhaus, ungewichtetes Mittel aller Netze | Verband | monatlich | ct/kWh | Deutschland |
| Fernwärme *Netz* (Untereintrag) | Fernwärme | dieselbe Plattform, Mischpreis des gewählten Netzes | Verband | monatlich | ct/kWh | Deutschland |
| *Eigener Preis* (Untereintrag) | frei wählbar | von Hand eingetragen | lokal | bei jeder Eingabe | frei wählbar | alle |

**Grundpreis:** Der Eurostat-Gaspreis und die Fernwärme-Mischpreise enthalten Grundpreis und Messkosten schon. Diese
Sensoren tragen deshalb `includes_fixed_charges: true`. Heizöl und Pellets haben keinen Grundpreis. Beim eigenen
Preis wird der Arbeitspreis eingetragen und ein Grundpreis getrennt angegeben.

Stromdirektheizung fehlt bewusst: Das Audit rechnet sie aus dem eigenen Haushaltsstrompreis.

Quellenangabe Holzpellets: Deutsches Pelletinstitut GmbH (DEPI). Fernwärme: waermepreise.info (AGFW, BDEW, VKU).
Jede Installation ruft die Daten selbst für den privaten Gebrauch ab.

## Installation

1. HACS → Integrationen → Menü → Benutzerdefinierte Repositories → `https://github.com/NuckNuck/heating-energy-prices`,
   Kategorie Integration.
2. „Heizenergiepreise“ installieren und Home Assistant neu starten.
3. Einstellungen → Geräte & Dienste → Integration hinzufügen → „Heizenergiepreise“.

## Einrichtung

1. **Land und Abfrageintervall.** Das Land kommt aus der HA-Konfiguration und lässt sich ändern. Das Intervall gilt
   für alle Quellen, Standard ist einmal täglich. Häufiger lohnt nicht: Die Quellen ändern sich wöchentlich bis
   halbjährlich.
2. **Quellen.** Angeboten werden nur Quellen, die das Land abdecken. Jede gewählte Quelle wird ein Sensor. Wer nur
   den Heizölpreis vergleichen will, wählt nur das Oil Bulletin. Bei Pellets lässt sich die Region wählen.
3. **Fernwärmenetz** (optional, nur Deutschland): In der Integration „Fernwärmenetz hinzufügen“ und nacheinander
   Bundesland, Stadt und Netz auswählen.
4. **Eigener Preis** (optional): „Eigenen Preis hinzufügen“, Name und Heizsystem angeben, dann Einheit und
   gegebenenfalls den Grundpreis pro Jahr. Den Preis selbst trägt man danach im Eingabefeld des neuen Geräts ein.
   Der Tag der Eingabe wird als Stand gespeichert. Gedacht ist das für Angebote oder den Preis des früheren Vertrags.

Optionen (Land, Intervall, Quellen) lassen sich über „Konfigurieren“ jederzeit ändern.

Scheitert ein Abruf, ist der Sensor „nicht verfügbar“. Es wird nie ein geschätzter oder veralteter Wert angezeigt.

## Eigene Händlerseite anbinden (für Fortgeschrittene)

Den Preis eines örtlichen Händlers kann man mit der eingebauten HA-Integration
[Scrape](https://www.home-assistant.io/integrations/scrape/) auslesen, sofern die Seite den Preis ohne JavaScript
ausliefert und ihre Nutzungsbedingungen das erlauben. Damit das Audit den Sensor erkennt, braucht er das Attribut
`heating_system`, das man per `customize` ergänzt:

```yaml
# configuration.yaml
scrape:
  - resource: https://www.example.com/heizoel
    scan_interval: 86400  # einmal täglich
    sensor:
      - name: Heizöl Händler
        select: ".price"
        value_template: "{{ value | replace('.', '') | replace(',', '.') | float }}"
        unit_of_measurement: "€/100 L"
        state_class: measurement

homeassistant:
  customize:
    sensor.heizol_handler:
      heating_system: heating_oil
      source: Heizöl Händler
      source_kind: local
```

## Für Entwickler

### Sensor-Vertrag

Jeder Preis-Sensor erfüllt den Vertrag aus Abschnitt 7.3 der Spezifikation des Wärmepumpen-Audits:

| Teil | Inhalt |
|---|---|
| `state` | Brennstoffpreis, brutto |
| `unit_of_measurement` | `€/kWh`, `ct/kWh`, `€/MWh` (alle Systeme); `€/L`, `ct/L`, `€/100 L`, `€/1000 L` (nur Heizöl); `€/kg`, `€/t` (nur Holzpellets) |
| `heating_system` | `heating_oil`, `natural_gas`, `wood_pellets`, `district_heating` (Pflicht) |
| `source` | Name der Quelle |
| `source_kind` | `official`, `association`, `commercial`, `local` |
| `as_of` | Stand des Preises, ISO-Datum |
| `includes_fixed_charges` | `true`, wenn der Preis Grundpreis und Messkosten schon enthält |
| `annual_base_fee` | Grundpreis in €/a, falls getrennt angegeben (nur eigener Preis) |

Zusätzliche Attribute je Quelle: `period` (Eurostat, z. B. `2026-S1`), `sample_size` und `weighting` (Fernwärme
Bundesmittel), `company`, `network`, `city` (Fernwärmenetz). Alle Sensoren haben `state_class: measurement`.

`as_of`: Oil Bulletin = Stichtag der Datei; Eurostat = letzter Tag des Halbjahres; DEPI = Erhebungsmonat
(Monatserster); Fernwärme-Bundesmittel = Stichtag der Tabelle, Netz = dessen Preisstand; eigener Preis = Tag der
Eingabe.

### Aufbau

- `sources.py`: Adressen, Länderabdeckung und Parser, ohne HA-Abhängigkeit. XLSX liest `xlsx.py` mit `zipfile`;
  es gibt keine Zusatzpakete.
- `coordinator.py`: ein `DataUpdateCoordinator` je Quelle. Für Fernwärme gibt es einen gemeinsamen Coordinator, der
  die jüngste Tabelle aus dem Download-Archiv lädt, denn die Dateinamen lassen sich nicht vorhersagen.
- `sensor.py`, `number.py`, `config_flow.py`: Entitäten, Einrichtung, Optionen und Untereinträge.

### Tests

```bash
python3.14 -m venv .venv && .venv/bin/pip install pytest-homeassistant-custom-component pytest-cov
.venv/bin/pytest --cov=custom_components/heating_energy_prices
```

Die Parser-Tests laufen gegen echte Abrufe der Quellen vom 08.11.2026 (`tests/fixtures/`). Kein Test greift auf das
Netz zu.

## Lizenz

MIT

# Changelog

Alle nennenswerten Änderungen an dieser Integration. Format nach [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
Versionen nach [Semantic Versioning](https://semver.org/lang/de/).

## [0.1.0] – unveröffentlicht

Erste Version (Issue #1).

### Neu

- Icon für „Geräte & Dienste“ und den Marketplace (Ordner `brand/`, #3); Vorlage `docs/brand/icon.svg`.
- Preis-Sensoren nach dem Vertrag des Luft-Wasser-Wärmepumpen-Audits (Spezifikation 7.3): Attribut
  `heating_system`, dazu `source`, `source_kind`, `as_of` und `includes_fixed_charges`.
- Quellen, je Quelle ein Sensor:
  - Heizöl: EU Weekly Oil Bulletin (amtlich, wöchentlich, €/1000 L mit Steuern).
  - Erdgas: Eurostat `nrg_pc_202`, Haushalte Band D2, alle Steuern und Abgaben (amtlich, halbjährlich, inkl.
    Grundpreis und Messkosten).
  - Holzpellets: Deutsches Pelletinstitut (DEPI), 6 t, Bundesdurchschnitt oder Region (monatlich).
  - Fernwärme: Bundesmittel der Preistransparenzplattform waermepreise.info (ungewichtet, monatlich).
- Untereintrag „Fernwärmenetz“: eigenes Netz aus der Liste von waermepreise.info wählen.
- Untereintrag „Eigener Preis“: Vergleichspreis von Hand eintragen, optional mit Grundpreis pro Jahr.
- Land und Abfrageintervall (Standard einmal täglich) einstellbar; angeboten werden nur Quellen, die das Land
  abdecken.

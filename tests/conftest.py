"""Gemeinsame Fixtures. Aufruf (venv mit homeassistant + pytest-homeassistant-custom-component): pytest

Die Beispieldateien unter `fixtures/` sind echte Abrufe der Quellen vom 08.11.2026 (Archivseite gekürzt auf den
Download-Abschnitt). Tests greifen nie aufs Netz zu.
"""

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Custom Integrations im Test-HA erlauben."""
    yield

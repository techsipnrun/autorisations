"""Même isolation pour pytest, lorsqu'il est installé avec pytest-django."""
from tests.support.isolation import isoler_environnement


def pytest_configure(config):
    config._agida_isolation = isoler_environnement()


def pytest_unconfigure(config):
    isolation = getattr(config, "_agida_isolation", None)
    if isolation:
        isolation.close()

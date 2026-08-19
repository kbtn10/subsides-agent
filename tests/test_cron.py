"""Veille nocturne : câblage du planificateur, sans lancer de vrai scrape."""

import importlib
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
def _reset_cron():
    import cron
    importlib.reload(cron)
    yield
    cron.arreter_cron()


def test_cron_desactive_par_defaut(monkeypatch):
    import cron
    monkeypatch.delenv("CRON_SCRAPE", raising=False)
    cron.demarrer_cron()
    assert cron._scheduler is None       # rien planifié


async def test_cron_active_planifie_un_job(monkeypatch):
    # async : AsyncIOScheduler.start() exige une boucle d'événements active.
    import cron
    monkeypatch.setenv("CRON_SCRAPE", "true")
    monkeypatch.setenv("CRON_SCRAPE_CRON", "0 3 * * *")
    cron.demarrer_cron()
    assert cron._scheduler is not None
    assert cron._scheduler.get_job("scrape_nocturne") is not None


def test_cron_expression_invalide_ne_plante_pas(monkeypatch):
    import cron
    monkeypatch.setenv("CRON_SCRAPE", "true")
    monkeypatch.setenv("CRON_SCRAPE_CRON", "pas une cron")
    cron.demarrer_cron()
    assert cron._scheduler is None       # refusé proprement, pas de crash


async def test_tache_nocturne_saute_si_scrape_en_cours(monkeypatch):
    import cron
    with patch("jobs.job_en_cours", return_value="un-job-id"), \
         patch("jobs.creer_job", new=AsyncMock()) as creer:
        await cron._tache_nocturne()
    creer.assert_not_called()            # n'a pas lancé de second scrape
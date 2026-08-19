"""Veille nocturne : scrape complet chaque nuit, activable via .env.

Réutilise le job de scraping existant tel quel (idempotence + hash déjà prouvés).
Si un scrape manuel tourne déjà, le cron le saute (mécanique 409 existante).
Après le scrape : purge des profils éphémères > 7 jours et log des matchings
invalidés par les fiches modifiées.

.env :
    CRON_SCRAPE=true           # active la veille (défaut : désactivée)
    CRON_SCRAPE_CRON=0 3 * * * # optionnel, expression cron (défaut 03h00)
                               # ex. pour tester : "*/5 * * * *" (toutes les 5 min)
"""

import logging
import os

log = logging.getLogger(__name__)

_scheduler = None
TZ = "Europe/Brussels"


async def _tache_nocturne():
    import jobs
    import profils

    if jobs.job_en_cours():
        log.info("[cron] un scrape tourne déjà — saut de la veille nocturne")
        return

    log.info("[cron] démarrage de la veille nocturne")
    try:
        job_id = await jobs.creer_job()
    except RuntimeError as e:  # course : un scrape a démarré entre-temps
        log.info("[cron] scrape non lancé : %s", e)
        return

    # Attendre la fin du scrape pour enchaîner la purge.
    import asyncio
    job = jobs.get_job(job_id)
    while job and job["statut"] == "running":
        await asyncio.sleep(10)

    rapport = (job or {}).get("rapport") or {}
    invalides = sum(s.get("matchings_invalides", 0) for s in rapport.get("sources", []))
    supprimes = profils.purge_ephemeres(7)
    log.info("[cron] veille terminée : %d matching(s) invalidé(s) par des fiches "
             "modifiées, %d profil(s) éphémère(s) purgé(s)", invalides, supprimes)


def demarrer_cron():
    """Démarre le planificateur si CRON_SCRAPE=true. No-op sinon."""
    global _scheduler
    if os.getenv("CRON_SCRAPE", "").lower() not in ("true", "1", "yes", "oui"):
        log.info("[cron] veille désactivée (CRON_SCRAPE non 'true')")
        return
    if _scheduler is not None:
        return

    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger

    expr = os.getenv("CRON_SCRAPE_CRON", "0 3 * * *")
    try:
        trigger = CronTrigger.from_crontab(expr, timezone=TZ)
    except ValueError:
        log.error("[cron] expression cron invalide '%s' — veille non démarrée", expr)
        return

    _scheduler = AsyncIOScheduler(timezone=TZ)
    _scheduler.add_job(_tache_nocturne, trigger, id="scrape_nocturne",
                       max_instances=1, coalesce=True)
    _scheduler.start()
    log.info("[cron] veille active : '%s' (%s)", expr, TZ)


def arreter_cron():
    global _scheduler
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:  # boucle déjà fermée (ex. en teardown de test) — sans gravité
            pass
        _scheduler = None
        log.info("[cron] planificateur arrêté")

#!/usr/bin/env python3
"""Brulocalis-INDEX : titres (Brulocalis) -> fiche OFFICIELLE (recherche) -> Subsidia.

Brulocalis est protégée par un anti-bot (BunkerWeb) et signale ne pas vouloir de
crawlers de contenu. On l'utilise donc UNIQUEMENT comme index de TITRES (via
Playwright, notre outil standard), puis pour chaque titre on cherche la SOURCE
OFFICIELLE (commune/région/FWB…) et on extrait CELLE-CI — jamais le contenu de
Brulocalis. Les fiches ainsi trouvées entrent TOUJOURS `à vérifier` (la recherche
peut pointer une page périmée : décision du 20/08/2026).

Lancement MANUEL (pas dans le cron nocturne : on ne martèle pas l'anti-bot).
    export SEARCH_API_KEY=...          # clé de l'API de recherche (Brave par défaut)
    python scripts/brulocalis_index.py --limite 10
    python scripts/brulocalis_index.py --dry-run           # titres + URLs trouvées, sans extraire
"""

import argparse
import asyncio
import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

import db  # noqa: E402
from scraper import robots, recherche_web  # noqa: E402
from scraper.fetcher import fermer_browser, user_agent  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(name)-16s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("brulocalis")

UA = "SubsidesAgentBot/0.1 (projet personnel; contact: contact-non-configure)"
# ASBL + appels à projet, la vue la plus utile pour nos utilisateurs.
LISTING = ("https://www.brulocalis.brussels/fr/subsides"
           "?f%5B0%5D=beneficiaires%3A110&f%5B1%5D=type_of_assistance%3A115")
SOURCE = {"id": "brulocalis", "nom": "Brulocalis (index) — sources officielles",
          "delai_secondes": 3.0, "rendu_js": False, "pdf_annexes": True}


def _titres_brulocalis(max_titres: int) -> list[str]:
    """Titres des fiches individuelles via Playwright (passe le challenge JS)."""
    from playwright.sync_api import sync_playwright
    from bs4 import BeautifulSoup
    titres = []
    with sync_playwright() as p:
        b = p.chromium.launch(); ctx = b.new_context(user_agent=UA, locale="fr-BE")
        pg = ctx.new_page()
        pg.goto(LISTING, wait_until="domcontentloaded", timeout=45000)
        pg.wait_for_timeout(33000)   # laisser BunkerWeb passer
        soup = BeautifulSoup(pg.content(), "lxml")
        vus = set()
        for a in soup.find_all("a", href=True):
            if re.match(r"^/fr/subsides/[a-z0-9-]{6,}$", a["href"]):
                t = " ".join(a.get_text().split())
                # on écarte les méta-pages de l'index (calendrier, sessions…)
                if (len(t) > 12 and t not in vus
                        and not re.search(r"calendrier|sessions|synoptiques|base de donn", t, re.I)):
                    vus.add(t); titres.append(t)
        ctx.close(); b.close()
    return titres[:max_titres]


async def main():
    ap = argparse.ArgumentParser(description="Brulocalis-index -> sources officielles.")
    ap.add_argument("--limite", type=int, default=10, help="nb max de titres traités")
    ap.add_argument("--dry-run", action="store_true", help="titres + URLs sans extraire")
    args = ap.parse_args()

    db.init_db()
    from jobs import _traiter_fiche

    log.info("Crawl Brulocalis (index de titres, Playwright)…")
    titres = _titres_brulocalis(args.limite)
    log.info("%d titre(s) récupéré(s)", len(titres))

    ua = user_agent()
    rapport = {k: 0 for k in ("tokens_in", "tokens_out", "a_verifier", "traitees",
                              "extractions", "echecs", "caracteres_pdf", "fiches_avec_pdf",
                              "pdf_exploites", "matchings_invalides", "ignorees_hash",
                              "ignorees_robots")}
    rapport["erreurs"] = []
    trouvees = ingerees = 0

    for titre in titres:
        url = recherche_web.chercher_officiel(titre)
        if not url:
            log.info("  ✗ pas de source officielle : %s", titre[:60]); continue
        trouvees += 1
        print(f"  {titre[:55]:57} -> {url}")
        if args.dry_run:
            continue
        if not robots.autorise(url, ua):
            log.warning("  robots.txt interdit %s — sauté", url); continue
        if db.id_par_url(url):
            log.info("  déjà en base : %s", url); continue
        try:
            await _traiter_fiche(url, SOURCE, rapport, forcer=True)
            sub = db.get_subside(db.id_par_url(url))
            if sub and sub.get("titre"):
                # à vérifier TOUJOURS : la recherche peut pointer une page périmée.
                db.connect().execute(
                    "UPDATE subsides SET a_verifier = 1 WHERE url_source = ?",
                    (db.normaliser_url(url),))
                db.connect().commit()
                ingerees += 1
                log.info("  ✓ [%s] %s", sub.get("nature"), sub["titre"][:55])
        except Exception as e:
            log.error("  KO %s : %s", url, e); rapport["erreurs"].append(f"{url}: {e}")
        await asyncio.sleep(robots.delai_effectif(url, ua, 3.0))

    await fermer_browser()
    log.info("=== Terminé : %d titre(s), %d source(s) officielle(s) trouvée(s), "
             "%d ingérée(s) (à vérifier), %d tokens in / %d out ===",
             len(titres), trouvees, ingerees, rapport["tokens_in"], rapport["tokens_out"])


if __name__ == "__main__":
    asyncio.run(main())

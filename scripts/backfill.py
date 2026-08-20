#!/usr/bin/env python3
"""Ré-extraction ciblée des fiches où un champ donné est vide.

À lancer MANUELLEMENT. Quand on ajoute un champ au schéma (zone au lot 2,
type_beneficiaire au lot 3), les fiches déjà en base ont ce champ vide. Le hash
source les laisserait `inchange` à un re-run normal (jamais ré-extraites). Ce
script force la ré-extraction (en ignorant le hash) UNIQUEMENT pour les fiches où
le champ visé est vide.

Il respecte robots.txt et les délais comme un run normal, et coûte des tokens
(un appel LLM par fiche) — d'où le lancement manuel.

Usage :
    python scripts/backfill.py --champ zone_categorie      # zone (lot 2)
    python scripts/backfill.py --champ type_beneficiaire   # types (lot 3)
    python scripts/backfill.py --champ zone_geographique
    python scripts/backfill.py --champ type_beneficiaire --source cocof --limite 20
    python scripts/backfill.py --champ type_beneficiaire --dry-run
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

import db  # noqa: E402
from config.sources import get_source  # noqa: E402
from scraper import robots  # noqa: E402
from scraper.fetcher import fermer_browser, user_agent  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(name)-16s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("backfill")

# Prédicat "champ vide" par champ : la valeur qui signale l'absence diffère.
VIDE = {
    "zone_categorie": "(zone_categorie IS NULL OR zone_categorie = 'inconnue')",
    "zone_geographique": "(zone_geographique IS NULL OR zone_geographique = '')",
    "type_beneficiaire": "(type_beneficiaire IS NULL OR type_beneficiaire IN ('[]',''))",
    "nature": "(nature IS NULL OR nature = '')",
}


def _fiches_a_traiter(champ, source_id=None):
    sql = (f"SELECT id, url_source, source_id FROM subsides "
           f"WHERE {VIDE[champ]} AND statut != 'echec_extraction'")
    params = []
    if source_id:
        sql += " AND source_id = ?"
        params.append(source_id)
    sql += " ORDER BY id"
    return db.connect().execute(sql, params).fetchall()


async def main():
    ap = argparse.ArgumentParser(description="Backfill d'un champ par ré-extraction ciblée.")
    ap.add_argument("--champ", choices=sorted(VIDE), required=True,
                    help="champ à renseigner")
    ap.add_argument("--source", help="limiter à une source (id)")
    ap.add_argument("--limite", type=int, default=100, help="nb max de fiches (défaut 100)")
    ap.add_argument("--dry-run", action="store_true", help="liste sans ré-extraire")
    args = ap.parse_args()

    db.init_db()
    from jobs import _traiter_fiche  # import tardif : db doit être initialisé

    fiches = _fiches_a_traiter(args.champ, args.source)
    log.info("%d fiche(s) sans '%s'%s", len(fiches), args.champ,
             f" (source={args.source})" if args.source else "")

    if args.dry_run:
        for f in fiches[: args.limite]:
            print(f"  [{f['source_id']}] {f['url_source']}")
        return

    ua = user_agent()
    rapport = {"tokens_in": 0, "tokens_out": 0, "erreurs": [], "a_verifier": 0}
    traitees = renseignees = 0

    for f in fiches[: args.limite]:
        source = get_source(f["source_id"]) or {"id": f["source_id"], "rendu_js": False,
                                                 "delai_secondes": 3.0}
        url = f["url_source"]
        if not robots.autorise(url, ua):
            log.warning("robots.txt interdit %s — sautée", url)
            continue
        try:
            await _traiter_fiche(url, source, rapport, forcer=True)  # forcer : ignore le hash
            traitees += 1
            apres = db.get_subside(f["id"])
            val = apres.get(args.champ) if apres else None
            rempli = bool(val) and val != "inconnue" and val != []
            if rempli:
                renseignees += 1
                log.info("  %s=%s <- %s", args.champ, val, url)
        except Exception as e:
            log.error("KO %s : %s", url, e)
            rapport["erreurs"].append(f"{url}: {e}")
        await asyncio.sleep(robots.delai_effectif(url, ua, source.get("delai_secondes", 3.0)))

    await fermer_browser()
    log.info("=== Terminé : %d traitée(s), %d '%s' renseigné(s), %d tokens in / %d out ===",
             traitees, renseignees, args.champ, rapport["tokens_in"], rapport["tokens_out"])


if __name__ == "__main__":
    asyncio.run(main())

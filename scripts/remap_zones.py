"""Ré-applique le mapping zone_categorie aux fiches déjà en base.

Pourquoi : `zone_categorie` est calculée par du code pur (validator.categoriser_zone)
au moment de l'extraction. Quand on enrichit le mapping — au lot 2, « Scheldevallei »
n'était pas reconnu comme flamand — les fiches déjà stockées gardent l'ancienne
catégorie. Ce script les corrige SANS ré-extraction : zéro appel LLM, zéro requête
réseau, zéro euro.

Idempotent : le relancer ne change plus rien. Dry-run par défaut.

    python scripts/remap_zones.py               # aperçu, n'écrit rien
    python scripts/remap_zones.py --appliquer   # écrit
    python scripts/remap_zones.py --appliquer --source kbs_frb
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

import db  # noqa: E402  (après load_dotenv : db lit DB_PATH à l'import)
from scraper.validator import categoriser_zone  # noqa: E402


def calculer(source: str | None = None) -> list[dict]:
    """[{id, url, zone_geographique, avant, apres}] pour les fiches à corriger."""
    sql = "SELECT id, url_source, zone_geographique, zone_categorie FROM subsides"
    params = ()
    if source:
        sql += " WHERE source_id = ?"
        params = (source,)

    changements = []
    for r in db.connect().execute(sql, params):
        avant = r["zone_categorie"] or "inconnue"
        apres = categoriser_zone(r["zone_geographique"])
        if apres != avant:
            changements.append({
                "id": r["id"], "url": r["url_source"],
                "zone_geographique": r["zone_geographique"],
                "avant": avant, "apres": apres,
            })
    return changements


def appliquer(changements: list[dict]) -> int:
    conn = db.connect()
    for c in changements:
        conn.execute("UPDATE subsides SET zone_categorie = ? WHERE id = ?",
                     (c["apres"], c["id"]))
    conn.commit()
    return len(changements)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--appliquer", action="store_true",
                    help="écrit en base (sans ce drapeau : simple aperçu)")
    ap.add_argument("--source", help="limite à une source (ex: kbs_frb)")
    args = ap.parse_args()

    db.init_db()
    changements = calculer(args.source)

    total = db.connect().execute("SELECT COUNT(*) n FROM subsides").fetchone()["n"]
    print(f"{total} fiche(s) en base — {len(changements)} à recatégoriser\n")

    if not changements:
        print("Rien à faire : le mapping stocké est déjà à jour.")
        return 0

    # Récapitulatif par transition, c'est ce qu'on veut relire avant d'écrire.
    par_transition: dict[tuple[str, str], int] = {}
    for c in changements:
        cle = (c["avant"], c["apres"])
        par_transition[cle] = par_transition.get(cle, 0) + 1
    for (avant, apres), n in sorted(par_transition.items(), key=lambda kv: -kv[1]):
        print(f"  {avant:>10} -> {apres:<10} : {n}")

    print("\nDétail :")
    for c in changements[:40]:
        zone = (c["zone_geographique"] or "—")[:45]
        print(f"  [{c['avant']} -> {c['apres']}] {zone:<45} {c['url'][:60]}")
    if len(changements) > 40:
        print(f"  … et {len(changements) - 40} autre(s)")

    if not args.appliquer:
        print("\nAPERÇU — rien n'a été écrit. Relance avec --appliquer pour corriger.")
        return 0

    n = appliquer(changements)
    print(f"\n{n} fiche(s) corrigée(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

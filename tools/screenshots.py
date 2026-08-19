"""Captures Playwright des écrans livrés — desktop 1440 et mobile 375.

Prend les vraies pages servies par Next avec le backend qui tourne et les
données réelles de data/subsides.db. Le but est de PROUVER le rendu, pas de
le décrire : un « build vert » ne dit rien de ce qu'on voit.

Usage :
    .venv/bin/python tools/screenshots.py [--front http://localhost:3001]

Nécessite : backend sur :8000, front Next en dev, instance Clerk de test
(les adresses « +clerk_test » acceptent le code de vérification 424242).
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

RACINE = Path(__file__).resolve().parent.parent
SORTIE = RACINE / "docs" / "screenshots"
DB = RACINE / "data" / "subsides.db"

EMAIL_TEST = "subsidia+clerk_test@example.com"
MDP_TEST = "Subsidia-Test-2026!"
CODE_TEST = "424242"

DESKTOP = {"viewport": {"width": 1440, "height": 900}, "device_scale_factor": 2}
MOBILE = {"viewport": {"width": 375, "height": 812}, "device_scale_factor": 2,
          "is_mobile": True, "has_touch": True}


def capture(page: Page, nom: str, suffixe: str, pleine: bool | None = None) -> None:
    """Sur mobile, la barre de navigation est `fixed` : une capture pleine page
    la peint au milieu du document. On photographie donc le viewport, ce que
    l'utilisateur voit réellement."""
    if pleine is None:
        pleine = not suffixe.startswith("mobile")
    SORTIE.mkdir(parents=True, exist_ok=True)
    chemin = SORTIE / f"{nom}-{suffixe}.png"
    page.screenshot(path=str(chemin), full_page=pleine)
    print(f"  ✓ {chemin.relative_to(RACINE)}")


def stabiliser(page: Page, ms: int = 900) -> None:
    """Laisse les animations d'entrée se poser (Framer Motion) avant la photo."""
    page.wait_for_timeout(ms)


# ---------------------------------------------------------------- auth Clerk
# Le formulaire d'inscription est protégé par Cloudflare Turnstile : impossible
# à franchir en navigateur headless (et hors de question de le contourner).
# On passe donc par la voie prévue pour ça : l'API backend Clerk crée un compte
# de test et un « sign-in token », que le front consomme via ?__clerk_ticket=.

CLERK_API = "https://api.clerk.com/v1"


def _cle_secrete() -> str:
    env = RACINE / "frontend" / ".env.local"
    for ligne in env.read_text().splitlines():
        if ligne.startswith("CLERK_SECRET_KEY="):
            return ligne.split("=", 1)[1].strip().strip('"')
    raise SystemExit("CLERK_SECRET_KEY introuvable dans frontend/.env.local")


def compte_de_test() -> str:
    """Renvoie l'id Clerk du compte de test, en le créant au besoin."""
    import httpx
    h = {"Authorization": f"Bearer {_cle_secrete()}"}
    with httpx.Client(timeout=30) as c:
        r = c.get(f"{CLERK_API}/users", params={"email_address": [EMAIL_TEST]}, headers=h)
        r.raise_for_status()
        if r.json():
            return r.json()[0]["id"]
        r = c.post(f"{CLERK_API}/users", headers=h, json={
            "email_address": [EMAIL_TEST], "password": MDP_TEST,
            "skip_password_checks": True, "first_name": "Ateliers", "last_name": "Foot",
        })
        if r.status_code >= 400:
            raise SystemExit(f"Création du compte de test refusée : {r.text}")
        return r.json()["id"]


def connecter(page: Page, base: str, clerk_user_id: str) -> None:
    import httpx
    h = {"Authorization": f"Bearer {_cle_secrete()}"}
    with httpx.Client(timeout=30) as c:
        r = c.post(f"{CLERK_API}/sign_in_tokens", headers=h,
                   json={"user_id": clerk_user_id, "expires_in_seconds": 900})
        r.raise_for_status()
        ticket = r.json()["token"]
    page.goto(f"{base}/sign-in?__clerk_ticket={ticket}", wait_until="domcontentloaded")
    page.wait_for_timeout(5000)


def supprimer_compte_de_test(clerk_user_id: str) -> None:
    """À appeler pour ne pas laisser traîner de compte de démo dans Clerk."""
    import httpx
    with httpx.Client(timeout=30) as c:
        c.delete(f"{CLERK_API}/users/{clerk_user_id}",
                 headers={"Authorization": f"Bearer {_cle_secrete()}"})


# ------------------------------------------------------- données de la démo

def copier_profil_reel(clerk_user_id: str, source_profil: int = 2) -> tuple[int, str]:
    """Rattache une COPIE d'un profil réel (et de ses jugements déjà payés) au
    compte de test. Aucun appel LLM n'est déclenché : on réutilise des
    résultats existants en base."""
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    u = conn.execute("SELECT id, clerk_user_id FROM users WHERE clerk_user_id = ?",
                     (clerk_user_id,)).fetchone()
    if u is None:
        raise SystemExit(f"Compte {clerk_user_id} absent de la base : "
                         "le front n'a pas encore appelé l'API authentifiée.")

    dejala = conn.execute(
        "SELECT id FROM profils WHERE user_id = ? AND ephemere = 0 ORDER BY id DESC LIMIT 1",
        (u["id"],)).fetchone()
    if dejala:
        conn.close()
        return dejala["id"], u["clerk_user_id"]

    cols = [c[1] for c in conn.execute("PRAGMA table_info(profils)") if c[1] != "id"]
    src = conn.execute("SELECT * FROM profils WHERE id = ?", (source_profil,)).fetchone()
    vals = [u["id"] if c == "user_id" else src[c] for c in cols]
    cur = conn.execute(
        f"INSERT INTO profils ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", vals)
    pid = cur.lastrowid

    mcols = [c[1] for c in conn.execute("PRAGMA table_info(matchings)") if c[1] != "id"]
    for m in conn.execute("SELECT * FROM matchings WHERE profil_id = ?", (source_profil,)):
        mv = [pid if c == "profil_id" else m[c] for c in mcols]
        conn.execute(
            f"INSERT INTO matchings ({','.join(mcols)}) VALUES ({','.join('?' * len(mcols))})", mv)
    conn.commit()
    conn.close()
    return pid, u["clerk_user_id"]


def premier_matching(profil_id: int) -> int | None:
    conn = sqlite3.connect(DB)
    r = conn.execute(
        "SELECT id FROM matchings WHERE profil_id = ? AND verdict != 'non_eligible' "
        "ORDER BY id LIMIT 1", (profil_id,)).fetchone()
    conn.close()
    return r[0] if r else None


# ---------------------------------------------------------------- parcours

def tour_public(page: Page, base: str, suffixe: str) -> None:
    page.goto(base, wait_until="domcontentloaded")
    stabiliser(page, 1400)
    page.mouse.wheel(0, 20000)          # déclenche les whileInView
    page.wait_for_timeout(1200)
    page.mouse.wheel(0, -20000)
    page.wait_for_timeout(600)
    capture(page, "01-landing", suffixe)

    page.goto(f"{base}/confidentialite", wait_until="domcontentloaded")
    stabiliser(page)
    capture(page, "02-confidentialite", suffixe)


def tour_app(page: Page, base: str, suffixe: str, profil_id: int, matching_id: int | None) -> None:
    page.goto(base, wait_until="domcontentloaded")
    page.evaluate("(id) => localStorage.setItem('subsidia_profil_id', String(id))", profil_id)

    page.goto(f"{base}/dashboard", wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    capture(page, "03-dashboard", suffixe)

    # Section « non retenus » dépliée : c'est là que vit le tri honnête.
    try:
        page.get_by_role("button", name="Voir les non retenus").click(timeout=3000)
        page.wait_for_timeout(1200)
        capture(page, "04-dashboard-non-retenus", suffixe)
    except Exception:
        print("  · pas de section « non retenus » à déplier")

    if matching_id:
        page.goto(f"{base}/subside/{matching_id}", wait_until="domcontentloaded")
        page.wait_for_timeout(2500)
        capture(page, "05-detail", suffixe)

    page.goto(f"{base}/echeances", wait_until="domcontentloaded")
    page.wait_for_timeout(2500)
    capture(page, "06-echeances", suffixe)

    page.goto(f"{base}/recherche", wait_until="domcontentloaded")
    page.wait_for_timeout(1800)
    capture(page, "07-recherche", suffixe)

    page.goto(f"{base}/onboarding?edit=1", wait_until="domcontentloaded")
    page.wait_for_timeout(2200)
    capture(page, "08-profil", suffixe)

    page.goto(f"{base}/admin", wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    capture(page, "09-admin", suffixe)

    page.goto(f"{base}/subside/999999", wait_until="domcontentloaded")
    page.wait_for_timeout(2000)
    capture(page, "10-introuvable", suffixe)

    # Vrai run de matching. Si les jugements sont en cache (profil_hash +
    # subside_hash inchangés), il se termine en moins d'une seconde : le
    # bandeau de progression n'a pas le temps d'exister. Dans ce cas on ne
    # capture RIEN plutôt que d'écraser une capture prise pendant un vrai
    # run LLM (celle qui montre la barre à 8/25).
    page.goto(f"{base}/dashboard", wait_until="domcontentloaded")
    page.wait_for_timeout(2500)
    try:
        page.get_by_role("button", name="Relancer l'analyse").click(timeout=4000)
        page.get_by_text("analyse en cours").wait_for(state="visible", timeout=5000)
        page.wait_for_timeout(2000)
        if page.get_by_text("analyse en cours").count():
            capture(page, "11-streaming", suffixe)
        else:
            print("  · run trop rapide (tout en cache) — capture de streaming conservée")
        page.wait_for_timeout(6000)
    except Exception as e:
        print(f"  · streaming non capturé ({e.__class__.__name__})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--front", default="http://localhost:3001")
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()
    base = args.front.rstrip("/")

    with sync_playwright() as p:
        nav = p.chromium.launch(headless=not args.headed)

        print("Desktop 1440 — pages publiques")
        ctx = nav.new_context(locale="fr-BE", **DESKTOP)
        page = ctx.new_page()
        tour_public(page, base, "desktop")

        print("Connexion (compte de test Clerk)…")
        uid = compte_de_test()
        connecter(page, base, uid)
        # Une page du shell suffit à déclencher un appel API authentifié :
        # c'est lui qui crée la ligne `users` côté backend.
        page.goto(f"{base}/onboarding", wait_until="domcontentloaded")
        page.wait_for_timeout(4000)
        if "sign-in" in page.url or "sign-up" in page.url:
            print("  ✗ connexion échouée — arrêt")
            return 1
        print(f"  ✓ connecté ({page.url})")

        profil_id, clerk_id = copier_profil_reel(uid)
        mid = premier_matching(profil_id)
        print(f"  · profil {profil_id} (clerk {clerk_id}), matching de démo {mid}")

        etat = SORTIE.parent / "session-test.txt"
        etat.parent.mkdir(parents=True, exist_ok=True)
        etat.write_text(f"clerk_user_id={clerk_id}\nprofil_id={profil_id}\nmatching_id={mid}\n")

        print("Desktop 1440 — app")
        tour_app(page, base, "desktop", profil_id, mid)
        storage = ctx.storage_state()
        ctx.close()

        # Les pages publiques se photographient DÉCONNECTÉ : un visiteur
        # authentifié est redirigé vers /dashboard, on capturerait l'app.
        print("Mobile 375 — pages publiques (visiteur anonyme)")
        ctxm = nav.new_context(locale="fr-BE", **MOBILE)
        pagem = ctxm.new_page()
        tour_public(pagem, base, "mobile")
        ctxm.close()

        print("Mobile 375 — app")
        ctxma = nav.new_context(locale="fr-BE", storage_state=storage, **MOBILE)
        pagema = ctxma.new_page()
        tour_app(pagema, base, "mobile", profil_id, mid)
        ctxma.close()

        nav.close()
    print(f"\nTerminé — {SORTIE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

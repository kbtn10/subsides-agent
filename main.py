"""API FastAPI + service du frontend.

Lancement :  uvicorn main:app --reload
"""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import ValidationError

load_dotenv()

import auth_clerk  # noqa: E402
import candidatures as cand_mod  # noqa: E402
import db  # noqa: E402  (après load_dotenv : db lit DB_PATH à l'import)
import etage3  # noqa: E402
import jobs  # noqa: E402
import matching  # noqa: E402
import profils  # noqa: E402
from config.sources import SOURCES  # noqa: E402
from cron import demarrer_cron, arreter_cron  # noqa: E402

LOG_PATH = os.getenv("LOG_PATH", "data/agent.log")
Path(LOG_PATH).parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)-22s | %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler(LOG_PATH, encoding="utf-8")],
)
# httpx logue chaque requête en INFO : trop bavard à côté de nos propres logs.
logging.getLogger("httpx").setLevel(logging.WARNING)

log = logging.getLogger("main")
STATIC = Path(__file__).parent / "static"

# Lot 8.1 : plafond de recherches sauvegardées par user (garde-fou anti-abus).
MAX_RECHERCHES_PAR_USER = int(os.getenv("MAX_RECHERCHES_PAR_USER", "10"))


def _erreurs_pydantic(e: ValidationError):
    """pydantic v2 .errors() peut contenir un ctx non sérialisable en JSON
    (l'exception d'origine) -> on renvoie une forme propre pour le 422."""
    return [{"champ": ".".join(str(x) for x in err["loc"]), "message": err["msg"]}
            for err in e.errors()]


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    log.info("Base prête : %s", db.DB_PATH)
    if not os.getenv("ANTHROPIC_API_KEY"):
        log.warning("ANTHROPIC_API_KEY absente — /scrape échouera. Voir .env.example")

    # Garde-fou auth : ne jamais laisser une prod tourner sans vérification JWT.
    if not auth_clerk.clerk_actif():
        if os.getenv("ENV", "").lower() in ("production", "prod"):
            raise RuntimeError(
                "ENV=production mais CLERK_JWKS_URL absent : refus de démarrer "
                "(les routes /profils, /matching* seraient ouvertes à tous)."
            )
        log.warning("=" * 72)
        log.warning("  AUTH DÉSACTIVÉE — MODE DÉVELOPPEMENT")
        log.warning("  CLERK_JWKS_URL absent : /profils, /matching*, /admin/* sont OUVERTS.")
        log.warning("  Ne jamais exposer cette instance publiquement en l'état.")
        log.warning("=" * 72)
    # Purge des profils éphémères anciens au démarrage (leçon RGPD + hygiène).
    try:
        profils.purge_ephemeres(7)
    except Exception:
        log.exception("purge éphémères au démarrage")
    demarrer_cron()  # no-op si CRON_SCRAPE != true
    yield
    arreter_cron()


app = FastAPI(title="Agent Subsides Bruxelles", version="0.1.0", lifespan=lifespan)

# CORS : autorise l'origine du frontend Next.js (configurable). Les vues vanilla
# servies par FastAPI lui-même ne sont pas concernées (même origine).
_origines = [o.strip() for o in os.getenv("FRONTEND_ORIGIN", "http://localhost:3000").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origines,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- Auth Clerk (dépendance) ----
# Mode vanilla (Clerk inactif) : renvoie None, les routes fonctionnent sans token
# (non-régression /app + admin). Mode Clerk actif : Bearer valide EXIGÉ (401 sinon).
def _claims(authorization: str | None) -> dict | None:
    """Claims du Bearer, ou None si Clerk inactif. Lève 401 si token absent/invalide."""
    if not auth_clerk.clerk_actif():
        return None
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="authentification requise")
    token = authorization.split(" ", 1)[1].strip()
    try:
        return auth_clerk.verifier_token(token)
    except Exception:
        raise HTTPException(status_code=401, detail="token invalide")


async def utilisateur_optionnel(authorization: str | None = Header(default=None)) -> dict | None:
    claims = _claims(authorization)
    if claims is None:
        return None
    clerk_id, ident = auth_clerk.identite_depuis_claims(claims)
    return profils.get_or_create_user_clerk(clerk_id, ident)


async def exiger_admin(authorization: str | None = Header(default=None)) -> dict | None:
    """Réservé aux admins. Clerk inactif (dev) -> laissé passer (mode vanilla)."""
    claims = _claims(authorization)
    if claims is None:
        return None
    if not auth_clerk.est_admin(claims):
        raise HTTPException(status_code=403, detail="réservé aux administrateurs")
    clerk_id, ident = auth_clerk.identite_depuis_claims(claims)
    return profils.get_or_create_user_clerk(clerk_id, ident)


def _verifier_proprietaire(user: dict | None, profil_id: int):
    """En mode Clerk, un user ne touche QUE ses propres profils (403 sinon)."""
    if user is None:
        return  # mode vanilla : pas de cloisonnement
    p = profils.get_profil(profil_id)
    if p is None:
        raise HTTPException(status_code=404, detail="profil inconnu")
    if p.get("user_id") != user["id"]:
        raise HTTPException(status_code=403, detail="ce profil ne vous appartient pas")


@app.get("/")
async def index():
    """Vue admin : scrape + table brute (inchangée)."""
    return FileResponse(STATIC / "index.html")


@app.get("/app")
async def app_dashboard():
    """Vue produit : onboarding profil + dashboard de matching."""
    return FileResponse(STATIC / "app.html")


@app.get("/derniere-maj")
async def derniere_maj():
    """Timestamp du dernier scrape terminé (survit au redémarrage)."""
    run = db.dernier_scrape_run()
    return {"fin": run["fin"] if run else None,
            "total_subsides": db.compter_surveilles()}


@app.get("/sources")
async def get_sources():
    """Alimente le filtre "source" du frontend."""
    return [
        {"id": s["id"], "nom": s["nom"], "actif": s["actif"], "strategie": s["strategie"]}
        for s in SOURCES
    ]


@app.get("/sources/registry")
async def get_sources_registry():
    """Registre des sources (lot 9) : couverture visible et honnête, avec les
    différées et les écartées. Public (rien de sensible)."""
    from config.registre import compter
    return {"sources": db.lister_registre(), "comptes": compter()}


@app.post("/scrape")
async def scrape(
    source: str | None = Query(None, description="limite le run à cette source (backfill ciblé)"),
    backfill: bool = Query(False, description="relit en profondeur et ignore le cache de hash"),
    _: dict | None = Depends(exiger_admin),
):
    """Lance un scrape.

    Sans paramètre : run standard (delta), toutes les sources actives, budget
    réparti équitablement. Avec `source` : run ciblé, la source prend tout le
    budget. Avec `backfill=true` : pagination profonde + relecture des fiches
    déjà connues (pour les enrichir des annexes PDF). Le backfill est MANUEL —
    la veille nocturne reste toujours en mode delta.
    """
    try:
        job_id = await jobs.creer_job(source_id=source, backfill=backfill)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"job_id": job_id, "source": source, "backfill": backfill}


@app.get("/status/{job_id}")
async def status(job_id: str, _: dict | None = Depends(exiger_admin)):
    job = jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job inconnu")
    return {
        "statut": job["statut"],
        "source_en_cours": job["source_en_cours"],
        "fiches_traitees": job["fiches_traitees"],
        "fiches_total_estime": job["fiches_total_estime"],
        "erreurs": job["erreurs"],
        "rapport": job["rapport"],
    }


@app.get("/subsides")
async def subsides(
    statut: str | None = Query(None, description="nouveau|modifie|inchange|a_verifier|echec_extraction"),
    source: str | None = Query(None),
    zone: str | None = Query(None, description="bruxelles|fwb|national|flandre|wallonie|autre|inconnue"),
    tri: str = Query("deadline", description="deadline|titre|source|recent"),
    masquer_expires: bool = Query(False, description="masquer les subsides dont la deadline est passée"),
):
    return db.lister_subsides(statut=statut, source=source, tri=tri, zone=zone,
                              masquer_expires=masquer_expires)


@app.get("/subsides/{subside_id}")
async def subside(subside_id: int):
    s = db.get_subside(subside_id)
    if s is None:
        raise HTTPException(status_code=404, detail="subside inconnu")
    return s


@app.get("/stats")
async def stats():
    return {"par_statut": db.compter_par_statut(), "total": len(db.lister_subsides())}


# ==================== Users & Profils (lot 3) ====================

@app.post("/users")
async def creer_user(body: dict = Body(...)):
    """v1 : un simple identifiant texte (pas de mot de passe). Idempotent."""
    ident = (body.get("identifiant") or "").strip()
    if not ident:
        raise HTTPException(status_code=400, detail="identifiant requis")
    return profils.get_or_create_user(ident)


@app.post("/profils")
async def creer_profil(body: dict = Body(...), user: dict | None = Depends(utilisateur_optionnel)):
    user_id = user["id"] if user else body.get("user_id")
    try:
        p = profils.creer_profil(user_id, body)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=_erreurs_pydantic(e))
    return p


@app.get("/profils")
async def get_profils(user: dict | None = Depends(utilisateur_optionnel),
                      user_query: int | None = Query(None, alias="user")):
    # Mode Clerk : uniquement les profils de l'utilisateur authentifié.
    return profils.lister_profils(user_id=user["id"] if user else user_query)


@app.get("/profils/{profil_id}")
async def get_un_profil(profil_id: int, user: dict | None = Depends(utilisateur_optionnel)):
    _verifier_proprietaire(user, profil_id)
    p = profils.get_profil(profil_id)
    if p is None:
        raise HTTPException(status_code=404, detail="profil inconnu")
    return p


@app.put("/profils/{profil_id}")
async def maj_profil(profil_id: int, body: dict = Body(...),
                     user: dict | None = Depends(utilisateur_optionnel)):
    _verifier_proprietaire(user, profil_id)
    try:
        p = profils.maj_profil(profil_id, body)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=_erreurs_pydantic(e))
    if p is None:
        raise HTTPException(status_code=404, detail="profil inconnu")
    return p


@app.delete("/profils/{profil_id}")
async def supprimer_profil(profil_id: int, user: dict | None = Depends(utilisateur_optionnel)):
    """RGPD : supprime le profil ET ses matchings."""
    _verifier_proprietaire(user, profil_id)
    if not profils.supprimer_profil(profil_id):
        raise HTTPException(status_code=404, detail="profil inconnu")
    return {"supprime": True}


# ==================== Recherches sauvegardées (lot 8.1) ====================
# Une recherche sauvegardée est un profil type='recherche'. Elle réutilise le
# cloisonnement, le matching, la veille et la suppression cascade des profils —
# seuls la création (transformation) et la liste enrichie sont spécifiques.

@app.get("/recherches")
async def lister_recherches(user: dict | None = Depends(utilisateur_optionnel)):
    """« Mes recherches » : les hypothèses sauvegardées de l'utilisateur."""
    return {"recherches": profils.lister_recherches(user["id"] if user else None),
            "max": MAX_RECHERCHES_PAR_USER}


@app.post("/recherches/{profil_id}/sauvegarder")
async def sauvegarder_recherche(profil_id: int, body: dict = Body(default={}),
                                user: dict | None = Depends(utilisateur_optionnel)):
    """Transforme une recherche éphémère en recherche sauvegardée (nommée)."""
    _verifier_proprietaire(user, profil_id)
    p = profils.get_profil(profil_id)
    if p is None:
        raise HTTPException(status_code=404, detail="recherche inconnue")
    # Le plafond ne compte que les recherches DÉJÀ sauvegardées : re-sauvegarder
    # (renommer) une recherche existante ne doit jamais buter dessus.
    if p["type"] != "recherche" and user is not None:
        if profils.compter_recherches(user["id"]) >= MAX_RECHERCHES_PAR_USER:
            raise HTTPException(
                status_code=409,
                detail="Supprimez une recherche pour en sauvegarder une nouvelle "
                       f"(maximum {MAX_RECHERCHES_PAR_USER}).")
    r = profils.sauvegarder_recherche(profil_id, body.get("nom") or "")
    if r is None:
        raise HTTPException(status_code=404, detail="recherche inconnue")
    return r


@app.put("/recherches/{profil_id}")
async def renommer_recherche(profil_id: int, body: dict = Body(...),
                             user: dict | None = Depends(utilisateur_optionnel)):
    """Renomme une recherche sauvegardée."""
    _verifier_proprietaire(user, profil_id)
    r = profils.renommer_recherche(profil_id, body.get("nom") or "")
    if r is None:
        raise HTTPException(status_code=404, detail="recherche inconnue")
    return r


# ==================== Matching (lot 3) ====================

# ATTENTION à l'ordre : FastAPI teste les routes dans l'ordre de déclaration.
# `/matching/recherche` DOIT être déclarée avant `/matching/{profil_id}`, sinon
# c'est la route paramétrée qui capture l'appel et tente de lire « recherche »
# comme un entier — 422 incompréhensible côté client.
@app.post("/matching/recherche")
async def matching_recherche(body: dict = Body(...), user: dict | None = Depends(utilisateur_optionnel)):
    """Recherche libre : crée un profil éphémère puis lance le matching."""
    body = {**body, "ephemere": True}
    user_id = user["id"] if user else body.get("user_id")
    try:
        p = profils.creer_profil(user_id, body)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=_erreurs_pydantic(e))
    job_id = await jobs.creer_job_matching(p["id"])
    return {"profil_id": p["id"], "job_id": job_id, "ephemere": True}


@app.post("/matching/{profil_id}")
async def lancer_matching(profil_id: int, user: dict | None = Depends(utilisateur_optionnel)):
    _verifier_proprietaire(user, profil_id)
    try:
        job_id = await jobs.creer_job_matching(profil_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"job_id": job_id}


@app.get("/matching/status/{job_id}")
async def matching_status(job_id: str, user: dict | None = Depends(utilisateur_optionnel)):
    job = jobs.get_matching_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job de matching inconnu")
    _verifier_proprietaire(user, job["profil_id"])
    return {
        "statut": job["statut"],
        "profil_id": job["profil_id"],
        "total_candidats": job["total_candidats"],
        "traites": job["traites"],
        "matchs": job["matchs"],
        "resultats": job["resultats"],          # ordre de production (streaming)
        "erreurs": job["erreurs"],
        "cout_estime_usd": job["cout_estime_usd"],
    }


@app.get("/matchings/{profil_id}")
async def get_matchings(profil_id: int, user: dict | None = Depends(utilisateur_optionnel)):
    _verifier_proprietaire(user, profil_id)
    if profils.get_profil(profil_id) is None:
        raise HTTPException(status_code=404, detail="profil inconnu")
    return matching.resultats(profil_id)


@app.get("/matchings/{profil_id}/resume")
async def get_resume(profil_id: int, user: dict | None = Depends(utilisateur_optionnel)):
    """Chiffres du bandeau (correspondances, deadlines<60j scopées éligibles)."""
    _verifier_proprietaire(user, profil_id)
    if profils.get_profil(profil_id) is None:
        raise HTTPException(status_code=404, detail="profil inconnu")
    return matching.resume_profil(profil_id)


@app.get("/matching-detail/{matching_id}")
async def matching_detail(matching_id: int, user: dict | None = Depends(utilisateur_optionnel)):
    """Vue détail d'une correspondance (deep link). Cloisonné par propriétaire."""
    m = matching.detail(matching_id)
    if m is None:
        raise HTTPException(status_code=404, detail="correspondance inconnue")
    _verifier_proprietaire(user, m["profil_id"])
    # Nature du profil : sur une recherche sauvegardée/éphémère, le front masque
    # « Préparer ma candidature » (les candidatures vivent sur le principal).
    p = profils.get_profil(m["profil_id"])
    m["profil_type"] = p["type"] if p else "principal"
    # Récurrence annuelle (lot 7) : « cet appel semble récurrent (édition X) ».
    if m.get("subside"):
        m["recurrence"] = cand_mod.detecter_recurrence(m["subside"])
    return m


# ==================== Candidatures (lot 7, étage 3) ====================
# Cloisonnement systématique : une candidature appartient à un profil, qui
# appartient à un user. On refuse (403) toute route sur une candidature d'autrui.

def _verifier_candidature(user: dict | None, candidature_id: int) -> dict:
    c = cand_mod.get_candidature(candidature_id)
    if c is None:
        raise HTTPException(status_code=404, detail="candidature inconnue")
    if user is not None:
        proprio = cand_mod.user_de_candidature(candidature_id)
        if proprio != user["id"]:
            raise HTTPException(status_code=403, detail="cette candidature ne vous appartient pas")
    return c


def _uid(user):
    return user["id"] if user else None


@app.post("/candidatures")
async def creer_candidature(body: dict = Body(...),
                            user: dict | None = Depends(utilisateur_optionnel)):
    """Ouvre une candidature (bouton « Préparer ma candidature »). Idempotent."""
    profil_id = body.get("profil_id")
    subside_id = body.get("subside_id")
    if not profil_id or not subside_id:
        raise HTTPException(status_code=422, detail="profil_id et subside_id requis")
    _verifier_proprietaire(user, profil_id)
    if db.get_subside(subside_id) is None:
        raise HTTPException(status_code=404, detail="subside inconnu")
    return cand_mod.creer_candidature(profil_id, subside_id, body.get("matching_id"))


@app.get("/candidatures/{profil_id}")
async def lister_candidatures(profil_id: int, user: dict | None = Depends(utilisateur_optionnel)):
    _verifier_proprietaire(user, profil_id)
    return {"candidatures": cand_mod.lister_candidatures(profil_id),
            "stats": cand_mod.stats(profil_id)}


@app.get("/candidature/{candidature_id}")
async def get_candidature(candidature_id: int, user: dict | None = Depends(utilisateur_optionnel)):
    _verifier_candidature(user, candidature_id)
    c = cand_mod.get_candidature_enrichie(candidature_id)
    c["checklist"] = etage3.etat_checklist(candidature_id)
    c["copilote"] = etage3.historique_copilote(candidature_id)
    if c.get("subside"):
        c["recurrence"] = cand_mod.detecter_recurrence(c["subside"])
    return c


@app.put("/candidature/{candidature_id}")
async def maj_candidature(candidature_id: int, body: dict = Body(...),
                          user: dict | None = Depends(utilisateur_optionnel)):
    _verifier_candidature(user, candidature_id)
    try:
        c = cand_mod.maj_candidature(candidature_id, body)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=_erreurs_pydantic(e))
    return c


@app.delete("/candidature/{candidature_id}")
async def supprimer_candidature(candidature_id: int, user: dict | None = Depends(utilisateur_optionnel)):
    _verifier_candidature(user, candidature_id)
    return {"supprime": cand_mod.supprimer_candidature(candidature_id)}


# ---- Checklist des pièces ----

@app.post("/candidature/{candidature_id}/checklist")
async def generer_checklist(candidature_id: int, body: dict = Body(default={}),
                            user: dict | None = Depends(utilisateur_optionnel)):
    _verifier_candidature(user, candidature_id)
    try:
        return etage3.generer_checklist(candidature_id, _uid(user),
                                        forcer=bool(body.get("forcer")))
    except etage3.PlafondAtteint as e:
        raise HTTPException(status_code=429, detail=str(e))


@app.patch("/checklist-item/{item_id}")
async def cocher_item(item_id: int, body: dict = Body(...),
                      user: dict | None = Depends(utilisateur_optionnel)):
    if user is not None and etage3.user_de_item(item_id) != user["id"]:
        raise HTTPException(status_code=403, detail="item hors de votre périmètre")
    etage3.cocher_item(item_id, bool(body.get("coche")))
    return {"ok": True}


@app.post("/candidature/{candidature_id}/checklist/item")
async def ajouter_item(candidature_id: int, body: dict = Body(...),
                       user: dict | None = Depends(utilisateur_optionnel)):
    _verifier_candidature(user, candidature_id)
    intitule = (body.get("intitule") or "").strip()
    if not intitule:
        raise HTTPException(status_code=422, detail="intitulé requis")
    return etage3.ajouter_item(candidature_id, intitule)


@app.delete("/checklist-item/{item_id}")
async def supprimer_item(item_id: int, user: dict | None = Depends(utilisateur_optionnel)):
    if user is not None and etage3.user_de_item(item_id) != user["id"]:
        raise HTTPException(status_code=403, detail="item hors de votre périmètre")
    etage3.supprimer_item(item_id)
    return {"supprime": True}


# ---- Conformité ----

@app.post("/candidature/{candidature_id}/conformite")
async def verifier_conformite(candidature_id: int, body: dict = Body(default={}),
                              user: dict | None = Depends(utilisateur_optionnel)):
    _verifier_candidature(user, candidature_id)
    try:
        return etage3.verifier_conformite(candidature_id, _uid(user),
                                          body.get("description") or "")
    except etage3.PlafondAtteint as e:
        raise HTTPException(status_code=429, detail=str(e))


# ---- Copilote de rédaction ----

@app.post("/candidature/{candidature_id}/copilote")
async def copilote(candidature_id: int, body: dict = Body(...),
                   user: dict | None = Depends(utilisateur_optionnel)):
    _verifier_candidature(user, candidature_id)
    try:
        return etage3.copilote(candidature_id, _uid(user),
                               body.get("action") or "", body.get("entree") or "")
    except etage3.PlafondAtteint as e:
        raise HTTPException(status_code=429, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@app.get("/dashboard/{profil_id}")
async def dashboard_agrege(profil_id: int, user: dict | None = Depends(utilisateur_optionnel)):
    """TOUT le dashboard en UN appel : résumé, correspondances, fraîcheur.

    Évite un appel par carte (perf) : le frontend n'a besoin que de celui-ci
    (+ le polling de statut pendant une analyse en cours).
    """
    _verifier_proprietaire(user, profil_id)
    p = profils.get_profil(profil_id)
    if p is None:
        raise HTTPException(status_code=404, detail="profil inconnu")
    run = db.dernier_scrape_run()
    return {
        "profil": {"id": p["id"], "nom": p["nom"], "commune_siege": p["commune_siege"],
                   "type": p["type"], "nom_recherche": p["nom_recherche"]},
        "resume": matching.resume_profil(profil_id),
        "matchings": matching.resultats(profil_id),
        "derniere_maj": run["fin"] if run else None,
        "total_subsides": db.compter_surveilles(),
    }


# ==================== Admin (lot 4b) ====================

@app.get("/admin/moi")
async def admin_moi(authorization: str | None = Header(default=None)):
    """Suis-je admin ? Répond toujours 200 — le front s'en sert pour afficher
    (ou non) l'entrée « Admin » du menu. Couvre les DEUX voies : rôle dans le
    JWT Clerk et allowlist ADMIN_CLERK_USER_IDS."""
    claims = _claims(authorization)
    if claims is None:
        return {"admin": True}  # mode vanilla (Clerk inactif) : dev local
    return {"admin": auth_clerk.est_admin(claims)}


@app.get("/admin/scrape-runs")
async def admin_scrape_runs(limite: int = Query(10, ge=1, le=100),
                            _: dict | None = Depends(exiger_admin)):
    """Historique des scrapes (date, durée, compteurs, coût)."""
    return db.lister_scrape_runs(limite)


def _sante_sources() -> list[dict]:
    """Santé par source, construite UNE fois et servie par deux routes.

    Trois origines croisées : le contenu réel en base (stats_par_source), la
    trace persistante du dernier passage de chaque source (source_health,
    lot 5 — survit au redémarrage et au plantage d'un run suivant), et le
    rapport du dernier run en date (détail des stratégies).
    """
    par_source = db.stats_par_source()
    persistee = db.sante_sources()
    dernier = db.dernier_scrape_run()
    rapport_sources = {}
    if dernier and dernier.get("rapport"):
        for s in (dernier["rapport"].get("sources") or []):
            rapport_sources[s.get("source_id")] = s

    out = []
    for s in SOURCES:
        stats = par_source.get(s["id"], {})
        r = rapport_sources.get(s["id"], {})
        h = persistee.get(s["id"], {})
        # Les points d'entrée déclarés, même ceux qui n'ont encore rien rapporté :
        # un filet à 0 URL en propre reste un filet, il doit se voir.
        entrees = s.get("decouverte") or [{"nom": s.get("strategie"), "strategie": s.get("strategie")}]
        apports = {a.get("nom"): a for a in (r.get("apports") or h.get("strategies") or [])}
        out.append({
            "id": s["id"], "nom": s["nom"], "actif": s["actif"],
            "strategie": s["strategie"],
            "strategie_utilisee": r.get("strategie_utilisee"),
            "fiches": stats.get("total", 0),
            "echecs": stats.get("echecs", 0),
            "dernier_passage": h.get("dernier_passage") or stats.get("derniere_verification"),
            "dernier_succes": h.get("dernier_succes"),
            "urls_decouvertes": h.get("urls_decouvertes", 0),
            "muette": bool(h.get("dernier_succes")) and (h.get("urls_decouvertes") or 0) == 0,
            "points_entree": [
                {
                    "nom": e.get("nom") or e.get("strategie"),
                    "strategie": e.get("strategie", s["strategie"]),
                    "trouvees": apports.get(e.get("nom") or e.get("strategie"), {}).get("trouvees", 0),
                    "en_propre": apports.get(e.get("nom") or e.get("strategie"), {}).get("en_propre", 0),
                }
                for e in entrees
            ],
            "statut_dernier_run": r.get("statut") or h.get("statut"),
            "erreurs_dernier_run": (r.get("erreurs") or h.get("erreurs") or [])[:3],
        })
    return out


@app.get("/sources/health")
async def sources_health(_: dict | None = Depends(exiger_admin)):
    """Santé des sources (lot 5) : passage, apport de chaque point d'entrée,
    détection de source muette. Données opérationnelles -> réservé aux admins."""
    return _sante_sources()


@app.get("/admin/sources-sante")
async def admin_sources_sante(_: dict | None = Depends(exiger_admin)):
    """Alias historique consommé par l'admin Next.js (lot 4b). Même source de
    vérité que /sources/health — surtout ne pas dupliquer la logique."""
    return _sante_sources()


@app.exception_handler(Exception)
async def erreur_inattendue(request, exc):
    log.exception("Erreur non gérée sur %s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": f"{type(exc).__name__}: {exc}"})

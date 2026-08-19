"""Moteur de matching : pré-filtre, cache, invalidation, verdict, profils.

Aucun réseau ni API : le jugement LLM est mocké. On prouve la logique de
sélection et de cache, pas la qualité du jugement (ça, c'est le run réel).
"""

import importlib
import json
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "m.db"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-faux")
    monkeypatch.setenv("EXTRACTION_MODEL", "claude-haiku-4-5")
    import db as dbm
    importlib.reload(dbm)
    dbm.init_db()
    import profils as pm; importlib.reload(pm)
    import matching as mm; importlib.reload(mm)
    from scraper import extractor
    extractor.CLIENT = None
    yield dbm, pm, mm
    extractor.CLIENT = None
    conn = getattr(dbm._local, "conn", None)
    if conn:
        conn.close(); dbm._local.conn = None


def seed_subside(db, url, **over):
    base = {
        "url_source": url, "titre": "Subside test", "organisme": "COCOF",
        "deadline": "2099-12-31", "permanent": False,
        "zone_categorie": "bruxelles", "zone_geographique": "Bruxelles",
        "type_beneficiaire": ["asbl"], "langue": "fr",
        "criteres_eligibilite": ["Siège en RBC"], "secteurs": ["sport"],
    }
    base.update(over)
    db.upsert_subside(base, over.get("source_id", "cocof"), text_hash=over.get("text_hash", "h-"+url))
    return db.id_par_url(url)


def profil_test(pm, db, **over):
    data = {"nom": "Club test", "commune_siege": "Ixelles", "langue": "fr",
            "secteurs": ["sport"], "budget_categorie": "moins_50k"}
    data.update(over)
    u = pm.get_or_create_user("testeur")
    return pm.creer_profil(u["id"], data)


def faux_verdict(verdict="probablement_eligible", pertinence="forte"):
    payload = {
        "verdict": verdict, "criteres_satisfaits": ["Siège bruxellois : OK"],
        "criteres_a_verifier": ["Budget max à confirmer"], "criteres_non_satisfaits": [],
        "pertinence": pertinence, "justification": "Semble éligible sous réserve.",
    }
    bloc = MagicMock(); bloc.type = "text"; bloc.text = json.dumps(payload)
    msg = MagicMock(); msg.content = [bloc]; msg.stop_reason = "end_turn"
    msg.usage.input_tokens = 800; msg.usage.output_tokens = 120
    return msg


# --- Pré-filtre ------------------------------------------------------------

def test_prefiltre_exclut_zone_flandre(env):
    db, pm, mm = env
    seed_subside(db, "https://a.be/bxl", zone_categorie="bruxelles")
    seed_subside(db, "https://a.be/vl", zone_categorie="flandre")
    p = profil_test(pm, db)
    urls = [c["url_source"] for c in mm.pre_filtrer(p)]
    assert "https://a.be/bxl" in urls
    assert "https://a.be/vl" not in urls


def test_prefiltre_inclut_zone_inconnue(env):
    db, pm, mm = env
    seed_subside(db, "https://a.be/x", zone_categorie="inconnue")
    p = profil_test(pm, db)
    assert any(c["url_source"] == "https://a.be/x" for c in mm.pre_filtrer(p))


def test_prefiltre_exclut_deadline_passee(env):
    db, pm, mm = env
    seed_subside(db, "https://a.be/vieux", deadline="2020-01-01")
    seed_subside(db, "https://a.be/futur", deadline="2099-01-01")
    p = profil_test(pm, db)
    urls = [c["url_source"] for c in mm.pre_filtrer(p)]
    assert "https://a.be/futur" in urls and "https://a.be/vieux" not in urls


def test_prefiltre_inclut_permanent_sans_deadline(env):
    db, pm, mm = env
    seed_subside(db, "https://a.be/perm", deadline=None, permanent=True)
    p = profil_test(pm, db)
    assert any(c["url_source"] == "https://a.be/perm" for c in mm.pre_filtrer(p))


def test_prefiltre_exclut_type_individu(env):
    db, pm, mm = env
    seed_subside(db, "https://a.be/indiv", type_beneficiaire=["individu"])
    seed_subside(db, "https://a.be/asbl", type_beneficiaire=["asbl"])
    seed_subside(db, "https://a.be/mixte", type_beneficiaire=["individu", "asbl"])
    p = profil_test(pm, db)
    urls = [c["url_source"] for c in mm.pre_filtrer(p)]
    assert "https://a.be/asbl" in urls
    assert "https://a.be/mixte" in urls        # contient asbl -> inclus
    assert "https://a.be/indiv" not in urls


def test_prefiltre_inclut_type_null(env):
    db, pm, mm = env
    seed_subside(db, "https://a.be/null", type_beneficiaire=None)
    p = profil_test(pm, db)
    assert any(c["url_source"] == "https://a.be/null" for c in mm.pre_filtrer(p))


def test_prefiltre_exclut_echec_extraction(env):
    db, pm, mm = env
    db.upsert_subside({"url_source": "https://a.be/ko"}, "cocof",
                      echec_extraction=True, raw_text="x")
    p = profil_test(pm, db)
    assert not any(c["url_source"] == "https://a.be/ko" for c in mm.pre_filtrer(p))


def test_prefiltre_ordre_bruxelles_dabord(env):
    db, pm, mm = env
    seed_subside(db, "https://a.be/nat", zone_categorie="national", deadline="2099-01-01")
    seed_subside(db, "https://a.be/bxl", zone_categorie="bruxelles", deadline="2099-06-01")
    p = profil_test(pm, db)
    cand = mm.pre_filtrer(p)
    assert cand[0]["zone_categorie"] == "bruxelles"   # Bruxelles avant national


# --- Cache -----------------------------------------------------------------

def test_cache_evite_second_appel(env):
    db, pm, mm = env
    sid = seed_subside(db, "https://a.be/1")
    p = profil_test(pm, db)
    sub = db.get_subside(sid)

    faux = MagicMock(); faux.messages.create.return_value = faux_verdict()
    with patch("scraper.extractor._client", return_value=faux):
        v1 = mm.juger_un(p, sub); v1.pop("_tokens", None)
        mm.stocker_matching(p, sub, v1)
        assert faux.messages.create.call_count == 1
        # cache hit : mm.matching_cache renvoie le matching sans nouvel appel
        assert mm.matching_cache(p, sub) is not None
        assert faux.messages.create.call_count == 1


def test_cache_invalide_si_profil_change(env):
    db, pm, mm = env
    sid = seed_subside(db, "https://a.be/1")
    p = profil_test(pm, db)
    sub = db.get_subside(sid)
    faux = MagicMock(); faux.messages.create.return_value = faux_verdict()
    with patch("scraper.extractor._client", return_value=faux):
        v = mm.juger_un(p, sub); v.pop("_tokens", None)
        mm.stocker_matching(p, sub, v)
    # profil modifié -> nouveau profil_hash -> cache invalide
    p2 = pm.maj_profil(p["id"], {"secteurs": ["sport", "culture"]})
    assert p2["profil_hash"] != p["profil_hash"]
    assert mm.matching_cache(p2, sub) is None


def test_cache_invalide_si_subside_change(env):
    db, pm, mm = env
    sid = seed_subside(db, "https://a.be/1", text_hash="hash-v1")
    p = profil_test(pm, db)
    sub = db.get_subside(sid)
    faux = MagicMock(); faux.messages.create.return_value = faux_verdict()
    with patch("scraper.extractor._client", return_value=faux):
        v = mm.juger_un(p, sub); v.pop("_tokens", None)
        mm.stocker_matching(p, sub, v)
    sub2 = dict(sub); sub2["text_hash"] = "hash-v2"      # la fiche a changé
    assert mm.matching_cache(p, sub2) is None


# --- Invalidation ----------------------------------------------------------

def test_invalidation_supprime_matchings(env):
    db, pm, mm = env
    sid = seed_subside(db, "https://a.be/1")
    p = profil_test(pm, db)
    sub = db.get_subside(sid)
    faux = MagicMock(); faux.messages.create.return_value = faux_verdict()
    with patch("scraper.extractor._client", return_value=faux):
        v = mm.juger_un(p, sub); v.pop("_tokens", None)
        mm.stocker_matching(p, sub, v)
    assert mm.matching_pour(p["id"], sid) is not None
    n = mm.invalider_pour_subside(sid)
    assert n == 1
    assert mm.matching_pour(p["id"], sid) is None


async def test_invalidation_via_scrape_quand_fiche_modifiee(env):
    """Une fiche qui passe 'modifie' dans le pipeline purge ses matchings."""
    import jobs
    db, pm, mm = env
    sid = seed_subside(db, "https://a.be/1", titre="Ancien", text_hash="h1")
    p = profil_test(pm, db)
    sub = db.get_subside(sid)
    faux_v = MagicMock(); faux_v.messages.create.return_value = faux_verdict()
    with patch("scraper.extractor._client", return_value=faux_v):
        v = mm.juger_un(p, sub); v.pop("_tokens", None)
        mm.stocker_matching(p, sub, v)
    assert mm.matching_pour(p["id"], sid) is not None

    # Le pipeline ré-extrait la fiche avec un titre différent -> 'modifie'
    from tests.test_pipeline import faux_message
    FICHE = {"titre": "Nouveau titre", "organisme": "COCOF", "deadline": "2099-12-31",
             "permanent": False, "montant": None, "public_cible": None,
             "criteres_eligibilite": [], "secteurs": [], "lien_candidature": None,
             "langue": "fr", "zone_geographique": None, "type_beneficiaire": None}
    faux_e = MagicMock(); faux_e.messages.create.return_value = faux_message(FICHE)
    rapport = {"tokens_in": 0, "tokens_out": 0, "erreurs": [], "a_verifier": 0}
    with patch("jobs.recuperer_texte", return_value=("texte modifié", "<html/>")), \
         patch("scraper.extractor._client", return_value=faux_e):
        statut = await jobs._traiter_fiche("https://a.be/1", {"id": "cocof"}, rapport)
    assert statut == "modifies"
    assert mm.matching_pour(p["id"], sid) is None       # matching invalidé


# --- Verdict malformé ------------------------------------------------------

def test_verdict_malforme_donne_erreur(env):
    db, pm, mm = env
    sid = seed_subside(db, "https://a.be/1")
    p = profil_test(pm, db); sub = db.get_subside(sid)
    bloc = MagicMock(); bloc.type = "text"; bloc.text = "pas du json"
    msg = MagicMock(); msg.content = [bloc]; msg.stop_reason = "end_turn"
    msg.usage.input_tokens = 10; msg.usage.output_tokens = 5
    faux = MagicMock(); faux.messages.create.return_value = msg
    with patch("scraper.extractor._client", return_value=faux):
        v = mm.juger_un(p, sub)
    assert v["verdict"] == "erreur"       # pas de crash


def test_verdict_erreur_non_mis_en_cache(env):
    db, pm, mm = env
    sid = seed_subside(db, "https://a.be/1")
    p = profil_test(pm, db); sub = db.get_subside(sid)
    mm.stocker_matching(p, sub, {"verdict": "erreur", "justification": "x",
                                 "pertinence": None, "criteres_satisfaits": [],
                                 "criteres_a_verifier": [], "criteres_non_satisfaits": []})
    assert mm.matching_cache(p, sub) is None       # une erreur se retente


# --- Profils ---------------------------------------------------------------

def test_profil_hash_ignore_le_nom(env):
    db, pm, mm = env
    from profils import calcul_profil_hash
    a = {"nom": "Club A", "commune_siege": "Ixelles", "secteurs": ["sport"]}
    b = {"nom": "Club B", "commune_siege": "Ixelles", "secteurs": ["sport"]}
    assert calcul_profil_hash(a) == calcul_profil_hash(b)  # le nom ne compte pas


def test_profil_hash_sensible_aux_secteurs(env):
    from profils import calcul_profil_hash
    a = {"commune_siege": "Ixelles", "secteurs": ["sport"]}
    b = {"commune_siege": "Ixelles", "secteurs": ["sport", "culture"]}
    assert calcul_profil_hash(a) != calcul_profil_hash(b)


def test_profil_nom_commune_requis(env):
    db, pm, mm = env
    from pydantic import ValidationError
    u = pm.get_or_create_user("x")
    with pytest.raises(ValidationError):
        pm.creer_profil(u["id"], {"nom": "", "commune_siege": "Ixelles"})


def test_suppression_profil_supprime_matchings(env):
    db, pm, mm = env
    sid = seed_subside(db, "https://a.be/1")
    p = profil_test(pm, db); sub = db.get_subside(sid)
    mm.stocker_matching(p, sub, faux_verdict_dict())
    assert mm.matching_pour(p["id"], sid) is not None
    assert pm.supprimer_profil(p["id"]) is True
    assert mm.matching_pour(p["id"], sid) is None   # cascade


def test_purge_ephemeres(env):
    db, pm, mm = env
    u = pm.get_or_create_user("x")
    p = pm.creer_profil(u["id"], {"nom": "Ephem", "commune_siege": "Ixelles", "ephemere": True})
    # forcer une date de création ancienne
    db.connect().execute("UPDATE profils SET cree_le='2020-01-01T00:00:00+00:00' WHERE id=?",
                         (p["id"],))
    db.connect().commit()
    assert pm.purge_ephemeres(7) == 1
    assert pm.get_profil(p["id"]) is None


def faux_verdict_dict():
    return {"verdict": "probablement_eligible", "pertinence": "forte",
            "justification": "ok", "criteres_satisfaits": [], "criteres_a_verifier": [],
            "criteres_non_satisfaits": []}


# --- Job de matching (orchestration + streaming + cache) -------------------

async def test_job_matching_bout_en_bout(env):
    import asyncio
    import jobs
    db, pm, mm = env
    seed_subside(db, "https://a.be/1", titre="Sport A", zone_categorie="bruxelles")
    seed_subside(db, "https://a.be/2", titre="Sport B", zone_categorie="national")
    seed_subside(db, "https://a.be/vl", zone_categorie="flandre")   # exclu au pré-filtre
    p = profil_test(pm, db)

    faux = MagicMock(); faux.messages.create.return_value = faux_verdict()
    with patch("scraper.extractor._client", return_value=faux):
        jid = await jobs.creer_job_matching(p["id"])
        job = jobs.get_matching_job(jid)
        while job["statut"] == "running":
            await asyncio.sleep(0.02)

    assert job["statut"] == "done"
    assert job["total_candidats"] == 2          # flandre exclu
    assert job["traites"] == 2
    assert job["matchs"] == 2                    # les 2 sont probablement_eligible
    assert len(job["resultats"]) == 2
    # chaque résultat porte la fiche enrichie pour l'affichage
    assert all("subside" in m and "titre" in m["subside"] for m in job["resultats"])
    assert faux.messages.create.call_count == 2

    # re-run : 100 % cache, 0 appel supplémentaire
    with patch("scraper.extractor._client", return_value=faux):
        jid2 = await jobs.creer_job_matching(p["id"])
        job2 = jobs.get_matching_job(jid2)
        while job2["statut"] == "running":
            await asyncio.sleep(0.02)
    assert job2["traites"] == 2
    assert faux.messages.create.call_count == 2   # AUCUN nouvel appel (cache)


async def test_job_matching_refuse_double(env):
    import jobs
    db, pm, mm = env
    seed_subside(db, "https://a.be/1")
    p = profil_test(pm, db)
    faux = MagicMock(); faux.messages.create.return_value = faux_verdict()
    with patch("scraper.extractor._client", return_value=faux):
        jid = await jobs.creer_job_matching(p["id"])
        jobs.get_matching_job(jid)["statut"] = "running"   # fige
        with pytest.raises(RuntimeError, match="déjà"):
            await jobs.creer_job_matching(p["id"])
        jobs.get_matching_job(jid)["statut"] = "done"


async def test_job_matching_plafond(env, monkeypatch):
    import jobs
    monkeypatch.setenv("MAX_JUGEMENTS_PAR_MATCHING", "2")
    db, pm, mm = env
    for i in range(5):
        seed_subside(db, f"https://a.be/{i}", titre=f"S{i}")
    p = profil_test(pm, db)
    faux = MagicMock(); faux.messages.create.return_value = faux_verdict()
    with patch("scraper.extractor._client", return_value=faux):
        jid = await jobs.creer_job_matching(p["id"])
        job = jobs.get_matching_job(jid)
        import asyncio
        while job["statut"] == "running":
            await asyncio.sleep(0.02)
    assert job["total_candidats"] == 2                 # plafonné
    assert any("plafond" in e for e in job["erreurs"])


# --- P0.1 : compteur de deadlines scopé aux correspondances ----------------

def test_resume_deadlines_scopees_aux_eligibles(env):
    from datetime import date, timedelta
    db, pm, mm = env
    p = profil_test(pm, db)
    aujd = date(2026, 7, 19)
    proche = (aujd + timedelta(days=20)).isoformat()      # < 60 j
    # 2 éligibles + 1 NON éligible, toutes avec une deadline proche
    for i, v in enumerate(["probablement_eligible", "eligible_sous_conditions", "non_eligible"]):
        sid = seed_subside(db, f"https://a.be/{i}", deadline=proche)
        mm.stocker_matching(p, db.get_subside(sid), {**faux_verdict_dict(), "verdict": v})
    r = mm.resume_profil(p["id"], aujourdhui=aujd)
    assert r["correspondances"] == 2
    assert r["deadlines_60j"] == 2        # les 2 éligibles seulement, pas le non_eligible


def test_resume_deadline_lointaine_non_comptee(env):
    from datetime import date, timedelta
    db, pm, mm = env
    p = profil_test(pm, db)
    aujd = date(2026, 7, 19)
    sid = seed_subside(db, "https://a.be/loin", deadline=(aujd+timedelta(days=200)).isoformat())
    mm.stocker_matching(p, db.get_subside(sid),
                        {**faux_verdict_dict(), "verdict": "probablement_eligible"})
    r = mm.resume_profil(p["id"], aujourdhui=aujd)
    assert r["correspondances"] == 1 and r["deadlines_60j"] == 0


# --- P0.2 : pieces_dossier -------------------------------------------------

def test_pieces_dossier_stockees_et_relues(env):
    db, pm, mm = env
    p = profil_test(pm, db)
    sid = seed_subside(db, "https://a.be/1")
    v = {**faux_verdict_dict(), "pieces_dossier": ["Statuts de l'ASBL", "Comptes annuels"]}
    mm.stocker_matching(p, db.get_subside(sid), v)
    m = mm.matching_pour(p["id"], sid)
    assert m["pieces_dossier"] == ["Statuts de l'ASBL", "Comptes annuels"]


def test_verdict_valide_pieces_dossier(env):
    from matching import Verdict
    v = Verdict(verdict="probablement_eligible", pertinence="forte", justification="ok",
                pieces_dossier=["Formulaire", "Budget prévisionnel"]).model_dump()
    assert v["pieces_dossier"] == ["Formulaire", "Budget prévisionnel"]


def test_verdict_pieces_dossier_defaut_vide(env):
    from matching import Verdict
    v = Verdict(verdict="non_eligible", pertinence="faible", justification="x").model_dump()
    assert v["pieces_dossier"] == []


def test_schema_verdict_contient_pieces_dossier(env):
    from prompts.matching import SCHEMA_VERDICT
    assert "pieces_dossier" in SCHEMA_VERDICT["properties"]
    assert "pieces_dossier" in SCHEMA_VERDICT["required"]


# --- Migration lot 2 -> lot 3 ----------------------------------------------

def test_migration_lot2_vers_lot3(tmp_path, monkeypatch):
    """Base au schéma lot 2 (subsides seuls) -> les tables lot 3 apparaissent."""
    import sqlite3
    p = tmp_path / "l2.db"
    conn = sqlite3.connect(p)
    conn.execute("""CREATE TABLE subsides (
        id INTEGER PRIMARY KEY, url_source TEXT UNIQUE, source_id TEXT, titre TEXT,
        deadline TEXT, zone_categorie TEXT, statut TEXT NOT NULL,
        premiere_detection TEXT NOT NULL, derniere_verification TEXT NOT NULL)""")
    conn.execute("INSERT INTO subsides (id,url_source,source_id,titre,statut,"
                 "premiere_detection,derniere_verification) VALUES "
                 "(1,'https://a.be/x','cocof','T','nouveau','2026-01-01','2026-01-01')")
    conn.commit(); conn.close()

    monkeypatch.setenv("DB_PATH", str(p))
    import db as dbm; importlib.reload(dbm)
    dbm.init_db()
    tables = {r["name"] for r in dbm.connect().execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"users", "profils", "matchings", "scrape_runs"} <= tables
    assert dbm.get_subside(1)["titre"] == "T"      # données lot 2 intactes
    dbm.connect().close(); dbm._local.conn = None
    importlib.reload(dbm)
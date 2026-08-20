"""Lot 9 : registre des sources + config des nouvelles sources bruxelloises."""

import importlib
import re

import pytest


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "l9.db"))
    import db as dbm
    importlib.reload(dbm)
    dbm.init_db()
    yield dbm
    conn = getattr(dbm._local, "conn", None)
    if conn:
        conn.close(); dbm._local.conn = None


# --- Registre ---------------------------------------------------------------

def test_registre_peuple_et_compte(db):
    from config.registre import REGISTRE, compter
    rows = db.lister_registre()
    assert len(rows) == len(REGISTRE)
    c = compter()
    assert c["total"] == len(REGISTRE)
    assert c["active"] == sum(1 for e in REGISTRE if e["statut"] == "active")
    # Les actives sortent en tête (tri du lister).
    assert rows[0]["statut"] == "active"


def test_registre_statuts_valides():
    from config.registre import REGISTRE
    valides = {"active", "a_evaluer", "differee", "ecartee"}
    niveaux = {"federal", "regional", "communautaire", "commune", "philanthropique", "europeen"}
    for e in REGISTRE:
        assert e["statut"] in valides, e["id"]
        assert e["niveau"] in niveaux, e["id"]
        assert e["nom"] and e["raison"]


def test_registre_idempotent_preserve_evaluee_le(db):
    avant = {r["id"]: r["evaluee_le"] for r in db.lister_registre()}
    db._peupler_registre(db.connect()); db.connect().commit()   # re-seed
    apres = {r["id"]: r["evaluee_le"] for r in db.lister_registre()}
    assert avant == apres   # evaluee_le préservé au ré-upsert


def test_ecartees_documentees():
    from config.registre import REGISTRE
    ecartees = {e["id"] for e in REGISTRE if e["statut"] == "ecartee"}
    assert {"enmieux_be", "monasbl"} <= ecartees


# --- Config des nouvelles sources ------------------------------------------

NOUVELLES = ["hub_appels", "bruxelles_ville", "actiris", "accrochage_scolaire",
             "economie_emploi", "brulocalis"]


@pytest.mark.parametrize("sid", NOUVELLES)
def test_nouvelle_source_config_bien_formee(sid):
    from config.sources import get_source
    s = get_source(sid)
    assert s is not None, sid
    for champ in ("id", "nom", "start_urls", "strategie", "delai_secondes", "actif", "niveau"):
        assert champ in s, f"{sid} manque {champ}"
    assert s["start_urls"] and all(u.startswith("https://") for u in s["start_urls"])
    assert s["niveau"] in {"regional", "commune", "communautaire", "federal",
                           "philanthropique", "europeen"}


def test_commune_pilote_est_bruxelles_ville():
    from config.sources import get_source
    s = get_source("bruxelles_ville")
    assert s["niveau"] == "commune"
    assert s["actif"] is True


def test_brulocalis_non_active():
    """brulocalis (anti-bot BunkerWeb) ne doit PAS être crawlée : décision
    d'exploitation laissée au propriétaire."""
    from config.sources import get_source
    assert get_source("brulocalis")["actif"] is False


def test_nouvelles_actives_avec_fiches():
    """Les 3 nouvelles sources validées avec fiches réelles sont actives."""
    from config.sources import get_source
    for sid in ("hub_appels", "bruxelles_ville", "economie_emploi"):
        assert get_source(sid)["actif"] is True, sid


def test_ids_registre_actives_referencent_config():
    """Chaque entrée 'active' du registre pointe une source de config active —
    sauf brulocalis, active en tant qu'INDEX de titres (script dédié), dont la
    source de config reste actif=False (le pipeline normal ne la crawle pas)."""
    from config.registre import REGISTRE
    from config.sources import get_source
    for e in REGISTRE:
        if e["statut"] == "active" and e.get("config_id"):
            s = get_source(e["config_id"])
            assert s is not None, e["id"]
            if e["id"] != "brulocalis":
                assert s["actif"] is True, e["id"]


# --- Recherche web (index Brulocalis -> source officielle) ------------------

def test_recherche_web_sans_cle(monkeypatch):
    """Sans SEARCH_API_KEY : aucune recherche, aucune URL inventée -> None."""
    monkeypatch.delenv("SEARCH_API_KEY", raising=False)
    from scraper import recherche_web
    assert recherche_web.chercher_officiel("Un appel à projets") is None


def test_recherche_web_filtre_officiels(monkeypatch):
    """Ne retient qu'un domaine officiel belge (.brussels/.be), pas l'index ni
    le bruit social, et pas une racine de domaine."""
    monkeypatch.setenv("SEARCH_API_KEY", "x")
    from scraper import recherche_web
    faux = [
        "https://fr.wikipedia.org/wiki/Subside",
        "https://www.brulocalis.brussels/fr/subsides/xyz",   # l'index : exclu
        "https://www.facebook.com/appel",                     # social : exclu
        "https://servicepublic.brussels/",                    # racine : exclue
        "https://servicepublic.brussels/appel-a-projets-region-jeune/",  # bonne fiche
    ]
    monkeypatch.setattr(recherche_web, "_brave", lambda q, cle, n=8: faux)
    url = recherche_web.chercher_officiel("Région jeune et dynamique")
    assert url == "https://servicepublic.brussels/appel-a-projets-region-jeune/"


def test_recherche_web_aucun_officiel(monkeypatch):
    monkeypatch.setenv("SEARCH_API_KEY", "x")
    from scraper import recherche_web
    monkeypatch.setattr(recherche_web, "_brave",
                        lambda q, cle, n=8: ["https://wikipedia.org/x", "https://monasbl.be/y"])
    assert recherche_web.chercher_officiel("Truc") is None


# --- Détection des quasi-doublons inter-sources (garde-fou lot 9) -----------

def test_quasi_doublons_inter_sources(db):
    # Même appel relayé par deux sources -> détecté (aucune fusion).
    base = {"deadline": "2099-12-31", "zone_categorie": "bruxelles"}
    db.upsert_subside({**base, "url_source": "https://a.be/x1",
                       "titre": "Appel à projets Good Food 2026"}, "hub_appels", text_hash="h1")
    db.upsert_subside({**base, "url_source": "https://b.be/y1",
                       "titre": "Appel à projets : Good Food"}, "economie_emploi", text_hash="h2")
    # Une fiche d'une seule source ne compte pas.
    db.upsert_subside({**base, "url_source": "https://a.be/z1",
                       "titre": "Prime vélo cargo Anderlecht"}, "hub_appels", text_hash="h3")
    groupes = db.quasi_doublons_inter_sources()
    assert len(groupes) == 1
    srcs = {i["source_id"] for i in groupes[0]}
    assert srcs == {"hub_appels", "economie_emploi"}

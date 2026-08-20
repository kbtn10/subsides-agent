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
    """Chaque entrée 'active' du registre doit pointer une source active en config."""
    from config.registre import REGISTRE
    from config.sources import get_source
    for e in REGISTRE:
        if e["statut"] == "active" and e.get("config_id"):
            s = get_source(e["config_id"])
            assert s is not None and s["actif"] is True, e["id"]


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

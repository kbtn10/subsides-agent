"""Lot 8.1 : recherches sauvegardées (type de profil, purge, limite, cloisonnement).

Aucun réseau ni LLM : on prouve la logique de types, de transformation et de
purge. Le matching est réutilisé tel quel (déjà couvert par test_matching).
"""

import importlib
import sqlite3

import pytest


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "l81.db"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-faux")
    import db as dbm
    importlib.reload(dbm)
    dbm.init_db()
    import profils as pm; importlib.reload(pm)
    import matching as mm; importlib.reload(mm)
    yield dbm, pm, mm
    conn = getattr(dbm._local, "conn", None)
    if conn:
        conn.close(); dbm._local.conn = None


def seed_subside(db, url, **over):
    base = {"url_source": url, "titre": "Subside test", "organisme": "COCOF",
            "deadline": "2099-12-31", "permanent": False, "zone_categorie": "bruxelles",
            "zone_geographique": "Bruxelles", "type_beneficiaire": ["asbl"], "langue": "fr",
            "criteres_eligibilite": ["Siège en RBC"], "secteurs": ["sport"]}
    base.update(over)
    db.upsert_subside(base, "cocof", text_hash="h-" + url)
    return db.id_par_url(url)


def faux_verdict_dict():
    return {"verdict": "probablement_eligible", "pertinence": "forte",
            "justification": "ok", "criteres_satisfaits": [], "criteres_a_verifier": [],
            "criteres_non_satisfaits": []}


# --- Types de profil --------------------------------------------------------

def test_creer_profil_type_par_defaut(env):
    db, pm, _ = env
    u = pm.get_or_create_user("x")
    principal = pm.creer_profil(u["id"], {"nom": "ASBL", "commune_siege": "Ixelles"})
    ephem = pm.creer_profil(u["id"], {"nom": "Hypothèse", "commune_siege": "Forest",
                                      "ephemere": True})
    assert principal["type"] == "principal" and principal["ephemere"] is False
    assert ephem["type"] == "ephemere" and ephem["ephemere"] is True


def test_type_et_ephemere_restent_synchronises(env):
    db, pm, _ = env
    u = pm.get_or_create_user("x")
    # type='recherche' explicite -> ephemere doit retomber à False.
    p = pm.creer_profil(u["id"], {"nom": "R", "commune_siege": "Jette",
                                  "ephemere": True, "type": "recherche",
                                  "nom_recherche": "Vélo Anderlecht"})
    assert p["type"] == "recherche"
    assert p["ephemere"] is False
    assert p["nom_recherche"] == "Vélo Anderlecht"


def test_row_to_profil_deduit_type_sur_base_ancienne(env):
    """Base d'avant le lot 8.1 : la colonne type peut être NULL en lecture."""
    db, pm, _ = env
    u = pm.get_or_create_user("x")
    p = pm.creer_profil(u["id"], {"nom": "Vieux", "commune_siege": "Uccle"})
    db.connect().execute("UPDATE profils SET type = NULL WHERE id = ?", (p["id"],))
    db.connect().commit()
    relu = pm.get_profil(p["id"])
    assert relu["type"] == "principal"   # déduit du booléen ephemere=0


def test_migration_retro_classement(tmp_path, monkeypatch):
    """Une base à l'ancien schéma (sans colonne type) est reclassée : les
    éphémères -> 'ephemere', le reste -> 'principal'."""
    p = tmp_path / "vieille.db"
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE profils (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, nom TEXT,
        commune_siege TEXT, langue TEXT, secteurs TEXT, publics_cibles TEXT,
        budget_categorie TEXT, agrements TEXT, description_libre TEXT,
        ephemere INTEGER DEFAULT 0, region TEXT DEFAULT 'bruxelles',
        profil_hash TEXT, cree_le TEXT, modifie_le TEXT)""")
    # _migrer_tables_lot3 touche aussi matchings/users : on les crée déjà à jour
    # pour isoler l'assertion sur la seule reclassification des profils.
    conn.execute("CREATE TABLE matchings (id INTEGER PRIMARY KEY, pieces_dossier TEXT)")
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, clerk_user_id TEXT)")
    conn.execute("INSERT INTO profils (nom, ephemere, cree_le, modifie_le) "
                 "VALUES ('Principal', 0, 't', 't')")
    conn.execute("INSERT INTO profils (nom, ephemere, cree_le, modifie_le) "
                 "VALUES ('Ephem', 1, 't', 't')")
    conn.commit()

    monkeypatch.setenv("DB_PATH", str(p))
    import db as dbm; importlib.reload(dbm)
    dbm._migrer_tables_lot3(conn)   # applique la migration sur l'ancienne base
    conn.commit()
    rows = {r["nom"]: r["type"] for r in conn.execute("SELECT nom, type FROM profils")}
    assert rows == {"Principal": "principal", "Ephem": "ephemere"}
    conn.close()


# --- Sauvegarde d'une recherche ---------------------------------------------

def test_sauvegarder_recherche_transforme_et_conserve_le_hash(env):
    """Sauvegarder = passer ephemere -> recherche SANS changer le hash : les
    jugements déjà en cache restent valides (c'est tout l'intérêt de la veille)."""
    db, pm, mm = env
    sid = seed_subside(db, "https://a.be/1")
    u = pm.get_or_create_user("x")
    p = pm.creer_profil(u["id"], {"nom": "Recherche libre", "commune_siege": "Anderlecht",
                                  "ephemere": True})
    sub = db.get_subside(sid)
    mm.stocker_matching(p, sub, faux_verdict_dict())
    hash_avant = p["profil_hash"]

    r = pm.sauvegarder_recherche(p["id"], "Atelier vélo Anderlecht")
    assert r["type"] == "recherche"
    assert r["nom_recherche"] == "Atelier vélo Anderlecht"
    assert r["profil_hash"] == hash_avant          # hash inchangé
    assert mm.matching_pour(p["id"], sid) is not None   # matching conservé


def test_recherche_sauvegardee_est_re_matchee_quand_la_fiche_change(env):
    """Criterion 3 : une recherche sauvegardée bénéficie de la veille — quand
    une fiche change (text_hash différent), son matching en cache est invalidé
    et sera re-jugé. C'est le même chemin que pour un profil principal."""
    db, pm, mm = env
    sid = seed_subside(db, "https://a.be/veille", text_hash="v1")
    u = pm.get_or_create_user("x")
    p = pm.creer_profil(u["id"], {"nom": "R", "commune_siege": "Ixelles", "ephemere": True})
    pm.sauvegarder_recherche(p["id"], "Veillée")
    rech = pm.get_profil(p["id"])
    sub = db.get_subside(sid)
    mm.stocker_matching(rech, sub, faux_verdict_dict())
    # Tant que la fiche ne bouge pas : cache frais.
    assert mm.matching_cache(rech, sub) is not None
    # La fiche change (nouveau text_hash) -> cache invalidé -> re-jugement.
    db.upsert_subside({"url_source": "https://a.be/veille", "titre": "Nouveau titre",
                       "deadline": "2098-01-01", "zone_categorie": "bruxelles",
                       "criteres_eligibilite": ["Autre critère"]}, "cocof", text_hash="v2")
    sub2 = db.get_subside(sid)
    assert mm.matching_cache(rech, sub2) is None


def test_renommer_recherche(env):
    db, pm, _ = env
    u = pm.get_or_create_user("x")
    p = pm.creer_profil(u["id"], {"nom": "R", "commune_siege": "Jette", "ephemere": True})
    pm.sauvegarder_recherche(p["id"], "Nom 1")
    r = pm.renommer_recherche(p["id"], "Nom 2")
    assert r["nom_recherche"] == "Nom 2"
    # Renommer un profil qui n'est pas une recherche : refusé (None).
    principal = pm.creer_profil(u["id"], {"nom": "ASBL", "commune_siege": "Uccle"})
    assert pm.renommer_recherche(principal["id"], "X") is None


# --- Purge ------------------------------------------------------------------

def test_purge_epargne_les_recherches_sauvegardees(env):
    db, pm, _ = env
    u = pm.get_or_create_user("x")
    vieux = "2020-01-01T00:00:00+00:00"
    ephem = pm.creer_profil(u["id"], {"nom": "E", "commune_siege": "Forest", "ephemere": True})
    rech = pm.creer_profil(u["id"], {"nom": "R", "commune_siege": "Forest", "ephemere": True})
    pm.sauvegarder_recherche(rech["id"], "Gardée")
    principal = pm.creer_profil(u["id"], {"nom": "P", "commune_siege": "Forest"})
    for pid in (ephem["id"], rech["id"], principal["id"]):
        db.connect().execute("UPDATE profils SET cree_le = ? WHERE id = ?", (vieux, pid))
    db.connect().commit()

    assert pm.purge_ephemeres(7) == 1                 # seul l'éphémère part
    assert pm.get_profil(ephem["id"]) is None
    assert pm.get_profil(rech["id"]) is not None      # recherche épargnée
    assert pm.get_profil(principal["id"]) is not None # principal épargné


# --- Liste + limite + cloisonnement -----------------------------------------

def test_lister_recherches_cloisonne_et_enrichi(env):
    db, pm, mm = env
    sid = seed_subside(db, "https://a.be/2")
    sub = db.get_subside(sid)
    ua = pm.get_or_create_user("a")
    ub = pm.get_or_create_user("b")
    ra = pm.creer_profil(ua["id"], {"nom": "RA", "commune_siege": "Ixelles", "ephemere": True})
    mm.stocker_matching(ra, sub, faux_verdict_dict())
    pm.sauvegarder_recherche(ra["id"], "Reche A")
    rb = pm.creer_profil(ub["id"], {"nom": "RB", "commune_siege": "Jette", "ephemere": True})
    pm.sauvegarder_recherche(rb["id"], "Reche B")

    listea = pm.lister_recherches(ua["id"])
    assert [r["nom_recherche"] for r in listea] == ["Reche A"]   # pas celle de B
    assert listea[0]["correspondances"] == 1                     # enrichi


def test_lister_profils_exclut_les_recherches(env):
    """Régression : une recherche (ephemere=0) ne doit PAS fuiter dans la liste
    des profils principaux (sinon le compte/l'édition la prendraient pour le
    profil de l'ASBL)."""
    db, pm, _ = env
    u = pm.get_or_create_user("x")
    principal = pm.creer_profil(u["id"], {"nom": "ASBL", "commune_siege": "Ixelles"})
    rech = pm.creer_profil(u["id"], {"nom": "R", "commune_siege": "Jette", "ephemere": True})
    pm.sauvegarder_recherche(rech["id"], "Une recherche")
    ids = [p["id"] for p in pm.lister_profils(u["id"])]
    assert ids == [principal["id"]]


def test_compter_recherches_pour_la_limite(env):
    db, pm, _ = env
    u = pm.get_or_create_user("x")
    assert pm.compter_recherches(u["id"]) == 0
    for i in range(3):
        p = pm.creer_profil(u["id"], {"nom": f"R{i}", "commune_siege": "Forest",
                                      "ephemere": True})
        pm.sauvegarder_recherche(p["id"], f"R{i}")
    assert pm.compter_recherches(u["id"]) == 3


def test_verifier_proprietaire_refuse_autre_user(env, monkeypatch):
    """Cloisonnement au niveau endpoint : un user ne touche pas la recherche
    d'un autre (403)."""
    db, pm, _ = env
    monkeypatch.setenv("DB_PATH", db.DB_PATH)
    import main; importlib.reload(main)
    from fastapi import HTTPException
    ua = pm.get_or_create_user("a")
    ub = pm.get_or_create_user("b")
    ra = pm.creer_profil(ua["id"], {"nom": "RA", "commune_siege": "Ixelles", "ephemere": True})
    pm.sauvegarder_recherche(ra["id"], "A")
    with pytest.raises(HTTPException) as exc:
        main._verifier_proprietaire({"id": ub["id"]}, ra["id"])
    assert exc.value.status_code == 403

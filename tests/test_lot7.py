"""Lot 7 : accompagnement de la candidature (étage 3).

Couvre le socle déterministe : migration, cloisonnement, cascade RGPD, stats,
récurrence, plafond quotidien, et le cache de checklist (régénération sur fiche
modifiée sans écraser les coches). Les appels LLM eux-mêmes sont mockés.
"""

import importlib

import pytest


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "lot7.db"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-faux")
    import db as dbm
    importlib.reload(dbm)
    dbm.init_db()
    import profils as pm; importlib.reload(pm)
    import candidatures as ca; importlib.reload(ca)
    import etage3; importlib.reload(etage3)
    yield dbm, pm, ca, etage3
    conn = getattr(dbm._local, "conn", None)
    if conn:
        conn.close()
        dbm._local.conn = None


def _subside(dbm, url="https://x/1", titre="Appel sport 2026", **over):
    # source_id et text_hash sont des paramètres de upsert_subside, pas des
    # champs du dict de données.
    source_id = over.pop("source_id", "cocof")
    text_hash = over.pop("text_hash", "h1")
    dbm.upsert_subside({"url_source": url, "titre": titre, **over},
                       source_id, text_hash=text_hash)
    return dbm.id_par_url(url)


# --- Migration + CRUD -------------------------------------------------------

def test_migration_cree_les_tables(env):
    dbm, *_ = env
    tables = {r["name"] for r in dbm.connect().execute(
        "select name from sqlite_master where type='table'")}
    for t in ("candidatures", "checklist_items", "checklist_meta",
              "copilote_messages", "etage3_usage", "etage3_cache"):
        assert t in tables


def test_creation_idempotente(env):
    dbm, pm, ca, _ = env
    u = pm.get_or_create_user("a")
    p = pm.creer_profil(u["id"], {"nom": "T", "commune_siege": "Ixelles"})
    s = _subside(dbm)
    c1 = ca.creer_candidature(p["id"], s)
    c2 = ca.creer_candidature(p["id"], s)   # même couple -> pas de doublon
    assert c1["id"] == c2["id"]
    assert c1["statut"] == "a_etudier"


def test_maj_statut_pose_les_dates_auto(env):
    dbm, pm, ca, _ = env
    u = pm.get_or_create_user("a")
    p = pm.creer_profil(u["id"], {"nom": "T", "commune_siege": "Ixelles"})
    c = ca.creer_candidature(p["id"], _subside(dbm))
    ca.maj_candidature(c["id"], {"statut": "soumis"})
    assert ca.get_candidature(c["id"])["date_soumission"] is not None
    ca.maj_candidature(c["id"], {"statut": "obtenu", "montant_obtenu": "2 500 €"})
    d = ca.get_candidature(c["id"])
    assert d["date_decision"] is not None
    assert d["montant_obtenu"] == 2500.0     # parsé en nombre


def test_montant_parse_depuis_texte_libre(env):
    _, _, ca, _ = env
    assert ca._parse_montant("3 000 €") == 3000.0
    assert ca._parse_montant("12500") == 12500.0
    assert ca._parse_montant("environ 1.500,50") == 1500.50
    assert ca._parse_montant("") is None
    assert ca._parse_montant(None) is None


# --- Statistiques -----------------------------------------------------------

def test_taux_succes_seulement_a_partir_de_3_decisions(env):
    dbm, pm, ca, _ = env
    u = pm.get_or_create_user("a")
    p = pm.creer_profil(u["id"], {"nom": "T", "commune_siege": "Ixelles"})
    for i, statut in enumerate(("obtenu", "refuse")):
        c = ca.creer_candidature(p["id"], _subside(dbm, url=f"https://x/{i}"))
        ca.maj_candidature(c["id"], {"statut": statut})
    assert ca.stats(p["id"])["taux_succes"] is None    # 2 décisions < 3
    c = ca.creer_candidature(p["id"], _subside(dbm, url="https://x/z"))
    ca.maj_candidature(c["id"], {"statut": "obtenu"})
    st = ca.stats(p["id"])
    assert st["decisions"] == 3
    assert st["taux_succes"] == round(2 / 3, 2)


def test_stats_somme_les_montants(env):
    dbm, pm, ca, _ = env
    u = pm.get_or_create_user("a")
    p = pm.creer_profil(u["id"], {"nom": "T", "commune_siege": "Ixelles"})
    c = ca.creer_candidature(p["id"], _subside(dbm))
    ca.maj_candidature(c["id"], {"montant_demande": "3000", "montant_obtenu": "2000"})
    st = ca.stats(p["id"])
    assert st["total_demande"] == 3000.0 and st["total_obtenu"] == 2000.0


# --- Cloisonnement + cascade RGPD ------------------------------------------

def test_user_de_candidature(env):
    dbm, pm, ca, _ = env
    ua = pm.get_or_create_user("a"); ub = pm.get_or_create_user("b")
    pa = pm.creer_profil(ua["id"], {"nom": "A", "commune_siege": "Ixelles"})
    c = ca.creer_candidature(pa["id"], _subside(dbm))
    assert ca.user_de_candidature(c["id"]) == ua["id"]
    assert ca.user_de_candidature(c["id"]) != ub["id"]


def test_suppression_profil_cascade_tout(env):
    dbm, pm, ca, e3 = env
    u = pm.get_or_create_user("a")
    p = pm.creer_profil(u["id"], {"nom": "T", "commune_siege": "Ixelles"})
    c = ca.creer_candidature(p["id"], _subside(dbm))
    e3.ajouter_item(c["id"], "Statuts")
    dbm.connect().execute(
        "insert into copilote_messages (candidature_id, action, entree, sortie, cree_le) "
        "values (?, 'relire', 'x', 'y', '2026-01-01')", (c["id"],))
    dbm.connect().commit()
    pm.supprimer_profil(p["id"])
    for t in ("candidatures", "checklist_items", "copilote_messages"):
        col = "id" if t == "candidatures" else "candidature_id"
        assert dbm.connect().execute(
            f"select count(*) from {t} where {col} = ?", (c["id"],)).fetchone()[0] == 0


# --- Récurrence -------------------------------------------------------------

def test_recurrence_meme_appel_annees_differentes(env):
    dbm, _, ca, _ = env
    _subside(dbm, url="https://x/25", titre="Prix Médiatine 2025", deadline="2025-09-01")
    id26 = _subside(dbm, url="https://x/26", titre="Prix Médiatine 2026", deadline="2026-09-01")
    sub = dbm.get_subside(id26)
    r = ca.detecter_recurrence(sub)
    assert r is not None
    assert r["annee"] == "2025" and r["annee_courante"] == "2026"


def test_pas_de_recurrence_sur_programmes_voisins_meme_annee(env):
    """Deux programmes proches de la MÊME édition ne sont pas une récurrence
    (écart d'année requis)."""
    dbm, _, ca, _ = env
    _subside(dbm, url="https://x/a", titre="Bourse exploratoire design 2026", deadline="2026-01-01")
    idb = _subside(dbm, url="https://x/b", titre="Bourse d'aboutissement design 2026", deadline="2026-02-01")
    assert ca.detecter_recurrence(dbm.get_subside(idb)) is None


def test_pas_de_recurrence_entre_sources_differentes(env):
    dbm, _, ca, _ = env
    _subside(dbm, url="https://x/c1", titre="Prix Médiatine 2025", source_id="cocof")
    idc = _subside(dbm, url="https://x/c2", titre="Prix Médiatine 2026", source_id="culture_be")
    # sources différentes -> pas considéré comme le même appel
    assert ca.detecter_recurrence(dbm.get_subside(idc)) is None


# --- Plafond quotidien ------------------------------------------------------

def test_plafond_quotidien_bloque_au_dela(env, monkeypatch):
    _, pm, _, e3 = env
    monkeypatch.setenv("MAX_APPELS_ETAGE3_PAR_JOUR", "2")
    u = pm.get_or_create_user("a")
    assert e3.appels_restants(u["id"]) == 2
    e3._consommer_un_appel(u["id"])
    e3._consommer_un_appel(u["id"])
    assert e3.appels_restants(u["id"]) == 0
    with pytest.raises(e3.PlafondAtteint):
        e3._consommer_un_appel(u["id"])


def test_plafond_ignore_en_mode_vanilla(env):
    """user_id None (Clerk inactif) : pas de quota, pas de blocage."""
    _, _, _, e3 = env
    for _ in range(100):
        e3._consommer_un_appel(None)   # ne lève jamais


# --- Checklist : cache + régénération sans écraser les coches ---------------

def _fausse_checklist(items):
    """Renvoie une fonction qui mocke l'appel LLM checklist."""
    def faux(system, schema, message, *, user_id, quoi):
        return {"items": items}, 0.001
    return faux


def test_checklist_generee_puis_cachee(env, monkeypatch):
    dbm, pm, ca, e3 = env
    u = pm.get_or_create_user("a")
    p = pm.creer_profil(u["id"], {"nom": "T", "commune_siege": "Ixelles"})
    c = ca.creer_candidature(p["id"], _subside(dbm, text_hash="h1"))

    appels = {"n": 0}
    def faux(*a, **k):
        appels["n"] += 1
        return {"items": [{"intitule": "Statuts de l'ASBL", "type": "document",
                           "source_citation": "joindre les statuts"}]}, 0.001
    monkeypatch.setattr(e3, "_appel_json", faux)

    r1 = e3.generer_checklist(c["id"], u["id"])
    assert len(r1["items"]) == 1 and appels["n"] == 1
    # 2e appel : même subside_hash -> cache, pas de nouvel appel LLM
    r2 = e3.generer_checklist(c["id"], u["id"])
    assert r2["depuis_cache"] is True and appels["n"] == 1


def test_checklist_regeneration_sur_fiche_modifiee_preserve_les_coches(env, monkeypatch):
    dbm, pm, ca, e3 = env
    u = pm.get_or_create_user("a")
    p = pm.creer_profil(u["id"], {"nom": "T", "commune_siege": "Ixelles"})
    url = "https://x/1"
    c = ca.creer_candidature(p["id"], _subside(dbm, url=url, text_hash="h1"))

    monkeypatch.setattr(e3, "_appel_json", _fausse_checklist(
        [{"intitule": "Statuts", "type": "document", "source_citation": "cit"}]))
    e3.generer_checklist(c["id"], u["id"])
    item = e3._checklist_stockee(c["id"])[0]
    e3.cocher_item(item["id"], True)                 # l'utilisateur coche

    # La fiche change (nouveau text_hash) + un nouvel item apparaît.
    dbm.upsert_subside({"url_source": url, "titre": "Appel sport 2026"},
                       "cocof", text_hash="h2")
    etat = e3.etat_checklist(c["id"])
    assert etat["fiche_a_change"] is True

    monkeypatch.setattr(e3, "_appel_json", _fausse_checklist([
        {"intitule": "Statuts", "type": "document", "source_citation": "cit"},
        {"intitule": "Budget prévisionnel", "type": "document", "source_citation": "cit2"}]))
    e3.generer_checklist(c["id"], u["id"], forcer=True)

    items = e3._checklist_stockee(c["id"])
    intitules = {i["intitule"] for i in items}
    assert intitules == {"Statuts", "Budget prévisionnel"}   # nouvel item ajouté
    statuts = next(i for i in items if i["intitule"] == "Statuts")
    assert statuts["coche"] == 1                             # la coche est préservée


def test_checklist_vide_marque_texte_absent(env, monkeypatch):
    dbm, pm, ca, e3 = env
    u = pm.get_or_create_user("a")
    p = pm.creer_profil(u["id"], {"nom": "T", "commune_siege": "Ixelles"})
    c = ca.creer_candidature(p["id"], _subside(dbm))
    monkeypatch.setattr(e3, "_appel_json", _fausse_checklist([]))
    r = e3.generer_checklist(c["id"], u["id"])
    assert r["items"] == [] and r["texte_absent"] is True


def test_item_utilisateur_ajoute_et_supprime(env):
    dbm, pm, ca, e3 = env
    u = pm.get_or_create_user("a")
    p = pm.creer_profil(u["id"], {"nom": "T", "commune_siege": "Ixelles"})
    c = ca.creer_candidature(p["id"], _subside(dbm))
    it = e3.ajouter_item(c["id"], "Ma pièce à moi")
    assert it["origine"] == "utilisateur"
    e3.supprimer_item(it["id"])
    assert e3._checklist_stockee(c["id"]) == []

import importlib

import pytest


@pytest.fixture
def db(tmp_path, monkeypatch):
    """db.py frais, pointant sur une base jetable."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    import db as db_module
    importlib.reload(db_module)
    db_module.init_db()
    yield db_module
    conn = getattr(db_module._local, "conn", None)
    if conn:
        conn.close()
        db_module._local.conn = None


# --- Normalisation d'URL ---------------------------------------------------

from db import normaliser_url  # noqa: E402  (fonction pure, pas besoin de la fixture)


@pytest.mark.parametrize("brut,attendu", [
    # slash final
    ("https://a.be/x/", "https://a.be/x"),
    ("https://a.be/x", "https://a.be/x"),
    ("https://a.be/", "https://a.be/"),          # racine : le slash reste
    # casse
    ("HTTPS://A.BE/X", "https://a.be/X"),        # host minuscule, path préservé
    # fragment
    ("https://a.be/x#section", "https://a.be/x"),
    # ports par défaut
    ("https://a.be:443/x", "https://a.be/x"),
    ("http://a.be:80/x", "http://a.be/x"),
    ("https://a.be:8443/x", "https://a.be:8443/x"),   # port explicite conservé
    # tracking
    ("https://a.be/x?utm_source=nl&utm_campaign=c", "https://a.be/x"),
    ("https://a.be/x?fbclid=123", "https://a.be/x"),
    ("https://a.be/x?gclid=1&id=7", "https://a.be/x?id=7"),
    ("https://a.be/x?UTM_SOURCE=nl", "https://a.be/x"),   # insensible à la casse
    # params significatifs conservés et triés
    ("https://a.be/x?b=2&a=1", "https://a.be/x?a=1&b=2"),
    # combiné
    ("HTTPS://A.BE/x/?utm_source=z&id=1#frag", "https://a.be/x?id=1"),
    # vide
    ("", ""),
    ("   ", ""),
])
def test_normaliser_url(brut, attendu):
    assert normaliser_url(brut) == attendu


def test_normalisation_idempotente():
    u = "HTTPS://A.BE/x/?utm_source=z&b=2&a=1#frag"
    once = normaliser_url(u)
    assert normaliser_url(once) == once


def test_urls_equivalentes_meme_cle():
    variantes = [
        "https://info.hub.brussels/subsides/finexpo",
        "https://info.hub.brussels/subsides/finexpo/",
        "https://info.hub.brussels/subsides/finexpo#top",
        "https://info.hub.brussels/subsides/finexpo?utm_source=newsletter",
        "HTTPS://INFO.HUB.BRUSSELS/subsides/finexpo",
    ]
    assert len({normaliser_url(u) for u in variantes}) == 1


def test_query_distincte_reste_distincte():
    # Deux fiches réellement différentes ne doivent pas fusionner.
    assert normaliser_url("https://a.be/f?id=1") != normaliser_url("https://a.be/f?id=2")


# --- Normalisation TYPO3 (culture.be) --------------------------------------

def test_typo3_meme_fiche_contextes_differents_fusionnent():
    # Même tt_news=11664, mais backPid et cHash différents (contexte de nav).
    a = ("https://www.culture.be/vous-cherchez/appels-a-projetcandidature/detail/"
         "?tx_ttnews%5BbackPid%5D=17500&tx_ttnews%5Btt_news%5D=11664&cHash=aaa111")
    b = ("https://www.culture.be/vous-cherchez/appels-a-projetcandidature/detail/"
         "?tx_ttnews%5BbackPid%5D=99999&tx_ttnews%5Btt_news%5D=11664&cHash=bbb222")
    assert normaliser_url(a) == normaliser_url(b)


def test_typo3_fiches_differentes_restent_distinctes():
    a = "https://c.be/detail/?tx_ttnews%5Btt_news%5D=11664&cHash=x"
    b = "https://c.be/detail/?tx_ttnews%5Btt_news%5D=11663&cHash=y"
    assert normaliser_url(a) != normaliser_url(b)


def test_typo3_tt_news_conserve():
    u = "https://c.be/detail/?tx_ttnews%5Btt_news%5D=11664&cHash=abc&tx_ttnews%5BbackPid%5D=17500"
    n = normaliser_url(u)
    assert "tt_news" in n and "11664" in n
    assert "chash" not in n.lower() and "backpid" not in n.lower()


def test_typo3_pointer_et_chash_retires():
    u = "https://c.be/appels/?tx_ttnews%5Bpointer%5D=2&cHash=8c01"
    assert normaliser_url(u) == "https://c.be/appels"


def test_no_cache_retire():
    assert normaliser_url("https://c.be/x?no_cache=1&id=7") == "https://c.be/x?id=7"


# --- Hash source (court-circuit de ré-extraction) --------------------------

def test_hash_texte_deterministe():
    from db import hash_texte
    assert hash_texte("bonjour") == hash_texte("bonjour")
    assert hash_texte("a") != hash_texte("b")
    assert len(hash_texte("x")) == 64  # sha-256 hex


def test_hash_connu_apres_insert(db):
    h = db.hash_texte("texte de la fiche")
    db.upsert_subside(fiche(), "hub", text_hash=h)
    assert db.hash_connu("https://info.hub.brussels/subsides/finexpo") == h


def test_hash_connu_none_si_absente(db):
    assert db.hash_connu("https://jamais.vue/x") is None


def test_hash_connu_none_si_echec(db):
    # Une fiche en échec doit être retentée -> hash_connu renvoie None.
    db.upsert_subside(fiche(), "hub", text_hash=None, echec_extraction=True,
                      raw_text="brut")
    assert db.hash_connu(fiche()["url_source"]) is None


def test_hash_connu_insensible_a_l_url_variante(db):
    h = db.hash_texte("t")
    db.upsert_subside(fiche(), "hub", text_hash=h)
    # URL avec slash final + tracking -> même clé normalisée -> même hash retrouvé
    assert db.hash_connu("https://info.hub.brussels/subsides/finexpo/?utm_source=x") == h


def test_toucher_marque_inchange(db):
    db.upsert_subside(fiche(), "hub", text_hash="h")
    avant = db.lister_subsides()[0]["derniere_verification"]
    assert db.toucher(fiche()["url_source"]) == "inchange"
    apres = db.lister_subsides()[0]
    assert apres["statut"] == "inchange"
    assert apres["derniere_verification"] >= avant


# --- Détection de changement normalisée (anti faux "modifié") --------------

def test_reformulation_cosmetique_reste_inchange(db):
    db.upsert_subside(fiche(montant="5 000 €", titre="Finexpo"), "hub", text_hash="h1")
    # même sens, casse/espaces différents -> ne doit PAS être "modifié"
    r = db.upsert_subside(fiche(montant="5 000 €  ", titre="FINEXPO"), "hub", text_hash="h2")
    assert r == "inchange"


def test_vrai_changement_montant_reste_modifie(db):
    db.upsert_subside(fiche(montant="5 000 €"), "hub", text_hash="h1")
    assert db.upsert_subside(fiche(montant="9 999 €"), "hub", text_hash="h2") == "modifie"


def test_criteres_reordonnes_restent_inchanges(db):
    db.upsert_subside(fiche(criteres_eligibilite=["A", "B"]), "hub", text_hash="h1")
    r = db.upsert_subside(fiche(criteres_eligibilite=["b", "a"]), "hub", text_hash="h2")
    assert r == "inchange"      # même ensemble, ordre/casse différents


# --- Zone ------------------------------------------------------------------

def test_zone_stockee_et_filtrable(db):
    db.upsert_subside({**fiche(url_source="https://a.be/1"),
                       "zone_geographique": "Région de Bruxelles-Capitale",
                       "zone_categorie": "bruxelles"}, "hub")
    db.upsert_subside({**fiche(url_source="https://a.be/2"),
                       "zone_geographique": "Flandre", "zone_categorie": "flandre"}, "hub")
    assert len(db.lister_subsides(zone="bruxelles")) == 1
    assert db.lister_subsides(zone="bruxelles")[0]["zone_categorie"] == "bruxelles"


def test_zone_defaut_inconnue(db):
    db.upsert_subside(fiche(), "hub")   # pas de zone fournie
    assert db.lister_subsides()[0]["zone_categorie"] == "inconnue"


def test_migration_ajoute_colonnes_sur_base_ancienne(tmp_path, monkeypatch):
    """Une base créée sans les colonnes zone/hash doit être migrée sans perte."""
    import sqlite3
    p = tmp_path / "vieux.db"
    conn = sqlite3.connect(p)
    # Schéma v1 réel (avant lot 2) : a deadline mais PAS zone/hash.
    conn.execute("""CREATE TABLE subsides (
        id INTEGER PRIMARY KEY, url_source TEXT UNIQUE, source_id TEXT,
        titre TEXT, deadline TEXT, statut TEXT NOT NULL,
        premiere_detection TEXT NOT NULL, derniere_verification TEXT NOT NULL)""")
    conn.execute("INSERT INTO subsides (id,url_source,source_id,titre,statut,"
                 "premiere_detection,derniere_verification) VALUES "
                 "(1,'https://a.be/x','hub','T','nouveau','2026-01-01','2026-01-01')")
    conn.commit(); conn.close()

    monkeypatch.setenv("DB_PATH", str(p))
    import importlib, db as dbm
    importlib.reload(dbm)
    dbm.init_db()   # doit ajouter zone_geographique, zone_categorie, text_hash
    cols = {r["name"] for r in dbm.connect().execute("PRAGMA table_info(subsides)")}
    assert {"zone_geographique", "zone_categorie", "text_hash"} <= cols
    # la fiche existante survit
    assert dbm.get_subside(1)["titre"] == "T"
    dbm.connect().close(); dbm._local.conn = None
    importlib.reload(dbm)


# --- Dédup / upsert --------------------------------------------------------

def fiche(**over):
    base = {
        "url_source": "https://info.hub.brussels/subsides/finexpo",
        "titre": "Finexpo",
        "organisme": "SPF",
        "description": "Aide à l'export.",
        "montant": "5 000 €",
        "deadline": "2026-12-31",
        "permanent": False,
        "public_cible": "ASBL",
        "criteres_eligibilite": ["Siège en RBC"],
        "secteurs": ["Export"],
        "lien_candidature": "https://finexpo.be/form",
        "langue": "fr",
    }
    base.update(over)
    return base


def test_insert_nouveau(db):
    assert db.upsert_subside(fiche(), "hub") == "nouveau"
    assert len(db.lister_subsides()) == 1


def test_rejoue_identique_est_inchange(db):
    db.upsert_subside(fiche(), "hub")
    assert db.upsert_subside(fiche(), "hub") == "inchange"
    assert len(db.lister_subsides()) == 1     # pas de doublon


def test_idempotence_urls_equivalentes(db):
    db.upsert_subside(fiche(), "hub")
    db.upsert_subside(fiche(url_source="https://info.hub.brussels/subsides/finexpo/"), "hub")
    db.upsert_subside(fiche(url_source="https://info.hub.brussels/subsides/finexpo?utm_source=x"), "hub")
    assert len(db.lister_subsides()) == 1


@pytest.mark.parametrize("champ,valeur", [
    ("deadline", "2027-01-15"),
    ("montant", "10 000 €"),
    ("titre", "Finexpo 2027"),
    ("criteres_eligibilite", ["Siège en RBC", "Moins de 50 ETP"]),
])
def test_champs_suivis_declenchent_modifie(db, champ, valeur):
    db.upsert_subside(fiche(), "hub")
    assert db.upsert_subside(fiche(**{champ: valeur}), "hub") == "modifie"
    s = db.lister_subsides()[0]
    assert s["statut"] == "modifie"
    assert champ in s["modifications"]
    assert s["modifications"][champ]["avant"] is not None


def test_champ_non_suivi_ne_declenche_pas_modifie(db):
    db.upsert_subside(fiche(), "hub")
    # public_cible n'est pas dans CHAMPS_SUIVIS
    assert db.upsert_subside(fiche(public_cible="Autre"), "hub") == "inchange"


def test_premiere_detection_stable_derniere_verification_bouge(db):
    db.upsert_subside(fiche(), "hub")
    avant = db.lister_subsides()[0]
    db.upsert_subside(fiche(montant="99 €"), "hub")
    apres = db.lister_subsides()[0]
    assert apres["premiere_detection"] == avant["premiere_detection"]
    assert apres["derniere_verification"] >= avant["derniere_verification"]


def test_url_source_manquante_leve(db):
    with pytest.raises(ValueError):
        db.upsert_subside(fiche(url_source=""), "hub")


def test_echec_extraction_conserve_le_brut(db):
    db.upsert_subside(fiche(), "hub", raw_text="texte brut", echec_extraction=True)
    s = db.get_subside(db.lister_subsides()[0]["id"])
    assert s["statut"] == "echec_extraction" and s["raw_text"] == "texte brut"


def test_echec_extraction_ne_detruit_pas_les_donnees_existantes(db):
    db.upsert_subside(fiche(), "hub")
    db.upsert_subside(fiche(titre=None), "hub", raw_text="brut", echec_extraction=True)
    s = db.lister_subsides()[0]
    assert s["statut"] == "echec_extraction"
    assert s["titre"] == "Finexpo"        # l'ancienne valeur valide survit


# --- Lecture ---------------------------------------------------------------

def test_tri_deadline_futur_puis_permanent_puis_expire(db):
    # Tri lot 3 : à venir croissantes -> permanent/null -> expirés en bas.
    db.upsert_subside(fiche(url_source="https://a.be/1", deadline=None), "hub")
    db.upsert_subside(fiche(url_source="https://a.be/2", deadline="2020-01-01"), "hub")   # expiré
    db.upsert_subside(fiche(url_source="https://a.be/3", deadline="2099-09-09"), "hub")   # futur lointain
    db.upsert_subside(fiche(url_source="https://a.be/4", deadline="2099-01-01"), "hub")   # futur proche
    assert [s["deadline"] for s in db.lister_subsides(tri="deadline")] == [
        "2099-01-01", "2099-09-09", None, "2020-01-01",
    ]


def test_expire_calcule(db):
    db.upsert_subside(fiche(url_source="https://a.be/1", deadline="2020-01-01"), "hub")
    db.upsert_subside(fiche(url_source="https://a.be/2", deadline="2099-01-01"), "hub")
    db.upsert_subside(fiche(url_source="https://a.be/3", deadline=None, permanent=True), "hub")
    par_url = {s["url_source"]: s for s in db.lister_subsides()}
    assert par_url["https://a.be/1"]["expire"] is True
    assert par_url["https://a.be/2"]["expire"] is False
    assert par_url["https://a.be/3"]["expire"] is False   # permanent n'expire pas


def test_masquer_expires(db):
    db.upsert_subside(fiche(url_source="https://a.be/1", deadline="2020-01-01"), "hub")
    db.upsert_subside(fiche(url_source="https://a.be/2", deadline="2099-01-01"), "hub")
    assert len(db.lister_subsides()) == 2
    visibles = db.lister_subsides(masquer_expires=True)
    assert len(visibles) == 1 and visibles[0]["deadline"] == "2099-01-01"


def test_filtre_par_source(db):
    db.upsert_subside(fiche(url_source="https://a.be/1"), "hub")
    db.upsert_subside(fiche(url_source="https://b.be/1"), "kbs")
    assert len(db.lister_subsides(source="kbs")) == 1


def test_filtre_a_verifier(db):
    db.upsert_subside(fiche(url_source="https://a.be/1"), "hub", a_verifier=True)
    db.upsert_subside(fiche(url_source="https://a.be/2"), "hub", a_verifier=False)
    assert len(db.lister_subsides(statut="a_verifier")) == 1


def test_listes_json_font_l_aller_retour(db):
    db.upsert_subside(fiche(criteres_eligibilite=["a", "b"], secteurs=["x"]), "hub")
    s = db.lister_subsides()[0]
    assert s["criteres_eligibilite"] == ["a", "b"] and s["secteurs"] == ["x"]


def test_raw_text_absent_de_la_liste_present_au_detail(db):
    db.upsert_subside(fiche(), "hub", raw_text="brut")
    assert "raw_text" not in db.lister_subsides()[0]
    assert db.get_subside(db.lister_subsides()[0]["id"])["raw_text"] == "brut"

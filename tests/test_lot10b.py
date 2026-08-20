"""Lot 10B : obligations post-octroi.

Socle déterministe : migration, génération (LLM mocké), délais relatifs +
ancrage (jamais de date inventée), cache/régénération sans perdre les 'fait',
cloisonnement, cascade RGPD, échéances du profil.
"""

import importlib

import pytest


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "lot10b.db"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-faux")
    import db as dbm; importlib.reload(dbm); dbm.init_db()
    import profils as pm; importlib.reload(pm)
    import candidatures as ca; importlib.reload(ca)
    import etage3; importlib.reload(etage3)
    import obligations as ob; importlib.reload(ob)
    yield dbm, pm, ca, etage3, ob
    conn = getattr(dbm._local, "conn", None)
    if conn:
        conn.close(); dbm._local.conn = None


def _cand(dbm, pm, ca, **sub):
    u = pm.get_or_create_user("a")
    p = pm.creer_profil(u["id"], {"nom": "T", "commune_siege": "Ixelles"})
    dbm.upsert_subside({"url_source": "https://x/1", "titre": "Appel sport 2026", **sub},
                       "cocof", text_hash=sub.get("text_hash", "h1"))
    sid = dbm.id_par_url("https://x/1")
    return p, ca.creer_candidature(p["id"], sid), sid


def _mock(etage3, items):
    def faux(*a, **k):
        return {"items": items}, 0.001
    etage3._appel_json = faux


# --- Migration --------------------------------------------------------------

def test_migration(env):
    dbm, *_ = env
    tables = {r["name"] for r in dbm.connect().execute(
        "select name from sqlite_master where type='table'")}
    assert {"obligations", "obligations_meta"} <= tables
    cols = {r[1] for r in dbm.connect().execute("PRAGMA table_info(candidatures)")}
    assert "date_fin_projet" in cols


# --- Génération -------------------------------------------------------------

def test_generation_avec_citation_et_date_absolue(env):
    dbm, pm, ca, etage3, ob = env
    p, c, _ = _cand(dbm, pm, ca)
    _mock(etage3, [
        {"intitule": "Déclaration de créance", "type": "justificatif",
         "echeance": "2027-03-31", "delai_jours": None, "source_citation": "au plus tard le 31 mars 2027"},
        {"intitule": "Apposer le logo de la COCOF", "type": "communication",
         "echeance": None, "delai_jours": None, "source_citation": "le logo doit figurer sur tous les supports"},
    ])
    etat = ob.generer_obligations(c["id"], None)
    assert etat["total"] == 2 and etat["generee"]
    just = next(i for i in etat["items"] if i["type"] == "justificatif")
    assert just["echeance"] == "2027-03-31"
    assert just["source_citation"] and just["source"] == "reglement"
    assert not etat["ancrage_requis"]


def test_delai_relatif_demande_ancrage_puis_calcule(env):
    dbm, pm, ca, etage3, ob = env
    p, c, _ = _cand(dbm, pm, ca)
    _mock(etage3, [
        {"intitule": "Rapport dans les 3 mois suivant la fin du projet", "type": "rapport",
         "echeance": None, "delai_jours": 90, "source_citation": "endéans les 3 mois"},
    ])
    etat = ob.generer_obligations(c["id"], None)
    assert etat["ancrage_requis"] is True
    assert etat["items"][0]["echeance"] is None      # pas de date inventée
    # Ancrage : fin de projet -> échéance = ancre + 90 j.
    etat = ob.definir_ancrage(c["id"], "2027-01-01")
    assert etat["items"][0]["echeance"] == "2027-04-01"
    assert etat["ancrage_requis"] is False
    # Effacer l'ancrage remet l'échéance à null (jamais figée arbitrairement).
    etat = ob.definir_ancrage(c["id"], None)
    assert etat["items"][0]["echeance"] is None


def test_date_absurde_llm_ignoree(env):
    dbm, pm, ca, etage3, ob = env
    p, c, _ = _cand(dbm, pm, ca)
    _mock(etage3, [{"intitule": "X", "type": "autre", "echeance": "bientôt",
                    "delai_jours": None, "source_citation": "c"}])
    etat = ob.generer_obligations(c["id"], None)
    assert etat["items"][0]["echeance"] is None      # 'bientôt' n'est pas une date


def test_texte_muet_liste_vide(env):
    dbm, pm, ca, etage3, ob = env
    p, c, _ = _cand(dbm, pm, ca)
    _mock(etage3, [])
    etat = ob.generer_obligations(c["id"], None)
    assert etat["total"] == 0 and etat["texte_absent"] and etat["generee"]


# --- Cache + régénération ---------------------------------------------------

def test_cache_et_regeneration_preserve_fait(env):
    dbm, pm, ca, etage3, ob = env
    p, c, _ = _cand(dbm, pm, ca, text_hash="h1")
    _mock(etage3, [{"intitule": "Rapport final", "type": "rapport",
                    "echeance": None, "delai_jours": None, "source_citation": "c"}])
    etat = ob.generer_obligations(c["id"], None)
    oid = etat["items"][0]["id"]
    ob.basculer(oid, True)                       # marquée faite
    # 2e appel sans forcer, même hash -> cache, aucun doublon.
    etat = ob.generer_obligations(c["id"], None)
    assert etat.get("depuis_cache") and etat["total"] == 1
    # La fiche change -> régénération ; le 'fait' est préservé, pas de doublon.
    dbm.upsert_subside({"url_source": "https://x/1", "titre": "Appel sport 2026",
                        "montant": "5000 €"}, "cocof", text_hash="h2")
    etat = ob.generer_obligations(c["id"], None, forcer=True)
    faites = [i for i in etat["items"] if i["statut"] == "fait"]
    assert len(faites) == 1 and etat["total"] == 1


def test_en_regle_quand_tout_fait(env):
    dbm, pm, ca, etage3, ob = env
    p, c, _ = _cand(dbm, pm, ca)
    _mock(etage3, [{"intitule": "A", "type": "autre", "echeance": None,
                    "delai_jours": None, "source_citation": "c"}])
    etat = ob.generer_obligations(c["id"], None)
    assert not etat["en_regle"]
    ob.basculer(etat["items"][0]["id"], True)
    assert ob.etat_obligations(c["id"])["en_regle"] is True


# --- Manuel + cloisonnement + cascade --------------------------------------

def test_ajout_manuel(env):
    dbm, pm, ca, etage3, ob = env
    p, c, _ = _cand(dbm, pm, ca)
    o = ob.ajouter(c["id"], "Envoyer les comptes", "2027-06-30", "justificatif")
    assert o["source"] == "manuelle" and o["echeance"] == "2027-06-30"


def test_cloisonnement(env):
    dbm, pm, ca, etage3, ob = env
    p, c, _ = _cand(dbm, pm, ca)
    o = ob.ajouter(c["id"], "X")
    ua = pm.get_or_create_user("a")
    assert ob.user_de_obligation(o["id"]) == ua["id"]
    assert ob.user_de_obligation(999999) is None


def test_cascade_rgpd(env):
    dbm, pm, ca, etage3, ob = env
    p, c, _ = _cand(dbm, pm, ca)
    ob.ajouter(c["id"], "X")
    assert ca.supprimer_candidature(c["id"]) is True
    assert dbm.connect().execute(
        "SELECT COUNT(*) n FROM obligations WHERE candidature_id=?", (c["id"],)
    ).fetchone()["n"] == 0


def test_echeances_du_profil_seulement_a_faire_datees(env):
    dbm, pm, ca, etage3, ob = env
    p, c, _ = _cand(dbm, pm, ca)
    o1 = ob.ajouter(c["id"], "Datée", "2027-05-01")
    ob.ajouter(c["id"], "Sans date")             # pas d'échéance -> exclue
    faite = ob.ajouter(c["id"], "Faite", "2027-04-01"); ob.basculer(faite["id"], True)
    ech = ob.echeances_du_profil(p["id"])
    assert [e["id"] for e in ech] == [o1["id"]]

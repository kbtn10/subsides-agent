"""Lot 10A : coffre documentaire — chiffrement, flag, limites, fraîcheur,
versions, cascade RGPD (suppression physique), pont checklist.
"""

import importlib

import pytest
from cryptography.fernet import Fernet


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "l10a.db"))
    monkeypatch.setenv("DATA_DOCUMENTS", str(tmp_path / "docs"))
    monkeypatch.setenv("DOCUMENTS_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("COFFRE_ACTIF", "true")
    monkeypatch.setenv("MAX_DOCUMENTS_PAR_PROFIL", "30")
    import db as dbm; importlib.reload(dbm); dbm.init_db()
    import profils as pm; importlib.reload(pm)
    import coffre; importlib.reload(coffre)
    u = pm.get_or_create_user("a")
    p = pm.creer_profil(u["id"], {"nom": "T", "commune_siege": "Ixelles"})
    yield dbm, pm, coffre, p, tmp_path
    conn = getattr(dbm._local, "conn", None)
    if conn:
        conn.close(); dbm._local.conn = None


PDF = "application/pdf"


# --- Flag -------------------------------------------------------------------

def test_flag_off_refuse_upload(env, monkeypatch):
    dbm, pm, coffre, p, _ = env
    monkeypatch.setenv("COFFRE_ACTIF", "false")
    assert coffre.actif() is False
    with pytest.raises(coffre.CoffreDesactive):
        coffre.uploader(p["id"], "statuts", "S", "s.pdf", PDF, b"x")


# --- Chiffrement round-trip -------------------------------------------------

def test_chiffrement_round_trip(env):
    dbm, pm, coffre, p, tmp = env
    secret = b"CONTENU-CONFIDENTIEL-ASBL"
    d = coffre.uploader(p["id"], "statuts", "Statuts", "statuts.pdf", PDF, secret)
    disque = (tmp / "docs" / d["chemin_stockage"]).read_bytes()
    assert secret not in disque                     # illisible sur le disque
    assert d["chemin_stockage"].endswith(".enc") and "statuts" not in d["chemin_stockage"]
    nom, mime, data = coffre.telecharger(d["id"])
    assert data == secret and nom == "statuts.pdf"  # l'original restitué


# --- Limites ----------------------------------------------------------------

def test_type_refuse(env):
    dbm, pm, coffre, p, _ = env
    with pytest.raises(coffre.DocumentRefuse):
        coffre.uploader(p["id"], "statuts", "S", "s.exe", "application/x-msdownload", b"x")


def test_taille_refusee(env):
    dbm, pm, coffre, p, _ = env
    with pytest.raises(coffre.DocumentRefuse):
        coffre.uploader(p["id"], "statuts", "S", "s.pdf", PDF, b"x" * (coffre.TAILLE_MAX + 1))


def test_quota(env, monkeypatch):
    dbm, pm, coffre, p, _ = env
    monkeypatch.setattr(coffre, "MAX_PAR_PROFIL", 2)
    coffre.uploader(p["id"], "statuts", "S", "s.pdf", PDF, b"a")
    coffre.uploader(p["id"], "bilan", "B", "b.pdf", PDF, b"b")
    with pytest.raises(coffre.DocumentRefuse):
        coffre.uploader(p["id"], "comptes_annuels", "C", "c.pdf", PDF, b"c")


# --- Péremption / fraîcheur -------------------------------------------------

def test_peremption_par_categorie(env):
    dbm, pm, coffre, p, _ = env
    from datetime import date
    base = "2026-01-15"
    onss = coffre.uploader(p["id"], "attestation_onss", "ONSS", "o.pdf", PDF, b"o", date_document=base)
    banc = coffre.uploader(p["id"], "attestation_bancaire", "B", "b.pdf", PDF, b"b", date_document=base)
    cptes = coffre.uploader(p["id"], "comptes_annuels", "C", "c.pdf", PDF, b"c", date_document=base)
    stat = coffre.uploader(p["id"], "statuts", "S", "s.pdf", PDF, b"s", date_document=base)
    assert onss["expire_le"] == "2026-04-15"   # +3 mois
    assert banc["expire_le"] == "2026-07-15"   # +6 mois
    assert cptes["expire_le"] == "2027-01-15"  # +12 mois
    assert stat["expire_le"] is None           # statuts : pas de péremption


def test_agrement_utilise_echeance_saisie(env):
    dbm, pm, coffre, p, _ = env
    d = coffre.uploader(p["id"], "agrement", "Agrément", "a.pdf", PDF, b"a",
                        date_document="2026-01-01", expire_le="2028-12-31")
    assert d["expire_le"] == "2028-12-31"      # échéance saisie, pas calculée


def test_fraicheur_etats(env):
    dbm, pm, coffre, p, _ = env
    from datetime import date, timedelta
    today = date(2026, 6, 1)
    assert coffre.fraicheur(None, today)["etat"] == "a_jour"
    assert coffre.fraicheur((today + timedelta(days=90)).isoformat(), today)["etat"] == "a_jour"
    assert coffre.fraicheur((today + timedelta(days=10)).isoformat(), today)["etat"] == "expire_bientot"
    assert coffre.fraicheur((today - timedelta(days=5)).isoformat(), today)["etat"] == "a_renouveler"


# --- Versions (remplacement) ------------------------------------------------

def test_remplacement_archive_ancien(env):
    dbm, pm, coffre, p, _ = env
    v1 = coffre.uploader(p["id"], "statuts", "Statuts v1", "s1.pdf", PDF, b"1")
    v2 = coffre.uploader(p["id"], "statuts", "Statuts v2", "s2.pdf", PDF, b"2")
    assert v2["remplace_document_id"] == v1["id"]
    etat = coffre.etat_coffre(p["id"])
    cat = next(c for c in etat["categories"] if c["id"] == "statuts")
    assert cat["document"]["id"] == v2["id"] and cat["versions_count"] == 1
    assert coffre.compter(p["id"]) == 1        # v1 archivée ne compte pas au quota


# --- Suppression physique + cascade RGPD ------------------------------------

def test_suppression_physique(env):
    dbm, pm, coffre, p, tmp = env
    d = coffre.uploader(p["id"], "statuts", "S", "s.pdf", PDF, b"x")
    chemin = tmp / "docs" / d["chemin_stockage"]
    assert chemin.exists()
    assert coffre.supprimer(d["id"]) is True
    assert not chemin.exists()                 # fichier vraiment effacé
    assert coffre._get(d["id"]) is None


def test_cascade_rgpd_supprime_fichiers(env):
    dbm, pm, coffre, p, tmp = env
    d1 = coffre.uploader(p["id"], "statuts", "S", "s.pdf", PDF, b"1")
    d2 = coffre.uploader(p["id"], "bilan", "B", "b.pdf", PDF, b"2")
    coffre.supprimer_fichiers_du_profil(p["id"])
    assert not (tmp / "docs" / d1["chemin_stockage"]).exists()
    assert not (tmp / "docs" / d2["chemin_stockage"]).exists()
    # puis la cascade DB (FK) retire les lignes
    assert pm.supprimer_profil(p["id"]) is True
    assert coffre._get(d1["id"]) is None


def test_cloisonnement(env):
    dbm, pm, coffre, p, _ = env
    d = coffre.uploader(p["id"], "statuts", "S", "s.pdf", PDF, b"x")
    u = pm.get_or_create_user("a")
    assert coffre.user_de_document(d["id"]) == u["id"]
    assert coffre.user_de_document(999999) is None


# --- Pont checklist <-> coffre ----------------------------------------------

@pytest.mark.parametrize("intitule,cat", [
    ("Statuts de l'ASBL", "statuts"),
    ("Comptes annuels 2025", "comptes_annuels"),
    ("Composition du conseil d'administration", "composition_ca"),
    ("Attestation bancaire (RIB)", "attestation_bancaire"),
    ("Attestation ONSS", "attestation_onss"),
    ("Budget prévisionnel du projet", None),   # non reconnu -> None
])
def test_mapping_checklist(env, intitule, cat):
    dbm, pm, coffre, p, _ = env
    assert coffre.categorie_pour_intitule(intitule) == cat


def test_rapprochement_present_et_a_jour(env):
    dbm, pm, coffre, p, _ = env
    coffre.uploader(p["id"], "statuts", "Statuts 2024", "s.pdf", PDF, b"x")
    items = [{"id": 1, "intitule": "Statuts de l'ASBL"},
             {"id": 2, "intitule": "Devis du prestataire"}]
    rap = coffre.rapprochement_checklist(p["id"], items)
    assert rap[1]["present"] and rap[1]["a_jour"] and rap[1]["categorie"] == "statuts"
    assert 2 not in rap                          # item non mappé -> pas de pont


def test_rapprochement_vide_si_flag_off(env, monkeypatch):
    dbm, pm, coffre, p, _ = env
    coffre.uploader(p["id"], "statuts", "S", "s.pdf", PDF, b"x")
    monkeypatch.setenv("COFFRE_ACTIF", "false")
    assert coffre.rapprochement_checklist(p["id"], [{"id": 1, "intitule": "Statuts"}]) == {}


# --- Endpoint : flag off -> 403 partout -------------------------------------

def test_endpoints_403_si_flag_off(tmp_path, monkeypatch):
    import importlib
    monkeypatch.setenv("DB_PATH", str(tmp_path / "ep.db"))
    monkeypatch.setenv("DATA_DOCUMENTS", str(tmp_path / "docs"))
    monkeypatch.setenv("DOCUMENTS_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("COFFRE_ACTIF", "false")
    import db as dbm; importlib.reload(dbm); dbm.init_db()
    import coffre; importlib.reload(coffre)
    import main; importlib.reload(main)
    # Mode vanilla APRÈS le load_dotenv() de main : auth désactivée -> on atteint
    # bien la garde du flag (403) plutôt que la garde d'auth (401).
    monkeypatch.setenv("CLERK_JWKS_URL", "")
    from fastapi.testclient import TestClient
    cli = TestClient(main.app)
    assert cli.get("/coffre/1").status_code == 403
    assert cli.get("/document/1/download").status_code == 403
    assert cli.delete("/document/1").status_code == 403
    # /coffre/config reste accessible et annonce actif=false
    r = cli.get("/coffre/config")
    assert r.status_code == 200 and r.json()["actif"] is False

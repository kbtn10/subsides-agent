"""Lot 10C : mémoire des dossiers (repartir de l'édition précédente).

L'encart mémoire n'apparaît QUE si l'ASBL a candidaté à l'édition antérieure ;
« repartir » pré-remplit montant + notes mais JAMAIS la checklist.
"""

import importlib

import pytest


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "lot10c.db"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-faux")
    import db as dbm; importlib.reload(dbm); dbm.init_db()
    import profils as pm; importlib.reload(pm)
    import candidatures as ca; importlib.reload(ca)
    import etage3; importlib.reload(etage3)
    yield dbm, pm, ca, etage3
    conn = getattr(dbm._local, "conn", None)
    if conn:
        conn.close(); dbm._local.conn = None


def _sub(dbm, url, titre, **over):
    dbm.upsert_subside({"url_source": url, "titre": titre, **over}, "cocof",
                       text_hash=over.get("text_hash", "h-" + url))
    return dbm.id_par_url(url)


def _profil(pm):
    u = pm.get_or_create_user("a")
    return pm.creer_profil(u["id"], {"nom": "T", "commune_siege": "Ixelles"})


# --- memoire_pour -----------------------------------------------------------

def test_pas_de_memoire_sans_recurrence(env):
    dbm, pm, ca, _ = env
    p = _profil(pm)
    sid = _sub(dbm, "https://x/nouveau", "Un appel unique 2026")
    assert ca.memoire_pour(p["id"], dbm.get_subside(sid)) is None


def test_pas_de_memoire_si_ancienne_edition_non_candidatee(env):
    dbm, pm, ca, _ = env
    p = _profil(pm)
    _sub(dbm, "https://x/2025", "Sport pour tous 2025", deadline="2025-06-01")
    neuf = _sub(dbm, "https://x/2026", "Sport pour tous 2026", deadline="2026-06-01")
    # Récurrence détectable, MAIS aucune candidature sur l'édition 2025.
    assert ca.detecter_recurrence(dbm.get_subside(neuf)) is not None
    assert ca.memoire_pour(p["id"], dbm.get_subside(neuf)) is None


def test_memoire_si_ancienne_candidatee(env):
    dbm, pm, ca, _ = env
    p = _profil(pm)
    vieux = _sub(dbm, "https://x/2025", "Sport pour tous 2025", deadline="2025-06-01")
    neuf = _sub(dbm, "https://x/2026", "Sport pour tous 2026", deadline="2026-06-01")
    anc = ca.creer_candidature(p["id"], vieux)
    ca.maj_candidature(anc["id"], {"montant_demande": "3000", "notes": "Projet foot filles."})
    mem = ca.memoire_pour(p["id"], dbm.get_subside(neuf))
    assert mem is not None
    assert mem["ancienne_candidature_id"] == anc["id"]
    assert mem["annee"] == "2025" and mem["montant_demande"] == 3000.0 and mem["a_notes"]


# --- repartir_de ------------------------------------------------------------

def test_repartir_pre_remplit_sans_checklist(env):
    dbm, pm, ca, e3 = env
    import obligations  # noqa: F401 (assure la table pour l'enrichissement)
    p = _profil(pm)
    vieux = _sub(dbm, "https://x/2025", "Sport pour tous 2025", deadline="2025-06-01")
    neuf = _sub(dbm, "https://x/2026", "Sport pour tous 2026", deadline="2026-06-01")
    anc = ca.creer_candidature(p["id"], vieux)
    ca.maj_candidature(anc["id"], {"montant_demande": "3000", "notes": "Projet foot filles."})
    # On pose une checklist sur l'ANCIENNE pour prouver qu'elle n'est PAS copiée.
    e3.ajouter_item(anc["id"], "Statuts de l'ASBL")

    neuve = ca.repartir_de(p["id"], neuf, anc["id"])
    assert neuve["subside_id"] == neuf
    assert neuve["montant_demande"] == 3000.0
    assert "Repris de votre dossier 2025" in (neuve["notes"] or "")
    assert "Projet foot filles." in (neuve["notes"] or "")
    # La checklist n'est JAMAIS recopiée.
    n = dbm.connect().execute(
        "SELECT COUNT(*) c FROM checklist_items WHERE candidature_id=?", (neuve["id"],)
    ).fetchone()["c"]
    assert n == 0


def test_repartir_idempotent(env):
    dbm, pm, ca, _ = env
    p = _profil(pm)
    vieux = _sub(dbm, "https://x/2025", "Sport pour tous 2025", deadline="2025-06-01")
    neuf = _sub(dbm, "https://x/2026", "Sport pour tous 2026", deadline="2026-06-01")
    anc = ca.creer_candidature(p["id"], vieux)
    a = ca.repartir_de(p["id"], neuf, anc["id"])
    b = ca.repartir_de(p["id"], neuf, anc["id"])
    assert a["id"] == b["id"]


def test_repartir_cloisonne(env):
    dbm, pm, ca, _ = env
    ua = pm.get_or_create_user("a"); ub = pm.get_or_create_user("b")
    pa = pm.creer_profil(ua["id"], {"nom": "A", "commune_siege": "Ixelles"})
    pb = pm.creer_profil(ub["id"], {"nom": "B", "commune_siege": "Jette"})
    vieux = _sub(dbm, "https://x/2025", "Sport 2025", deadline="2025-06-01")
    neuf = _sub(dbm, "https://x/2026", "Sport 2026", deadline="2026-06-01")
    anc = ca.creer_candidature(pa["id"], vieux)   # dossier de A
    # B tente de repartir du dossier de A -> refusé (None).
    assert ca.repartir_de(pb["id"], neuf, anc["id"]) is None

"""Lot 6 : ASBL francophones hors Bruxelles (région pilotée par le profil).

Couvre : la région pilote les zones éligibles, le pré-filtre respecte la région,
la rétrocompat du hash (pas d'invalidation des profils bruxellois existants), la
migration, et la validation du champ region.

Aucun réseau, aucun LLM.
"""

import importlib

import pytest


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "lot6.db"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-faux")
    import db as dbm
    importlib.reload(dbm)
    dbm.init_db()
    import profils as pm; importlib.reload(pm)
    import matching as mm; importlib.reload(mm)
    yield dbm, pm, mm
    conn = getattr(dbm._local, "conn", None)
    if conn:
        conn.close()
        dbm._local.conn = None


# --- Zones pilotées par la région -------------------------------------------

def test_zones_eligibles_selon_la_region(env):
    _, _, mm = env
    assert mm.zones_eligibles({"region": "bruxelles"}) == ("bruxelles", "fwb", "national", "inconnue")
    assert mm.zones_eligibles({"region": "wallonie"}) == ("wallonie", "fwb", "national", "inconnue")
    # Une ASBL bruxelloise ne voit PAS la Wallonie, et réciproquement.
    assert "wallonie" not in mm.zones_eligibles({"region": "bruxelles"})
    assert "bruxelles" not in mm.zones_eligibles({"region": "wallonie"})


def test_region_absente_ou_invalide_retombe_sur_bruxelles(env):
    _, _, mm = env
    for profil in ({}, {"region": None}, {"region": ""}, {"region": "flandre"}):
        assert mm.zones_eligibles(profil) == ("bruxelles", "fwb", "national", "inconnue")


def test_prefiltre_cloisonne_par_region(env):
    """Un appel wallon ne remonte QU'À une ASBL wallonne ; un appel bruxellois
    qu'à une ASBL bruxelloise. Les zones communes (fwb, national) remontent aux
    deux."""
    dbm, pm, mm = env

    def seed(url, zone):
        dbm.upsert_subside(
            {"url_source": url, "titre": f"appel {zone}", "zone_categorie": zone,
             "zone_geographique": zone, "deadline": "2099-12-31",
             "type_beneficiaire": ["asbl"]}, "src", text_hash="h")

    seed("https://x/bxl", "bruxelles")
    seed("https://x/wal", "wallonie")
    seed("https://x/fwb", "fwb")
    seed("https://x/nat", "national")

    zones_bxl = {s["zone_categorie"] for s in mm.pre_filtrer({"region": "bruxelles"})}
    zones_wal = {s["zone_categorie"] for s in mm.pre_filtrer({"region": "wallonie"})}

    assert zones_bxl == {"bruxelles", "fwb", "national"}
    assert zones_wal == {"wallonie", "fwb", "national"}


def test_prefiltre_trie_la_zone_locale_dabord(env):
    dbm, pm, mm = env
    dbm.upsert_subside({"url_source": "https://x/nat", "titre": "n", "zone_categorie": "national",
                        "deadline": "2099-01-01", "type_beneficiaire": ["asbl"]}, "s", text_hash="h")
    dbm.upsert_subside({"url_source": "https://x/wal", "titre": "w", "zone_categorie": "wallonie",
                        "deadline": "2099-12-31", "type_beneficiaire": ["asbl"]}, "s", text_hash="h")
    # Malgré une deadline plus lointaine, l'appel wallon passe devant pour une
    # ASBL wallonne (zone régionale prioritaire).
    ordre = [s["zone_categorie"] for s in mm.pre_filtrer({"region": "wallonie"})]
    assert ordre[0] == "wallonie"


# --- Rétrocompat du hash ----------------------------------------------------

def test_hash_bruxellois_inchange_par_lajout_de_region(env):
    """Le hash d'un profil bruxellois (défaut) ne doit PAS changer avec le lot 6 :
    sinon les 251 matchings en cache seraient invalidés pour un résultat identique."""
    _, pm, _ = env
    base = {"commune_siege": "Ixelles", "secteurs": ["sport"], "description_libre": "foot"}
    assert pm.calcul_profil_hash(base) == pm.calcul_profil_hash({**base, "region": "bruxelles"})


def test_hash_wallon_differe(env):
    """La région wallonne change l'éligibilité : le hash DOIT différer (sinon un
    profil déplacé garderait des jugements calculés pour la mauvaise zone)."""
    _, pm, _ = env
    base = {"commune_siege": "Namur", "secteurs": ["sport"]}
    assert pm.calcul_profil_hash({**base, "region": "bruxelles"}) != \
        pm.calcul_profil_hash({**base, "region": "wallonie"})


# --- Persistance + validation -----------------------------------------------

def test_profil_wallon_persiste_sa_region(env):
    dbm, pm, _ = env
    u = pm.get_or_create_user("asbl-wallonne")
    p = pm.creer_profil(u["id"], {"nom": "Club namurois", "commune_siege": "Namur",
                                  "region": "wallonie"})
    assert p["region"] == "wallonie"
    assert pm.get_profil(p["id"])["region"] == "wallonie"


def test_region_invalide_rejetee_vers_bruxelles(env):
    """Robustesse : une région inconnue ne fait pas échouer la création, elle
    retombe sur bruxelles (défaut sûr)."""
    dbm, pm, _ = env
    u = pm.get_or_create_user("x")
    p = pm.creer_profil(u["id"], {"nom": "T", "commune_siege": "Nulle part", "region": "narnia"})
    assert p["region"] == "bruxelles"


def test_profil_sans_region_defaut_bruxelles(env):
    dbm, pm, _ = env
    u = pm.get_or_create_user("y")
    p = pm.creer_profil(u["id"], {"nom": "T", "commune_siege": "Ixelles"})
    assert p["region"] == "bruxelles"


def test_migration_ajoute_region_avec_defaut(env):
    """Une base d'avant le lot 6 : la colonne est ajoutée, les profils existants
    prennent 'bruxelles'."""
    dbm, pm, _ = env
    cols = {r["name"] for r in dbm.connect().execute("PRAGMA table_info(profils)")}
    assert "region" in cols
    u = pm.get_or_create_user("z")
    # insertion « à l'ancienne » sans region, puis relecture
    p = pm.creer_profil(u["id"], {"nom": "T", "commune_siege": "Jette"})
    assert p["region"] == "bruxelles"

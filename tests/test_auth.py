"""Vérification JWT Clerk + CORS, sans dépendre du vrai Clerk.

On génère une paire RSA de test, on signe un JWT, et on mocke la résolution de
clé JWKS pour renvoyer notre clé publique. Aucun réseau.
"""

import importlib
import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


@pytest.fixture
def cle_rsa():
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_pem = priv.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption())
    return priv, priv_pem, priv.public_key()


def _token(priv_pem, sub="user_clerk_123", email="asbl@test.be", **extra):
    payload = {"sub": sub, "email": email, "exp": int(time.time()) + 3600,
               "iat": int(time.time()), **extra}
    return jwt.encode(payload, priv_pem, algorithm="RS256")


def test_verifier_token_valide(cle_rsa, monkeypatch):
    import auth_clerk; importlib.reload(auth_clerk)
    priv, priv_pem, pub = cle_rsa
    monkeypatch.setenv("CLERK_JWKS_URL", "https://exemple.clerk/jwks")
    monkeypatch.setattr(auth_clerk, "_signing_key", lambda t: pub)
    claims = auth_clerk.verifier_token(_token(priv_pem))
    assert claims["sub"] == "user_clerk_123"
    assert auth_clerk.identite_depuis_claims(claims) == ("user_clerk_123", "asbl@test.be")


def test_verifier_token_expire(cle_rsa, monkeypatch):
    import auth_clerk; importlib.reload(auth_clerk)
    priv, priv_pem, pub = cle_rsa
    monkeypatch.setenv("CLERK_JWKS_URL", "https://exemple.clerk/jwks")
    monkeypatch.setattr(auth_clerk, "_signing_key", lambda t: pub)
    vieux = jwt.encode({"sub": "x", "exp": int(time.time()) - 10}, priv_pem, algorithm="RS256")
    with pytest.raises(jwt.ExpiredSignatureError):
        auth_clerk.verifier_token(vieux)


def test_azp_liste_dorigines(cle_rsa, monkeypatch):
    """CLERK_AUTHORIZED_PARTY accepte plusieurs origines (dev :3000/:3001,
    apex + www en prod) — et refuse tout ce qui n'est pas dans la liste."""
    import auth_clerk; importlib.reload(auth_clerk)
    priv, priv_pem, pub = cle_rsa
    monkeypatch.setenv("CLERK_JWKS_URL", "https://exemple.clerk/jwks")
    monkeypatch.setenv("CLERK_AUTHORIZED_PARTY",
                       "http://localhost:3000, http://localhost:3001")
    monkeypatch.setattr(auth_clerk, "_signing_key", lambda t: pub)

    for origine in ("http://localhost:3000", "http://localhost:3001"):
        assert auth_clerk.verifier_token(_token(priv_pem, azp=origine))["azp"] == origine

    with pytest.raises(jwt.InvalidTokenError):
        auth_clerk.verifier_token(_token(priv_pem, azp="https://pirate.example"))


def test_clerk_inactif_sans_url(monkeypatch):
    import auth_clerk; importlib.reload(auth_clerk)
    monkeypatch.delenv("CLERK_JWKS_URL", raising=False)
    assert auth_clerk.clerk_actif() is False


# --- Bout en bout via l'API (TestClient) -----------------------------------

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "auth.db"))
    monkeypatch.delenv("CRON_SCRAPE", raising=False)
    import db as dbm; importlib.reload(dbm)
    import profils as pm; importlib.reload(pm)
    import auth_clerk as ac; importlib.reload(ac)
    import main as mn; importlib.reload(mn)
    from fastapi.testclient import TestClient
    with TestClient(mn.app) as c:
        yield c, mn, ac
    conn = getattr(dbm._local, "conn", None)
    if conn: conn.close(); dbm._local.conn = None


def test_vanilla_sans_clerk_fonctionne(client, monkeypatch):
    """Non-régression : Clerk inactif -> /profils marche sans token."""
    c, mn, ac = client
    monkeypatch.delenv("CLERK_JWKS_URL", raising=False)
    u = c.post("/users", json={"identifiant": "vanilla"}).json()
    r = c.post("/profils", json={"user_id": u["id"], "nom": "Club", "commune_siege": "Ixelles"})
    assert r.status_code == 200


def test_recherche_libre_nest_pas_capturee_par_la_route_parametree(client, monkeypatch):
    """`/matching/recherche` doit être déclarée AVANT `/matching/{profil_id}`.

    Sinon FastAPI teste la route paramétrée d'abord, tente de lire « recherche »
    comme un entier, et renvoie un 422 « int_parsing » incompréhensible — bug
    réel : la page Recherche libre était inutilisable.
    """
    c, mn, ac = client
    monkeypatch.delenv("CLERK_JWKS_URL", raising=False)   # mode vanilla
    r = c.post("/matching/recherche",
               json={"nom": "Recherche libre", "commune_siege": "Anderlecht",
                     "secteurs": ["sport"], "publics_cibles": ["jeunes"],
                     "description_libre": "Un atelier vélo le samedi."})
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["ephemere"] is True
    assert isinstance(corps["profil_id"], int) and corps["job_id"]

    # Et la route paramétrée continue de refuser un id non numérique.
    assert c.post("/matching/pas-un-entier").status_code == 422


def test_clerk_actif_refuse_sans_token(client, monkeypatch):
    c, mn, ac = client
    monkeypatch.setenv("CLERK_JWKS_URL", "https://exemple.clerk/jwks")
    r = c.post("/profils", json={"nom": "Club", "commune_siege": "Ixelles"})
    assert r.status_code == 401
    assert c.get("/matchings/1").status_code == 401


def test_clerk_actif_accepte_avec_token(client, monkeypatch, cle_rsa):
    c, mn, ac = client
    priv, priv_pem, pub = cle_rsa
    monkeypatch.setenv("CLERK_JWKS_URL", "https://exemple.clerk/jwks")
    monkeypatch.setattr(ac, "_signing_key", lambda t: pub)
    tok = _token(priv_pem, sub="clerk_abc", email="a@b.be")
    r = c.post("/profils", json={"nom": "Club", "commune_siege": "Ixelles"},
               headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    # le profil est rattaché à l'utilisateur Clerk mappé
    prof = r.json()
    listing = c.get("/profils", headers={"Authorization": f"Bearer {tok}"}).json()
    assert any(pp["id"] == prof["id"] for pp in listing)


def test_clerk_cloisonnement_entre_users(client, monkeypatch, cle_rsa):
    """Un user ne peut pas voir le profil d'un autre (403)."""
    c, mn, ac = client
    priv, priv_pem, pub = cle_rsa
    monkeypatch.setenv("CLERK_JWKS_URL", "https://exemple.clerk/jwks")
    monkeypatch.setattr(ac, "_signing_key", lambda t: pub)
    tok_a = _token(priv_pem, sub="userA", email="a@b.be")
    tok_b = _token(priv_pem, sub="userB", email="b@b.be")
    prof = c.post("/profils", json={"nom": "A", "commune_siege": "Ixelles"},
                  headers={"Authorization": f"Bearer {tok_a}"}).json()
    r = c.get(f"/profils/{prof['id']}", headers={"Authorization": f"Bearer {tok_b}"})
    assert r.status_code == 403


def test_cors_header_present(client):
    c, mn, ac = client
    r = c.get("/derniere-maj", headers={"Origin": "http://localhost:3000"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:3000"


# --- Rôle admin (lot 4b) ---------------------------------------------------

def _admin_token(priv_pem, **extra):
    return _token(priv_pem, sub="admin_1", email="admin@b.be",
                  metadata={"role": "admin"}, **extra)


def test_admin_refuse_utilisateur_normal(client, monkeypatch, cle_rsa):
    c, mn, ac = client
    priv, priv_pem, pub = cle_rsa
    monkeypatch.setenv("CLERK_JWKS_URL", "https://exemple.clerk/jwks")
    monkeypatch.delenv("ADMIN_CLERK_USER_IDS", raising=False)
    monkeypatch.setattr(ac, "_signing_key", lambda t: pub)
    tok = _token(priv_pem, sub="simple_user")          # pas de rôle admin
    h = {"Authorization": f"Bearer {tok}"}
    assert c.get("/admin/scrape-runs", headers=h).status_code == 403
    assert c.get("/admin/sources-sante", headers=h).status_code == 403
    assert c.post("/scrape", headers=h).status_code == 403


def test_admin_accepte_role_dans_le_jwt(client, monkeypatch, cle_rsa):
    c, mn, ac = client
    priv, priv_pem, pub = cle_rsa
    monkeypatch.setenv("CLERK_JWKS_URL", "https://exemple.clerk/jwks")
    monkeypatch.setattr(ac, "_signing_key", lambda t: pub)
    h = {"Authorization": f"Bearer {_admin_token(priv_pem)}"}
    assert c.get("/admin/scrape-runs", headers=h).status_code == 200
    assert c.get("/admin/sources-sante", headers=h).status_code == 200


def test_admin_accepte_allowlist_env(client, monkeypatch, cle_rsa):
    """Repli tant que le template de token Clerk n'est pas configuré."""
    c, mn, ac = client
    priv, priv_pem, pub = cle_rsa
    monkeypatch.setenv("CLERK_JWKS_URL", "https://exemple.clerk/jwks")
    monkeypatch.setenv("ADMIN_CLERK_USER_IDS", "boss_42, autre")
    monkeypatch.setattr(ac, "_signing_key", lambda t: pub)
    h = {"Authorization": f"Bearer {_token(priv_pem, sub='boss_42')}"}
    assert c.get("/admin/scrape-runs", headers=h).status_code == 200


def test_admin_sans_token_401(client, monkeypatch):
    c, mn, ac = client
    monkeypatch.setenv("CLERK_JWKS_URL", "https://exemple.clerk/jwks")
    assert c.get("/admin/scrape-runs").status_code == 401


def test_admin_moi_repond_200_dans_les_deux_cas(client, monkeypatch, cle_rsa):
    """Le front s'en sert pour afficher (ou non) l'entrée « Admin » du menu :
    il doit répondre 200 même à un non-admin, avec admin=false."""
    c, mn, ac = client
    priv, priv_pem, pub = cle_rsa
    monkeypatch.setenv("CLERK_JWKS_URL", "https://exemple.clerk/jwks")
    monkeypatch.delenv("ADMIN_CLERK_USER_IDS", raising=False)
    monkeypatch.setattr(ac, "_signing_key", lambda t: pub)

    r = c.get("/admin/moi", headers={"Authorization": f"Bearer {_token(priv_pem, sub='simple')}"})
    assert r.status_code == 200 and r.json()["admin"] is False

    r = c.get("/admin/moi", headers={"Authorization": f"Bearer {_admin_token(priv_pem)}"})
    assert r.status_code == 200 and r.json()["admin"] is True

    # Sans token, Clerk actif : toujours 401 (pas de fuite d'information).
    assert c.get("/admin/moi").status_code == 401


# --- Dashboard agrégé + détail (cloisonnement) -----------------------------

def test_dashboard_agrege_et_detail_cloisonnes(client, monkeypatch, cle_rsa):
    c, mn, ac = client
    priv, priv_pem, pub = cle_rsa
    monkeypatch.setenv("CLERK_JWKS_URL", "https://exemple.clerk/jwks")
    monkeypatch.setattr(ac, "_signing_key", lambda t: pub)
    ha = {"Authorization": f"Bearer {_token(priv_pem, sub='userA', email='a@b.be')}"}
    hb = {"Authorization": f"Bearer {_token(priv_pem, sub='userB', email='b@b.be')}"}

    prof = c.post("/profils", json={"nom": "A", "commune_siege": "Ixelles"}, headers=ha).json()
    r = c.get(f"/dashboard/{prof['id']}", headers=ha)
    assert r.status_code == 200
    d = r.json()
    assert {"profil", "resume", "matchings", "derniere_maj", "total_subsides"} <= set(d)

    # userB ne doit pas voir le dashboard de userA
    assert c.get(f"/dashboard/{prof['id']}", headers=hb).status_code == 403
    # détail inexistant -> 404 propre
    assert c.get("/matching-detail/99999", headers=ha).status_code == 404
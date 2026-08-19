"""Vérification des JWT Clerk côté FastAPI.

Clerk n'est qu'une référence d'identité : la table `users` reste la source de
vérité applicative. À la première requête authentifiée, on crée/retrouve la
ligne users par `clerk_user_id`.

Deux modes :
- **Clerk actif** (CLERK_JWKS_URL défini) : les routes protégées EXIGENT un
  Bearer token valide (401 sinon). C'est le mode de l'app Next.js.
- **Clerk inactif** (pas de config) : l'auth est transparente (les vues vanilla
  /app et l'admin continuent de fonctionner sans token — fallback lot 3).

La vérification utilise les clés publiques JWKS de Clerk (PyJWKClient les met en
cache). Aucune clé secrète Clerk n'est nécessaire pour VÉRIFIER un token.
"""

import logging
import os

import jwt
from jwt import PyJWKClient

log = logging.getLogger(__name__)

_jwks_client: PyJWKClient | None = None


def clerk_actif() -> bool:
    return bool(os.getenv("CLERK_JWKS_URL"))


def _client() -> PyJWKClient:
    """Client JWKS mis en cache (une seule instance, JWKS caché en interne)."""
    global _jwks_client
    if _jwks_client is None:
        url = os.getenv("CLERK_JWKS_URL")
        if not url:
            raise RuntimeError("CLERK_JWKS_URL non défini")
        _jwks_client = PyJWKClient(url, cache_keys=True)
    return _jwks_client


def _signing_key(token: str):
    """Clé de signature pour ce token (surchargeable dans les tests)."""
    return _client().get_signing_key_from_jwt(token).key


def verifier_token(token: str) -> dict:
    """Renvoie les claims si le token est valide ; lève sinon.

    On vérifie signature + expiration. On NE force pas l'audience (Clerk ne la
    remplit pas par défaut sur les session tokens) ; on peut restreindre l'azp
    via CLERK_AUTHORIZED_PARTY si besoin.
    """
    key = _signing_key(token)
    claims = jwt.decode(
        token, key, algorithms=["RS256"],
        options={"verify_aud": False, "require": ["exp", "sub"]},
    )
    # CLERK_AUTHORIZED_PARTY accepte plusieurs origines séparées par des
    # virgules : en dev le front peut basculer de :3000 à :3001, et en prod on
    # veut souvent autoriser le domaine apex ET le www.
    autorisees = [o.strip() for o in os.getenv("CLERK_AUTHORIZED_PARTY", "").split(",") if o.strip()]
    if autorisees and claims.get("azp") and claims["azp"] not in autorisees:
        raise jwt.InvalidTokenError("azp non autorisé")
    return claims


def est_admin(claims: dict) -> bool:
    """Le porteur du token est-il admin ?

    Deux sources, dans cet ordre (défense en profondeur — on ne se fie JAMAIS au
    seul frontend) :
    1. Un claim dans le JWT. Clerk ne met PAS publicMetadata dans le token de
       session par défaut : il faut personnaliser le « session token » dans le
       dashboard Clerk (Sessions -> Customize) avec :
           { "metadata": "{{user.public_metadata}}" }
       On accepte aussi `public_metadata.role` ou un claim `role` à plat.
    2. Repli : liste d'IDs Clerk dans ADMIN_CLERK_USER_IDS (séparés par virgule),
       pratique tant que le template de token n'est pas configuré.
    """
    for cle in ("metadata", "public_metadata", "publicMetadata"):
        bloc = claims.get(cle)
        if isinstance(bloc, dict) and str(bloc.get("role", "")).lower() == "admin":
            return True
    if str(claims.get("role", "")).lower() == "admin":
        return True
    autorises = {i.strip() for i in os.getenv("ADMIN_CLERK_USER_IDS", "").split(",") if i.strip()}
    return bool(autorises) and claims.get("sub") in autorises


def identite_depuis_claims(claims: dict) -> tuple[str, str]:
    """(clerk_user_id, identifiant lisible). L'email si présent, sinon le sub."""
    clerk_id = claims["sub"]
    email = claims.get("email") or claims.get("email_address") or \
        (claims.get("user", {}) or {}).get("email")
    return clerk_id, (email or clerk_id)

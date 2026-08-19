"""Profils ASBL et users : CRUD, validation pydantic, hash de contenu.

Le `profil_hash` est la clé de cache du matching : deux profils au contenu
identique produisent le même jugement pour un subside donné. On hache donc le
contenu *pertinent pour l'éligibilité* — pas le nom (simple label) ni les
timestamps.
"""

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

import db

log = logging.getLogger(__name__)

SECTEURS_VALIDES = [
    "culture", "jeunesse", "sport", "social_sante", "cohesion_sociale",
    "education_permanente", "egalite_chances", "environnement", "cooperation",
    "media", "recherche", "autre",
]
BUDGETS_VALIDES = ["moins_50k", "50k_250k", "250k_1M", "plus_1M", "inconnu"]
LANGUES_VALIDES = ["fr", "nl", "bilingue"]
# Lot 6 : régions couvertes (ASBL francophones). La région du siège pilote les
# zones de subsides éligibles au matching (voir matching.zones_eligibles).
REGIONS_VALIDES = ["bruxelles", "wallonie"]
# Lot 8.1 : nature du profil (voir la migration db._migrer_tables_lot3).
TYPES_PROFIL = ["principal", "recherche", "ephemere"]

COMMUNES_19 = [
    "Anderlecht", "Auderghem", "Berchem-Sainte-Agathe", "Bruxelles-Ville",
    "Etterbeek", "Evere", "Forest", "Ganshoren", "Ixelles", "Jette",
    "Koekelberg", "Molenbeek-Saint-Jean", "Saint-Gilles", "Saint-Josse-ten-Noode",
    "Schaerbeek", "Uccle", "Watermael-Boitsfort", "Woluwe-Saint-Lambert",
    "Woluwe-Saint-Pierre",
]


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Profil(BaseModel):
    """Seuls nom et commune_siege sont attendus ; tout le reste peut être vide."""

    model_config = {"extra": "ignore"}

    nom: str
    commune_siege: str
    region: str = "bruxelles"
    langue: Optional[str] = None
    secteurs: list[str] = Field(default_factory=list)
    publics_cibles: list[str] = Field(default_factory=list)
    budget_categorie: Optional[str] = None
    agrements: list[str] = Field(default_factory=list)
    description_libre: Optional[str] = None
    ephemere: bool = False
    # `type` est la source de vérité ; `ephemere` en est un miroir (compat).
    type: Optional[str] = None
    nom_recherche: Optional[str] = None

    @field_validator("nom", "commune_siege")
    @classmethod
    def _non_vide(cls, v):
        v = (v or "").strip()
        if not v:
            raise ValueError("champ requis")
        return v[:200]

    @field_validator("region", mode="before")
    @classmethod
    def _region(cls, v):
        # Tolérant : une valeur vide ou inconnue retombe sur 'bruxelles' plutôt
        # que de faire échouer la création du profil.
        v = (v or "").strip().lower()
        return v if v in REGIONS_VALIDES else "bruxelles"

    @field_validator("langue")
    @classmethod
    def _langue(cls, v):
        if v in (None, ""):
            return None
        if v not in LANGUES_VALIDES:
            raise ValueError(f"langue invalide (attendu {LANGUES_VALIDES})")
        return v

    @field_validator("budget_categorie")
    @classmethod
    def _budget(cls, v):
        if v in (None, ""):
            return None
        if v not in BUDGETS_VALIDES:
            raise ValueError(f"budget invalide (attendu {BUDGETS_VALIDES})")
        return v

    @field_validator("secteurs", mode="before")
    @classmethod
    def _secteurs(cls, v):
        if not v:
            return []
        if isinstance(v, str):
            v = [v]
        # ne garde que les secteurs connus (ignore le bruit), en préservant l'ordre
        return [s for s in (str(x).strip().lower() for x in v) if s in SECTEURS_VALIDES]

    @field_validator("publics_cibles", "agrements", mode="before")
    @classmethod
    def _listes_libres(cls, v):
        if not v:
            return []
        if isinstance(v, str):
            v = [v]
        return [str(x).strip() for x in v if str(x).strip()]

    @field_validator("description_libre")
    @classmethod
    def _desc(cls, v):
        if v is None:
            return None
        v = v.strip()
        return v[:2000] if v else None

    @model_validator(mode="after")
    def _reconcilier_type(self):
        """`type` et `ephemere` doivent toujours concorder.

        Si `type` est fourni, il fait foi (ephemere en découle). Sinon on le
        déduit de l'ancien booléen `ephemere` — ainsi le code et les bases
        d'avant le lot 8.1 continuent de marcher sans y penser.
        """
        t = (self.type or "").strip().lower()
        if t not in TYPES_PROFIL:
            t = "ephemere" if self.ephemere else "principal"
        self.type = t
        self.ephemere = (t == "ephemere")
        # Un nom de recherche n'a de sens que pour une recherche sauvegardée.
        if t != "recherche":
            self.nom_recherche = None
        else:
            self.nom_recherche = (self.nom_recherche or "").strip()[:200] or None
        return self


def calcul_profil_hash(p: dict) -> str:
    """Hash déterministe du contenu pertinent pour l'éligibilité (pas le nom)."""
    pertinent = {
        "commune_siege": (p.get("commune_siege") or "").strip().casefold(),
        "langue": p.get("langue") or "",
        "secteurs": sorted(p.get("secteurs") or []),
        "publics_cibles": sorted(s.strip().casefold() for s in (p.get("publics_cibles") or [])),
        "budget_categorie": p.get("budget_categorie") or "",
        "agrements": sorted(s.strip().casefold() for s in (p.get("agrements") or [])),
        "description_libre": (p.get("description_libre") or "").strip().casefold(),
    }
    # La région change l'éligibilité, elle DOIT donc entrer dans le hash. Mais on
    # ne l'ajoute que si elle diffère du défaut historique 'bruxelles' : ainsi le
    # hash de tous les profils créés avant le lot 6 reste identique au bit près et
    # leurs jugements en cache ne sont pas invalidés pour rien.
    region = (p.get("region") or "bruxelles").strip().lower()
    if region != "bruxelles":
        pertinent["region"] = region
    blob = json.dumps(pertinent, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _dumps(v):
    return json.dumps(v or [], ensure_ascii=False)


# --- Users -----------------------------------------------------------------

def get_or_create_user(identifiant: str) -> dict:
    identifiant = (identifiant or "").strip()
    if not identifiant:
        raise ValueError("identifiant vide")
    conn = db.connect()
    row = conn.execute("SELECT * FROM users WHERE identifiant = ?", (identifiant,)).fetchone()
    if row:
        return dict(row)
    cur = conn.execute("INSERT INTO users (identifiant, cree_le) VALUES (?,?)",
                       (identifiant, _now()))
    conn.commit()
    return {"id": cur.lastrowid, "identifiant": identifiant, "cree_le": _now()}


def get_or_create_user_clerk(clerk_user_id: str, identifiant: str) -> dict:
    """Mappe une identité Clerk vers une ligne users (source de vérité applicative).

    À la première requête authentifiée, crée la ligne. Si un user vanilla portait
    déjà cet identifiant (email), on l'adopte en y rattachant le clerk_user_id.
    """
    conn = db.connect()
    row = conn.execute("SELECT * FROM users WHERE clerk_user_id = ?", (clerk_user_id,)).fetchone()
    if row:
        return dict(row)
    # rattachement d'un éventuel user existant portant cet identifiant
    row = conn.execute("SELECT * FROM users WHERE identifiant = ?", (identifiant,)).fetchone()
    if row:
        conn.execute("UPDATE users SET clerk_user_id = ? WHERE id = ?", (clerk_user_id, row["id"]))
        conn.commit()
        return {**dict(row), "clerk_user_id": clerk_user_id}
    cur = conn.execute(
        "INSERT INTO users (identifiant, clerk_user_id, cree_le) VALUES (?,?,?)",
        (identifiant, clerk_user_id, _now()))
    conn.commit()
    return {"id": cur.lastrowid, "identifiant": identifiant,
            "clerk_user_id": clerk_user_id, "cree_le": _now()}


# --- Profils ---------------------------------------------------------------

def _row_to_profil(row) -> dict:
    d = dict(row)
    for champ in ("secteurs", "publics_cibles", "agrements"):
        try:
            d[champ] = json.loads(d.get(champ) or "[]")
        except (json.JSONDecodeError, TypeError):
            d[champ] = []
    d["ephemere"] = bool(d.get("ephemere"))
    d["region"] = d.get("region") or "bruxelles"   # bases d'avant le lot 6
    # bases d'avant le lot 8.1 : déduire le type du booléen ephemere
    d["type"] = d.get("type") or ("ephemere" if d["ephemere"] else "principal")
    d["nom_recherche"] = d.get("nom_recherche")
    return d


def creer_profil(user_id, data: dict) -> dict:
    """Valide et insère un profil. Lève ValidationError si nom/commune manquent."""
    p = Profil(**data).model_dump()
    ph = calcul_profil_hash(p)
    conn = db.connect()
    maintenant = _now()
    cur = conn.execute(
        """INSERT INTO profils (user_id, nom, commune_siege, region, langue, secteurs,
             publics_cibles, budget_categorie, agrements, description_libre,
             ephemere, type, nom_recherche, profil_hash, cree_le, modifie_le)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (user_id, p["nom"], p["commune_siege"], p["region"], p["langue"],
         _dumps(p["secteurs"]), _dumps(p["publics_cibles"]), p["budget_categorie"],
         _dumps(p["agrements"]), p["description_libre"], int(p["ephemere"]),
         p["type"], p["nom_recherche"], ph, maintenant, maintenant),
    )
    conn.commit()
    return get_profil(cur.lastrowid)


def get_profil(profil_id) -> Optional[dict]:
    row = db.connect().execute("SELECT * FROM profils WHERE id = ?", (profil_id,)).fetchone()
    return _row_to_profil(row) if row else None


def lister_profils(user_id=None, inclure_ephemeres=False) -> list[dict]:
    """Par défaut : uniquement les profils PRINCIPAUX.

    Depuis le lot 8.1 les recherches sauvegardées ont ephemere=0 (elles ne sont
    pas purgées) : filtrer sur ephemere=0 les laissait fuiter dans la résolution
    du « profil de mon ASBL » (compte, édition, dashboard). On filtre donc sur
    type='principal'. `inclure_ephemeres=True` lève tout filtre de type."""
    conn = db.connect()
    sql, params = "SELECT * FROM profils", []
    where = []
    if user_id is not None:
        where.append("user_id = ?"); params.append(user_id)
    if not inclure_ephemeres:
        where.append("type = 'principal'")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY modifie_le DESC"
    return [_row_to_profil(r) for r in conn.execute(sql, params).fetchall()]


def maj_profil(profil_id, data: dict) -> Optional[dict]:
    """Met à jour un profil et recalcule profil_hash (invalide le cache matching)."""
    existant = get_profil(profil_id)
    if existant is None:
        return None
    fusion = {**existant, **{k: v for k, v in data.items() if k in Profil.model_fields}}
    p = Profil(**fusion).model_dump()
    ph = calcul_profil_hash(p)
    db.connect().execute(
        """UPDATE profils SET nom=?, commune_siege=?, region=?, langue=?, secteurs=?,
             publics_cibles=?, budget_categorie=?, agrements=?, description_libre=?,
             ephemere=?, type=?, nom_recherche=?, profil_hash=?, modifie_le=? WHERE id=?""",
        (p["nom"], p["commune_siege"], p["region"], p["langue"], _dumps(p["secteurs"]),
         _dumps(p["publics_cibles"]), p["budget_categorie"], _dumps(p["agrements"]),
         p["description_libre"], int(p["ephemere"]), p["type"], p["nom_recherche"],
         ph, _now(), profil_id),
    )
    db.connect().commit()
    return get_profil(profil_id)


def supprimer_profil(profil_id) -> bool:
    """Supprime le profil ET ses matchings (RGPD). Renvoie True si existait."""
    conn = db.connect()
    # ON DELETE CASCADE nécessite PRAGMA foreign_keys=ON (activé dans db.connect).
    cur = conn.execute("DELETE FROM profils WHERE id = ?", (profil_id,))
    conn.commit()
    return cur.rowcount > 0


def purge_ephemeres(jours: int = 7) -> int:
    """Supprime les recherches ÉPHÉMÈRES plus vieilles que `jours` (et leurs
    matchings). Ne touche JAMAIS les recherches sauvegardées (type='recherche')
    ni les profils principaux : on filtre sur type='ephemere'."""
    from datetime import timedelta
    limite = (datetime.now(timezone.utc) - timedelta(days=jours)).isoformat(timespec="seconds")
    conn = db.connect()
    cur = conn.execute("DELETE FROM profils WHERE type = 'ephemere' AND cree_le < ?", (limite,))
    conn.commit()
    if cur.rowcount:
        log.info("Purge : %d profil(s) éphémère(s) > %d jours supprimé(s)", cur.rowcount, jours)
    return cur.rowcount


# --- Recherches sauvegardées (lot 8.1) -------------------------------------

def compter_recherches(user_id) -> int:
    """Nombre de recherches SAUVEGARDÉES d'un user (pour la limite)."""
    row = db.connect().execute(
        "SELECT COUNT(*) n FROM profils WHERE user_id = ? AND type = 'recherche'",
        (user_id,)).fetchone()
    return row["n"] if row else 0


def lister_recherches(user_id) -> list[dict]:
    """Recherches sauvegardées d'un user, enrichies pour la liste « Mes
    recherches » : nombre de correspondances au dernier matching + date.

    Import local de `matching` pour éviter une boucle d'import (matching
    importe profils)."""
    import matching
    conn = db.connect()
    sql = "SELECT * FROM profils WHERE type = 'recherche'"
    params = []
    if user_id is not None:
        sql += " AND user_id = ?"; params.append(user_id)
    sql += " ORDER BY modifie_le DESC"
    out = []
    for r in conn.execute(sql, params).fetchall():
        p = _row_to_profil(r)
        resume = matching.resume_profil(p["id"])
        out.append({
            "id": p["id"],
            "nom_recherche": p["nom_recherche"] or p["nom"],
            "commune_siege": p["commune_siege"],
            "region": p["region"],
            "secteurs": p["secteurs"],
            "description_libre": p["description_libre"],
            "correspondances": resume["correspondances"],
            "total_analyses": resume["total_analyses"],
            "cree_le": p["cree_le"],
            "modifie_le": p["modifie_le"],
        })
    return out


def sauvegarder_recherche(profil_id, nom: str) -> Optional[dict]:
    """Transforme une recherche éphémère en recherche sauvegardée (type=recherche).

    Idempotent sur une recherche déjà sauvegardée (met juste à jour le nom).
    Renvoie None si le profil n'existe pas. Le hash ne change pas : les
    jugements déjà en cache restent valides et la veille les reprend."""
    existant = get_profil(profil_id)
    if existant is None:
        return None
    nom = (nom or "").strip()[:200]
    if not nom:
        # Nom par défaut : commune + un mot, plutôt que vide.
        nom = existant.get("commune_siege") or "Recherche"
    return maj_profil(profil_id, {"type": "recherche", "nom_recherche": nom})


def renommer_recherche(profil_id, nom: str) -> Optional[dict]:
    """Renomme une recherche sauvegardée. None si absente/non recherche."""
    existant = get_profil(profil_id)
    if existant is None or existant.get("type") != "recherche":
        return None
    nom = (nom or "").strip()[:200]
    if not nom:
        return existant
    return maj_profil(profil_id, {"nom_recherche": nom})

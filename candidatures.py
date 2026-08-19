"""Candidatures : suivi d'une demande de subside de « à étudier » à « obtenu ».

Étage 3 (lot 7). Subsidia est un COPILOTE, jamais l'auteur : ce module suit,
structure et cloisonne — il ne soumet rien et ne rédige rien.

Cloisonnement : une candidature appartient à un profil, qui appartient à un
user. Toute lecture/écriture vérifie cette chaîne (voir main.py, dépendances).
"""

import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, field_validator

import db

log = logging.getLogger(__name__)

STATUTS = ["a_etudier", "dossier_en_cours", "soumis", "obtenu", "refuse", "abandonne"]
# Statuts qui comptent comme une « décision » rendue (pour le taux de succès).
STATUTS_DECIDES = ["obtenu", "refuse"]


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_montant(v) -> Optional[float]:
    """Extrait un nombre d'euros d'une saisie libre ('3 000 €', '3000', 3000).

    Tolérant : on prend le premier nombre plausible ; None si rien d'exploitable.
    """
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(" ", " ").replace("\xa0", " ")
    # retire séparateurs de milliers, garde le point décimal
    s = re.sub(r"(?<=\d)[ .](?=\d{3}\b)", "", s)
    s = s.replace(",", ".")
    m = re.search(r"\d+(?:\.\d+)?", s)
    return float(m.group()) if m else None


class CandidatureInput(BaseModel):
    """Champs modifiables. Tout est optionnel sauf, à la création, subside_id."""

    model_config = {"extra": "ignore"}

    statut: Optional[str] = None
    montant_demande: Optional[float] = None
    montant_obtenu: Optional[float] = None
    date_soumission: Optional[str] = None
    date_decision: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("statut")
    @classmethod
    def _statut(cls, v):
        if v in (None, ""):
            return None
        if v not in STATUTS:
            raise ValueError(f"statut invalide (attendu {STATUTS})")
        return v

    @field_validator("montant_demande", "montant_obtenu", mode="before")
    @classmethod
    def _montant(cls, v):
        return _parse_montant(v)

    @field_validator("notes")
    @classmethod
    def _notes(cls, v):
        if v is None:
            return None
        return v.strip()[:5000] or None


def _row(r) -> dict:
    return dict(r) if r else None


# --- Cloisonnement ----------------------------------------------------------

def user_de_candidature(candidature_id: int) -> Optional[int]:
    """user_id propriétaire d'une candidature, ou None si elle n'existe pas."""
    row = db.connect().execute(
        """SELECT p.user_id FROM candidatures c
           JOIN profils p ON p.id = c.profil_id WHERE c.id = ?""",
        (candidature_id,)).fetchone()
    return row["user_id"] if row else None


# --- CRUD -------------------------------------------------------------------

def creer_candidature(profil_id: int, subside_id: int,
                      matching_id: Optional[int] = None) -> dict:
    """Crée (ou renvoie l'existante) une candidature pour ce couple profil/subside.

    Idempotent : « Préparer ma candidature » deux fois ne crée pas de doublon —
    on ramène celle déjà ouverte.
    """
    conn = db.connect()
    existante = conn.execute(
        "SELECT * FROM candidatures WHERE profil_id = ? AND subside_id = ?",
        (profil_id, subside_id)).fetchone()
    if existante:
        return _row(existante)

    maintenant = _now()
    cur = conn.execute(
        """INSERT INTO candidatures (profil_id, subside_id, matching_id, statut,
             cree_le, modifie_le) VALUES (?,?,?,'a_etudier',?,?)""",
        (profil_id, subside_id, matching_id, maintenant, maintenant))
    conn.commit()
    return get_candidature(cur.lastrowid)


def get_candidature(candidature_id: int) -> Optional[dict]:
    return _row(db.connect().execute(
        "SELECT * FROM candidatures WHERE id = ?", (candidature_id,)).fetchone())


def get_candidature_enrichie(candidature_id: int) -> Optional[dict]:
    """Candidature + fiche subside embarquée (pour l'espace candidature)."""
    c = get_candidature(candidature_id)
    if c is None:
        return None
    sub = db.get_subside(c["subside_id"])
    c["subside"] = sub
    return c


def lister_candidatures(profil_id: int) -> list[dict]:
    """Toutes les candidatures d'un profil, fiche subside embarquée, plus
    récente d'abord."""
    rows = db.connect().execute(
        "SELECT * FROM candidatures WHERE profil_id = ? ORDER BY modifie_le DESC",
        (profil_id,)).fetchall()
    out = []
    for r in rows:
        d = _row(r)
        s = db.get_subside(d["subside_id"])
        # sous-ensemble léger pour les cartes du Kanban
        d["subside"] = None if s is None else {
            "id": s["id"], "titre": s["titre"], "organisme": s.get("organisme"),
            "deadline": s.get("deadline"), "permanent": s.get("permanent"),
            "url_source": s.get("url_source"), "source_id": s.get("source_id"),
            "expire": s.get("expire"),
        }
        out.append(d)
    return out


def maj_candidature(candidature_id: int, data: dict) -> Optional[dict]:
    """Met à jour les champs fournis. Applique quelques automatismes doux :
    passer à 'soumis' pose la date de soumission si absente, etc."""
    existante = get_candidature(candidature_id)
    if existante is None:
        return None

    champs = CandidatureInput(**data).model_dump(exclude_none=True)
    # Un champ explicitement mis à null par l'appelant (ex. effacer une note)
    # doit pouvoir l'être : on distingue "absent" de "présent mais null".
    for cle in ("notes", "montant_demande", "montant_obtenu",
                "date_soumission", "date_decision"):
        if cle in data and data[cle] in (None, ""):
            champs[cle] = None

    nouveau_statut = champs.get("statut", existante["statut"])
    if nouveau_statut == "soumis" and not existante["date_soumission"] \
            and "date_soumission" not in champs:
        champs["date_soumission"] = _now()[:10]
    if nouveau_statut in STATUTS_DECIDES and not existante["date_decision"] \
            and "date_decision" not in champs:
        champs["date_decision"] = _now()[:10]

    if not champs:
        return existante

    champs["modifie_le"] = _now()
    cols = ", ".join(f"{k} = ?" for k in champs)
    db.connect().execute(
        f"UPDATE candidatures SET {cols} WHERE id = ?",
        (*champs.values(), candidature_id))
    db.connect().commit()
    return get_candidature(candidature_id)


def supprimer_candidature(candidature_id: int) -> bool:
    conn = db.connect()
    cur = conn.execute("DELETE FROM candidatures WHERE id = ?", (candidature_id,))
    conn.commit()
    return cur.rowcount > 0


# --- Statistiques -----------------------------------------------------------

def stats(profil_id: int) -> dict:
    """Total demandé / obtenu / taux de succès. Le taux n'est renvoyé qu'à
    partir de 3 décisions (avant, c'est du bruit)."""
    rows = db.connect().execute(
        "SELECT statut, montant_demande, montant_obtenu FROM candidatures WHERE profil_id = ?",
        (profil_id,)).fetchall()

    def _num(v):  # robuste à un montant stocké en texte (bases anciennes)
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    total_demande = sum(_num(r["montant_demande"]) for r in rows)
    total_obtenu = sum(_num(r["montant_obtenu"]) for r in rows)
    decides = [r for r in rows if r["statut"] in STATUTS_DECIDES]
    obtenus = [r for r in decides if r["statut"] == "obtenu"]
    taux = round(len(obtenus) / len(decides), 2) if len(decides) >= 3 else None
    return {
        "total_candidatures": len(rows),
        "total_demande": total_demande,
        "total_obtenu": total_obtenu,
        "decisions": len(decides),
        "taux_succes": taux,   # None tant que < 3 décisions
    }


# --- Détection de récurrence (code pur, aucun LLM) --------------------------

_STOP = {"appel", "a", "à", "projets", "projet", "candidature", "candidatures",
         "de", "des", "du", "la", "le", "les", "l", "d", "pour", "aux", "au",
         "et", "en", "un", "une", "the"}


def _titre_normalise(titre: str) -> frozenset:
    """Signature d'un titre insensible à l'année et aux mots vides.

    « Sport pour tous 2025 » et « Sport pour tous 2026 » -> même signature.
    """
    t = (titre or "").casefold()
    t = re.sub(r"\b(19|20)\d{2}\b", " ", t)          # retire les années
    t = re.sub(r"\b\d+(?:er|e|ème|eme)\b", " ", t)   # 3e, 10ème édition…
    mots = re.findall(r"[a-zàâäéèêëîïôöùûüç]{3,}", t)
    return frozenset(m for m in mots if m not in _STOP)


def _similaires(a: frozenset, b: frozenset) -> bool:
    """Jaccard >= 0.6 sur les mots signifiants, et au moins 2 mots communs."""
    if not a or not b:
        return False
    inter = a & b
    if len(inter) < 2:
        return False
    return len(inter) / len(a | b) >= 0.6


def _annee(*champs) -> Optional[str]:
    """Première année 20xx trouvée dans les champs fournis (titre, deadline…)."""
    for champ in champs:
        m = re.search(r"\b(20\d{2})\b", str(champ or ""))
        if m:
            return m.group(1)
    return None


def detecter_recurrence(subside: dict) -> Optional[dict]:
    """Cherche un « frère » d'une AUTRE année : même source, titre très proche à
    l'année près, ET une année distincte détectable. Renvoie
    {frere_id, frere_titre, annee, annee_courante} ou None.

    L'écart d'année est requis : sans lui, on confondrait deux programmes
    voisins de la même édition (ex. « Bourse exploratoire » vs « Bourse
    d'aboutissement ») avec une vraie récurrence annuelle. v1 volontairement
    simple (spec) : on informe sur la fiche, aucune alerte proactive.
    """
    if not subside or not subside.get("titre"):
        return None
    sig = _titre_normalise(subside["titre"])
    if len(sig) < 2:
        return None
    annee_courante = _annee(subside.get("titre"), subside.get("deadline"),
                            subside.get("premiere_detection"))

    freres = db.connect().execute(
        """SELECT id, titre, deadline, premiere_detection FROM subsides
           WHERE source_id = ? AND id != ? AND statut != 'echec_extraction'""",
        (subside.get("source_id"), subside.get("id") or -1)).fetchall()

    for f in freres:
        if not _similaires(sig, _titre_normalise(f["titre"])):
            continue
        annee_frere = _annee(f["titre"], f["deadline"], f["premiere_detection"])
        # Vraie récurrence : deux années connues ET différentes.
        if annee_frere and annee_courante and annee_frere != annee_courante:
            return {"frere_id": f["id"], "frere_titre": f["titre"],
                    "annee": annee_frere, "annee_courante": annee_courante}
    return None

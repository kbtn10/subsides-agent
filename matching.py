"""Moteur de matching profil ↔ subsides.

Même principe que le scraping : le CODE filtre et valide, le LLM juge.
- pre_filtrer  : SQL pur, écarte l'évidemment hors-cible (zone, deadline, type).
- juger_un     : un appel LLM par paire, verdict contraint par schéma + validé.
- cache        : (profil_hash, subside_hash) — pas de ré-appel si rien n'a changé.
- invalidation : une fiche qui change (hash source) purge ses matchings.

Aucun verdict inventé : ce que le profil ne permet pas de trancher va dans
criteres_a_verifier (géré côté prompt). L'app ne dit jamais « éligible » sec.
"""

import json
import logging
from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field, ValidationError, field_validator

import db
from prompts import matching as prompt

log = logging.getLogger(__name__)

# Zones de subsides acceptées selon la région du siège de l'ASBL (lot 6).
# Communes à toutes les régions francophones :
#   - fwb       : Fédération Wallonie-Bruxelles, couvre Bruxelles ET la Wallonie
#   - national  : dispositifs fédéraux / belges
#   - inconnue  : zone non extraite — INCLUSE, le doute profite au subside, pas
#                 l'inverse (une fiche mal étiquetée ne doit pas être masquée)
# Ce qui distingue les régions : leur propre zone régionale.
#   - une ASBL bruxelloise voit 'bruxelles', pas 'wallonie'
#   - une ASBL wallonne voit 'wallonie', pas 'bruxelles'
# (flandre reste exclue partout : hors cible francophone — lot 6 option A.)
_ZONES_COMMUNES = ("fwb", "national", "inconnue")
ZONES_PAR_REGION = {
    "bruxelles": ("bruxelles",) + _ZONES_COMMUNES,
    "wallonie": ("wallonie",) + _ZONES_COMMUNES,
}
# Rétrocompat : l'ancien nom, encore importé ailleurs éventuellement.
ZONES_BRUXELLES = ZONES_PAR_REGION["bruxelles"]


def region_profil(profil: dict) -> str:
    """Région du siège, avec repli robuste sur 'bruxelles'."""
    r = (profil.get("region") or "bruxelles").strip().lower()
    return r if r in ZONES_PAR_REGION else "bruxelles"


def zones_eligibles(profil: dict) -> tuple:
    """Zones géographiques de subsides acceptables pour ce profil, d'après la
    région de son siège. Défaut bruxellois pour les profils d'avant le lot 6."""
    return ZONES_PAR_REGION[region_profil(profil)]


# --- Pré-filtre SQL (code pur) ---------------------------------------------

def pre_filtrer(profil: dict) -> list[dict]:
    """Candidats plausibles, triés (Bruxelles d'abord, deadline la plus proche).

    Exclut : fiches en échec, deadlines passées (sauf permanent), zones hors
    profil, et fiches dont le type de bénéficiaire est explicitement SANS 'asbl'.
    """
    zones = zones_eligibles(profil)
    zone_locale = region_profil(profil)   # 'bruxelles' ou 'wallonie'
    placeholders = ",".join("?" * len(zones))
    sql = f"""
        SELECT * FROM subsides
        WHERE statut != 'echec_extraction'
          AND (deadline IS NULL OR deadline = '' OR deadline >= date('now') OR permanent = 1)
          AND zone_categorie IN ({placeholders})
          AND (type_beneficiaire IS NULL OR type_beneficiaire IN ('[]','')
               OR type_beneficiaire LIKE '%"asbl"%')
        ORDER BY
          CASE WHEN zone_categorie = ? THEN 0 ELSE 1 END,  -- la zone régionale d'abord
          CASE WHEN deadline IS NULL OR deadline = '' THEN 1
               WHEN deadline >= date('now') THEN 0 ELSE 2 END,
          deadline ASC
    """
    rows = db.connect().execute(sql, (*zones, zone_locale)).fetchall()
    return [db._row_to_dict(r) for r in rows]


# --- Validation du verdict LLM ---------------------------------------------

class Verdict(BaseModel):
    model_config = {"extra": "ignore"}
    verdict: Literal["probablement_eligible", "eligible_sous_conditions", "non_eligible"]
    criteres_satisfaits: list[str] = Field(default_factory=list)
    criteres_a_verifier: list[str] = Field(default_factory=list)
    criteres_non_satisfaits: list[str] = Field(default_factory=list)
    pieces_dossier: list[str] = Field(default_factory=list)
    pertinence: Literal["forte", "moyenne", "faible"]
    justification: str

    @field_validator("criteres_satisfaits", "criteres_a_verifier",
                     "criteres_non_satisfaits", "pieces_dossier", mode="before")
    @classmethod
    def _listes(cls, v):
        if not v:
            return []
        if isinstance(v, str):
            v = [v]
        return [str(x).strip() for x in v if str(x).strip()]


def juger_un(profil: dict, subside: dict) -> dict:
    """Un appel LLM. Renvoie un dict verdict validé, ou verdict='erreur'.

    Ne lève jamais : un échec devient un matching 'erreur' re-tentable.
    """
    # Import tardif : réutilise le client + la logique temperature de l'extracteur.
    from scraper import extractor
    import anthropic

    try:
        reponse = extractor._client().messages.create(
            model=extractor.modele(),
            max_tokens=1500,
            system=prompt.SYSTEM_PROMPT,
            output_config={"format": {"type": "json_schema", "schema": prompt.SCHEMA_VERDICT}},
            messages=[{"role": "user", "content": prompt.message_utilisateur(profil, subside)}],
            **extractor._params_sampling(extractor.modele()),
        )
    except anthropic.APIStatusError as e:
        msg = (getattr(e, "message", "") or "").lower()
        # Erreur de facturation : on la nomme explicitement, sinon on cherche
        # longtemps pourquoi TOUS les jugements échouent en 400 (vécu au lot 4a).
        if "credit balance" in msg or "billing" in msg or "quota" in msg:
            log.error("!!! CRÉDITS ANTHROPIC ÉPUISÉS — tous les jugements vont échouer. "
                      "Rechargez sur console.anthropic.com (Plans & Billing). Détail: %s",
                      getattr(e, "message", "")[:200])
        else:
            log.error("Jugement KO (HTTP %s) profil=%s subside=%s : %s", e.status_code,
                      profil.get("id"), subside.get("id"), getattr(e, "message", "")[:200])
        return {"verdict": "erreur", "justification": "analyse indisponible",
                "pertinence": None, "_tokens": (0, 0)}
    except Exception:
        log.exception("Jugement KO profil=%s subside=%s", profil.get("id"), subside.get("id"))
        return {"verdict": "erreur", "justification": "analyse indisponible",
                "pertinence": None, "_tokens": (0, 0)}

    tokens = (reponse.usage.input_tokens, reponse.usage.output_tokens)

    if reponse.stop_reason in ("refusal", "max_tokens"):
        return {"verdict": "erreur", "justification": "analyse interrompue",
                "pertinence": None, "_tokens": tokens}

    brut = next((b.text for b in reponse.content if b.type == "text"), None)
    if not brut:
        return {"verdict": "erreur", "justification": "analyse indisponible",
                "pertinence": None, "_tokens": tokens}

    try:
        data = json.loads(brut)
        v = Verdict(**data).model_dump()
    except (json.JSONDecodeError, ValidationError) as e:
        log.warning("Verdict malformé profil=%s subside=%s : %s",
                    profil.get("id"), subside.get("id"), e)
        return {"verdict": "erreur", "justification": "analyse indisponible",
                "pertinence": None, "_tokens": tokens}

    v["_tokens"] = tokens
    return v


# --- Cache + stockage ------------------------------------------------------

def _dumps(v):
    return json.dumps(v or [], ensure_ascii=False)


def matching_cache(profil: dict, subside: dict) -> Optional[dict]:
    """Matching déjà en base ET à jour (mêmes hashes profil+subside) ? Sinon None."""
    row = db.connect().execute(
        "SELECT * FROM matchings WHERE profil_id = ? AND subside_id = ?",
        (profil["id"], subside["id"]),
    ).fetchone()
    if row is None:
        return None
    if row["profil_hash"] != profil.get("profil_hash"):
        return None
    if row["subside_hash"] != subside.get("text_hash"):
        return None
    if row["verdict"] == "erreur":
        return None  # on retente les erreurs
    return _row_to_matching(row)


def stocker_matching(profil: dict, subside: dict, v: dict) -> dict:
    """Upsert un matching (UNIQUE(profil_id, subside_id))."""
    from datetime import datetime, timezone
    conn = db.connect()
    conn.execute(
        """INSERT INTO matchings (profil_id, subside_id, profil_hash, subside_hash,
             verdict, criteres_satisfaits, criteres_a_verifier, criteres_non_satisfaits,
             pieces_dossier, pertinence, justification, cree_le)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(profil_id, subside_id) DO UPDATE SET
             profil_hash=excluded.profil_hash, subside_hash=excluded.subside_hash,
             verdict=excluded.verdict, criteres_satisfaits=excluded.criteres_satisfaits,
             criteres_a_verifier=excluded.criteres_a_verifier,
             criteres_non_satisfaits=excluded.criteres_non_satisfaits,
             pieces_dossier=excluded.pieces_dossier,
             pertinence=excluded.pertinence, justification=excluded.justification,
             cree_le=excluded.cree_le""",
        (profil["id"], subside["id"], profil.get("profil_hash"), subside.get("text_hash"),
         v.get("verdict"), _dumps(v.get("criteres_satisfaits")),
         _dumps(v.get("criteres_a_verifier")), _dumps(v.get("criteres_non_satisfaits")),
         _dumps(v.get("pieces_dossier")), v.get("pertinence"), v.get("justification"),
         datetime.now(timezone.utc).isoformat(timespec="seconds")),
    )
    conn.commit()
    return matching_pour(profil["id"], subside["id"])


def _row_to_matching(row) -> dict:
    d = dict(row)
    for c in ("criteres_satisfaits", "criteres_a_verifier", "criteres_non_satisfaits",
              "pieces_dossier"):
        try:
            d[c] = json.loads(d.get(c) or "[]")
        except (json.JSONDecodeError, TypeError):
            d[c] = []
    return d


def matching_pour(profil_id, subside_id) -> Optional[dict]:
    row = db.connect().execute(
        "SELECT * FROM matchings WHERE profil_id = ? AND subside_id = ?",
        (profil_id, subside_id),
    ).fetchone()
    return _row_to_matching(row) if row else None


def resultats(profil_id) -> list[dict]:
    """Matchings d'un profil, joints aux fiches, triés (verdict > pertinence > deadline).

    Enrichit chaque matching avec les champs de la fiche pour l'affichage.
    """
    rows = db.connect().execute("SELECT * FROM matchings WHERE profil_id = ?",
                                (profil_id,)).fetchall()
    ordre_verdict = {"probablement_eligible": 0, "eligible_sous_conditions": 1,
                     "non_eligible": 2, "erreur": 3}
    ordre_pert = {"forte": 0, "moyenne": 1, "faible": 2, None: 3}
    out = []
    for r in rows:
        m = _row_to_matching(r)
        s = db.get_subside(m["subside_id"])
        if s is None:
            continue
        m["subside"] = {k: s[k] for k in (
            "id", "titre", "organisme", "source_id", "deadline", "permanent",
            "montant", "url_source", "lien_officiel", "zone_categorie", "expire") if k in s}
        out.append(m)
    out.sort(key=lambda m: (
        ordre_verdict.get(m["verdict"], 4),
        ordre_pert.get(m.get("pertinence"), 3),
        m["subside"].get("deadline") or "9999-12-31",
    ))
    return out


VERDICTS_ELIGIBLES = ("probablement_eligible", "eligible_sous_conditions")


def detail(matching_id) -> Optional[dict]:
    """Un matching par son id, enrichi de la fiche complète (vue détail).

    Renvoie aussi profil_id pour que l'API vérifie la propriété (cloisonnement).
    """
    row = db.connect().execute("SELECT * FROM matchings WHERE id = ?", (matching_id,)).fetchone()
    if row is None:
        return None
    m = _row_to_matching(row)
    s = db.get_subside(m["subside_id"])
    if s is None:
        return None
    # La vue détail affiche tout : montant, zone, critères de la fiche, etc.
    m["subside"] = {k: s.get(k) for k in (
        "id", "titre", "organisme", "source_id", "deadline", "permanent", "montant",
        "url_source", "lien_officiel", "zone_categorie", "zone_geographique", "expire",
        "description", "public_cible", "criteres_eligibilite", "secteurs",
        "lien_candidature", "type_beneficiaire", "langue")}
    return m


def resume_profil(profil_id, aujourdhui: date = None) -> dict:
    """Chiffres du bandeau, calculés côté serveur (donc testables).

    Point corrigé (0.1) : les deadlines < 60 j ne sont comptées QUE parmi les
    correspondances (verdicts éligibles), pas sur tout le périmètre analysé —
    sinon on affichait plus de deadlines que de correspondances.
    """
    aujourdhui = aujourdhui or date.today()
    res = resultats(profil_id)
    correspondances = [m for m in res if m["verdict"] in VERDICTS_ELIGIBLES]
    deadlines_60j = 0
    for m in correspondances:
        d = m["subside"].get("deadline")
        if not d:
            continue
        try:
            jours = (date.fromisoformat(d) - aujourdhui).days
        except ValueError:
            continue
        if 0 <= jours <= 60:
            deadlines_60j += 1
    return {
        "total_analyses": len(res),
        "correspondances": len(correspondances),
        "probablement_eligible": sum(1 for m in res if m["verdict"] == "probablement_eligible"),
        "eligible_sous_conditions": sum(1 for m in res if m["verdict"] == "eligible_sous_conditions"),
        "non_eligible": sum(1 for m in res if m["verdict"] == "non_eligible"),
        "deadlines_60j": deadlines_60j,
    }


def invalider_pour_subside(subside_id) -> int:
    """Supprime les matchings d'une fiche (appelé quand elle passe 'modifie').
    Ils seront re-jugés à la prochaine consultation des profils concernés."""
    conn = db.connect()
    cur = conn.execute("DELETE FROM matchings WHERE subside_id = ?", (subside_id,))
    conn.commit()
    if cur.rowcount:
        log.info("Invalidation : %d matching(s) supprimé(s) pour subside %s",
                 cur.rowcount, subside_id)
    return cur.rowcount

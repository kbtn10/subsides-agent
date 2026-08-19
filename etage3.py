"""Étage 3 (lot 7) : les trois appels LLM d'accompagnement de la candidature.

  - generer_checklist   : pièces exigées par le règlement (+ citations).
  - verifier_conformite : croise règlement / profil / état déclaré du dossier.
  - copilote            : structurer / relire / reformuler (jamais rédiger).

Transverse : Subsidia est un COPILOTE, jamais l'auteur. Plafond quotidien
d'appels par user (garde-fou de coût), coût logué, caches pour ne pas repayer.
"""

import hashlib
import json
import logging
import os
from datetime import datetime, timezone

import anthropic

import candidatures as ca
import db
from prompts import checklist as p_checklist
from prompts import conformite as p_conformite
from prompts import copilote as p_copilote
from scraper.extractor import _client, _params_sampling, modele

log = logging.getLogger(__name__)

# Tarifs $ / million de tokens (repris de jobs.TARIFS, gardés locaux pour ne pas
# créer de dépendance croisée).
_TARIFS = {
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-opus-4-8": (5.00, 25.00),
}
MAX_TOKENS = 1500


def _plafond() -> int:
    return int(os.getenv("MAX_APPELS_ETAGE3_PAR_JOUR", "50"))


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _jour():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _cout(tin: int, tout: int) -> float:
    pin, pout = _TARIFS.get(modele(), (0.0, 0.0))
    return round(tin / 1e6 * pin + tout / 1e6 * pout, 5)


class PlafondAtteint(Exception):
    """Levée quand un user dépasse son quota quotidien d'appels étage 3."""


def appels_restants(user_id) -> int:
    if user_id is None:      # mode vanilla (Clerk inactif) : pas de quota
        return _plafond()
    row = db.connect().execute(
        "SELECT appels FROM etage3_usage WHERE user_id = ? AND jour = ?",
        (user_id, _jour())).fetchone()
    return max(0, _plafond() - (row["appels"] if row else 0))


def _consommer_un_appel(user_id):
    """Incrémente le compteur du jour. Lève PlafondAtteint si dépassement."""
    if user_id is None:
        return
    if appels_restants(user_id) <= 0:
        raise PlafondAtteint(
            f"plafond quotidien atteint ({_plafond()} analyses). Réessayez demain.")
    db.connect().execute(
        """INSERT INTO etage3_usage (user_id, jour, appels) VALUES (?,?,1)
           ON CONFLICT(user_id, jour) DO UPDATE SET appels = appels + 1""",
        (user_id, _jour()))
    db.connect().commit()


def _appel_json(system: str, schema: dict, message: str, *, user_id, quoi: str):
    """Appel LLM JSON structuré, avec quota et log de coût. Renvoie (data|None, cout)."""
    _consommer_un_appel(user_id)
    try:
        rep = _client().messages.create(
            model=modele(), max_tokens=MAX_TOKENS, system=system,
            output_config={"format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": message}],
            **_params_sampling(modele()),
        )
    except anthropic.APIStatusError as e:
        log.error("Étage3/%s KO (HTTP %s) : %s", quoi, e.status_code, e.message)
        return None, 0.0
    except Exception as e:
        log.exception("Étage3/%s KO", quoi)
        return None, 0.0

    tin, tout = rep.usage.input_tokens, rep.usage.output_tokens
    cout = _cout(tin, tout)
    log.info("Étage3/%s | tokens in=%d out=%d | ~$%.5f", quoi, tin, tout, cout)
    brut = next((b.text for b in rep.content if b.type == "text"), None)
    if not brut:
        return None, cout
    try:
        return json.loads(brut), cout
    except json.JSONDecodeError:
        log.error("Étage3/%s : JSON illisible", quoi)
        return None, cout


def _appel_texte(system: str, message: str, *, user_id, quoi: str):
    """Appel LLM texte libre (copilote). Renvoie (texte|None, cout)."""
    _consommer_un_appel(user_id)
    try:
        rep = _client().messages.create(
            model=modele(), max_tokens=MAX_TOKENS, system=system,
            messages=[{"role": "user", "content": message}],
            **_params_sampling(modele()),
        )
    except Exception:
        log.exception("Étage3/%s KO", quoi)
        return None, 0.0
    tin, tout = rep.usage.input_tokens, rep.usage.output_tokens
    cout = _cout(tin, tout)
    log.info("Étage3/%s | tokens in=%d out=%d | ~$%.5f", quoi, tin, tout, cout)
    txt = next((b.text for b in rep.content if b.type == "text"), None)
    return (txt.strip() if txt else None), cout


def _profil_resume(profil: dict) -> str:
    if not profil:
        return "(profil indisponible)"
    parts = [f"Nom : {profil.get('nom')}",
             f"Région/commune : {profil.get('region')} / {profil.get('commune_siege')}"]
    if profil.get("secteurs"):
        parts.append("Secteurs : " + ", ".join(profil["secteurs"]))
    if profil.get("publics_cibles"):
        parts.append("Publics : " + ", ".join(profil["publics_cibles"]))
    if profil.get("budget_categorie"):
        parts.append("Budget : " + profil["budget_categorie"])
    if profil.get("agrements"):
        parts.append("Agréments : " + ", ".join(profil["agrements"]))
    if profil.get("description_libre"):
        parts.append("Description : " + profil["description_libre"])
    return "\n".join(parts)


def _texte_subside(sub: dict) -> str:
    """Texte à donner au LLM : on privilégie le brut conservé (page+annexes PDF),
    sinon on recompose depuis les champs structurés."""
    if sub.get("raw_text"):
        return sub["raw_text"]
    morceaux = [sub.get("titre") or "", sub.get("description") or ""]
    if sub.get("criteres_eligibilite"):
        morceaux.append("Critères : " + " ; ".join(sub["criteres_eligibilite"]))
    if sub.get("montant"):
        morceaux.append("Montant : " + str(sub["montant"]))
    if sub.get("deadline"):
        morceaux.append("Échéance : " + str(sub["deadline"]))
    return "\n".join(m for m in morceaux if m)


# ==================== Checklist ============================================

def _checklist_stockee(candidature_id: int) -> list[dict]:
    rows = db.connect().execute(
        "SELECT * FROM checklist_items WHERE candidature_id = ? ORDER BY id",
        (candidature_id,)).fetchall()
    return [dict(r) for r in rows]


def etat_checklist(candidature_id: int) -> dict:
    """Checklist stockée + méta (générée ? fiche changée depuis ?)."""
    meta = db.connect().execute(
        "SELECT * FROM checklist_meta WHERE candidature_id = ?",
        (candidature_id,)).fetchone()
    cand = ca.get_candidature(candidature_id)
    sub = db.get_subside(cand["subside_id"]) if cand else None
    hash_actuel = sub.get("text_hash") if sub else None
    fiche_a_change = bool(meta and meta["subside_hash"] and hash_actuel
                          and meta["subside_hash"] != hash_actuel)
    return {
        "items": _checklist_stockee(candidature_id),
        "generee": meta is not None,
        "texte_absent": bool(meta["texte_absent"]) if meta else False,
        "fiche_a_change": fiche_a_change,
    }


def generer_checklist(candidature_id: int, user_id, *, forcer: bool = False) -> dict:
    """Génère (ou régénère) la checklist. Sans `forcer`, ne régénère pas si elle
    existe déjà pour la version actuelle de la fiche (cache par subside_hash).

    En régénération, on NE écrase PAS les coches ni les items ajoutés par
    l'utilisateur : on ajoute seulement les nouveaux items LLM manquants.
    """
    cand = ca.get_candidature(candidature_id)
    if cand is None:
        raise LookupError("candidature inconnue")
    sub = db.get_subside(cand["subside_id"])
    if sub is None:
        raise LookupError("subside inconnu")

    meta = db.connect().execute(
        "SELECT * FROM checklist_meta WHERE candidature_id = ?",
        (candidature_id,)).fetchone()
    hash_actuel = sub.get("text_hash")
    if meta and not forcer and meta["subside_hash"] == hash_actuel:
        return {**etat_checklist(candidature_id), "depuis_cache": True, "cout": 0.0}

    data, cout = _appel_json(
        p_checklist.SYSTEM_PROMPT, p_checklist.SCHEMA,
        p_checklist.message_utilisateur(sub.get("titre") or "", _texte_subside(sub)),
        user_id=user_id, quoi="checklist")
    if data is None:
        return {"erreur": "analyse indisponible", "cout": cout,
                **etat_checklist(candidature_id)}

    items = data.get("items") or []
    conn = db.connect()
    # Anti-doublon : on n'ajoute pas un item LLM déjà présent (même intitulé).
    existants = {(r["intitule"].strip().casefold())
                 for r in _checklist_stockee(candidature_id)}
    for it in items:
        cle = (it.get("intitule") or "").strip().casefold()
        if not cle or cle in existants:
            continue
        existants.add(cle)
        conn.execute(
            """INSERT INTO checklist_items
                 (candidature_id, intitule, type, source_citation, origine, coche, cree_le)
               VALUES (?,?,?,?, 'llm', 0, ?)""",
            (candidature_id, it["intitule"], it.get("type", "document"),
             it.get("source_citation"), _now()))
    conn.execute(
        """INSERT INTO checklist_meta (candidature_id, subside_hash, genere_le, texte_absent)
           VALUES (?,?,?,?)
           ON CONFLICT(candidature_id) DO UPDATE SET
             subside_hash=excluded.subside_hash, genere_le=excluded.genere_le,
             texte_absent=excluded.texte_absent""",
        (candidature_id, hash_actuel, _now(), 0 if items else 1))
    conn.commit()
    return {**etat_checklist(candidature_id), "depuis_cache": False, "cout": cout}


def cocher_item(item_id: int, coche: bool):
    db.connect().execute("UPDATE checklist_items SET coche = ? WHERE id = ?",
                         (1 if coche else 0, item_id))
    db.connect().commit()


def ajouter_item(candidature_id: int, intitule: str) -> dict:
    conn = db.connect()
    cur = conn.execute(
        """INSERT INTO checklist_items
             (candidature_id, intitule, type, origine, coche, cree_le)
           VALUES (?,?, 'document', 'utilisateur', 0, ?)""",
        (candidature_id, intitule.strip()[:300], _now()))
    conn.commit()
    return dict(conn.execute("SELECT * FROM checklist_items WHERE id = ?",
                             (cur.lastrowid,)).fetchone())


def supprimer_item(item_id: int):
    db.connect().execute("DELETE FROM checklist_items WHERE id = ?", (item_id,))
    db.connect().commit()


def user_de_item(item_id: int):
    row = db.connect().execute(
        """SELECT p.user_id FROM checklist_items ci
           JOIN candidatures c ON c.id = ci.candidature_id
           JOIN profils p ON p.id = c.profil_id WHERE ci.id = ?""",
        (item_id,)).fetchone()
    return row["user_id"] if row else None


# ==================== Conformité ==========================================

def verifier_conformite(candidature_id: int, user_id, description: str) -> dict:
    """Croise règlement / profil / checklist / état déclaré. Caché par
    (candidature, hash(état déclaré + checklist + subside_hash))."""
    cand = ca.get_candidature(candidature_id)
    if cand is None:
        raise LookupError("candidature inconnue")
    sub = db.get_subside(cand["subside_id"])
    import profils as pm
    profil = pm.get_profil(cand["profil_id"])

    etat = etat_checklist(candidature_id)
    checklist_txt = "\n".join(
        f"[{'x' if it['coche'] else ' '}] {it['intitule']}" for it in etat["items"])

    cle = hashlib.sha256(
        ((description or "") + "|" + checklist_txt + "|" + (sub.get("text_hash") or ""))
        .encode("utf-8")).hexdigest()
    cache = db.connect().execute(
        "SELECT resultat FROM etage3_cache WHERE candidature_id=? AND genre='conformite' AND cle=?",
        (candidature_id, cle)).fetchone()
    if cache:
        return {**json.loads(cache["resultat"]), "depuis_cache": True, "cout": 0.0}

    data, cout = _appel_json(
        p_conformite.SYSTEM_PROMPT, p_conformite.SCHEMA,
        p_conformite.message_utilisateur(
            sub.get("titre") or "", _texte_subside(sub),
            _profil_resume(profil), checklist_txt, description or ""),
        user_id=user_id, quoi="conformite")
    if data is None:
        return {"erreur": "analyse indisponible", "cout": cout}

    db.connect().execute(
        """INSERT OR REPLACE INTO etage3_cache
             (candidature_id, genre, cle, resultat, cree_le) VALUES (?,?,?,?,?)""",
        (candidature_id, "conformite", cle, json.dumps(data, ensure_ascii=False), _now()))
    db.connect().commit()
    return {**data, "depuis_cache": False, "cout": cout}


# ==================== Copilote ============================================

ACTIONS = ("structurer", "relire", "reformuler")


def copilote(candidature_id: int, user_id, action: str, entree: str) -> dict:
    if action not in ACTIONS:
        raise ValueError(f"action inconnue (attendu {ACTIONS})")
    if not (entree or "").strip():
        raise ValueError("entrée vide")

    cand = ca.get_candidature(candidature_id)
    if cand is None:
        raise LookupError("candidature inconnue")
    sub = db.get_subside(cand["subside_id"])
    contexte = ""
    if sub:
        contexte = f"{sub.get('titre')}\n" + (
            "Critères : " + " ; ".join(sub.get("criteres_eligibilite") or [])
            if sub.get("criteres_eligibilite") else (sub.get("description") or ""))

    sortie, cout = _appel_texte(
        p_copilote.PROMPTS[action],
        p_copilote.message_utilisateur(action, contexte, entree.strip()[:6000]),
        user_id=user_id, quoi=f"copilote/{action}")
    if sortie is None:
        return {"erreur": "assistance indisponible", "cout": cout}

    db.connect().execute(
        """INSERT INTO copilote_messages (candidature_id, action, entree, sortie, cree_le)
           VALUES (?,?,?,?,?)""",
        (candidature_id, action, entree.strip()[:6000], sortie, _now()))
    db.connect().commit()
    return {"action": action, "sortie": sortie,
            "note": p_copilote.NOTE_PIED, "depuis_cache": False, "cout": cout}


def historique_copilote(candidature_id: int) -> list[dict]:
    rows = db.connect().execute(
        "SELECT action, entree, sortie, cree_le FROM copilote_messages "
        "WHERE candidature_id = ? ORDER BY id", (candidature_id,)).fetchall()
    return [dict(r) for r in rows]

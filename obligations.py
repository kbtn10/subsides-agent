"""Obligations POST-OCTROI (lot 10B).

Quand une candidature passe en 'obtenu', on relève du règlement les obligations
qui s'imposent après (justifications datées, rapports, communication/logo,
versement du solde) — avec citation, et sans jamais inventer de date. Les délais
relatifs (« dans les 3 mois suivant la fin du projet ») sont convertis en JOURS ;
l'échéance n'est calculée qu'à partir d'une date d'ancrage saisie par l'humain.

Miroir de la checklist (etage3) : même grammaire de cache, mêmes garde-fous, on
préserve les 'fait' à la régénération.
"""

import logging
from datetime import date, datetime, timedelta, timezone

import candidatures as ca
import db
import etage3
from prompts import obligations as p_oblig

log = logging.getLogger(__name__)

TYPES = ("justificatif", "rapport", "communication", "autre")


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _items(candidature_id: int) -> list[dict]:
    rows = db.connect().execute(
        "SELECT * FROM obligations WHERE candidature_id = ? ORDER BY "
        "CASE WHEN echeance IS NULL THEN 1 ELSE 0 END, echeance, id",
        (candidature_id,)).fetchall()
    return [dict(r) for r in rows]


def etat_obligations(candidature_id: int) -> dict:
    """Obligations stockées + méta + progression + date d'ancrage."""
    meta = db.connect().execute(
        "SELECT * FROM obligations_meta WHERE candidature_id = ?",
        (candidature_id,)).fetchone()
    cand = ca.get_candidature(candidature_id)
    sub = db.get_subside(cand["subside_id"]) if cand else None
    hash_actuel = sub.get("text_hash") if sub else None
    fiche_a_change = bool(meta and meta["subside_hash"] and hash_actuel
                          and meta["subside_hash"] != hash_actuel)
    items = _items(candidature_id)
    faites = sum(1 for it in items if it["statut"] == "fait")
    # Une obligation relative sans échéance calculée = ancrage manquant.
    ancrage_requis = any(it["delai_jours"] and not it["echeance"] for it in items)
    return {
        "items": items,
        "generee": meta is not None,
        "texte_absent": bool(meta["texte_absent"]) if meta else False,
        "fiche_a_change": fiche_a_change,
        "total": len(items),
        "faites": faites,
        "en_regle": bool(items) and faites == len(items),
        "date_fin_projet": cand.get("date_fin_projet") if cand else None,
        "ancrage_requis": ancrage_requis,
    }


def generer_obligations(candidature_id: int, user_id, *, forcer: bool = False) -> dict:
    """Génère (ou régénère) les obligations depuis le règlement. Cache par
    subside_hash ; en régénération, préserve les 'fait' et les ajouts manuels
    (on n'ajoute que les nouveaux items règlement manquants)."""
    cand = ca.get_candidature(candidature_id)
    if cand is None:
        raise LookupError("candidature inconnue")
    sub = db.get_subside(cand["subside_id"])
    if sub is None:
        raise LookupError("subside inconnu")

    meta = db.connect().execute(
        "SELECT * FROM obligations_meta WHERE candidature_id = ?",
        (candidature_id,)).fetchone()
    hash_actuel = sub.get("text_hash")
    if meta and not forcer and meta["subside_hash"] == hash_actuel:
        return {**etat_obligations(candidature_id), "depuis_cache": True, "cout": 0.0}

    data, cout = etage3._appel_json(
        p_oblig.SYSTEM_PROMPT, p_oblig.SCHEMA,
        p_oblig.message_utilisateur(sub.get("titre") or "", etage3._texte_subside(sub)),
        user_id=user_id, quoi="obligations")
    if data is None:
        return {"erreur": "analyse indisponible", "cout": cout,
                **etat_obligations(candidature_id)}

    items = data.get("items") or []
    conn = db.connect()
    existants = {(r["intitule"].strip().casefold()) for r in _items(candidature_id)}
    ancre = cand.get("date_fin_projet")
    for it in items:
        cle = (it.get("intitule") or "").strip().casefold()
        if not cle or cle in existants:
            continue
        existants.add(cle)
        echeance = _valider_date(it.get("echeance"))
        delai = it.get("delai_jours") if isinstance(it.get("delai_jours"), int) else None
        # Si un délai relatif ET une ancre déjà connue : on calcule tout de suite.
        if echeance is None and delai and ancre:
            echeance = _ajouter_jours(ancre, delai)
        conn.execute(
            """INSERT INTO obligations
                 (candidature_id, intitule, type, echeance, delai_jours, source,
                  source_citation, statut, cree_le)
               VALUES (?,?,?,?,?, 'reglement', ?, 'a_faire', ?)""",
            (candidature_id, it["intitule"][:400],
             it.get("type") if it.get("type") in TYPES else "autre",
             echeance, delai, it.get("source_citation"), _now()))
    conn.execute(
        """INSERT INTO obligations_meta (candidature_id, subside_hash, genere_le, texte_absent)
           VALUES (?,?,?,?)
           ON CONFLICT(candidature_id) DO UPDATE SET
             subside_hash=excluded.subside_hash, genere_le=excluded.genere_le,
             texte_absent=excluded.texte_absent""",
        (candidature_id, hash_actuel, _now(), 0 if items else 1))
    conn.commit()
    return {**etat_obligations(candidature_id), "depuis_cache": False, "cout": cout}


def _valider_date(v) -> str | None:
    """Ne garde qu'une vraie date ISO ; tout le reste -> None (jamais d'invention)."""
    if not v:
        return None
    try:
        return date.fromisoformat(str(v)[:10]).isoformat()
    except ValueError:
        return None


def _ajouter_jours(ancre_iso: str, jours: int) -> str | None:
    try:
        return (date.fromisoformat(str(ancre_iso)[:10]) + timedelta(days=int(jours))).isoformat()
    except (ValueError, TypeError):
        return None


def definir_ancrage(candidature_id: int, date_fin_projet: str | None) -> dict:
    """Fixe la date de fin de projet et (re)calcule l'échéance des obligations à
    délai relatif. date_fin_projet=None efface l'ancrage et remet ces échéances
    à null (jamais de date inventée)."""
    ancre = _valider_date(date_fin_projet)
    conn = db.connect()
    conn.execute("UPDATE candidatures SET date_fin_projet=?, modifie_le=? WHERE id=?",
                 (ancre, _now(), candidature_id))
    for it in _items(candidature_id):
        if it["delai_jours"]:
            echeance = _ajouter_jours(ancre, it["delai_jours"]) if ancre else None
            conn.execute("UPDATE obligations SET echeance=? WHERE id=?", (echeance, it["id"]))
    conn.commit()
    return etat_obligations(candidature_id)


def basculer(obligation_id: int, fait: bool):
    db.connect().execute(
        "UPDATE obligations SET statut=?, fait_le=? WHERE id=?",
        ("fait" if fait else "a_faire", _now()[:10] if fait else None, obligation_id))
    db.connect().commit()


def ajouter(candidature_id: int, intitule: str, echeance: str | None = None,
            type_: str = "autre") -> dict:
    conn = db.connect()
    cur = conn.execute(
        """INSERT INTO obligations
             (candidature_id, intitule, type, echeance, source, statut, cree_le)
           VALUES (?,?,?,?, 'manuelle', 'a_faire', ?)""",
        (candidature_id, intitule.strip()[:400],
         type_ if type_ in TYPES else "autre", _valider_date(echeance), _now()))
    conn.commit()
    return dict(conn.execute("SELECT * FROM obligations WHERE id=?", (cur.lastrowid,)).fetchone())


def editer(obligation_id: int, data: dict) -> dict | None:
    champs = {}
    if "intitule" in data and (data["intitule"] or "").strip():
        champs["intitule"] = data["intitule"].strip()[:400]
    if "echeance" in data:
        champs["echeance"] = _valider_date(data["echeance"])
    if "type" in data and data["type"] in TYPES:
        champs["type"] = data["type"]
    if not champs:
        row = db.connect().execute("SELECT * FROM obligations WHERE id=?", (obligation_id,)).fetchone()
        return dict(row) if row else None
    cols = ", ".join(f"{k}=?" for k in champs)
    db.connect().execute(f"UPDATE obligations SET {cols} WHERE id=?",
                         (*champs.values(), obligation_id))
    db.connect().commit()
    row = db.connect().execute("SELECT * FROM obligations WHERE id=?", (obligation_id,)).fetchone()
    return dict(row) if row else None


def supprimer(obligation_id: int):
    db.connect().execute("DELETE FROM obligations WHERE id=?", (obligation_id,))
    db.connect().commit()


def user_de_obligation(obligation_id: int):
    row = db.connect().execute(
        """SELECT p.user_id FROM obligations o
           JOIN candidatures c ON c.id = o.candidature_id
           JOIN profils p ON p.id = c.profil_id WHERE o.id = ?""",
        (obligation_id,)).fetchone()
    return row["user_id"] if row else None


# --- Rappels (dashboard + échéances) ---------------------------------------

def echeances_du_profil(profil_id: int) -> list[dict]:
    """Obligations À FAIRE datées des candidatures d'un profil, pour la page
    Échéances et les bannières de rappel. Plus proche d'abord."""
    rows = db.connect().execute(
        """SELECT o.id, o.intitule, o.type, o.echeance, o.candidature_id,
                  s.titre AS subside_titre
           FROM obligations o
           JOIN candidatures c ON c.id = o.candidature_id
           LEFT JOIN subsides s ON s.id = c.subside_id
           WHERE c.profil_id = ? AND o.statut = 'a_faire' AND o.echeance IS NOT NULL
           ORDER BY o.echeance ASC""",
        (profil_id,)).fetchall()
    return [dict(r) for r in rows]

"""Coffre documentaire (lot 10A) — la surface RGPD la plus sensible du produit.

Documents d'ASBL (statuts, comptes, composition du CA…) : stockés sur le disque
CHIFFRÉS (Fernet, clé serveur DOCUMENTS_KEY), sous des noms aléatoires (uuid).
Si le disque fuit, les fichiers sont illisibles. Le nom d'origine n'est jamais
écrit sur le disque. Téléchargement uniquement via endpoint authentifié +
cloisonné (jamais servi statiquement).

TOUT est derrière le flag COFFRE_ACTIF (défaut false) : tant qu'il est false,
les endpoints répondent 403 et l'UI ne montre rien. Il ne passera true qu'en
production, sur un hébergement sérieux.
"""

import logging
import os
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

import db

log = logging.getLogger(__name__)

# --- Flag & config ----------------------------------------------------------

def actif() -> bool:
    return os.getenv("COFFRE_ACTIF", "false").strip().lower() in ("1", "true", "yes", "oui")


def _repertoire() -> Path:
    d = Path(os.getenv("DATA_DOCUMENTS", "data/documents"))
    d.mkdir(parents=True, exist_ok=True)
    return d


TAILLE_MAX = 10 * 1024 * 1024          # 10 Mo
MAX_PAR_PROFIL = int(os.getenv("MAX_DOCUMENTS_PAR_PROFIL", "30"))
# types autorisés : pdf/docx/xlsx/png/jpg
MIMES_OK = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "image/png": "png",
    "image/jpeg": "jpg",
}

# Catégories + règle de péremption par défaut (en mois). None = pas de péremption.
# 'agrement' : péremption selon l'échéance saisie par l'utilisateur (expire_le).
CATEGORIES = {
    "statuts":             {"label": "Statuts", "peremption_mois": None},
    "composition_ca":      {"label": "Composition du CA", "peremption_mois": 12},
    "comptes_annuels":     {"label": "Comptes annuels", "peremption_mois": 12},
    "bilan":               {"label": "Bilan", "peremption_mois": 12},
    "rapport_activite":    {"label": "Rapport d'activité", "peremption_mois": 12},
    "attestation_bancaire": {"label": "Attestation bancaire", "peremption_mois": 6},
    "attestation_onss":    {"label": "Attestation ONSS", "peremption_mois": 3},
    "agrement":            {"label": "Agrément", "peremption_mois": None},   # échéance saisie
    "autre":               {"label": "Autre", "peremption_mois": None},
}


class CoffreDesactive(Exception):
    """Le flag COFFRE_ACTIF est false."""


class DocumentRefuse(Exception):
    """Upload refusé (type, taille, quota, catégorie)."""


def _garde_active():
    if not actif():
        raise CoffreDesactive("fonctionnalité non activée")


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --- Chiffrement ------------------------------------------------------------

def _fernet():
    from cryptography.fernet import Fernet
    cle = os.getenv("DOCUMENTS_KEY")
    if not cle:
        raise DocumentRefuse("DOCUMENTS_KEY absente : coffre non configuré")
    return Fernet(cle.encode() if isinstance(cle, str) else cle)


# --- Péremption / fraîcheur -------------------------------------------------

def _ajouter_mois(base: date, mois: int) -> date:
    m = base.month - 1 + mois
    an = base.year + m // 12
    mo = m % 12 + 1
    # jour borné à la fin de mois (28 suffit ici : on reste au jour près)
    jour = min(base.day, 28)
    return date(an, mo, jour)


def _calcul_expiration(categorie: str, date_document: str | None,
                       expire_le: str | None) -> str | None:
    """expire_le calculé : agrément -> échéance saisie ; catégories à péremption
    -> date_document (ou aujourd'hui) + N mois ; sinon None."""
    conf = CATEGORIES.get(categorie, CATEGORIES["autre"])
    if categorie == "agrement":
        return _iso(expire_le)
    mois = conf["peremption_mois"]
    if not mois:
        return None
    base = _date(date_document) or date.today()
    return _ajouter_mois(base, mois).isoformat()


def _iso(v) -> str | None:
    d = _date(v)
    return d.isoformat() if d else None


def _date(v) -> date | None:
    if not v:
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def fraicheur(expire_le: str | None, aujourdhui: date = None) -> dict:
    """État de fraîcheur : vert (à jour) / ambre (expire bientôt) / gris (à
    renouveler)."""
    aujourdhui = aujourdhui or date.today()
    if not expire_le:
        return {"etat": "a_jour", "message": "à jour"}
    d = _date(expire_le)
    if d is None:
        return {"etat": "a_jour", "message": "à jour"}
    jours = (d - aujourdhui).days
    if jours < 0:
        return {"etat": "a_renouveler", "message": f"à renouveler (périmé depuis {-jours} j)", "expire_le": expire_le}
    if jours <= 30:
        return {"etat": "expire_bientot", "message": f"expire dans {jours} j", "expire_le": expire_le}
    return {"etat": "a_jour", "message": "à jour", "expire_le": expire_le}


# --- CRUD -------------------------------------------------------------------

def _archives_ids() -> set[int]:
    """ids de documents remplacés (donc archivés)."""
    return {r["remplace_document_id"] for r in db.connect().execute(
        "SELECT remplace_document_id FROM documents WHERE remplace_document_id IS NOT NULL")
        if r["remplace_document_id"]}


def compter(profil_id: int) -> int:
    """Nombre de documents COURANTS (hors versions archivées)."""
    arch = _archives_ids()
    return sum(1 for r in db.connect().execute(
        "SELECT id FROM documents WHERE profil_id=?", (profil_id,)) if r["id"] not in arch)


def uploader(profil_id: int, categorie: str, nom_affiche: str, nom_fichier: str,
             mime: str, data: bytes, date_document: str | None = None,
             expire_le: str | None = None) -> dict:
    _garde_active()
    if categorie not in CATEGORIES:
        raise DocumentRefuse(f"catégorie inconnue (attendu {list(CATEGORIES)})")
    if mime not in MIMES_OK:
        raise DocumentRefuse("type de fichier non autorisé (pdf, docx, xlsx, png, jpg)")
    if not data:
        raise DocumentRefuse("fichier vide")
    if len(data) > TAILLE_MAX:
        raise DocumentRefuse(f"fichier trop lourd (max {TAILLE_MAX // (1024*1024)} Mo)")
    if compter(profil_id) >= MAX_PAR_PROFIL:
        raise DocumentRefuse(f"quota atteint ({MAX_PAR_PROFIL} documents). Supprimez-en un.")

    # Écriture chiffrée sous un nom aléatoire.
    nom_disque = f"{uuid.uuid4().hex}.enc"
    (_repertoire() / nom_disque).write_bytes(_fernet().encrypt(data))

    conn = db.connect()
    # Remplacement : le document courant de cette catégorie devient une version.
    arch = _archives_ids()
    courant = conn.execute(
        "SELECT id FROM documents WHERE profil_id=? AND categorie=? ORDER BY id DESC",
        (profil_id, categorie)).fetchall()
    remplace = next((r["id"] for r in courant if r["id"] not in arch), None)

    cur = conn.execute(
        """INSERT INTO documents (profil_id, categorie, nom_affiche, nom_fichier,
             chemin_stockage, taille, mime, date_document, expire_le, uploade_le,
             remplace_document_id)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (profil_id, categorie, nom_affiche.strip()[:200] or CATEGORIES[categorie]["label"],
         nom_fichier[:255] if nom_fichier else None, nom_disque, len(data), mime,
         _iso(date_document), _calcul_expiration(categorie, date_document, expire_le),
         _now(), remplace))
    conn.commit()
    return _get(cur.lastrowid)


def _get(doc_id: int) -> dict | None:
    r = db.connect().execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
    return dict(r) if r else None


def telecharger(doc_id: int) -> tuple[str, str, bytes] | None:
    """(nom_fichier, mime, contenu déchiffré) — restitue l'ORIGINAL."""
    _garde_active()
    d = _get(doc_id)
    if d is None:
        return None
    chemin = _repertoire() / d["chemin_stockage"]
    if not chemin.exists():
        return None
    contenu = _fernet().decrypt(chemin.read_bytes())
    return (d["nom_fichier"] or d["nom_affiche"], d["mime"] or "application/octet-stream", contenu)


def supprimer(doc_id: int) -> bool:
    """Suppression DÉFINITIVE : fichier chiffré effacé du disque + ligne."""
    d = _get(doc_id)
    if d is None:
        return False
    chemin = _repertoire() / d["chemin_stockage"]
    try:
        chemin.unlink(missing_ok=True)
    except OSError:
        log.exception("suppression fichier coffre %s", chemin)
    db.connect().execute("DELETE FROM documents WHERE id=?", (doc_id,))
    db.connect().commit()
    return True


def supprimer_fichiers_du_profil(profil_id: int):
    """RGPD : efface PHYSIQUEMENT les fichiers d'un profil (avant la cascade DB)."""
    for r in db.connect().execute(
            "SELECT chemin_stockage FROM documents WHERE profil_id=?", (profil_id,)):
        try:
            (_repertoire() / r["chemin_stockage"]).unlink(missing_ok=True)
        except OSError:
            log.exception("purge fichier coffre profil %s", profil_id)


def user_de_document(doc_id: int):
    row = db.connect().execute(
        """SELECT p.user_id FROM documents d JOIN profils p ON p.id = d.profil_id
           WHERE d.id = ?""", (doc_id,)).fetchone()
    return row["user_id"] if row else None


def etat_coffre(profil_id: int) -> dict:
    """Vue par catégories : document courant + fraîcheur + versions précédentes."""
    arch = _archives_ids()
    rows = [dict(r) for r in db.connect().execute(
        "SELECT * FROM documents WHERE profil_id=? ORDER BY id DESC", (profil_id,))]
    par_cat: dict[str, list[dict]] = {}
    for r in rows:
        par_cat.setdefault(r["categorie"], []).append(r)

    categories = []
    a_jour = a_renouveler = 0
    for cid, conf in CATEGORIES.items():
        docs = par_cat.get(cid, [])
        courant = next((d for d in docs if d["id"] not in arch), None)
        versions = [d for d in docs if d is not courant]
        info = {"id": cid, "label": conf["label"], "document": None,
                "fraicheur": None, "versions_count": len(versions)}
        if courant:
            fr = fraicheur(courant["expire_le"])
            info["document"] = {k: courant[k] for k in
                ("id", "nom_affiche", "nom_fichier", "taille", "mime",
                 "date_document", "expire_le", "uploade_le")}
            info["fraicheur"] = fr
            if fr["etat"] == "a_renouveler":
                a_renouveler += 1
            else:
                a_jour += 1
        categories.append(info)
    return {"categories": categories, "a_jour": a_jour, "a_renouveler": a_renouveler,
            "total": a_jour + a_renouveler, "max": MAX_PAR_PROFIL}


def versions(profil_id: int, categorie: str) -> list[dict]:
    """Historique des versions d'une catégorie (récent d'abord)."""
    arch = _archives_ids()
    out = []
    for r in db.connect().execute(
            "SELECT * FROM documents WHERE profil_id=? AND categorie=? ORDER BY id DESC",
            (profil_id, categorie)):
        d = dict(r)
        out.append({"id": d["id"], "nom_affiche": d["nom_affiche"],
                    "nom_fichier": d["nom_fichier"], "uploade_le": d["uploade_le"],
                    "taille": d["taille"], "courant": d["id"] not in arch})
    return out


# --- Pont checklist <-> coffre (code pur, mots-clés) ------------------------

_MAP = [
    ("statuts", ("statut",)),
    ("comptes_annuels", ("comptes annuels", "comptes de l", "compte de résultat")),
    ("bilan", ("bilan",)),
    ("composition_ca", ("composition du ca", "conseil d'administration", "liste du ca",
                        "membres du conseil", "composition du conseil")),
    ("attestation_bancaire", ("attestation bancaire", "rib", "relevé d'identité bancaire",
                              "coordonnées bancaires", "iban")),
    ("attestation_onss", ("onss", "attestation onss", "sécurité sociale")),
    ("rapport_activite", ("rapport d'activité", "rapport d'activités")),
    ("agrement", ("agrément", "agrement", "reconnaissance")),
]


def categorie_pour_intitule(intitule: str) -> str | None:
    """Devine la catégorie de coffre d'un item de checklist (mots-clés). None
    si aucun rapprochement (on ne force jamais)."""
    t = (intitule or "").casefold()
    for cat, mots in _MAP:
        if any(m in t for m in mots):
            return cat
    return None


def rapprochement_checklist(profil_id: int, items: list[dict]) -> dict[int, dict]:
    """Pour chaque item de checklist reconnu, l'état du document du coffre :
    {item_id: {categorie, present, a_jour, nom, date, expire_le}} — vide si le
    flag est off. On fait le PONT informationnel, on n'attache aucun fichier."""
    if not actif():
        return {}
    etat = etat_coffre(profil_id)
    par_cat = {c["id"]: c for c in etat["categories"]}
    out = {}
    for it in items:
        cat = categorie_pour_intitule(it.get("intitule", ""))
        if not cat:
            continue
        c = par_cat.get(cat, {})
        doc = c.get("document")
        fr = c.get("fraicheur") or {}
        out[it["id"]] = {
            "categorie": cat, "label": CATEGORIES[cat]["label"],
            "present": doc is not None,
            "a_jour": bool(doc) and fr.get("etat") != "a_renouveler",
            "nom": doc["nom_affiche"] if doc else None,
            "document_id": doc["id"] if doc else None,
            "date": (doc.get("date_document") or doc.get("uploade_le")) if doc else None,
            "fraicheur": fr,
        }
    return out

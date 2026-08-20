"""Stockage SQLite : init, normalisation d'URL, dédup, détection de modifications."""

import hashlib
import json
import logging
import os
import re
import sqlite3
import threading
from datetime import date, datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

log = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", "data/subsides.db")

# Champs comparés pour décider "modifié" vs "inchangé" (spec).
CHAMPS_SUIVIS = ("titre", "deadline", "montant", "criteres_eligibilite")

# Paramètres de tracking retirés de l'URL avant dédup : ils changent d'une
# visite à l'autre sans désigner une fiche différente.
PARAMS_TRACKING = {
    "fbclid", "gclid", "msclkid", "mc_cid", "mc_eid", "igshid", "ref", "ref_src",
    "_ga", "_gl", "yclid", "twclid", "vero_id", "s_kwcid", "dclid",
    # TYPO3 (culture.be) : cHash est un hash d'intégrité recalculé à chaque
    # rendu, no_cache un flag de cache -> volatils, jamais l'identité de la fiche.
    "chash", "no_cache",
}

# Sous-paramètres tableau volatils de TYPO3, ex. tx_ttnews[backPid],
# tx_ttnews[pointer], tx_news_pi1[swords]... : contexte de navigation, pas
# l'identité. On GARDE tx_ttnews[tt_news] / [uid] (l'ID de l'enregistrement).
# Sans ça, la même fiche culture.be réapparaît sous une URL différente à
# chaque run (cHash + backPid changent) et casse la dédup.
_TYPO3_SOUS_PARAMS_VOLATILS = re.compile(
    r"^tx_[a-z0-9_]+\[(backpid|pointer|swords|overwritedemand|l10n_mode|"
    r"currentpage|page)\]$",
    re.IGNORECASE,
)

_local = threading.local()


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def hash_texte(texte: str) -> str:
    """SHA-256 du texte nettoyé. Sert de témoin de changement : hash identique
    au re-scrape -> la page n'a pas bougé -> on saute l'appel LLM (coûteux)."""
    return hashlib.sha256((texte or "").encode("utf-8")).hexdigest()


def normaliser_url(url: str) -> str:
    """Clé de dédup. Idempotent : normaliser_url(normaliser_url(u)) == normaliser_url(u).

    - scheme/host en minuscules, port par défaut retiré
    - paramètres de tracking (utm_*, fbclid, ...) retirés, le reste trié
    - fragment (#...) retiré
    - slash final retiré (sauf racine)
    """
    if not url or not url.strip():
        return ""
    url = url.strip()
    parts = urlsplit(url)

    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    if parts.port and not (
        (scheme == "http" and parts.port == 80) or (scheme == "https" and parts.port == 443)
    ):
        host = f"{host}:{parts.port}"

    # Les params sont triés : ?b=2&a=1 et ?a=1&b=2 désignent la même fiche.
    # On retire : tracking (utm_*, fbclid...), cHash/no_cache TYPO3, et les
    # sous-paramètres tableau de navigation (tx_*[backPid], [pointer]...).
    query = urlencode(
        sorted(
            (k, v)
            for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if k.lower() not in PARAMS_TRACKING
            and not k.lower().startswith("utm_")
            and not _TYPO3_SOUS_PARAMS_VOLATILS.match(k)
        )
    )

    path = parts.path
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")

    return urlunsplit((scheme, host, path, query, ""))


def lien_officiel(url_source: str) -> str:
    """URL prête à OUVRIR par un humain.

    Les fiches TYPO3 (culture.be & consorts) portent un cHash — un hash
    d'intégrité des paramètres — qu'on retire à la normalisation (il varie avec
    le contexte de navigation et casserait la dédup). Mais sans cHash, TYPO3
    refuse d'afficher la fiche : « Erreur : Les paramètres pour afficher la
    nouvelle sont incorrects ou absents ». Ajouter `no_cache=1` contourne la
    validation du cHash et rend bien la fiche. On ne touche qu'aux URLs
    concernées (tt_news sans cHash) et jamais à la clé de dédup stockée."""
    if not url_source:
        return url_source
    bas = url_source.lower()
    if "tt_news" in bas and "chash" not in bas and "no_cache" not in bas:
        return url_source + ("&" if "?" in url_source else "?") + "no_cache=1"
    return url_source


def connect():
    """Connexion par thread (sqlite3 n'aime pas le partage entre threads)."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
    return conn


def init_db():
    conn = connect()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS subsides (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            url_source           TEXT NOT NULL UNIQUE,
            source_id            TEXT NOT NULL,
            titre                TEXT,
            organisme            TEXT,
            description          TEXT,
            montant              TEXT,
            deadline             TEXT,
            permanent            INTEGER DEFAULT 0,
            public_cible         TEXT,
            criteres_eligibilite TEXT DEFAULT '[]',   -- JSON
            secteurs             TEXT DEFAULT '[]',   -- JSON
            lien_candidature     TEXT,
            langue               TEXT,
            zone_geographique    TEXT,                -- valeur libre extraite (ou NULL)
            zone_categorie       TEXT DEFAULT 'inconnue', -- valeur fermée (bruxelles|fwb|...)
            type_beneficiaire    TEXT DEFAULT '[]',   -- JSON [asbl|individu|entreprise|...]
            statut               TEXT NOT NULL,       -- nouveau|modifie|inchange|echec_extraction
            a_verifier           INTEGER DEFAULT 0,
            erreurs_validation   TEXT DEFAULT '[]',   -- JSON
            modifications        TEXT,                -- JSON {champ: {avant, apres}}
            text_hash            TEXT,                -- SHA-256 du texte source (témoin de changement)
            raw_text             TEXT,                -- brut conservé si extraction/validation KO
            premiere_detection   TEXT NOT NULL,
            derniere_verification TEXT NOT NULL
        );
        """
    )
    # Migration AVANT les index : sur une base v1, zone_categorie n'existe pas
    # encore, donc idx_zone doit être créé après l'ADD COLUMN.
    _migrer_colonnes(conn)
    conn.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_source  ON subsides(source_id);
        CREATE INDEX IF NOT EXISTS idx_statut  ON subsides(statut);
        CREATE INDEX IF NOT EXISTS idx_deadline ON subsides(deadline);
        CREATE INDEX IF NOT EXISTS idx_zone    ON subsides(zone_categorie);

        -- ================= Lot 3 : profils, matching, veille =================
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            identifiant   TEXT NOT NULL UNIQUE,  -- pseudo (v1 vanilla) ou email/sub Clerk
            clerk_user_id TEXT,                  -- référence d'identité Clerk (lot 4a)
            cree_le       TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS profils (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id          INTEGER,
            nom              TEXT,
            commune_siege    TEXT,
            langue           TEXT,
            secteurs         TEXT DEFAULT '[]',   -- JSON
            publics_cibles   TEXT DEFAULT '[]',   -- JSON
            budget_categorie TEXT,
            agrements        TEXT DEFAULT '[]',   -- JSON
            description_libre TEXT,
            ephemere         INTEGER DEFAULT 0,
            profil_hash      TEXT,                -- hash du contenu, clé de cache matching
            cree_le          TEXT NOT NULL,
            modifie_le       TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS matchings (
            id                       INTEGER PRIMARY KEY AUTOINCREMENT,
            profil_id                INTEGER NOT NULL,
            subside_id               INTEGER NOT NULL,
            profil_hash              TEXT,        -- témoins de fraîcheur du cache
            subside_hash             TEXT,
            verdict                  TEXT,        -- probablement_eligible|eligible_sous_conditions|non_eligible|erreur
            criteres_satisfaits      TEXT DEFAULT '[]',
            criteres_a_verifier      TEXT DEFAULT '[]',
            criteres_non_satisfaits  TEXT DEFAULT '[]',
            pieces_dossier           TEXT DEFAULT '[]',  -- pièces admin génériques (étage aide-dossier)
            pertinence               TEXT,        -- forte|moyenne|faible
            justification            TEXT,
            cree_le                  TEXT NOT NULL,
            UNIQUE(profil_id, subside_id),
            FOREIGN KEY(profil_id)  REFERENCES profils(id)  ON DELETE CASCADE,
            FOREIGN KEY(subside_id) REFERENCES subsides(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS scrape_runs (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            debut   TEXT NOT NULL,
            fin     TEXT,
            rapport TEXT               -- JSON du rapport, pour "données à jour il y a X h"
        );

        -- Lot 5 : santé PERSISTANTE par source. Le rapport de run vit en
        -- mémoire du job et disparaît au redémarrage ; ici on garde la trace
        -- du dernier passage de CHAQUE source, même si le run suivant a planté.
        CREATE TABLE IF NOT EXISTS source_health (
            source_id        TEXT PRIMARY KEY,
            dernier_passage  TEXT,      -- ISO : dernière tentative
            dernier_succes   TEXT,      -- ISO : dernière fois avec >0 URL découverte
            urls_decouvertes INTEGER DEFAULT 0,
            nouveaux         INTEGER DEFAULT 0,
            modifies         INTEGER DEFAULT 0,
            echecs           INTEGER DEFAULT 0,
            strategies       TEXT DEFAULT '[]',  -- JSON [{nom, strategie, trouvees, en_propre}]
            statut           TEXT,               -- ok|partiel|echec|ignoree
            erreurs          TEXT DEFAULT '[]'   -- JSON
        );

        -- ================= Lot 7 : accompagnement de la candidature =========
        -- Une candidature suit une demande de subside de « à étudier » à
        -- « obtenu ». Elle SURVIT à l'expiration du subside (valeur historique) ;
        -- elle est supprimée avec le profil (RGPD, cascade ci-dessous).
        CREATE TABLE IF NOT EXISTS candidatures (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            profil_id       INTEGER NOT NULL,
            subside_id      INTEGER NOT NULL,
            matching_id     INTEGER,
            statut          TEXT NOT NULL DEFAULT 'a_etudier',
                            -- a_etudier|dossier_en_cours|soumis|obtenu|refuse|abandonne
            montant_demande REAL,          -- euros, parsé du saisi (pour les stats)
            montant_obtenu  REAL,
            date_soumission TEXT,
            date_decision   TEXT,
            notes           TEXT,
            cree_le         TEXT NOT NULL,
            modifie_le      TEXT NOT NULL,
            FOREIGN KEY(profil_id)   REFERENCES profils(id)   ON DELETE CASCADE,
            FOREIGN KEY(subside_id)  REFERENCES subsides(id)  ON DELETE CASCADE,
            FOREIGN KEY(matching_id) REFERENCES matchings(id) ON DELETE SET NULL
        );

        -- Pièces du dossier : générées par LLM depuis la fiche+PDF, puis
        -- cochables/éditables par l'utilisateur. source_citation = extrait du
        -- règlement d'où vient l'item (la confiance passe par la source).
        CREATE TABLE IF NOT EXISTS checklist_items (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            candidature_id  INTEGER NOT NULL,
            intitule        TEXT NOT NULL,
            type            TEXT DEFAULT 'document',  -- document|formulaire|condition_forme
            source_citation TEXT,
            origine         TEXT DEFAULT 'llm',       -- llm|utilisateur
            coche           INTEGER DEFAULT 0,
            cree_le         TEXT NOT NULL,
            FOREIGN KEY(candidature_id) REFERENCES candidatures(id) ON DELETE CASCADE
        );

        -- Empreinte de la dernière génération de checklist, pour ne pas la
        -- régénérer inutilement et détecter qu'une fiche a changé (subside_hash).
        CREATE TABLE IF NOT EXISTS checklist_meta (
            candidature_id INTEGER PRIMARY KEY,
            subside_hash   TEXT,
            genere_le      TEXT,
            texte_absent   INTEGER DEFAULT 0,   -- 1 = le règlement ne détaillait rien
            FOREIGN KEY(candidature_id) REFERENCES candidatures(id) ON DELETE CASCADE
        );

        -- Historique du copilote de rédaction (structurer/relire/reformuler),
        -- conservé par candidature. Purement une aide : jamais un auteur.
        CREATE TABLE IF NOT EXISTS copilote_messages (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            candidature_id  INTEGER NOT NULL,
            action          TEXT NOT NULL,   -- structurer|relire|reformuler
            entree          TEXT,            -- ce que l'utilisateur a fourni
            sortie          TEXT,            -- la relecture d'aide renvoyée
            cree_le         TEXT NOT NULL,
            FOREIGN KEY(candidature_id) REFERENCES candidatures(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_profil_user   ON profils(user_id);
        CREATE INDEX IF NOT EXISTS idx_match_profil  ON matchings(profil_id);
        CREATE INDEX IF NOT EXISTS idx_match_subside ON matchings(subside_id);
        -- Cache des résultats LLM étage 3 (conformité) par (candidature, clé).
        -- La clé encode l'état déclaré + le subside_hash : identique -> zéro appel.
        CREATE TABLE IF NOT EXISTS etage3_cache (
            candidature_id INTEGER NOT NULL,
            genre          TEXT NOT NULL,     -- 'conformite'
            cle            TEXT NOT NULL,     -- hash (état déclaré + subside_hash)
            resultat       TEXT,             -- JSON
            cree_le        TEXT,
            PRIMARY KEY (candidature_id, genre, cle),
            FOREIGN KEY(candidature_id) REFERENCES candidatures(id) ON DELETE CASCADE
        );

        -- Compteur d'appels LLM étage 3 par user et par jour (plafond de coût).
        CREATE TABLE IF NOT EXISTS etage3_usage (
            user_id INTEGER NOT NULL,
            jour    TEXT NOT NULL,          -- AAAA-MM-JJ (UTC)
            appels  INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, jour)
        );

        CREATE INDEX IF NOT EXISTS idx_cand_profil   ON candidatures(profil_id);
        CREATE INDEX IF NOT EXISTS idx_cand_subside  ON candidatures(subside_id);
        CREATE INDEX IF NOT EXISTS idx_checklist_cand ON checklist_items(candidature_id);
        CREATE INDEX IF NOT EXISTS idx_copilote_cand  ON copilote_messages(candidature_id);

        -- Lot 9 : registre des sources (couverture visible et honnête). Le
        -- config/sources.py reste la vérité d'exécution ; ceci en est le miroir
        -- lisible, avec les différées et les écartées.
        CREATE TABLE IF NOT EXISTS sources_registry (
            id          TEXT PRIMARY KEY,
            nom         TEXT NOT NULL,
            url_entree  TEXT,
            niveau      TEXT,   -- federal|regional|communautaire|commune|philanthropique|europeen
            langue      TEXT,
            statut      TEXT,   -- active|a_evaluer|differee|ecartee
            raison      TEXT,
            evaluee_le  TEXT
        );
        """
    )
    _migrer_tables_lot3(conn)   # après création : ajoute les colonnes manquantes
    _peupler_registre(conn)
    conn.commit()
    return conn


def _peupler_registre(conn):
    """Upsert le registre des sources depuis config/registre.py. Préserve
    evaluee_le si la ligne existe déjà (première évaluation)."""
    try:
        from config.registre import REGISTRE
    except Exception:
        return
    maintenant = _now()
    for e in REGISTRE:
        conn.execute(
            """INSERT INTO sources_registry (id, nom, url_entree, niveau, langue,
                 statut, raison, evaluee_le)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                 nom=excluded.nom, url_entree=excluded.url_entree,
                 niveau=excluded.niveau, langue=excluded.langue,
                 statut=excluded.statut, raison=excluded.raison""",
            (e["id"], e["nom"], e.get("url_entree"), e.get("niveau"), e.get("langue"),
             e.get("statut"), e.get("raison"), maintenant),
        )


def lister_registre() -> list[dict]:
    """Le registre des sources, trié par statut (actives d'abord) puis niveau."""
    ordre = "CASE statut WHEN 'active' THEN 0 WHEN 'a_evaluer' THEN 1 " \
            "WHEN 'differee' THEN 2 ELSE 3 END"
    rows = connect().execute(
        f"SELECT * FROM sources_registry ORDER BY {ordre}, niveau, nom").fetchall()
    return [dict(r) for r in rows]


def _migrer_tables_lot3(conn):
    """Colonnes ajoutées après coup sur les tables lot 3 déjà existantes."""
    def cols(table):
        return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}

    if "pieces_dossier" not in cols("matchings"):
        conn.execute("ALTER TABLE matchings ADD COLUMN pieces_dossier TEXT DEFAULT '[]'")
        log.info("Migration : colonne 'matchings.pieces_dossier' ajoutée")
    if "clerk_user_id" not in cols("users"):
        conn.execute("ALTER TABLE users ADD COLUMN clerk_user_id TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_clerk ON users(clerk_user_id)")
        log.info("Migration : colonne 'users.clerk_user_id' ajoutée")
    # Lot 6 : région du siège, pilote les zones éligibles au matching.
    # Défaut 'bruxelles' : tous les profils existants ont été créés quand l'app
    # était bruxelloise, ce défaut reproduit exactement leur comportement.
    if "region" not in cols("profils"):
        conn.execute("ALTER TABLE profils ADD COLUMN region TEXT DEFAULT 'bruxelles'")
        log.info("Migration : colonne 'profils.region' ajoutée")
    # Lot 8.1 : nature du profil. `type` remplace peu à peu le booléen `ephemere`
    # (qu'on garde synchronisé pour la compatibilité des endpoints) :
    #   principal = le profil de MON ASBL (dashboard, échéances, candidatures)
    #   recherche = une hypothèse SAUVEGARDÉE, jamais purgée, avec veille
    #   ephemere  = une recherche non sauvegardée, purgée après 7 jours
    # Colonne AVANT l'index (idx_profil_type), comme la règle du projet l'exige.
    if "type" not in cols("profils"):
        conn.execute("ALTER TABLE profils ADD COLUMN type TEXT")
        # Rétro-classement : les éphémères actuels -> 'ephemere', le reste
        # (les vrais profils d'ASBL) -> 'principal'. Le hash ne bouge pas.
        conn.execute(
            "UPDATE profils SET type = CASE WHEN ephemere = 1 THEN 'ephemere' "
            "ELSE 'principal' END WHERE type IS NULL")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_profil_type ON profils(type)")
        log.info("Migration : colonne 'profils.type' ajoutée (+ rétro-classement)")
    if "nom_recherche" not in cols("profils"):
        conn.execute("ALTER TABLE profils ADD COLUMN nom_recherche TEXT")
        log.info("Migration : colonne 'profils.nom_recherche' ajoutée")


def _migrer_colonnes(conn):
    """Ajoute les colonnes manquantes sur une base créée par une version
    antérieure (ADD COLUMN ne casse pas les données existantes)."""
    existantes = {r["name"] for r in conn.execute("PRAGMA table_info(subsides)")}
    ajouts = {
        "zone_geographique": "TEXT",
        "zone_categorie": "TEXT DEFAULT 'inconnue'",
        "type_beneficiaire": "TEXT DEFAULT '[]'",
        "text_hash": "TEXT",
        # Lot 5 : URLs des règlements PDF réellement exploités pour cette fiche.
        "annexes_pdf": "TEXT DEFAULT '[]'",   # JSON [{url, ancre, caracteres}]
        # Lot 9 : nature du soutien (appel_a_projets|dispositif_permanent|
        # prix_concours|financement_instrument|NULL). Pilote les traitements UI.
        "nature": "TEXT",
    }
    for nom, decl in ajouts.items():
        if nom not in existantes:
            conn.execute(f"ALTER TABLE subsides ADD COLUMN {nom} {decl}")
            log.info("Migration : colonne '%s' ajoutée", nom)


def _dumps(v):
    return json.dumps(v or [], ensure_ascii=False)


def _canon(valeur) -> str:
    """Forme canonique pour comparer un champ : casse repliée, espaces
    normalisés. Évite qu'une reformulation cosmétique (majuscule, double
    espace) déclenche un faux 'modifié'."""
    if valeur is None:
        return ""
    return re.sub(r"\s+", " ", str(valeur)).strip().casefold()


def _canon_liste(valeurs) -> str:
    """Idem pour une liste (critères) : chaque élément canonisé, puis trié —
    l'ordre des critères renvoyé par le LLM ne doit pas compter."""
    if not valeurs:
        return ""
    return "\n".join(sorted(_canon(v) for v in valeurs if _canon(v)))


def _diff(ancien: sqlite3.Row, nouveau: dict) -> dict:
    """Compare les champs suivis sur leur forme CANONIQUE (casse/espaces).

    Renvoie {champ: {avant, apres}} avec les valeurs BRUTES pour ceux qui
    changent réellement. La comparaison canonique évite les faux positifs de
    reformulation ; on affiche quand même le texte d'origine dans le diff.
    """
    mods = {}
    for champ in CHAMPS_SUIVIS:
        avant_brut = ancien[champ]
        apres_brut = nouveau.get(champ)
        if champ == "criteres_eligibilite":
            avant_canon = _canon_liste(json.loads(avant_brut or "[]"))
            apres_canon = _canon_liste(apres_brut)
            apres_brut = _dumps(apres_brut)
            avant_brut = avant_brut or "[]"
        else:
            avant_canon = _canon(avant_brut)
            apres_canon = _canon(apres_brut)
        if avant_canon != apres_canon:
            mods[champ] = {"avant": avant_brut, "apres": apres_brut}
    return mods


def hash_connu(url_source: str) -> str | None:
    """text_hash stocké pour une URL (normalisée), ou None si fiche absente /
    déjà en échec. Sert au court-circuit : si le hash du texte fraîchement
    chargé est identique, on saute l'extraction LLM.

    On renvoie None pour les fiches en 'echec_extraction' : on veut retenter
    l'extraction à chaque run tant qu'elle n'a pas réussi.
    """
    url = normaliser_url(url_source or "")
    if not url:
        return None
    row = connect().execute(
        "SELECT text_hash, statut FROM subsides WHERE url_source = ?", (url,)
    ).fetchone()
    if row is None or row["statut"] == "echec_extraction":
        return None
    return row["text_hash"]


def toucher(url_source: str) -> str:
    """Marque une fiche 'inchange' sans rien ré-extraire (hash identique).
    Met juste à jour derniere_verification. Renvoie 'inchange'."""
    conn = connect()
    url = normaliser_url(url_source or "")
    conn.execute(
        "UPDATE subsides SET derniere_verification=?, statut='inchange' WHERE url_source=?",
        (_now(), url),
    )
    conn.commit()
    return "inchange"


def urls_connues(source_id: str = None) -> set[str]:
    """URLs normalisées déjà en base (toutes, ou d'une source).

    Sert à l'arrêt anticipé du crawl paginé : une page de listing qui ne
    contient que du déjà-vu signale qu'on est entré dans les archives.
    """
    sql = "SELECT url_source FROM subsides"
    params = ()
    if source_id:
        sql += " WHERE source_id = ?"
        params = (source_id,)
    return {r["url_source"] for r in connect().execute(sql, params)}


def dates_verification(source_id: str = None) -> dict[str, str]:
    """{url_normalisée: derniere_verification} — pour que le backfill traite
    d'abord ce qu'il n'a jamais vu, puis le plus ancien. Sans ça, un backfill
    plafonné par le budget rejouerait indéfiniment les mêmes premières fiches."""
    sql = "SELECT url_source, derniere_verification FROM subsides"
    params = ()
    if source_id:
        sql += " WHERE source_id = ?"
        params = (source_id,)
    return {r["url_source"]: r["derniere_verification"]
            for r in connect().execute(sql, params)}


def upsert_subside(donnees: dict, source_id: str, *, raw_text=None,
                   a_verifier=False, erreurs=None, echec_extraction=False,
                   text_hash=None, annexes_pdf=None) -> str:
    """Insert ou update avec dédup sur url_source normalisée.

    Renvoie le statut retenu : nouveau | modifie | inchange | echec_extraction.
    Idempotent : rejouer un scrape ne crée jamais de doublon.
    """
    conn = connect()
    url = normaliser_url(donnees.get("url_source") or "")
    if not url:
        raise ValueError("url_source manquante ou invalide")

    zone_geo = donnees.get("zone_geographique")
    zone_cat = donnees.get("zone_categorie") or "inconnue"
    type_benef = _dumps(donnees.get("type_beneficiaire"))
    # None (défaut) = « pas d'info sur les annexes ce coup-ci », on conserve
    # l'existant. Liste vide = « vérifié, aucune annexe » et on écrase.
    annexes = None if annexes_pdf is None else _dumps(annexes_pdf)
    maintenant = _now()
    existant = conn.execute(
        "SELECT * FROM subsides WHERE url_source = ?", (url,)
    ).fetchone()

    if existant is None:
        statut = "echec_extraction" if echec_extraction else "nouveau"
        conn.execute(
            """INSERT INTO subsides (
                 url_source, source_id, titre, organisme, description, montant,
                 deadline, permanent, public_cible, criteres_eligibilite, secteurs,
                 lien_candidature, langue, zone_geographique, zone_categorie,
                 type_beneficiaire, nature, statut, a_verifier, erreurs_validation,
                 modifications, text_hash, raw_text, annexes_pdf, premiere_detection,
                 derniere_verification)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                url, source_id, donnees.get("titre"), donnees.get("organisme"),
                donnees.get("description"), donnees.get("montant"), donnees.get("deadline"),
                int(bool(donnees.get("permanent"))), donnees.get("public_cible"),
                _dumps(donnees.get("criteres_eligibilite")), _dumps(donnees.get("secteurs")),
                donnees.get("lien_candidature"), donnees.get("langue"), zone_geo, zone_cat,
                type_benef, donnees.get("nature"), statut, int(bool(a_verifier)),
                _dumps(erreurs), None, text_hash, raw_text, annexes or "[]",
                maintenant, maintenant,
            ),
        )
        conn.commit()
        return statut

    if echec_extraction:
        # Fiche déjà connue mais l'extraction a échoué ce coup-ci : on ne détruit
        # pas les données valides déjà en base, on note juste le passage. On NE
        # met PAS à jour text_hash : la prochaine fois, le hash différera et on
        # retentera l'extraction.
        conn.execute(
            """UPDATE subsides SET derniere_verification=?, statut=?, raw_text=?,
                                   erreurs_validation=? WHERE url_source=?""",
            (maintenant, "echec_extraction", raw_text, _dumps(erreurs), url),
        )
        conn.commit()
        return "echec_extraction"

    mods = _diff(existant, donnees)
    if not mods:
        conn.execute(
            """UPDATE subsides SET derniere_verification=?, statut='inchange',
                 a_verifier=?, erreurs_validation=?, text_hash=?,
                 zone_geographique=?, zone_categorie=?, type_beneficiaire=?,
                 nature=COALESCE(?, nature),
                 annexes_pdf=COALESCE(?, annexes_pdf)
               WHERE url_source=?""",
            (maintenant, int(bool(a_verifier)), _dumps(erreurs), text_hash,
             zone_geo, zone_cat, type_benef, donnees.get("nature"), annexes, url),
        )
        conn.commit()
        return "inchange"

    conn.execute(
        """UPDATE subsides SET
             titre=?, organisme=?, description=?, montant=?, deadline=?, permanent=?,
             public_cible=?, criteres_eligibilite=?, secteurs=?, lien_candidature=?,
             langue=?, zone_geographique=?, zone_categorie=?, type_beneficiaire=?,
             nature=COALESCE(?, nature),
             statut='modifie', a_verifier=?, erreurs_validation=?, modifications=?,
             text_hash=?, raw_text=?, annexes_pdf=COALESCE(?, annexes_pdf),
             derniere_verification=?
           WHERE url_source=?""",
        (
            donnees.get("titre"), donnees.get("organisme"), donnees.get("description"),
            donnees.get("montant"), donnees.get("deadline"),
            int(bool(donnees.get("permanent"))), donnees.get("public_cible"),
            _dumps(donnees.get("criteres_eligibilite")), _dumps(donnees.get("secteurs")),
            donnees.get("lien_candidature"), donnees.get("langue"), zone_geo, zone_cat,
            type_benef, donnees.get("nature"), int(bool(a_verifier)), _dumps(erreurs),
            json.dumps(mods, ensure_ascii=False), text_hash, raw_text, annexes,
            maintenant, url,
        ),
    )
    conn.commit()
    log.info("Modifié %s : %s", url, ", ".join(mods))
    return "modifie"


def _row_to_dict(row: sqlite3.Row) -> dict:
    # .get() plutôt que d[...] : robuste à une colonne optionnelle absente
    # (base à peine migrée) — la lecture ne doit jamais planter là-dessus.
    d = dict(row)
    for champ in ("criteres_eligibilite", "secteurs", "erreurs_validation",
                  "type_beneficiaire"):
        try:
            d[champ] = json.loads(d.get(champ) or "[]")
        except (json.JSONDecodeError, TypeError):
            d[champ] = []
    try:
        d["modifications"] = json.loads(d["modifications"]) if d.get("modifications") else None
    except (json.JSONDecodeError, TypeError):
        d["modifications"] = None
    d["permanent"] = bool(d.get("permanent"))
    d["a_verifier"] = bool(d.get("a_verifier"))
    d.setdefault("zone_categorie", "inconnue")
    d.setdefault("zone_geographique", None)
    d.setdefault("type_beneficiaire", [])
    d.setdefault("nature", None)
    # 'expire' est CALCULÉ, jamais stocké (spec 0.1) : une deadline passée le
    # devient toute seule au fil du temps, sans re-scrape.
    dl = d.get("deadline")
    d["expire"] = bool(dl) and dl < date.today().isoformat()
    # Lien ouvrable (ajoute no_cache=1 aux fiches TYPO3 sans cHash).
    d["lien_officiel"] = lien_officiel(d.get("url_source"))
    return d


def lister_subsides(statut=None, source=None, tri="deadline", zone=None,
                    masquer_expires=False):
    conn = connect()
    where, params = [], []
    if statut:
        if statut == "a_verifier":
            where.append("a_verifier = 1")
        else:
            where.append("statut = ?")
            params.append(statut)
    if source:
        where.append("source_id = ?")
        params.append(source)
    if zone:
        where.append("zone_categorie = ?")
        params.append(zone)

    # Tri par défaut (spec 0.1) : à venir croissantes d'abord, puis permanents /
    # deadline inconnue, puis expirés (deadline passée) en bas. date('now') en
    # UTC — suffisant pour un tri au jour près.
    tri_deadline = (
        "CASE WHEN deadline IS NULL OR deadline='' THEN 1 "
        "     WHEN deadline >= date('now') THEN 0 ELSE 2 END ASC, "
        "deadline ASC"
    )
    ordres = {
        "deadline": tri_deadline,
        "titre": "titre COLLATE NOCASE ASC",
        "source": "source_id ASC, titre COLLATE NOCASE ASC",
        "recent": "premiere_detection DESC",
    }
    sql = "SELECT * FROM subsides"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY " + ordres.get(tri, ordres["deadline"])

    # raw_text peut peser lourd : exclu de la liste, dispo sur /subsides/{id}.
    lignes = [
        {k: v for k, v in _row_to_dict(r).items() if k != "raw_text"}
        for r in conn.execute(sql, params).fetchall()
    ]
    if masquer_expires:
        lignes = [s for s in lignes if not s["expire"]]
    return lignes


def get_subside(subside_id: int):
    conn = connect()
    row = conn.execute("SELECT * FROM subsides WHERE id = ?", (subside_id,)).fetchone()
    return _row_to_dict(row) if row else None


def id_par_url(url_source: str):
    """id d'une fiche par son URL (normalisée), ou None. Sert à l'invalidation
    des matchings quand une fiche change."""
    url = normaliser_url(url_source or "")
    if not url:
        return None
    row = connect().execute("SELECT id FROM subsides WHERE url_source = ?", (url,)).fetchone()
    return row["id"] if row else None


def compter_surveilles() -> int:
    """Nombre de subsides réellement surveillés (hors fiches en échec d'extraction)."""
    return connect().execute(
        "SELECT COUNT(*) n FROM subsides WHERE statut != 'echec_extraction'"
    ).fetchone()["n"]


def compter_par_statut():
    conn = connect()
    return {
        r["statut"]: r["n"]
        for r in conn.execute("SELECT statut, COUNT(*) n FROM subsides GROUP BY statut")
    }


# --- Historique des scrapes (pour « données à jour il y a X h ») ------------

def debuter_scrape_run() -> int:
    conn = connect()
    cur = conn.execute("INSERT INTO scrape_runs (debut) VALUES (?)", (_now(),))
    conn.commit()
    return cur.lastrowid


def cloturer_scrape_run(run_id: int, rapport: dict):
    conn = connect()
    conn.execute("UPDATE scrape_runs SET fin=?, rapport=? WHERE id=?",
                 (_now(), json.dumps(rapport, ensure_ascii=False), run_id))
    conn.commit()


def lister_scrape_runs(limite: int = 10) -> list[dict]:
    """Historique des scrapes, le plus récent d'abord (vue admin)."""
    rows = connect().execute(
        "SELECT * FROM scrape_runs ORDER BY id DESC LIMIT ?", (limite,)
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["rapport"] = json.loads(d["rapport"]) if d["rapport"] else None
        except (json.JSONDecodeError, TypeError):
            d["rapport"] = None
        rap = d.get("rapport") or {}
        # On aplatit l'essentiel pour que le frontend n'ait pas à fouiller.
        d["resume"] = {
            "duree_secondes": rap.get("duree_secondes"),
            "nouveaux": rap.get("total_nouveaux"),
            "modifies": rap.get("total_modifies"),
            "inchanges": rap.get("total_inchanges"),
            "echecs": rap.get("total_echecs"),
            "cout_estime_usd": rap.get("cout_estime_usd"),
        }
        out.append(d)
    return out


def stats_par_source() -> dict:
    """{source_id: {total, echecs, derniere_verification}} — santé des sources."""
    rows = connect().execute(
        """SELECT source_id,
                  COUNT(*) total,
                  SUM(CASE WHEN statut='echec_extraction' THEN 1 ELSE 0 END) echecs,
                  MAX(derniere_verification) derniere_verification
           FROM subsides GROUP BY source_id"""
    ).fetchall()
    return {r["source_id"]: {"total": r["total"], "echecs": r["echecs"] or 0,
                             "derniere_verification": r["derniere_verification"]}
            for r in rows}


def enregistrer_sante_source(rapport: dict) -> bool:
    """Persiste la santé d'une source après son passage.

    Renvoie True si c'est une SOURCE MORTE probable : 0 URL découverte alors
    qu'un passage précédent en trouvait. L'appelant en fait un log ERROR.
    """
    conn = connect()
    sid = rapport.get("source_id")
    if not sid:
        return False
    trouvees = rapport.get("fiches_trouvees", 0) or 0
    maintenant = _now()

    ancien = conn.execute(
        "SELECT urls_decouvertes, dernier_succes FROM source_health WHERE source_id = ?",
        (sid,)).fetchone()
    trouvait_avant = bool(ancien and (ancien["urls_decouvertes"] or 0) > 0)
    dernier_succes = maintenant if trouvees > 0 else (
        ancien["dernier_succes"] if ancien else None)

    conn.execute(
        """INSERT INTO source_health (source_id, dernier_passage, dernier_succes,
             urls_decouvertes, nouveaux, modifies, echecs, strategies, statut, erreurs)
           VALUES (?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(source_id) DO UPDATE SET
             dernier_passage=excluded.dernier_passage,
             dernier_succes=excluded.dernier_succes,
             urls_decouvertes=excluded.urls_decouvertes,
             nouveaux=excluded.nouveaux, modifies=excluded.modifies,
             echecs=excluded.echecs, strategies=excluded.strategies,
             statut=excluded.statut, erreurs=excluded.erreurs""",
        (sid, maintenant, dernier_succes, trouvees,
         rapport.get("nouveaux", 0) or 0, rapport.get("modifies", 0) or 0,
         rapport.get("echecs", 0) or 0,
         json.dumps(rapport.get("apports") or [], ensure_ascii=False),
         rapport.get("statut"),
         json.dumps((rapport.get("erreurs") or [])[:10], ensure_ascii=False)),
    )
    conn.commit()
    return trouvees == 0 and trouvait_avant


def sante_sources() -> dict:
    """{source_id: {...}} — ce que la base sait de la santé de chaque source."""
    out = {}
    for r in connect().execute("SELECT * FROM source_health"):
        d = dict(r)
        for champ in ("strategies", "erreurs"):
            try:
                d[champ] = json.loads(d[champ] or "[]")
            except (json.JSONDecodeError, TypeError):
                d[champ] = []
        out[d.pop("source_id")] = d
    return out


def scrape_run_en_cours(age_max_minutes: int = 180) -> dict | None:
    """Run de scrape non terminé, ou None.

    Le verrou « un seul job à la fois » ne vivait qu'en MÉMOIRE d'un process :
    un script lancé à côté de l'API pouvait démarrer un second scrape, et deux
    crawlers tapaient alors les mêmes sites en parallèle — impoli et coûteux.
    La base est le seul terrain commun aux deux, d'où ce verrou-ci.

    Au-delà de `age_max_minutes`, la ligne est considérée ORPHELINE (process
    tué en vol) et ne bloque plus : sans ça, un plantage interdirait tout
    scrape ultérieur.
    """
    row = connect().execute(
        "SELECT id, debut FROM scrape_runs WHERE fin IS NULL ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    try:
        debut = datetime.fromisoformat(row["debut"])
    except (TypeError, ValueError):
        return None
    if debut.tzinfo is None:
        debut = debut.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - debut).total_seconds() / 60
    if age > age_max_minutes:
        log.warning("Run %s ouvert depuis %.0f min — considéré orphelin, ne bloque plus",
                    row["id"], age)
        return None
    return {"id": row["id"], "debut": row["debut"], "age_minutes": round(age, 1)}


def cloturer_runs_orphelins(age_max_minutes: int = 180) -> int:
    """Ferme les runs restés ouverts (process tué). Renvoie le nombre fermé."""
    conn = connect()
    limite = (datetime.now(timezone.utc)
              - timedelta(minutes=age_max_minutes)).isoformat(timespec="seconds")
    cur = conn.execute(
        """UPDATE scrape_runs SET fin = ?, rapport = ?
           WHERE fin IS NULL AND debut < ?""",
        (_now(), json.dumps({"erreur": "run interrompu (process arrêté)"},
                            ensure_ascii=False), limite))
    conn.commit()
    return cur.rowcount


def dernier_scrape_run():
    """Dernier run terminé (fin non nulle), ou None. Survit au redémarrage."""
    row = connect().execute(
        "SELECT * FROM scrape_runs WHERE fin IS NOT NULL ORDER BY fin DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    d = dict(row)
    try:
        d["rapport"] = json.loads(d["rapport"]) if d["rapport"] else None
    except (json.JSONDecodeError, TypeError):
        d["rapport"] = None
    return d

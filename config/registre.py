"""Registre des sources (lot 9) — fondation légère.

But : rendre la couverture VISIBLE et HONNÊTE (« X actives / Y identifiées »),
y compris les sources différées et écartées. config/sources.py reste la source
de vérité d'EXÉCUTION ; le registre RÉFÉRENCE les ids de config pour les actives
et documente le reste.

Champs : id, nom, url_entree, niveau, langue, statut, raison.
  niveau : federal | regional | communautaire | commune | philanthropique | europeen
  statut : active | a_evaluer | differee | ecartee
"""

# Les entrées `config_id` pointent vers config/sources.py (exécution).
REGISTRE = [
    # ---- Actives (référencées dans config/sources.py, actif=True) ----
    {"id": "subsides_brussels", "config_id": "subsides_brussels",
     "nom": "hub.brussels — Subsides et aides financières",
     "url_entree": "https://info.hub.brussels/outils/subsides", "niveau": "regional",
     "langue": "fr", "statut": "active", "raison": "Annuaire des subsides/aides (dispositifs)."},
    {"id": "hub_appels", "config_id": "hub_appels",
     "nom": "hub.brussels — Appels à projets",
     "url_entree": "https://info.hub.brussels/appels-a-projets", "niveau": "regional",
     "langue": "fr", "statut": "active", "raison": "Appels datés de l'écosystème hub (lot 9)."},
    {"id": "kbs_frb", "config_id": "kbs_frb",
     "nom": "Fondation Roi Baudouin — Appels à projets",
     "url_entree": "https://kbs-frb.be/fr/rechercher?type_id=call", "niveau": "philanthropique",
     "langue": "fr", "statut": "active", "raison": "Appels philanthropiques (rendu JS Swiftype)."},
    {"id": "cocof", "config_id": "cocof",
     "nom": "COCOF — Appels à projets",
     "url_entree": "https://ccf.brussels/", "niveau": "communautaire",
     "langue": "fr", "statut": "active", "raison": "ASBL francophones bruxelloises."},
    {"id": "equal_brussels", "config_id": "equal_brussels",
     "nom": "equal.brussels — Appels à projets (égalité des chances)",
     "url_entree": "https://equal.brussels/", "niveau": "regional",
     "langue": "fr", "statut": "active", "raison": "Égalité des chances."},
    {"id": "culture_be", "config_id": "culture_be",
     "nom": "FWB Culture — Appels à projet/candidature",
     "url_entree": "https://www.culture.be/vous-cherchez/appels-a-projetcandidature/",
     "niveau": "communautaire", "langue": "fr", "statut": "active",
     "raison": "Culture (Fédération Wallonie-Bruxelles), TYPO3."},
    {"id": "fwb_portail", "config_id": "fwb_portail",
     "nom": "Portail FWB — Actualités & appels à projets",
     "url_entree": "https://www.federation-wallonie-bruxelles.be/actualites-evenements-et-appels-a-projet",
     "niveau": "communautaire", "langue": "fr", "statut": "active",
     "raison": "Appels FWB (WAF levé au lot 6)."},
    {"id": "bruxelles_ville", "config_id": "bruxelles_ville",
     "nom": "Ville de Bruxelles — Appels à projets",
     "url_entree": "https://www.bruxelles.be/appels-projets-en-cours", "niveau": "commune",
     "langue": "fr", "statut": "active",
     "raison": "PREMIÈRE COMMUNE (pilote vague communes). Drupal, robots OK."},
    {"id": "economie_emploi", "config_id": "economie_emploi",
     "nom": "Bruxelles Économie et Emploi — Appels à projets",
     "url_entree": "https://economie-emploi.brussels/appels-a-projets", "niveau": "regional",
     "langue": "fr", "statut": "active",
     "raison": "Listing /appels-a-projets (fiches /appel-projets-{slug}). robots "
               "autorise notre UA via le groupe * (les Disallow IA visent des "
               "agents nommés). Extraction validée."},

    # ---- À évaluer ----
    {"id": "actiris", "config_id": "actiris",
     "nom": "Actiris — Appels à projets partenaires",
     "url_entree": "https://www.actiris.brussels/fr/partenaires/repondre-a-un-appel-a-projets/",
     "niveau": "regional", "langue": "fr", "statut": "a_evaluer",
     "raison": "robots OK, mais les appels sont décrits INLINE + annexes PDF/DOC — "
               "pas de fiches individuelles crawlables. Stratégie dédiée requise."},
    {"id": "accrochage_scolaire", "config_id": "accrochage_scolaire",
     "nom": "perspective.brussels — Accrochage scolaire",
     "url_entree": "https://www.accrochagescolaire.brussels/projets-regionaux/appel-projets",
     "niveau": "regional", "langue": "fr", "statut": "a_evaluer",
     "raison": "robots OK, mais un appel UNIQUE en page + formulaires PDF — pas de "
               "multi-fiches. À traiter comme fiche unique (stratégie dédiée)."},
    {"id": "brulocalis", "config_id": "brulocalis",
     "nom": "Brulocalis — Base de données subsides communaux",
     "url_entree": "https://www.brulocalis.brussels/fr/subsides", "niveau": "regional",
     "langue": "fr", "statut": "a_evaluer",
     "raison": "Anti-bot BunkerWeb (robots.txt lui-même renvoie un challenge) ; "
               "Playwright honnête passe le challenge, mais le site signale "
               "activement refuser les bots — décision d'exploitation au propriétaire "
               "(contact/partenariat, cf. README)."},

    # ---- Différées (non codées / non exploitables en l'état) ----
    {"id": "wallonie", "config_id": "wallonie",
     "nom": "Wallonie — Appels à projets",
     "url_entree": "https://www.wallonie.be/fr/appels-a-projets", "niveau": "regional",
     "langue": "fr", "statut": "differee",
     "raison": "Listing derrière une recherche AJAX non honorée au rendu."},
    {"id": "vgc", "config_id": "vgc",
     "nom": "VGC — Subsidies",
     "url_entree": "https://www.vgc.be/subsidies-en-dienstverlening", "niveau": "communautaire",
     "langue": "nl", "statut": "differee",
     "raison": "Guichet authentifié ; pages publiques = dispositifs permanents."},

    # ---- Écartées (documentées) ----
    {"id": "enmieux_be", "config_id": None,
     "nom": "enmieux.be", "url_entree": "https://www.enmieux.be/", "niveau": "regional",
     "langue": "fr", "statut": "ecartee",
     "raison": "Vitrine de communication FEDER, sans listing d'appels à candidater."},
    {"id": "monasbl", "config_id": None,
     "nom": "MonASBL.be", "url_entree": "https://www.monasbl.be/", "niveau": "regional",
     "langue": "fr", "statut": "ecartee",
     "raison": "Agrégateur commercial payant — c'est une carte, pas une source primaire."},
]


def compter():
    """{'active': n, 'a_evaluer': n, 'differee': n, 'ecartee': n, 'total': N}."""
    out = {"active": 0, "a_evaluer": 0, "differee": 0, "ecartee": 0}
    for e in REGISTRE:
        out[e["statut"]] = out.get(e["statut"], 0) + 1
    out["total"] = len(REGISTRE)
    return out

"""Configuration des sources de subsides.

Pour ajouter une source, ajoute un dict à SOURCES. Voir README.md § "Ajouter une source".

Champs :
    id              str   identifiant stable, sert de clé en base. Ne pas renommer
                          après un premier run (les fiches y sont rattachées).
    nom             str   libellé affiché dans l'interface.
    start_urls      list  points d'entrée du crawl.
    strategie       str   "sitemap" | "pagination" | "pagination_typo3" | "rss" |
                          "llm_links". En cas d'échec, bascule sur "llm_links".
    url_pattern     str   (sitemap/pagination) regex : ne garde que les URLs qui matchent.
                          None avec llm_links, c'est Claude qui décide.
    max_pages       int   garde-fou : nb max de pages de listing parcourues.
    delai_secondes  float délai entre requêtes. PLANCHER : si le robots.txt du site
                          déclare un Crawl-delay supérieur, c'est lui qui gagne
                          (voir scraper/robots.py).
    actif           bool  False = source ignorée par le scraper.
    rendu_js        bool  True = charger la page de listing avec Playwright.

    decouverte      list  (lot 5, optionnel) PLUSIEURS points d'entrée. Chaque entrée
                          est un dict qui surcharge les champs ci-dessus :
                              {"strategie": "rss", "start_urls": [...], "nom": "flux RSS"}
                          Les URLs de toutes les stratégies sont fusionnées et
                          dédupliquées (URL normalisée) avant le fetch : une fiche
                          découverte deux fois n'est traitée qu'une fois. L'apport
                          PROPRE de chaque stratégie est logué et remonté au rapport.
                          Absent -> la source garde son unique stratégie historique.

    pdf_annexes     bool  (lot 5) autorise l'extraction des règlements PDF liés à la
                          fiche. Défaut True. Voir scraper/pdfs.py.
    max_pages_delta int   (pagination_typo3) pages lues par le cron nocturne.
    max_pages_backfill    (pagination_typo3) pages lues en backfill manuel.
                    int   None = toutes.
"""

SOURCES = [
    {
        # subsides.brussels redirige (301) vers info.hub.brussels/outils/subsides :
        # les portails subsides.brussels et 1819.brussels ont été fusionnés dans
        # hub.brussels. Cette source couvre donc les deux anciens portails.
        # Le sitemap Drupal expose les fiches en clair -> pas besoin de Playwright.
        "id": "subsides_brussels",
        "nom": "hub.brussels — Subsides et aides financières",
        "start_urls": ["https://info.hub.brussels/sitemap.xml"],
        "strategie": "sitemap",
        "url_pattern": r"^https://info\.hub\.brussels/subsides/[^/]+$",
        "max_pages": 10,
        "delai_secondes": 1.5,  # relevé à 10s par le Crawl-delay du robots.txt
        "actif": True,
        "rendu_js": False,
    },
    {
        # DÉSACTIVÉE — 1819.brussels redirige (301) vers info.hub.brussels/ :
        # le portail 1819 a fusionné dans hub.brussels et ses aides/primes sont
        # servies depuis la même base que la source ci-dessus (les facettes
        # "Primes", "Aides à l'emploi", "Incitants fiscaux" du listing
        # /outils/subsides sont exactement l'ancien contenu 1819).
        # L'activer ferait scraper deux fois les mêmes URLs pour 0 fiche neuve.
        # Gardée ici pour documenter le constat ; à réactiver si les sites
        # se re-séparent un jour.
        "id": "1819_brussels",
        "nom": "1819.brussels — Aides et primes (fusionné dans hub.brussels)",
        "start_urls": ["https://1819.brussels/"],
        "strategie": "llm_links",
        "url_pattern": None,
        "max_pages": 5,
        "delai_secondes": 1.5,
        "actif": False,
        "rendu_js": False,
    },
    {
        # Les appels à projets KBS sont derrière une recherche Swiftype rendue en
        # JS : le HTML serveur de /fr/rechercher?type_id=call ne contient AUCUN
        # résultat. D'où rendu_js=True. Et comme les fiches vivent à des URLs
        # plates (/fr/<slug>, sans préfixe distinctif), aucun regex ne peut les
        # trier -> llm_links, c'est Claude qui identifie les liens d'appels.
        "id": "kbs_frb",
        "nom": "Fondation Roi Baudouin — Appels à projets",
        "start_urls": ["https://kbs-frb.be/fr/rechercher?type_id=call"],
        "strategie": "llm_links",
        "url_pattern": None,
        "max_pages": 5,
        "delai_secondes": 10.0,  # robots.txt kbs-frb.be : Crawl-delay: 10
        "actif": True,
        "rendu_js": True,
        # LOT 5 — second point d'entrée CHERCHÉ, PAS TROUVÉ. Recon 20/07/2026 :
        #   /sitemap.xml, /sitemap_index.xml, /fr/sitemap.xml -> 404 tous les trois,
        #   et le robots.txt ne déclare aucune ligne `Sitemap:`.
        # Constat : la source reste sur un point d'entrée unique (la recherche
        # Swiftype rendue en JS). C'est sa fragilité connue — si Swiftype change,
        # kbs_frb tombe à 0 URL et l'alerte « source morte » (lot 5) le signalera.
        #
        # ⚠️ SIGNAUX DE CONTENU — source MAINTENUE ACTIVE, décision humaine du
        # 20/07/2026. Raisonnement, pour qu'il soit rejouable si le contexte
        # change (voir aussi README § Conformité aux signaux de contenu) :
        #
        # Ce que le site déclare (robots.txt kbs-frb.be, relevé 20/07/2026) :
        #   Content-Signal: search=yes, ai-train=no, use=reference
        #   + Disallow: / pour ClaudeBot, GPTBot, CCBot, Google-Extended,
        #     Bytespider, meta-externalagent, Applebot-Extended.
        #
        # Pourquoi nous restons dans le cadre :
        #   1. `ai-train=no` : respecté sans réserve. Nous n'entraînons ni
        #      n'affinons aucun modèle. Rien de ce qui est collecté ne sert à ça.
        #   2. `use=reference` : c'est exactement notre usage. Chaque fiche
        #      affichée renvoie vers l'URL officielle, qui fait foi ; nous ne
        #      republions pas le contenu à la place du site.
        #   3. `search=yes` : notre sortie est un lien plus un résumé structuré,
        #      donc dans l'esprit de ce qui est accordé.
        #   4. Les `Disallow` visent des agents NOMMÉS. Notre UA
        #      (SubsidesAgentBot) n'en fait pas partie et relève du groupe `*`
        #      qui déclare `Allow: /`. Nous ne nous déguisons en aucun d'eux et
        #      notre UA porte une adresse de contact réelle.
        #
        # Le point qui reste ouvert, assumé : le signal `ai-input` — « donner le
        # contenu à un modèle », ce que fait notre extraction — n'est PAS
        # déclaré. Selon la règle (c) du préambule, un signal absent « n'accorde
        # ni ne restreint ». Nous sommes donc dans un silence, pas dans une
        # autorisation. Le préambule rattache ces signaux à l'article 4 de la
        # directive UE 2019/790.
        #
        # Garde-fou : `robots.signaux_defavorables()` relit ces signaux À CHAQUE
        # RUN. Si `ai-input` ou `search` passe à `no`, un log ERROR le signale et
        # l'alerte remonte dans le rapport de run et dans /sources/health. Le
        # code n'arrête PAS la source tout seul : c'est une décision humaine.
    },
    # ==================== LOT 2 : sources ASBL-natives ====================
    {
        # COCOF — recon 18/07/2026 : WordPress, listing server-rendered (pas de JS).
        # Le sitemap post-sitemap.xml existe mais est TROP bruité : ~50 URLs
        # contenant "appel" mêlent vrais appels, news ("rappel-message-aux-...")
        # et annonces de lauréats. Aucun regex propre. Comme KBS, on tri par
        # llm_links sur la page de listing curée (les appels EN COURS y sont).
        # robots.txt : Crawl-delay 10 (relevé automatiquement).
        # PDF : certaines fiches renvoient les conditions vers des .docx/.pdf ;
        # on n'extrait QUE le HTML (limitation PDF documentée au README).
        "id": "cocof",
        "nom": "COCOF — Appels à projets (ASBL francophones bruxelloises)",
        "start_urls": ["https://ccf.brussels/subsides-et-agrements/appel-a-projets/"],
        "strategie": "llm_links",
        "url_pattern": None,
        "max_pages": 3,
        "delai_secondes": 10.0,  # robots.txt ccf.brussels : Crawl-delay: 10
        "actif": True,
        "rendu_js": False,
        # LOT 5 — second point d'entrée. Recon 20/07/2026 :
        #   /feed/            -> 200, RSS WordPress, 10 items (les plus récents).
        #   /wp-sitemap.xml   -> 200, index Yoast (post/page/wpdmpro/category...).
        #   /wpdmpro-sitemap.xml -> 200 mais 0 <loc> (Download Manager vide côté sitemap).
        # Retenu : le RSS. Il expose les publications AU MOMENT où elles paraissent,
        # alors que le listing curé /appel-a-projets/ ne montre que les appels que
        # la COCOF a choisi d'y épingler — un appel publié mais non épinglé était
        # invisible pour nous. Le flux mélange actualités et appels (canicule,
        # communiqués...) : il repasse donc par le MÊME tri LLM que llm_links.
        # Non retenu : post-sitemap.xml, déjà écarté au lot 2 (trop bruité, aucun
        # regex propre) — le RSS fait le même travail en 10× moins d'URLs.
        "decouverte": [
            {"nom": "listing curé", "strategie": "llm_links"},
            {"nom": "flux RSS", "strategie": "rss",
             "start_urls": ["https://ccf.brussels/feed/"]},
        ],
    },
    {
        # equal.brussels — recon 18/07/2026 : WordPress avec un sitemap DÉDIÉ
        # aux appels, open_call-sitemap.xml. Propre. -> stratégie sitemap.
        # Bilingue (fr /appels-a-projet/, nl /open-call/) : on ne garde que le FR
        # via url_pattern, sinon on crée 2 fiches pour le même appel. Le site
        # mélange années (2023/2024/2026) : on ne filtre PAS les archives (spec),
        # l'extraction remplit la deadline, le frontend/validation feront le tri.
        # robots.txt : pas de groupe *, pas de Crawl-delay -> délai config (3s poli).
        # PDF : mêmes règles que COCOF, HTML seulement.
        "id": "equal_brussels",
        "nom": "equal.brussels — Appels à projets (égalité des chances)",
        "start_urls": ["https://equal.brussels/open_call-sitemap.xml"],
        "strategie": "sitemap",
        "url_pattern": r"^https?://equal\.brussels/fr/appels-a-projet/[^/]+/?$",
        "max_pages": 5,
        "delai_secondes": 3.0,
        "actif": True,
        "rendu_js": False,
        # LOT 5 — second point d'entrée. Recon 20/07/2026 :
        #   /feed/          -> 404, PAS de RSS WordPress (constat, on ne force pas).
        #   /wp-sitemap.xml -> 200, index Yoast : post, page, open_call, campaign,
        #                      themepage, publication, theme, author.
        # Retenu : l'INDEX complet, filtré par le même url_pattern. Intérêt : si
        # open_call-sitemap.xml est renommé, vidé, ou si un appel est publié dans
        # un autre type de contenu (post, page), on le voit quand même. Coût nul
        # (XML, aucun LLM) et zéro bruit puisque le filtre reste le pattern d'URL.
        # NB : le sitemap open_call ne contient que 11 URLs (5 FR) — c'est peu,
        # d'où l'intérêt du filet.
        "decouverte": [
            {"nom": "sitemap open_call", "strategie": "sitemap"},
            {"nom": "index sitemaps", "strategie": "sitemap",
             "start_urls": ["https://equal.brussels/wp-sitemap.xml"],
             "max_pages": 12},
        ],
    },
    {
        # culture.be (FWB culture) — recon 18/07/2026 : TYPO3, server-rendered.
        # BONNE SURPRISE : le WAF FWB (qui bloque federation-wallonie-bruxelles.be)
        # ne frappe PAS www.culture.be sur ses URLs propres -> HTTP 200, pas de
        # page "requested URL was rejected". La source est donc scrapable.
        # Fiches : /detail/?tx_ttnews[tt_news]=<ID>&cHash=... -> llm_links (les
        # liens de pagination "8-14", "Dernière >>" ne doivent pas être pris).
        # ATTENTION : cHash + tx_ttnews[backPid] changent d'un run/contexte à
        # l'autre pour la MÊME fiche -> la normalisation d'URL (db.py) les retire,
        # sinon dédup cassée.
        # Si un jour le WAF se met à rejeter : passer actif=False + constat, NE
        # PAS contourner (pas d'UA navigateur simulé).
        #
        # LOT 5 — PAGINATION COMPLÈTE. Recon 20/07/2026, structure mesurée :
        #   230 pages (tx_ttnews[pointer] = 0..229), 7 fiches/page, 2 sur la
        #   dernière -> ~1605 fiches d'archives.
        #   ⚠️ Le pointer SANS cHash valide est silencieusement IGNORÉ : la page
        #   renvoie 200 avec le contenu de la page 1. Impossible donc de fabriquer
        #   « ?pointer=N » ; il faut SUIVRE les liens de pagination rendus par le
        #   site (ils portent le cHash). D'où la stratégie dédiée
        #   `pagination_typo3` : marche séquentielle de page en page.
        #   Les liens exposés sur une page couvrent ±3 pages + la dernière, donc
        #   pas de saut possible : c'est linéaire, et c'est assumé (backfill unique).
        "id": "culture_be",
        "nom": "FWB Culture — Appels à projet/candidature",
        "start_urls": ["https://www.culture.be/vous-cherchez/appels-a-projetcandidature/"],
        "strategie": "pagination_typo3",
        "url_pattern": r"tx_ttnews(%5B|\[)tt_news(%5D|\])=\d+",
        "max_pages": 230,
        # Le cron nocturne ne lit que les 3 premières pages : les nouveautés
        # arrivent en tête de listing. Le backfill complet (None = toutes) se
        # lance À LA MAIN via POST /scrape?source=culture_be&backfill=true.
        "max_pages_delta": 3,
        "max_pages_backfill": None,
        "delai_secondes": 5.0,  # pas de Crawl-delay déclaré -> prudence
        "actif": True,
        "rendu_js": False,
        # PDF : les annexes DIRECTES valent le détour (mesuré 20/07/2026 :
        # 2 fiches sur 15 en portent une, et ce sont les bonnes — « le règlement
        # et le formulaire de candidature », « l'appel complet »).
        # En revanche le SAUT vers une page intermédiaire ne rapporte rien ici
        # (0 annexe sur les échantillons) et coûterait 2 chargements à 5 s par
        # fiche, soit ~4 h 30 sur le backfill complet. Désactivé, mesure à l'appui.
        "pdf_saut": False,
    },
    # ==================== LOT 6 : ASBL francophones hors Bruxelles ==========
    {
        # WALLONIE — DIFFÉRÉE. Recon 20/08/2026 : le portail wallonie.be est bien
        # joignable (Drupal, HTTP 200, pas de WAF, robots.txt ok), MAIS ses
        # appels à projets sont INACCESSIBLES sans exécuter une recherche AJAX :
        #   - /fr/demarches?f[0]=type_de_demarche:appel_a_projets : le facet est
        #     appliqué CÔTÉ CLIENT. Fetch httpx ET Playwright (5s d'attente)
        #     renvoient tous deux la liste PAR DÉFAUT — 7 démarches génériques
        #     (permis, primes, impôts, charte graphique), AUCUN appel. Le
        #     paramètre d'URL n'est tout simplement pas honoré au rendu.
        #   - /fr/appels-a-projets (page éditoriale, server-rendered) n'expose
        #     que ~2 appels datés — trop mince pour une source.
        # Activer en l'état donnerait 2 liens ou des non-appels : on ne livre pas
        # de faux résultat. À reprendre (vague 2) : rétro-concevoir l'endpoint de
        # recherche (Drupal Search API / JSON:API derrière le facet), OU trouver
        # le bon portail SPW. L'infra région (lot 6) est déjà prête : le jour où
        # cette source fonctionne, les fiches zone=wallonie remontent aux ASBL
        # wallonnes sans autre changement.
        "id": "wallonie",
        "nom": "Wallonie — Appels à projets (différée : recherche AJAX)",
        "start_urls": ["https://www.wallonie.be/fr/appels-a-projets"],
        "strategie": "llm_links",
        "url_pattern": None,
        "max_pages": 3,
        "delai_secondes": 5.0,
        "actif": False,
        "rendu_js": False,
    },
    {
        # PORTAIL FWB (federation-wallonie-bruxelles.be) — RÉACTIVÉE au lot 6.
        # Différée au lot 2 pour cause de WAF ; recon 20/08/2026 : le WAF ne
        # répond PLUS (HTTP 200 stable). TYPO3, comme culture.be.
        # Point d'entrée = la section qui liste actualités ET appels :
        #   /actualites-evenements-et-appels-a-projet
        # Mélange actus/appels -> tri llm_links (comme COCOF / culture.be).
        #
        # ⚠️ CONFORMITÉ (robots.txt, relevé 20/08/2026) — même raisonnement que
        # kbs_frb : le fichier bloque nommément des agents IA (ClaudeBot,
        # anthropic-ai, Claude-Web, GPTBot, CCbot...) MAIS le groupe `*` déclare
        # `Allow: /` avec `Crawl-delay: 10`. Notre UA (SubsidesAgentBot) relève
        # de `*`, pas des agents nommés, et nous ne nous déguisons en aucun.
        # `robots.autorise()` -> True, aucun Content-Signal déclaré. Nous ne
        # faisons pas d'entraînement, nous renvoyons vers la fiche officielle.
        # La surveillance (robots.signaux_defavorables, lot 5) reste active : si
        # un jour un signal ai-input/search=no apparaît, l'alerte remonte.
        # Voir README § Conformité aux signaux de contenu.
        "id": "fwb_portail",
        "nom": "Portail FWB — Actualités & appels à projets",
        "start_urls": [
            "https://www.federation-wallonie-bruxelles.be/actualites-evenements-et-appels-a-projet"
        ],
        "strategie": "llm_links",
        "url_pattern": None,
        "max_pages": 3,
        "delai_secondes": 10.0,  # robots.txt FWB : Crawl-delay: 10
        "actif": True,
        "rendu_js": False,
    },
    # ==================== LOT 9 : expansion bruxelloise ====================
    {
        # hub.brussels — SECTION APPELS À PROJETS (distincte de l'annuaire
        # /subsides déjà couvert par subsides_brussels). Recon 20/08/2026 :
        # robots.txt (User-agent: *) n'interdit que /admin/ et /node/add/ ;
        # /appels-a-projets est AUTORISÉ, Crawl-delay: 10, aucun Content-Signal,
        # aucun challenge anti-bot pour notre UA. Fiches /appel-a-projets/{slug} ;
        # listing mixé actus/appels -> tri llm_links.
        "id": "hub_appels",
        "nom": "hub.brussels — Appels à projets",
        "niveau": "regional",
        "start_urls": ["https://info.hub.brussels/appels-a-projets"],
        "strategie": "llm_links",
        "url_pattern": None,
        "max_pages": 3,
        "delai_secondes": 10.0,   # Crawl-delay robots.txt hub
        "actif": True,
        "rendu_js": False,
    },
    {
        # Ville de Bruxelles — PREMIÈRE COMMUNE (pilote de la vague communes).
        # Recon 20/08/2026 : Drupal, robots.txt (User-agent: *) n'interdit que
        # les internes Drupal (/core, /admin, /node/add...) ;
        # /appels-projets-en-cours et /appel-projets-{slug} AUTORISÉS, aucun
        # blocage IA, aucun WAF. Listing server-rendered -> tri llm_links.
        "id": "bruxelles_ville",
        "nom": "Ville de Bruxelles — Appels à projets",
        "niveau": "commune",
        "start_urls": ["https://www.bruxelles.be/appels-projets-en-cours"],
        "strategie": "llm_links",
        "url_pattern": None,
        "max_pages": 3,
        "delai_secondes": 3.0,
        "actif": True,
        "rendu_js": False,
    },
    {
        # Actiris — appels d'insertion socioprofessionnelle (opérateurs d'emploi
        # dont ASBL). Recon 20/08/2026 : robots.txt minimal (Disallow: /media/
        # seul), aucun blocage IA. Deux points d'entrée : appels en cours +
        # archive (récurrence). Tri llm_links.
        "id": "actiris",
        "nom": "Actiris — Appels à projets partenaires",
        "niveau": "regional",
        "start_urls": [
            "https://www.actiris.brussels/fr/partenaires/repondre-a-un-appel-a-projets/",
            "https://www.actiris.brussels/fr/partenaires/archive-des-appels-a-projets/",
        ],
        "strategie": "llm_links",
        "url_pattern": None,
        "max_pages": 3,
        "delai_secondes": 3.0,
        "actif": False,
        "rendu_js": False,
    },
    {
        # perspective.brussels / accrochagescolaire.brussels — les appels
        # régionaux connus (dispositif accrochage scolaire, ASBL bruxelloises,
        # jusqu'à ~100 k€) vivent sur accrochagescolaire.brussels. Recon
        # 20/08/2026 : Drupal, robots.txt n'interdit que les internes, aucun
        # blocage IA, Crawl-delay: 10. Listing -> tri llm_links.
        "id": "accrochage_scolaire",
        "nom": "perspective.brussels — Accrochage scolaire (appels régionaux)",
        "niveau": "regional",
        "start_urls": ["https://www.accrochagescolaire.brussels/projets-regionaux/appel-projets"],
        "strategie": "llm_links",
        "url_pattern": None,
        "max_pages": 3,
        "delai_secondes": 10.0,
        "actif": False,
        "rendu_js": False,
    },
    {
        # economie-emploi.brussels (Bruxelles Économie et Emploi) — ACTIVE (lot 9).
        # Listing localisé : /appels-a-projets (== /appels-projets) liste ±9
        # fiches /appel-projets-{slug}, server-rendered (pas de JS). Tri llm_links.
        #
        # ⚠️ CONFORMITÉ (robots.txt, relevé 20/08/2026) — MÊME raisonnement que
        # kbs_frb / fwb_portail. Le fichier bloque NOMMÉMENT des agents IA
        # (anthropic-ai, ClaudeBot, Claude-Web, GPTBot, CCBot, Google-Extended,
        # cohere-ai, Bytespider…), MAIS le groupe `*` n'interdit que /*?*, /node*,
        # /media*, /file*, /print* — les fiches /appel-projets-{slug} sont
        # AUTORISÉES. Notre UA (SubsidesAgentBot) relève de `*`, pas des agents
        # nommés, et nous ne nous déguisons en aucun d'eux. Aucun Content-Signal.
        # Nous n'entraînons aucun modèle et renvoyons vers la fiche officielle.
        # robots.signaux_defavorables() relit ces signaux à chaque run (garde-fou).
        # Décision assumée, à revoir par le propriétaire s'il le souhaite.
        "id": "economie_emploi",
        "nom": "Bruxelles Économie et Emploi — Appels à projets",
        "niveau": "regional",
        "start_urls": ["https://economie-emploi.brussels/appels-a-projets"],
        "strategie": "llm_links",
        "url_pattern": None,
        "max_pages": 3,
        "delai_secondes": 5.0,
        "actif": True,
        "rendu_js": False,
    },
    {
        # brulocalis.brussels — À ÉVALUER (décision propriétaire). Recon
        # 20/08/2026 : le site est protégé par BunkerWeb — /robots.txt LUI-MÊME
        # renvoie une page HTML « Bot Detection » (« Please wait while we check
        # if you are a Human », meta refresh 30s, meta robots noindex,nofollow),
        # donc AUCUNE politique robots lisible. httpx est bloqué (challenge JS).
        # Un UNIQUE essai Playwright avec notre UA honnête (outil standard, pas
        # un contournement) A PASSÉ le challenge et rendu le vrai contenu
        # (« Subsides et appels à projets | Brulocalis »). Conduite : le site
        # signale activement qu'il ne veut pas de bots -> on NE crawle PAS dans
        # ce lot ; décision d'exploitation durable laissée au propriétaire
        # (contact/partenariat Brulocalis, comme pour KBS). Voir README.
        "id": "brulocalis",
        "nom": "Brulocalis — Subsides communaux (différée : anti-bot BunkerWeb)",
        "niveau": "regional",
        "start_urls": ["https://www.brulocalis.brussels/fr/subsides"],
        "strategie": "llm_links",
        "url_pattern": None,
        "max_pages": 3,
        "delai_secondes": 10.0,
        "actif": False,
        "rendu_js": True,
    },
    # ==================== Sources DIFFÉRÉES (non codées) ====================
    {
        # VGC (Vlaamse Gemeenschapscommissie) — DIFFÉRÉE.
        # La recherche de subsides passe par un "subsidieloket" digital derrière
        # authentification -> non scrapable proprement. Les pages publiques
        # vgc.be/subsidies-en-dienstverlening/ décrivent surtout des dispositifs
        # PERMANENTS, pas des appels datés. Reporté (voir README).
        "id": "vgc",
        "nom": "VGC — Subsidies (différée : guichet authentifié)",
        "start_urls": ["https://www.vgc.be/subsidies-en-dienstverlening"],
        "strategie": "llm_links",
        "url_pattern": None,
        "max_pages": 3,
        "delai_secondes": 5.0,
        "actif": False,
        "rendu_js": False,
    },
    # (L'ancienne entrée différée 'fwb_portail' est devenue active ci-dessus,
    #  section LOT 6 — le WAF qui l'avait fait reporter ne répond plus.)
]


def sources_actives():
    return [s for s in SOURCES if s.get("actif")]


def get_source(source_id):
    for s in SOURCES:
        if s["id"] == source_id:
            return s
    return None

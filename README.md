# Agent Subsides — Région bruxelloise

Deux usages, deux pages :

- **Vue produit — `/app`** (lot 3) : une ASBL crée un profil, l'app lui montre les
  subsides auxquels elle est **probablement éligible** (matching LLM), et une
  veille tourne la nuit. L'app ne dit jamais « vous êtes éligible » — elle dit
  « probablement éligible, vérifiez ces points ».
- **Vue admin — `/`** : bouton « Scraper », table brute des fiches, filtres.
  L'agent parcourt les portails de subsides bruxellois, extrait chaque fiche en
  JSON via l'API Claude, stocke en SQLite avec badges nouveau/modifié/à vérifier.

> ⚠️ **Vérifie toujours la deadline et les montants sur la fiche source avant de
> candidater.** L'extraction ET le jugement d'éligibilité sont faits par un LLM :
> fidèles la plupart du temps, jamais garantis. Voir [Limites connues](#limites-connues).

---

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium        # nécessaire pour la source KBS (rendue en JS)
```

## Configuration

```bash
cp .env.example .env
```

Puis édite `.env` :

| Variable | Rôle |
|---|---|
| `ANTHROPIC_API_KEY` | **Obligatoire.** Clé API ([console](https://console.claude.com/settings/keys)). Sans elle, `/scrape` échoue. |
| `EXTRACTION_MODEL` | Défaut `claude-haiku-4-5`. |
| `CONTACT_EMAIL` | Publié dans le User-Agent du bot. **Mets une vraie adresse** : c'est ce qui permet à un webmaster de te contacter plutôt que de te bloquer. |
| `MAX_FICHES_PAR_RUN` | Garde-fou de coût. Défaut 150. |
| `DB_PATH` / `LOG_PATH` | Optionnels. Défaut `data/subsides.db` et `data/agent.log`. |
| `FRONTEND_ORIGIN` | Origines CORS autorisées, **séparées par des virgules**. Défaut `http://localhost:3000`. Mets-y aussi `http://localhost:3001` : Next bascule sur ce port si 3000 est occupé, et sans ça toutes les requêtes du front échouent silencieusement. |
| `CLERK_AUTHORIZED_PARTY` | Origines acceptées dans le claim `azp` des JWT Clerk, **séparées par des virgules** (dev `:3000,:3001` ; en prod apex + www). |
| `ADMIN_CLERK_USER_IDS` | Repli admin : liste d'`user_…` Clerk séparés par des virgules, autorisés sur `/admin/*` et `/scrape`. Utile tant que le template de token Clerk n'expose pas le rôle. |

## Lancement

```bash
uvicorn main:app --reload
```

- **Vue produit (ASBL)** : <http://127.0.0.1:8000/app> — crée un profil, obtiens
  tes subsides.
- **Vue admin** : <http://127.0.0.1:8000/> — scrape + table brute.

La base et les logs sont créés au premier démarrage. Après avoir ajouté un champ
au schéma (zone, type de bénéficiaire), donne-le aux fiches existantes avec :

```bash
python scripts/backfill.py --champ type_beneficiaire --dry-run   # aperçu
python scripts/backfill.py --champ type_beneficiaire             # ré-extraction (coûte des tokens)
```

## Frontend Next.js (lot 4a)

Depuis le lot 4a, l'app produit a un **vrai visage** : une application Next.js
(`frontend/`) au design soigné, avec auth Clerk. Le backend FastAPI ne change pas
de rôle — il devient une **API pure** consommée par le frontend.

Deux process côte à côte :

| Process | Port | Rôle |
|---|---|---|
| **FastAPI** | 8000 | API (profils, matching, subsides) + les vues vanilla (fallback) |
| **Next.js** | 3000 | L'app produit (onboarding, dashboard) — le nouveau visage |

Le script `dev.sh` lance les deux :

```bash
./dev.sh                    # backend + frontend ensemble (Ctrl-C arrête les deux)
```

Ou séparément :

```bash
# terminal 1 — backend
uvicorn main:app --reload --port 8000
# terminal 2 — frontend
cd frontend && npm install && npm run dev
```

Puis <http://localhost:3000>.

> **Les vues vanilla restent servies par FastAPI** (`/` admin et `/app`), intactes
> — elles sont le fallback jusqu'à parité complète. Ne les confonds pas avec le
> frontend Next.js.

**Design** : chaleureux et rassurant (le public = des coordinateur·rice·s d'ASBL,
non-techniques, sur un sujet stressant). Blanc cassé chaud, vert profond confiant,
Fraunces (titres) + Inter (texte), animations de révélation au dashboard. Tokens
dans `frontend/app/globals.css`. Nom du produit : **Subsidia** (placeholder, isolé
dans `frontend/lib/constants.ts`).

### Auth Clerk — configuration pas à pas

Le backend vérifie les JWT Clerk, mais **par défaut Clerk est inactif** : sans
config, les vues vanilla et l'API marchent sans token (mode fallback). Pour
activer l'auth (nécessaire pour le frontend Next.js) :

1. Crée un compte et une application sur <https://dashboard.clerk.com>.
2. Dans **User & Authentication → Email, Phone, Username** : active **Email**, puis
   dans ses **Verification methods**, active **Email verification code** (code à
   6 chiffres) et désactive **Email verification link**. Le code évite l'erreur
   « verification link is invalid for this device » du magic link (le lien exige
   le même navigateur ; un code se tape dans l'onglet en cours — plus robuste,
   surtout en navigation privée). Les composants Clerk s'adaptent automatiquement,
   aucun changement de code.
3. Dans **User & Authentication → Social Connections** : active **Google**.
4. Dans **API keys** (menu latéral), copie :
   - la **Publishable key** (`pk_test_…`)
   - la **Secret key** (`sk_test_…`)
   - la **JWKS URL** (onglet « Show JWT public key » / « Advanced » —
     forme `https://<ton-sous-domaine>.clerk.accounts.dev/.well-known/jwks.json`).
5. **Frontend** — copie `frontend/.env.local.example` vers `frontend/.env.local`
   et colle `pk_test_…` et `sk_test_…`.
6. **Backend** — dans le `.env` racine, renseigne :
   ```
   CLERK_JWKS_URL=https://<ton-sous-domaine>.clerk.accounts.dev/.well-known/jwks.json
   FRONTEND_ORIGIN=http://localhost:3000,http://localhost:3001
   CLERK_AUTHORIZED_PARTY=http://localhost:3000,http://localhost:3001
   ```
7. Relance `./dev.sh`. Le sign-up magic link → onboarding → dashboard fonctionne.

> Sans ces clés, `npm run build` passe quand même (une clé publiable *placeholder*
> valide est fournie), mais le flux d'auth réel ne s'active qu'avec tes vraies clés.

## Structure de l'app (lot 4b)

Le lot 4a donnait un visage ; le lot 4b donne une **maison**. Trois groupes de
routes, trois habillages :

| Groupe | Routes | Habillage |
|---|---|---|
| `app/(marketing)/` | `/`, `/confidentialite`, `/sign-in`, `/sign-up` | En-tête marketing + pied de page |
| `app/(app)/` | `/dashboard`, `/echeances`, `/subside/[id]`, `/recherche`, `/onboarding`, `/admin` | Sidebar desktop (240 px, `sticky`) + barre basse mobile |
| racine | `/not-found` | — |

Quelques décisions à connaître :

- **Barre basse plutôt que burger** sur mobile : une cible au pouce, toujours
  visible, sans geste d'ouverture. Elle ne tient que 4 entrées — l'accès
  **Administration** vit donc aussi dans le menu compte.
- **Carte compacte en liste, format complet en détail.** La liste sert à
  scanner (titre, organisme, J-n, pertinence, nombre de points à vérifier) ;
  `/subside/{id}` porte la justification, les critères et la fiche officielle.
  Chaque carte est un `<Link>` : deep-link partageable et navigable au clavier.
- **Un seul appel pour le dashboard** (`GET /dashboard/{profil_id}`) : résumé,
  correspondances et fraîcheur des données arrivent ensemble.
- **`<Reveal>` plutôt que `whileInView` nu** (`components/reveal.tsx`).
  `whileInView` seul laisse le contenu à `opacity: 0` si l'IntersectionObserver
  ne se déclenche pas — deux sections de la landing sont réellement restées
  invisibles en capture. `Reveal` révèle de toute façon après 1,5 s :
  l'animation est un bonus, jamais une condition d'affichage.
- **Pas de `<UserButton>` Clerk** : son avatar par défaut est un dégradé violet
  qui jure avec la palette. Menu compte maison, actions Clerk conservées
  (`openUserProfile`, `signOut`).

### Espace admin

`/admin` (Next.js) : bouton de collecte avec progression live, santé par source,
historique des collectes, table des fiches filtrable (statut / source / zone).

L'accès est vérifié **côté serveur** — le front n'affiche l'entrée de menu que
si `GET /admin/moi` répond `{"admin": true}`, et toutes les routes `/admin/*` +
`/scrape` + `/status` exigent `Depends(exiger_admin)`. Deux sources de rôle :
le claim `role` du JWT Clerk, ou l'allowlist `ADMIN_CLERK_USER_IDS`.

### Captures d'écran

`docs/screenshots/` contient les captures **réelles** de chaque écran, en
desktop 1440 et mobile 375, prises avec le backend en marche et les données de
`data/subsides.db`. Elles se regénèrent avec :

```bash
.venv/bin/python tools/screenshots.py --front http://localhost:3001
```

Le script se connecte via un **sign-in token** de l'API backend Clerk (le
formulaire d'inscription est protégé par Cloudflare Turnstile, infranchissable
en navigateur headless — et hors de question de le contourner), copie un profil
réel et ses jugements **déjà en cache** vers le compte de test, puis photographie
chaque écran. Aucun appel Anthropic n'est déclenché.

Une exception : `11-streaming-desktop.png` (barre de progression à 8/25, cartes
qui arrivent une à une) exige un **vrai run LLM** — avec les jugements en cache,
l'analyse se termine en moins d'une seconde et le bandeau n'existe pas. Pour la
refaire, modifie la description du profil (le `profil_hash` change, le cache est
invalidé) puis relance. Coût mesuré : **~0,078 $** pour 25 jugements en ~26 s.
Le script ne réécrit pas cette capture si le run est trop rapide.

> Le compte de test créé dans Clerk (`subsidia+clerk_test@example.com`) et son id
> dans `ADMIN_CLERK_USER_IDS` sont à retirer quand tu n'en as plus besoin.

### Qualité

`npm run build` et `npm run lint` passent. TypeScript strict, types fidèles à
pydantic (`frontend/lib/types.ts`), `prefers-reduced-motion` respecté, next/font
(pas de fonts bloquantes). Le frontend ne parle **qu'à** l'API FastAPI — aucun
accès base ni appel Anthropic côté Next.js. Le favicon (`app/icon.svg`) est le
vrai glyphe « S » de Fraunces, vectorisé depuis la fonte.

## Tests

```bash
pytest                    # 232 tests, ~3s, aucun accès réseau ni API
```

Couvrent : validation (dates invalides, JSON malformé, URLs invalides),
normalisation d'URL et dédup, fusion des règles robots.txt, forme de la requête
API, et tolérance aux pannes du pipeline. Côté auth : vérification JWT,
cloisonnement des profils entre comptes, rôle admin (JWT + allowlist), et liste
d'origines `azp`.

---

## État réel des sources

**6 sources actives** (lot 1 : hub.brussels, KBS ; lot 2 : COCOF, equal.brussels,
culture.be ; lot 6 : portail FWB) + **3 différées** documentées. Toutes les
structures ont été vérifiées en direct sur les vrais sites avant de choisir la
stratégie.

### Lot 1 — recon 17/07/2026

| Source | Constat | Décision |
|---|---|---|
| **subsides.brussels** | Redirige (301) vers `info.hub.brussels/outils/subsides`. Site Drupal, sitemap exploitable, **109 fiches** en `/subsides/<slug>`, HTML statique. | ✅ Active, stratégie `sitemap`. **Vérifiée : 109 fiches, 0 erreur.** |
| **1819.brussels** | Redirige (301) vers `info.hub.brussels/`. Les deux portails ont **fusionné** dans hub.brussels. | ⛔️ **Désactivée** (`actif=False`). Scraperait 2× les mêmes URLs pour 0 fiche neuve. |
| **kbs-frb.be** | Appels à projets derrière une **recherche Swiftype rendue en JS** ; URLs plates `/fr/<slug>` non triables par regex. | ✅ Active, `rendu_js=True` + `llm_links`. Rendu Playwright vérifié. |

### Lot 2 — sources ASBL-natives, recon 18/07/2026

hub.brussels s'est révélé orienté **entreprises / aides permanentes**, alors que
la cible du projet est les **ASBL**. Le lot 2 ajoute des sources ASBL-natives.

| Source | Constat | Décision |
|---|---|---|
| **COCOF** (`ccf.brussels`) | WordPress, listing server-rendered. Sitemap `post-sitemap.xml` **trop bruité** (~50 URLs « appel » mêlant vrais appels, news, annonces de lauréats). Aucun regex propre. `Crawl-delay: 10`. | ✅ Active, `llm_links` sur la page de listing curée (comme KBS). Fetch d'une fiche vérifié. |
| **equal.brussels** | WordPress avec un **sitemap dédié `open_call-sitemap.xml`**. Bilingue (fr/nl). Mélange les années (archives). | ✅ Active, `sitemap` + `url_pattern` FR (évite les doublons NL). **Vérifié : 5 appels FR, 0 erreur.** Archives non filtrées au crawl (spec) — l'extraction remplit la deadline, le filtre Zone/le tri font le reste. |
| **culture.be** (FWB) | TYPO3. **Bonne surprise : PAS de blocage WAF** sur `www.culture.be` (HTTP 200, pas de « requested URL was rejected »). Fiches en `/detail/?tx_ttnews[tt_news]=ID&cHash=…`. | ✅ Active, `llm_links`. Fetch d'une fiche vérifié (deadline visible dans le texte). cHash/backPid normalisés (voir plus bas). |

**Surprise TLS — equal.brussels.** Son certificat est signé par une autorité
(GÉANT / Hellenic Academic CA) présente dans le magasin de l'OS et des
navigateurs, mais **absente du bundle certifi** qu'utilise httpx →
« unable to get local issuer certificate ». Corrigé avec **`truststore`**
(`scraper/__init__.py`), qui aligne Python sur le magasin de l'OS — c'est ce que
fait pip lui-même. **La vérification TLS n'est pas désactivée** : on vérifie
contre le même magasin que le navigateur avec lequel l'URL a été validée.

**culture.be et le WAF FWB.** Le pare-feu applicatif qui protège
`federation-wallonie-bruxelles.be` ne frappe **pas** `www.culture.be` sur ses
URLs propres. Si un jour il s'y met (page « requested URL was rejected » ou 403),
la source se marquera en échec dans le rapport ; passe-la alors `actif=False`
avec le constat — **ne contourne pas** (pas d'UA de navigateur simulé). Le
constat serait remonté dans le rapport final.

### Sources différées (documentées, non codées)

Présentes dans `config/sources.py` en `actif=False` :

- **VGC** (Vlaamse Gemeenschapscommissie) — la recherche de subsides passe par un
  *subsidieloket* digital **derrière authentification**, non scrapable proprement.
  Les pages publiques `vgc.be/subsidies-en-dienstverlening/` décrivent surtout des
  dispositifs permanents. Reporté.
- **Wallonie** (`wallonie.be`) — **différée au lot 6.** Le portail est joignable
  (Drupal, pas de WAF), mais ses appels à projets sont derrière une **recherche
  AJAX** : le facet `?f[0]=type_de_demarche:appel_a_projets` est appliqué côté
  client. Fetch httpx **et** Playwright (5 s d'attente) renvoient tous deux la
  liste par défaut — 7 démarches génériques (permis, primes, impôts), **aucun
  appel**. La page éditoriale `/fr/appels-a-projets` n'expose que ~2 appels.
  Reporté : activer en l'état donnerait des non-appels. À reprendre en
  rétro-concevant l'endpoint de recherche (Drupal Search API derrière le facet).
  **L'infra région (lot 6) est prête** : le jour où cette source fonctionne, les
  fiches `zone=wallonie` remontent aux ASBL wallonnes sans autre changement.

> **Portail FWB — RÉACTIVÉ au lot 6.** Différé au lot 2 pour cause de WAF ; recon
> 20/08/2026 : le WAF **ne répond plus** (HTTP 200 stable), TYPO3 comme culture.be.
> Point d'entrée `/actualites-evenements-et-appels-a-projet` (fil qui mêle actus
> et appels). Conformité : même cas que KBS — le robots.txt bloque des agents IA
> nommés (ClaudeBot, anthropic-ai…) mais le groupe `*` autorise `/` (Crawl-delay
> 10), notre UA en relève. Vérifié en réel : **2 vrais appels extraits, 0 erreur.**

### Deux points à connaître

**1. Le `delai_secondes` de la config est un plancher, pas une valeur finale.**
hub.brussels, kbs-frb.be **et** ccf.brussels (COCOF) déclarent tous
`Crawl-delay: 10` dans leur robots.txt — bien au-dessus du défaut de 1,5 s. Le
délai appliqué est `max(config, robots.txt)`, soit **10 s** sur ces sources
(equal.brussels et culture.be ne déclarent rien → délai config, 3-5 s). Un run
complet sur les 109 fiches de hub.brussels prend donc ~20 minutes. C'est voulu.

**2. kbs-frb.be limite agressivement le débit (Cloudflare).**
Constaté pendant le développement : après ~15 requêtes rapprochées, le site a
cessé de répondre (timeouts) pendant ~10 minutes — pour le bot poli **comme**
pour un User-Agent de navigateur, donc ce n'est pas un filtrage sur l'UA mais un
throttling d'IP. L'accès est revenu seul après la pause. D'où le `delai_secondes:
10` explicite sur cette source. Si KBS remonte en échec dans le rapport, c'est
probablement ça : espace les runs.

Son robots.txt autorise le crawl générique (`User-agent: * → Allow: /`) mais
bloque nommément les crawlers d'entraînement IA (ClaudeBot, GPTBot, CCBot,
Google-Extended…) et déclare `Content-Signal: ai-train=no, use=reference`. Cet
agent est cohérent avec ce signal : il lit pour **référence personnelle**, ne
réentraîne rien et ne republie rien. **Ne contourne pas ces protections** (pas
d'UA de navigateur usurpé, pas de résolution de challenge) : si KBS te bloque
durablement, la voie légitime est de leur écrire ou de suivre leur newsletter.

---

## Comment ça marche

```
POST /scrape ──> job async (uuid) ──> renvoie {job_id} immédiatement
                      │
                      ├─ pour chaque source active (séquentiel, tolérant aux pannes)
                      │    1. crawl      découverte des URLs (sitemap | pagination | llm_links)
                      │    2. fetch      httpx, ou Playwright si rendu JS -> texte nettoyé (trafilatura)
                      │    3. extract    API Claude -> JSON contraint par schéma
                      │    4. validate   pydantic + règles métier (aucun LLM)
                      │    5. store      SQLite, dédup sur url_source normalisée
                      │
                      └─ rapport final : nouveaux / modifiés / échecs / tokens / coût estimé

GET /status/{job_id}  <── le frontend interroge toutes les 2 s
```

### Endpoints

| Méthode | Route | Rôle |
|---|---|---|
| `GET` | `/` | Frontend |
| `POST` | `/scrape` | Lance un job → `{job_id}`. **409** si un job tourne déjà. |
| `GET` | `/status/{job_id}` | Statut, progression, erreurs, rapport |
| `GET` | `/subsides?statut=&source=&tri=` | Liste JSON. `tri` : `deadline` (défaut, NULL en bas), `titre`, `source`, `recent` |
| `GET` | `/subsides/{id}` | Détail complet (inclut `raw_text`) |
| `GET` | `/sources` | Sources configurées |
| `GET` | `/stats` | Compteurs par statut |

### Statuts

`statut` porte le **cycle de vie** et `a_verifier` la **qualité** — les deux sont
séparés pour qu'une fiche modifiée puisse aussi être signalée douteuse.

| Valeur | Sens |
|---|---|
| `nouveau` | Jamais vue |
| `modifie` | Un de `titre`/`deadline`/`montant`/`criteres_eligibilite` a changé. Le détail est dans `modifications` (JSON `{champ: {avant, apres}}`). |
| `inchange` | Revue, rien n'a bougé ; seul `derniere_verification` est mis à jour |
| `echec_extraction` | Page illisible, JSON malformé, ou validation en échec dur. Le texte brut est conservé dans `raw_text`. |
| `a_verifier` (booléen) | Échec **doux** : deadline aberrante, lien de candidature invalide, « permanent » avec une deadline… La donnée reste exploitable, elle mérite un œil. |

---

## Détection de changement (hash source + `temperature=0`)

Le badge « modifié » doit signaler un **vrai** changement de subside, pas une
reformulation du LLM. Deux mécanismes s'y emploient :

1. **Hash SHA-256 du texte source.** Le texte nettoyé de chaque fiche est haché
   et stocké (`text_hash`). Au re-scrape, si le hash est **identique** au dernier
   run réussi, la page n'a pas bougé → la fiche passe `inchange` **sans appel
   LLM**. C'est ce qui rend un re-run quasi gratuit (le rapport compte les fiches
   ainsi économisées dans `ignorees_hash`). Les fiches en `echec_extraction` ne
   stockent pas de hash : elles sont retentées à chaque run.
2. **`temperature=0` sur l'extraction.** Quand le hash *a* changé (le texte de la
   page a bougé quelque part), on ré-extrait — mais en mode déterministe, pour
   que la même page produise la même sortie. La comparaison des champs se fait en
   plus sur leur forme **canonique** (casse et espaces normalisés, critères
   triés) : une reformulation cosmétique ne déclenche donc pas de faux « modifié ».
   `temperature=0` n'est envoyée qu'aux modèles qui l'acceptent (dont
   `claude-haiku-4-5`) ; sur la famille 4.6+/5, qui l'a retirée, elle est omise.

## Zone géographique

Chaque fiche porte deux champs de zone :

- **`zone_geographique`** — texte libre extrait par le LLM, **uniquement** si la
  page mentionne explicitement une zone (le prompt interdit de la déduire du nom
  de l'organisme ou de la langue). `null` sinon.
- **`zone_categorie`** — valeur fermée dérivée de la précédente par un mapping de
  mots-clés **en code pur** (`validator.py`, aucun LLM) :
  `bruxelles` · `fwb` · `flandre` · `wallonie` · `national` · `autre` · `inconnue`.
  L'ordre des tests compte : « Fédération Wallonie-Bruxelles » → `fwb` (et non
  bruxelles/wallonie). La liste flamande est pragmatique (grandes villes/régions),
  pas exhaustive.

Le frontend expose un filtre **Zone**. Il ne masque **rien** par défaut : une
ASBL bruxelloise est éligible aux zones `bruxelles`, `fwb` **et** `national` — le
filtre est un outil de tri, pas une exclusion.

### Région du profil (lot 6)

Le matching n'est plus « bruxellois pour tout le monde » : chaque profil porte
une **région de siège** (`bruxelles` | `wallonie`, ASBL francophones) qui pilote
ses zones de subsides éligibles via `matching.zones_eligibles()` :

| Région du profil | Zones de subsides acceptées |
|---|---|
| `bruxelles` | `bruxelles` + `fwb` + `national` + `inconnue` |
| `wallonie` | `wallonie` + `fwb` + `national` + `inconnue` |

`fwb` et `national` sont communs (ils couvrent les deux). Ce qui distingue :
la zone régionale propre — une ASBL bruxelloise ne voit pas les appels wallons,
et réciproquement. `flandre` reste exclue partout (hors cible francophone).

Rétrocompatibilité : le champ `region` a pour défaut `bruxelles`, et le
`profil_hash` **ne l'inclut que s'il diffère du défaut** — les profils créés
avant le lot 6 gardent donc un hash identique au bit près, sans invalidation de
leurs jugements en cache.

**Backfill.** Les fiches déjà en base avant l'ajout de ce champ ont
`zone_categorie='inconnue'`. Le hash les laisserait `inchange` (jamais
ré-extraites). Pour leur attribuer une zone, un script manuel force la
ré-extraction **uniquement** pour elles :

```bash
python scripts/backfill_zone.py --dry-run          # liste ce qui serait traité
python scripts/backfill_zone.py --source cocof     # une source, ou toutes
python scripts/backfill_zone.py --limite 20        # plafond de sécurité
```

Il respecte robots.txt et les délais, et **coûte des tokens** (un appel LLM par
fiche) — d'où le lancement manuel.

---

## Choix d'implémentation à connaître

**`url_source` n'est jamais demandée au LLM.** On connaît déjà l'URL qu'on vient
de charger ; la faire recracher par le modèle n'apporte rien et ouvre une porte à
l'hallucination. Elle est injectée par le validateur. Idem pour la stratégie
`llm_links` : toute URL renvoyée par le modèle qui n'était pas dans la liste
fournie est écartée (et loguée).

**Les retries sont ceux du SDK.** `anthropic.Anthropic(max_retries=2)` retente
déjà les 429/408/409/5xx et les erreurs réseau avec backoff exponentiel — soit
exactement la politique demandée. Pas de retry maison qui ferait doublon.

**`scraper/robots.py` existe à cause d'un bug d'`urllib.robotparser.**
robotparser n'exploite que le **premier** groupe qui matche, alors que la spec
robots.txt demande de **fusionner** les groupes d'un même user-agent. kbs-frb.be
déclare deux groupes `User-agent: *` : le premier `Allow: /`, le second portant
`Crawl-delay: 10` et les `Disallow: /admin/`… Mesuré : robotparser renvoyait
`crawl_delay=None` et considérait `/admin/` **autorisé**. Ce module fusionne les
groupes et applique la règle la plus spécifique. robotparser n'est plus qu'un
repli quand aucune règle n'a pu être scannée.

**Le nettoyage a un repli.** trafilatura d'abord ; s'il rend moins de 500
caractères, on retombe sur `<main>`/`<article>`/`<body>` via BeautifulSoup après
retrait des `nav/header/footer/script` et des bandeaux cookies. Et si le HTML
statique reste maigre, on retente en Playwright — c'est ce qui rattrape les pages
rendues en JS non déclarées.

**Normalisation d'URL renforcée pour TYPO3 (culture.be).** Les fiches culture.be
ont des URLs `?tx_ttnews[tt_news]=ID&tx_ttnews[backPid]=…&cHash=…` où seul
`tt_news` est l'identité de la fiche : `cHash` (hash d'intégrité) et `backPid`
(contexte de navigation) **changent d'un run/contexte à l'autre pour la même
fiche**. `normaliser_url` (db.py) retire `cHash`, `no_cache` et les sous-params
tableau volatils (`tx_*[backPid]`, `tx_*[pointer]`…) tout en gardant `tt_news` —
sinon la même fiche réapparaîtrait sous une URL différente à chaque run et
casserait la dédup (et l'idempotence du hash). Testé sur de vraies URLs culture.be.

**Limitation PDF (rappel).** COCOF et culture.be renvoient parfois les conditions
détaillées vers des documents `.docx`/`.pdf` téléchargeables. L'agent extrait
**uniquement le HTML de la page** — les documents joints ne sont pas téléchargés.
Une fiche peut donc avoir une description partielle : la fiche source fait foi.

---

## Ajouter une 4ᵉ source

Ajoute un dict dans `SOURCES` (`config/sources.py`) :

```python
{
    "id": "bruxelles_environnement",       # stable : ne pas renommer après un run
    "nom": "Bruxelles Environnement — Appels à projets",
    "start_urls": ["https://environnement.brussels/appels-a-projets"],
    "strategie": "sitemap",                # "sitemap" | "pagination" | "llm_links"
    "url_pattern": r"^https://environnement\.brussels/appel/[^/]+$",
    "max_pages": 10,
    "delai_secondes": 1.5,                 # plancher ; le robots.txt peut le relever
    "actif": True,
    "rendu_js": False,                     # True si le contenu n'est pas dans le HTML serveur
}
```

**Choisir la stratégie :**

- `sitemap` — le site expose un `sitemap.xml` et les fiches ont une URL
  reconnaissable. Le plus fiable et le moins cher : à privilégier. Les
  `sitemapindex` sont suivis automatiquement.
- `pagination` — pages de listing en `?page=0,1,2…`, fiches filtrables par regex.
- `llm_links` — **quand aucun regex ne peut trier les fiches** (cas KBS : appels
  et pages thématiques partagent le même motif `/fr/<slug>`, seul le texte de
  l'ancre les distingue). Coûte un appel LLM par page de listing.

**Bascule automatique** : si `sitemap` ou `pagination` ne trouve rien de
plausible, l'agent repasse tout seul en `llm_links` et le signale dans le rapport
(`strategie_utilisee: "sitemap->llm_links"`). Tu n'as donc pas besoin de deviner
juste du premier coup.

**Avant d'activer une source**, vérifie son robots.txt :

```bash
python -c "
from scraper.robots import pour_url
from scraper.fetcher import user_agent
r = pour_url('https://exemple.be/', user_agent())
print('delai :', r.delai_effectif(1.5))
print('autorisé :', r.autorise('https://exemple.be/la-page'))"
```

---

## Coûts

Tokens in/out sont logués à chaque appel et agrégés dans le rapport, avec une
estimation en USD (barème dans `TARIFS`, `jobs.py` — **à ajuster si tu changes de
modèle**).

Ordre de grandeur avec `claude-haiku-4-5` ($1/MTok in, $5/MTok out) : une fiche
≈ 3–4k tokens in + ~300 out, soit **~0,005 $/fiche**. Un run complet sur les 109
fiches de hub.brussels ≈ **0,50 $**. `MAX_FICHES_PAR_RUN` (défaut 150) plafonne
la casse ; les fiches au-delà du budget sont signalées dans le rapport, jamais
tronquées en silence.

Relancer un scrape est **idempotent** : la dédup se fait sur l'URL normalisée
(sans paramètres de tracking, sans slash final, sans fragment, sans cHash TYPO3).
Les fiches déjà connues repassent en `inchange`. Depuis le lot 2, grâce au **hash
source**, un re-run où rien n'a changé **ne repaie pas l'extraction** : coût quasi
nul (voir § Détection de changement). Seul le tri des liens `llm_links` reste
facturé (un petit appel par source à stratégie `llm_links`).

---

## Profils & matching (lot 3)

**Principe, identique au scraping : le code filtre et valide, le LLM juge.** Et
côté verdicts, jamais d'invention : ce que le profil ne permet pas de trancher va
dans « à vérifier », pas dans « éligible » ni « non éligible ».

### Le pipeline de matching

```
Profil ASBL ─▶ pré-filtre SQL (code pur) ─▶ cache ─▶ jugement LLM ─▶ dashboard
              zone/deadline/type_bénéf.    (hash)   1 appel/paire   streaming
```

1. **Pré-filtre** (`matching.pre_filtrer`, SQL pur) : ne garde que les subsides
   plausibles — deadline à venir ou permanente, zone dans `{bruxelles, fwb,
   national, inconnue}` (exclut flandre/wallonie/autre pour un profil bruxellois ;
   `inconnue` est **incluse**, le doute profite au subside), type de bénéficiaire
   `null` ou contenant `asbl`, hors fiches en échec. La règle de zone vit dans une
   fonction (`zones_eligibles`) : depuis le lot 6 elle **dépend de la région du
   profil** (bruxelles/wallonie), la zone régionale locale étant triée en tête.
2. **Cache** : clé logique `(profil_hash, subside_hash)`. Si un jugement existe
   pour ces deux hashes → réutilisé, **zéro appel API**. Le `profil_hash` ignore
   le nom (un renommage n'invalide pas le cache) ; le `subside_hash` est le hash
   source déjà utilisé par le scraping.
3. **Jugement** : un appel LLM par paire (profil + fiche), `temperature=0` sur les
   modèles qui l'acceptent, verdict contraint par schéma + validé (pydantic).
   Échec → matching `erreur` (affiché discrètement, re-tentable). Le prompt vit
   dans `prompts/matching.py` (fichier dédié, itéré souvent).
4. **Invalidation** : quand une fiche passe `modifie` au scraping (hash source
   changé), ses matchings sont supprimés → re-jugés à la prochaine consultation.

Verdicts : `probablement_eligible` (vert) · `eligible_sous_conditions` (orange) ·
`non_eligible` (replié en bas) · `erreur`. Chaque carte montre les
`criteres_a_verifier` directement — c'est le cœur du produit : **on pointe ce que
l'humain doit vérifier, on ne tranche pas à sa place.**

### Endpoints

| Méthode | Route | Rôle |
|---|---|---|
| `POST` | `/users` | Crée/retrouve un user (pseudo simple, pas de mot de passe) |
| `POST` `GET` `PUT` `DELETE` | `/profils[/{id}]` | CRUD profil. `PUT` recalcule le hash (invalide le cache) |
| `POST` | `/matching/{profil_id}` | Lance l'analyse (job async). **409** si déjà en cours pour ce profil |
| `GET` | `/matching/status/{job_id}` | Progression + résultats produits (streaming, poll 1-2 s) |
| `GET` | `/matchings/{profil_id}` | Résultats complets triés (verdict → pertinence → deadline) |
| `POST` | `/matching/recherche` | Recherche libre : profil éphémère + matching |
| `GET` | `/derniere-maj` | « Données à jour il y a X h » (survit au redémarrage) |

### Garde-fous coût

Tokens logués par jugement, plafond `MAX_JUGEMENTS_PAR_MATCHING` (défaut 40),
coût estimé dans le rapport de job. Parallélisme : 4 jugements concurrents. Un
re-matching sans changement = 100 % cache, 0 appel.

## Veille nocturne (cron)

`CRON_SCRAPE=true` active un scrape complet chaque nuit à **03h00 Europe/Brussels**
(APScheduler). Réutilise le job de scraping existant (idempotence + hash prouvés).
Si un scrape manuel tourne, le cron le saute (mécanique 409). Après le scrape :
purge des profils éphémères > 7 jours, log des matchings invalidés. Le rapport du
dernier run est persisté (`scrape_runs`) pour que « données à jour il y a X h »
survive au redémarrage. Pour tester en dev : `CRON_SCRAPE_CRON="*/5 * * * *"`.

## Données personnelles (RGPD)

Cette v1 collecte le **strict minimum** et ne récolte **aucune donnée de contact**.

- **Ce qui est stocké**, en local dans `data/subsides.db` (SQLite, sur ta machine) :
  un pseudo (`users.identifiant`, choisi par l'utilisateur, pas de mot de passe),
  les profils ASBL (nom, commune, secteurs, budget, description libre…) et les
  résultats de matching. Le pseudo et l'id de profil sont aussi gardés dans le
  `localStorage` du navigateur pour retrouver la session.
- **Où** : nulle part ailleurs. Le texte des profils est envoyé à l'API Claude au
  moment du jugement (comme tout prompt) ; aucune autre transmission.
- **Comment supprimer** : bouton « Supprimer mes données » sur `/app`, ou
  `DELETE /profils/{id}` — supprime le profil **et tout ce qui en dépend** :
  matchings, **candidatures, checklists, historique du copilote** (cascade SQL
  `ON DELETE CASCADE`, testée). Les profils de recherche libre (éphémères) sont
  purgés automatiquement après 7 jours.
- **Lot 7 — données plus sensibles, RGPD relevé d'un cran.** Les candidatures
  portent de la stratégie (montants demandés/obtenus, notes, brouillons soumis
  au copilote). Choix délibéré : **aucun téléversement de fichier** dans ce lot.
  La vérification de conformité et le copilote sont **déclaratifs** — l'utilisateur
  décrit son dossier, il n'envoie pas ses documents (comptes, listes de membres…).
  L'upload fera exploser la surface RGPD ; il attendra l'hébergement production et
  une vraie politique de rétention. La v1 déclarative suffit à valider l'usage.

---

## Accompagnement de la candidature — étage 3 (lot 7)

Découvrir et matcher, c'était les étages 1-2. Le lot 7 accompagne l'ASBL
**pendant** la demande, de « je candidate » à « obtenu ». Principe cardinal :
**Subsidia est un copilote, jamais l'auteur.** Il analyse, vérifie, structure,
rappelle — il ne rédige pas un dossier de façon autonome et **ne soumet jamais
rien**. Le dépôt passe par les plateformes officielles (IRISbox, SUBside…).

### Suivi de candidatures
Table `candidatures` (statut `a_etudier → dossier_en_cours → soumis → obtenu /
refuse / abandonne`). Créée depuis la fiche d'un subside (« Préparer ma
candidature », idempotent). Écran **Mes candidatures** : colonnes par statut
(déplacement par menu, pas de drag — plus robuste en mobile), stats (total
demandé / obtenu / **taux de succès à partir de 3 décisions seulement**).
La candidature **survit à l'expiration** du subside (valeur historique).

**Rappels** intégrés au dashboard et aux échéances : un `dossier_en_cours` à
moins de 14 j de l'échéance → alerte ; un `soumis` sans décision depuis 90 j →
relance douce « des nouvelles ? ».

**Récurrence** (code pur, aucun LLM) : un appel dont un « frère » d'une **autre
année** existe en base (même source, titre proche à l'année près) est signalé
« Cet appel semble récurrent (édition X) ». L'écart d'année est requis, sinon on
confondrait deux programmes voisins de la même édition. Détecté en réel sur
COCOF (« Prix Médiatine 2025/2026 », « La Culture a de la Classe 2025/2026 »…).

### Trois appels LLM (chacun son prompt dans `prompts/`)
1. **Checklist** (`prompts/checklist.py`) — extrait les pièces EXIGÉES par le
   règlement + annexes, **chacune avec sa citation verbatim**. Si le texte est
   muet → liste vide + message honnête (« le règlement ne détaille pas les
   pièces »), jamais d'invention. Cache par `(candidature, subside_hash)` ;
   régénération sur fiche modifiée **sans écraser les coches** de l'utilisateur.
2. **Conformité** (`prompts/conformite.py`) — croise règlement / profil /
   checklist / **état déclaré** du dossier (v1 déclarative, pas d'upload). Retour
   `{points_conformes, points_manquants, points_a_clarifier, avertissements}`,
   factuel et actionnable, avec le rappel systématique « seule l'administration
   décide de la recevabilité ». Cache par `(candidature, état déclaré, subside_hash)`.
3. **Copilote** (`prompts/copilote.py`) — **trois actions, et seulement trois** :
   *structurer* (un plan, pas de texte), *relire* (des annotations, pas une
   réécriture), *reformuler* (améliore la clarté d'UN paragraphe fourni, garde le
   fond et la voix). Jamais de génération complète, jamais d'invention de faits
   sur l'ASBL. Chaque sortie porte « Relecture d'aide — vous restez l'auteur ».

### Garde-fous
`MAX_APPELS_ETAGE3_PAR_JOUR` (défaut 50) plafonne les appels LLM par user et par
jour (429 poli au-delà). Chaque appel logue ses tokens et son coût. Toutes les
routes candidatures vérifient l'appartenance au user (**403 sinon**, testé).
Captures réelles du parcours complet dans `docs/screenshots/lot7-*.png`.

---

## Profondeur des sources (lot 5)

Le lot 5 ne cherche pas de nouvelles sources : il creuse les cinq existantes. Le
constat de départ était que 149 fiches découvertes n'étaient jamais extraites
(plafond à 20), que culture.be n'était lu qu'en première page, et que chaque
source tenait sur un point d'entrée unique.

### Run ciblé et backfill

```bash
# run standard (delta) : toutes les sources, budget réparti
curl -X POST localhost:8000/scrape

# une seule source — elle prend TOUT le budget
curl -X POST "localhost:8000/scrape?source=culture_be"

# backfill : pagination profonde + relecture des fiches connues (annexes PDF)
curl -X POST "localhost:8000/scrape?source=culture_be&backfill=true"
```

Le backfill est **toujours manuel**. La veille nocturne reste en mode delta sur
toutes les sources — c'est une garantie de coût, pas une préférence.

### Le budget plafonne les extractions, pas les visites

Deux règles, apprises d'un défaut mesuré :

1. **Les fiches sont ordonnées « jamais vue d'abord, puis la plus anciennement
   vérifiée »** — en delta comme en backfill.
2. **Une fiche court-circuitée par le hash ne consomme pas le budget** : elle ne
   coûte aucun token, donc elle n'a pas à voler sa place à une fiche jamais
   extraite. Un plafond de visites (`FACTEUR_VISITES = 3` × budget) borne quand
   même le temps passé à revisiter du déjà-connu.

> **Le défaut que ça corrige.** L'ordre d'un sitemap est stable. Sans tri, le
> cron reprenait chaque nuit les mêmes N premières fiches. Mesuré sur
> hub.brussels : sur 109 URLs découvertes, **40/40 des premières étaient en base
> et 0/69 des suivantes** — ces 69 fiches étaient inatteignables *à vie*, alors
> que combler ce trou était précisément l'objet du lot. Couvert par
> `test_run_suivant_atteint_les_fiches_que_le_precedent_na_pas_pu_traiter`, qui
> échoue si on retire le tri.

### culture.be : 230 pages, et le piège du cHash

Structure mesurée le 20/07/2026 : `tx_ttnews[pointer]` de 0 à 229, 7 fiches par
page, 2 sur la dernière — **~1605 fiches**.

Le piège : **le `pointer` sans `cHash` valide est silencieusement ignoré**. La
page répond 200 avec le contenu de la page 1. Fabriquer `?pointer=N` donne donc
230 fois la même page sans le moindre message d'erreur. D'où la stratégie
`pagination_typo3`, qui **suit les liens rendus par le site** (ils portent le
cHash) de proche en proche. Les liens exposés couvrent ±3 pages plus la dernière :
aucun saut possible, la marche est linéaire.

- cron nocturne : `max_pages_delta = 3` + **arrêt anticipé** dès qu'une page ne
  contient que des URLs déjà en base
- backfill manuel : `max_pages_backfill = None` (toutes), sans arrêt anticipé

Dédup TYPO3 vérifiée sur volume réel : 20 pages de listing → 140 liens → **140
clés normalisées distinctes, 140 ids `tt_news` distincts**. Après ingestion de
70 fiches en base : 70 URLs distinctes, 70 ids distincts, aucun `cHash` ni
`backPid` résiduel, normalisation idempotente. Aucun doublon.

**Coût du backfill complet, mesuré et non estimé.** Un backfill borné à 10 pages
(70 fiches, 63 nouvelles) a tourné en 806 s pour $0,327 :

| | mesuré sur 70 fiches | extrapolé à ~1605 fiches |
|---|---|---|
| cadence | 11,5 s/fiche | **~5,1 heures** |
| coût | $0,00467/fiche | **~$7,50 (≈ 6,9 €)** |

⚠️ `MAX_FICHES_PAR_RUN=200` **plafonne un run à 200 fiches** : le backfill complet
demande soit de monter ce plafond le temps du run, soit ~8 relances successives
(l'ordre « jamais vue d'abord, puis la plus ancienne » garantit que chaque
relance progresse).

### Double point d'entrée : ce que les sites offrent réellement

| Source | 2ᵉ point d'entrée | Constat |
|---|---|---|
| `cocof` | **flux RSS** `/feed/` | Existe. Expose les publications à leur parution, alors que le listing curé ne montre que les appels épinglés. Mélange actualités et appels → repasse par le même tri LLM. |
| `equal_brussels` | **index `wp-sitemap.xml`** | Pas de RSS (`/feed/` → 404). L'index est filtré par le même `url_pattern` : coût nul, zéro bruit, et filet si `open_call-sitemap.xml` est renommé (il ne contient que 11 URLs, dont 5 FR). |
| `kbs_frb` | **aucun** | `/sitemap.xml`, `/sitemap_index.xml`, `/fr/sitemap.xml` → 404, et aucune ligne `Sitemap:` dans le robots.txt. Reste sur un point d'entrée unique — c'est sa fragilité connue, l'alerte « source muette » la couvre. |
| `subsides_brussels` | — | Sitemap déjà exhaustif, non touché (consigne). |
| `culture_be` | — | La pagination profonde tient lieu de profondeur. |

L'apport **en propre** de chaque point d'entrée (ce qu'il a trouvé et qu'aucun
autre n'avait) est logué à chaque run et exposé par `GET /sources/health`. Un
filet à 0 URL en propre reste affiché : c'est l'information utile.

### Annexes PDF

Le code décide quels PDF valent la peine, le LLM ne voit que du texte.

- même organisme (domaine ou sous-domaine évident), ancre évocatrice
- **2 PDF max par fiche**, 10 Mo max, robots.txt et Crawl-delay respectés
- budget total **20 000 caractères** par fiche : on tronque le PDF, **jamais la
  page** (la page est la source primaire)
- **hash sur le texte extrait, pas sur les octets** — un PDF regénéré à chaque
  requête a des octets différents à contenu identique ; hasher les octets ferait
  passer la fiche pour « modifiée » à chaque run
- URLs retenues stockées dans la colonne `annexes_pdf`

Un **saut de page unique** est autorisé quand la fiche ne porte aucun PDF : sur
ccf.brussels le règlement n'est pas sur l'appel mais sur la page du dispositif
qu'il référence. Bornes apprises en réel, pas en théorie :

- le saut n'accepte que des ancres explicitement normatives — sans ça, un appel
  equal.brussels sautait sur `/charte-graphique/` et ramenait un « guide des
  couleurs »
- au-delà de 60 000 caractères, ce n'est plus un règlement mais un document de
  politique générale (equal.brussels lie des plans de 200 000 caractères) → écarté
- 2 pages de saut maximum, et `pdf_saut: False` sur culture.be : mesuré, le saut
  n'y rapporte rien et coûtait 2 chargements à 5 s par fiche, soit ~4 h 30 sur le
  backfill complet

### Santé des sources

`GET /sources/health` (admin) — même source de vérité que `/admin/sources-sante`
consommé par l'admin Next.js. La table `source_health` persiste le dernier
passage de **chaque** source, donc l'information survit au redémarrage et au
plantage d'un run suivant.

**Alerte source muette** : si une source active découvre 0 URL alors qu'elle en
trouvait à un passage précédent, un `log.error` explicite le signale et le
message remonte dans les erreurs du job. C'est le signal le plus utile pour
détecter qu'un site a changé de structure.

### Conformité aux signaux de contenu

Certains sites déclarent, dans leur `robots.txt`, une extension Cloudflare qui
n'a **aucun effet technique** mais exprime une volonté :

```
Content-Signal: search=yes, ai-train=no, use=reference
```

Le préambule de ces fichiers rattache ces déclarations à l'**article 4 de la
directive UE 2019/790** (réserve de droits sur la fouille de textes et données).
Nous les lisons donc, à chaque run, pour le groupe d'user-agent qui nous
concerne.

**Cas kbs-frb.be — source maintenue active, décision du 20/07/2026.**

| Signal | Notre position |
|---|---|
| `ai-train=no` | Respecté sans réserve : nous n'entraînons ni n'affinons aucun modèle. |
| `use=reference` | C'est exactement notre usage : chaque fiche renvoie vers l'URL officielle, qui fait foi. Nous ne republions pas le contenu à la place du site. |
| `search=yes` | Notre sortie est un lien + un résumé structuré, dans l'esprit de ce qui est accordé. |
| `Disallow` sur ClaudeBot, GPTBot, CCBot… | Ces règles visent des agents **nommés**. Notre UA relève du groupe `*` (`Allow: /`). Nous ne nous déguisons en aucun d'eux, et l'UA porte une adresse de contact réelle (`CONTACT_EMAIL`). |

**Le point ouvert, assumé** : le signal `ai-input` — « donner le contenu à un
modèle », ce que fait notre extraction — n'est **pas déclaré**. Selon la règle du
préambule, un signal absent « n'accorde ni ne restreint ». Nous sommes dans un
silence, pas dans une autorisation.

**Le garde-fou.** `robots.signaux_defavorables()` relit ces signaux à chaque run.
Si `ai-input` ou `search` passe à `no` :

- un `log.error` explicite le signale ;
- l'alerte remonte dans le rapport de run et dans `GET /sources/health`.

Le code **n'arrête pas la source tout seul** : passer une source en
`actif=False` reste une décision humaine. `ai-train` n'est volontairement pas
surveillé comme bloquant — un « no » sur ce signal ne vise pas notre usage.

### Remapping des zones stockées

```bash
python scripts/remap_zones.py               # aperçu
python scripts/remap_zones.py --appliquer   # écrit
```

Code pur, zéro LLM, idempotent. Sert quand le mapping mot-clé s'enrichit : les
fiches déjà en base gardent sinon l'ancienne catégorie.

> Cas réel : le fonds « Een hart voor Scheldevallei » était stocké avec
> `zone_geographique = « vallée de l'Escaut »` — l'extraction avait **traduit** le
> nom néerlandais. Le mapping ne connaissait que « scheldevallei », la fiche
> tombait en `autre`. Les exonymes français ont été ajoutés (en expressions à
> plusieurs mots : « escaut » seul attraperait Tournai, en Wallonie).

## Limites connues

- **Le matching dit « probablement », jamais « oui ».** Le verdict est une aide au
  tri, pas une décision d'éligibilité. Les `criteres_a_verifier` sont là pour ça :
  c'est à l'humain de trancher sur la fiche source.
- **Next.js 16, pas 15.** `create-next-app@latest` a installé Next 16 (App Router,
  Turbopack, React 19, Tailwind v4) — le `middleware.ts` y est renommé `proxy.ts`,
  et Clerk 7 n'exporte plus `<SignedIn>`/`<SignedOut>` (remplacés par les hooks
  `useAuth()`/`useUser()`, utilisés ici). Rien de bloquant, mais c'est plus récent
  que la spec.
- **Le dashboard reste en polling** (toutes les ~1,3 s), pas en SSE. Le streaming
  animé des cartes tient bien à ce rythme sur ~20-40 candidats. Si un jour le
  nombre de candidats explose ou qu'on veut un flux plus fin, le backend
  gagnerait un endpoint SSE — noté pour plus tard, **non implémenté** (le polling
  actuel suffit et reste simple).
- **La règle de zone est pilotée par la région du profil (lot 6),** plus « brux­
  elloise pour tout le monde ». Un profil `bruxelles` voit bruxelles/fwb/national/
  inconnue ; un profil `wallonie` voit wallonie/fwb/national/inconnue. Cf. § Zone
  géographique › Région du profil. La **Flandre** reste hors cible (francophone).
- **La vérification humaine des deadlines reste indispensable avant de
  candidater.** Le prompt interdit explicitement d'inventer une date et de
  confondre date de publication et date limite, et le validateur signale les
  dates hors bornes (< 2020 ou > 3 ans). Ça réduit les erreurs, ça ne les
  supprime pas.
- **Les sites changent.** Si hub.brussels refond ses URLs, la regex `url_pattern`
  ne matchera plus : la bascule `llm_links` prend le relais, mais surveille le
  champ `strategie_utilisee` du rapport — il te dit ce qui s'est réellement passé.
- **kbs-frb.be peut échouer par intermittence** (throttling Cloudflare, cf.
  ci-dessus). Le job continue et le signale ; il ne plante pas.
- **hub.brussels est orienté entreprises**, pas ASBL — d'où l'ajout des sources
  ASBL-natives au lot 2 (COCOF, equal.brussels, culture.be). Aucun tri automatique
  ASBL/entreprise n'est fait (le LLM le rendrait sans base fiable) ; utilise les
  champs `public_cible` et `zone_categorie` pour filtrer toi-même.
- **Pas de filtre géographique automatique dur.** KBS et culture.be sont des
  sources **nationales/FWB** : elles contiennent des appels flamands ou wallons
  hors Bruxelles. La `zone_categorie` te permet de les repérer et de filtrer, mais
  rien n'est masqué par défaut (une ASBL bruxelloise reste éligible aux zones
  `bruxelles`, `fwb` et `national`).
- **PDF : texte natif seulement, pas d'OCR** (lot 5). Les règlements avec une
  couche texte sont lus et enrichissent la fiche ; un PDF **scanné** est logué et
  sauté. Cas réel mesuré : le « Règlement subvention » des clubs sportifs COCOF
  est un scan (259 caractères sur 5 pages) — il reste hors de portée. Les .docx
  ne sont toujours pas lus.
- **Checklist (lot 7) : dépend du texte disponible.** Elle est excellente quand
  la fiche a son texte complet page+PDF (`raw_text` présent, cas des fiches en
  `a_verifier`) — citations verbatim exactes. Pour une fiche « propre » sans
  `raw_text`, elle travaille sur `description` + critères extraits, plus pauvres,
  et affiche souvent l'honnête « le règlement ne détaille pas les pièces ».
  Amélioration v2 : re-télécharger le texte complet au moment de la génération.
- **Les sites changent.** Si une source refond ses URLs, la bascule `llm_links`
  prend le relais ; surveille `strategie_utilisee` dans le rapport.
- **culture.be** : pas de WAF constaté au 18/07/2026, mais l'écosystème FWB en a
  un. S'il s'active, la source échoue proprement (voir § État réel des sources).
- **kbs-frb.be peut échouer par intermittence** (throttling Cloudflare). Le job
  continue et le signale ; il ne plante pas.
- **La vérification humaine des deadlines reste indispensable.**
- Un seul job à la fois (`409` sinon), état en mémoire : les jobs sont perdus au
  redémarrage. Les subsides, eux, sont en base.

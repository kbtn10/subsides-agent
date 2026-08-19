"""Découverte des URLs de fiches, par source.

Trois stratégies, avec bascule automatique sur llm_links si la stratégie
déclarée ne trouve rien de plausible (spec). La stratégie réellement utilisée
est loguée et remontée dans le rapport du job.
"""

import asyncio
import logging
import re
import time
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from db import normaliser_url
from scraper import extractor, robots
from scraper.fetcher import charger_html, user_agent

log = logging.getLogger(__name__)

# Ancres qui ne mènent jamais à une fiche : filtrées avant d'appeler le LLM,
# pour ne pas lui faire payer 130 liens de navigation.
ANCRES_BRUIT = re.compile(
    r"^(accueil|home|contact|newsletter|s'?inscrire|connexion|login|fr|nl|en|de|"
    r"menu|retour|suivant|précédent|next|previous|\d+|cookies?|mentions? légales?|"
    r"privacy|politique de confidentialité|plan du site|sitemap|rechercher|search|"
    r"partager|imprimer|facebook|instagram|linkedin|youtube|twitter|x)$",
    re.IGNORECASE,
)
EXTENSIONS_BRUIT = re.compile(r"\.(pdf|jpe?g|png|gif|svg|zip|docx?|xlsx?|pptx?|mp4|css|js)$", re.I)


class ResultatCrawl:
    def __init__(self, urls, strategie_utilisee, erreurs=None, tokens_in=0, tokens_out=0,
                 apports=None, pages_lues=0, arret_anticipe=False):
        self.urls = urls
        self.strategie_utilisee = strategie_utilisee
        self.erreurs = erreurs or []
        self.tokens_in = tokens_in
        self.tokens_out = tokens_out
        # apports : [{"nom", "strategie", "trouvees", "en_propre"}] — combien
        # d'URLs chaque point d'entrée a apportées QUE LUI n'avait. C'est la
        # mesure de l'utilité du filet (lot 5).
        self.apports = apports or []
        self.pages_lues = pages_lues
        self.arret_anticipe = arret_anticipe


async def _pause(source, url):
    """Délai poli. Le Crawl-delay du robots.txt l'emporte s'il est plus lent."""
    delai = robots.delai_effectif(url, user_agent(), source.get("delai_secondes", 1.5))
    await asyncio.sleep(delai)


def _extraire_liens(html: str, url_base: str) -> list[tuple[str, str]]:
    """(url_absolue, texte_ancre)[] — même domaine, dédupliqués, bruit évident retiré."""
    soup = BeautifulSoup(html, "lxml")
    host_base = urlsplit(url_base).netloc
    vus, liens = set(), []

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        absolue = urljoin(url_base, href)
        parts = urlsplit(absolue)
        if parts.scheme not in ("http", "https") or parts.netloc != host_base:
            continue
        if EXTENSIONS_BRUIT.search(parts.path):
            continue

        cle = normaliser_url(absolue)
        if cle in vus:
            continue
        vus.add(cle)

        texte = a.get_text(strip=True) or a.get("title", "") or a.get("aria-label", "")
        if ANCRES_BRUIT.match(texte.strip()):
            continue
        liens.append((absolue, texte))

    return liens


async def _crawl_sitemap(source) -> ResultatCrawl:
    """Suit un sitemap.xml (y compris les sitemapindex) et filtre sur url_pattern."""
    pattern = re.compile(source["url_pattern"]) if source.get("url_pattern") else None
    a_visiter = list(source["start_urls"])
    vus_sitemaps, urls, erreurs = set(), [], []

    async with httpx.AsyncClient(
        headers={"User-Agent": user_agent()}, timeout=30, follow_redirects=True
    ) as client:
        while a_visiter and len(vus_sitemaps) < source.get("max_pages", 10):
            sm = a_visiter.pop(0)
            if sm in vus_sitemaps:
                continue
            vus_sitemaps.add(sm)

            if not robots.autorise(sm, user_agent()):
                log.warning("robots.txt interdit %s — ignoré", sm)
                erreurs.append(f"robots.txt interdit {sm}")
                continue

            try:
                r = await client.get(sm)
                r.raise_for_status()
            except httpx.HTTPError as e:
                log.warning("Sitemap illisible %s : %s", sm, e)
                erreurs.append(f"sitemap {sm}: {e}")
                continue

            soup = BeautifulSoup(r.text, "xml")

            # sitemapindex -> on empile les sous-sitemaps
            sous = [loc.get_text(strip=True) for loc in soup.select("sitemap > loc")]
            if sous:
                a_visiter.extend(s for s in sous if s not in vus_sitemaps)

            for loc in soup.select("url > loc"):
                u = loc.get_text(strip=True)
                if not pattern or pattern.match(u):
                    urls.append(u)

            await _pause(source, sm)

    return ResultatCrawl(urls, "sitemap", erreurs)


async def _crawl_pagination(source) -> ResultatCrawl:
    """Parcourt les pages de listing et garde les liens qui matchent url_pattern."""
    pattern = re.compile(source["url_pattern"]) if source.get("url_pattern") else None
    urls, erreurs = [], []

    for start in source["start_urls"]:
        for page in range(source.get("max_pages", 5)):
            url = start if page == 0 else f"{start}{'&' if '?' in start else '?'}page={page}"
            if not robots.autorise(url, user_agent()):
                erreurs.append(f"robots.txt interdit {url}")
                break

            html = await charger_html(url, rendu_js=source.get("rendu_js", False))
            if not html:
                erreurs.append(f"page illisible: {url}")
                break

            trouves = [
                u for u, _ in _extraire_liens(html, url)
                if not pattern or pattern.match(u)
            ]
            if not trouves:  # plus rien à paginer
                break
            urls.extend(trouves)
            await _pause(source, url)

    return ResultatCrawl(urls, "pagination", erreurs)


async def _crawl_llm_links(source) -> ResultatCrawl:
    """Envoie les liens (URL + ancre) au LLM et lui demande lesquels sont des fiches."""
    urls, erreurs, t_in, t_out = [], [], 0, 0

    for start in source["start_urls"]:
        if not robots.autorise(start, user_agent()):
            erreurs.append(f"robots.txt interdit {start}")
            continue

        html = await charger_html(start, rendu_js=source.get("rendu_js", False))
        if not html:
            erreurs.append(f"page illisible: {start}")
            continue

        liens = _extraire_liens(html, start)
        if not liens:
            erreurs.append(f"aucun lien exploitable sur {start}")
            continue

        log.info("llm_links : %d liens candidats sur %s", len(liens), start)
        res = await asyncio.to_thread(extractor.identifier_liens_fiches, liens, start)
        t_in += res.tokens_in
        t_out += res.tokens_out
        if not res.ok:
            erreurs.append(f"tri LLM échoué sur {start}: {res.erreur}")
            continue

        urls.extend(res.data["urls"])
        await _pause(source, start)

    return ResultatCrawl(urls, "llm_links", erreurs, t_in, t_out)


async def _crawl_rss(source) -> ResultatCrawl:
    """Flux RSS/Atom -> (lien, titre), puis MÊME tri LLM que llm_links.

    Un flux WordPress mélange actualités et appels : sans tri on créerait des
    fiches « communiqué canicule ». On réutilise donc le trieur de liens, qui
    reçoit (url, titre d'item) exactement comme il recevrait (url, ancre).
    """
    urls, erreurs, t_in, t_out = [], [], 0, 0

    async with httpx.AsyncClient(
        headers={"User-Agent": user_agent()}, timeout=30, follow_redirects=True
    ) as client:
        for start in source["start_urls"]:
            if not robots.autorise(start, user_agent()):
                erreurs.append(f"robots.txt interdit {start}")
                continue
            try:
                r = await client.get(start)
                r.raise_for_status()
            except httpx.HTTPError as e:
                erreurs.append(f"flux illisible {start}: {e}")
                continue

            soup = BeautifulSoup(r.text, "xml")
            items = []
            for it in soup.find_all(["item", "entry"]):
                lien = it.find("link")
                url = (lien.get_text(strip=True) if lien and lien.get_text(strip=True)
                       else (lien.get("href") if lien else None))
                titre = it.find("title")
                if url:
                    items.append((url, titre.get_text(strip=True) if titre else ""))

            if not items:
                erreurs.append(f"aucun item dans le flux {start}")
                continue

            log.info("rss : %d item(s) dans %s", len(items), start)
            res = await asyncio.to_thread(extractor.identifier_liens_fiches, items, start)
            t_in += res.tokens_in
            t_out += res.tokens_out
            if not res.ok:
                erreurs.append(f"tri LLM échoué sur {start}: {res.erreur}")
                continue
            urls.extend(res.data["urls"])
            await _pause(source, start)

    return ResultatCrawl(urls, "rss", erreurs, t_in, t_out)


# Pagination TYPO3 : le pointer n'est pris en compte QUE s'il est accompagné du
# cHash calculé par le site. On ne peut donc pas fabriquer les URLs de page —
# on suit les liens rendus, de proche en proche.
_POINTER = re.compile(r"pointer(?:%5D|\])=(\d+)")


def _liens_pagination(html: str, url_base: str) -> dict[int, str]:
    """{numéro_de_page: url} d'après les liens de pagination de la page."""
    soup = BeautifulSoup(html, "lxml")
    out = {}
    for a in soup.find_all("a", href=True):
        m = _POINTER.search(a["href"])
        if m:
            out[int(m.group(1))] = urljoin(url_base, a["href"])
    return out


async def _crawl_pagination_typo3(source, *, backfill: bool = False,
                                  urls_connues: set[str] | None = None) -> ResultatCrawl:
    """Marche séquentielle dans un listing TYPO3 paginé.

    - delta (défaut)  : `max_pages_delta` pages, avec ARRÊT ANTICIPÉ dès qu'une
      page entière ne contient que des URLs déjà en base (les suivantes sont
      encore plus anciennes).
    - backfill        : `max_pages_backfill` pages (None = toutes), sans arrêt
      anticipé — on veut justement les archives déjà connues ou non.
    """
    pattern = re.compile(source["url_pattern"]) if source.get("url_pattern") else None
    connues = urls_connues if urls_connues is not None else set()

    plafond = (source.get("max_pages_backfill") if backfill else source.get("max_pages_delta"))
    if plafond is None:
        plafond = source.get("max_pages", 230) if backfill else 3

    urls, erreurs = [], []
    pages_lues, arret_anticipe = 0, False

    for start in source["start_urls"]:
        url_courante, page_num, vues = start, 0, set()

        while url_courante and pages_lues < plafond:
            if url_courante in vues:      # le site nous renvoie en boucle
                break
            vues.add(url_courante)

            if not robots.autorise(url_courante, user_agent()):
                erreurs.append(f"robots.txt interdit {url_courante}")
                break

            html = await charger_html(url_courante, rendu_js=source.get("rendu_js", False))
            if not html:
                erreurs.append(f"page de listing illisible: {url_courante}")
                break

            pages_lues += 1
            trouvees = [u for u, _ in _extraire_liens(html, url_courante)
                        if not pattern or pattern.search(u)]

            if not trouvees:
                log.info("[%s] page %d sans fiche — fin de pagination", source["id"], page_num)
                break

            urls.extend(trouvees)

            # Arrêt anticipé (delta seulement) : page 100 % déjà connue.
            if not backfill and connues:
                nouvelles = [u for u in trouvees if normaliser_url(u) not in connues]
                if not nouvelles:
                    log.info("[%s] page %d ne contient que du déjà-vu — arrêt anticipé "
                             "(%d page(s) lue(s))", source["id"], page_num, pages_lues)
                    arret_anticipe = True
                    break

            liens_pages = _liens_pagination(html, url_courante)
            suivante = liens_pages.get(page_num + 1)
            if not suivante:
                log.info("[%s] plus de lien vers la page %d — fin de pagination",
                         source["id"], page_num + 1)
                break
            url_courante, page_num = suivante, page_num + 1
            await _pause(source, url_courante)

    log.info("[%s] pagination TYPO3 : %d page(s), %d lien(s) bruts%s",
             source["id"], pages_lues, len(urls),
             " (arrêt anticipé)" if arret_anticipe else "")
    return ResultatCrawl(urls, "pagination_typo3", erreurs,
                         pages_lues=pages_lues, arret_anticipe=arret_anticipe)


STRATEGIES = {
    "sitemap": _crawl_sitemap,
    "pagination": _crawl_pagination,
    "pagination_typo3": _crawl_pagination_typo3,
    "rss": _crawl_rss,
    "llm_links": _crawl_llm_links,
}


def _points_dentree(source) -> list[dict]:
    """Liste des configs de découverte à exécuter pour cette source.

    Sans clé `decouverte`, une source garde exactement son comportement d'avant :
    une seule stratégie, celle déclarée. Avec, chaque entrée hérite de la config
    de la source et n'en surcharge que ce qu'elle précise.
    """
    entrees = source.get("decouverte")
    if not entrees:
        return [{**source, "_nom_entree": source.get("strategie", "llm_links")}]
    return [
        {**source, **e, "_nom_entree": e.get("nom") or e.get("strategie", "?")}
        for e in entrees
    ]


async def _executer_entree(entree, *, backfill, urls_connues) -> ResultatCrawl:
    strategie = entree.get("strategie", "llm_links")
    fn = STRATEGIES.get(strategie)
    if fn is None:
        return ResultatCrawl([], strategie, [f"stratégie inconnue: {strategie}"])
    if strategie == "pagination_typo3":
        return await fn(entree, backfill=backfill, urls_connues=urls_connues)
    return await fn(entree)


async def decouvrir(source, *, backfill: bool = False,
                    urls_connues: set[str] | None = None) -> ResultatCrawl:
    """Découvre les fiches d'une source.

    Exécute TOUS ses points d'entrée, fusionne et déduplique les URLs (clé =
    URL normalisée), et mesure l'apport PROPRE de chacun. Garde la bascule
    automatique sur llm_links quand une source à point d'entrée unique est
    bredouille.
    """
    entrees = _points_dentree(source)
    vus, uniques, apports = set(), [], []
    erreurs, t_in, t_out = [], 0, 0
    strategies_ok, pages_lues, arret_anticipe = [], 0, False

    for entree in entrees:
        debut = time.monotonic()
        try:
            res = await _executer_entree(entree, backfill=backfill, urls_connues=urls_connues)
        except Exception as e:
            log.exception("[%s] point d'entrée '%s' KO", source["id"], entree["_nom_entree"])
            erreurs.append(f"{entree['_nom_entree']}: {type(e).__name__}: {e}")
            apports.append({"nom": entree["_nom_entree"],
                            "strategie": entree.get("strategie"),
                            "trouvees": 0, "en_propre": 0, "erreur": str(e)})
            continue

        erreurs.extend(res.erreurs)
        t_in += res.tokens_in
        t_out += res.tokens_out
        pages_lues += res.pages_lues
        arret_anticipe = arret_anticipe or res.arret_anticipe

        # Apport propre : ce que CE point d'entrée a apporté et qu'aucun
        # précédent n'avait. C'est la seule mesure honnête de l'utilité du filet.
        en_propre = 0
        for u in res.urls:
            cle = normaliser_url(u)
            if not cle or cle in vus:
                continue
            vus.add(cle)
            uniques.append(u)
            en_propre += 1

        apports.append({"nom": entree["_nom_entree"], "strategie": res.strategie_utilisee,
                        "trouvees": len(res.urls), "en_propre": en_propre})
        strategies_ok.append(res.strategie_utilisee)
        log.info("[%s] point d'entrée '%s' (%s) : %d URL(s) dont %d en propre, %.1fs",
                 source["id"], entree["_nom_entree"], res.strategie_utilisee,
                 len(res.urls), en_propre, time.monotonic() - debut)

    # Bascule automatique : aucune URL sur une source mono-stratégie non-LLM.
    declaree = source.get("strategie", "llm_links")
    if not uniques and len(entrees) == 1 and declaree != "llm_links":
        log.warning("[%s] stratégie '%s' bredouille — bascule automatique sur llm_links",
                    source["id"], declaree)
        secours = await _crawl_llm_links(source)
        secours.strategie_utilisee = f"{declaree}->llm_links"
        secours.erreurs = erreurs + secours.erreurs
        secours.apports = [{"nom": f"{declaree}->llm_links",
                            "strategie": "llm_links",
                            "trouvees": len(secours.urls), "en_propre": len(secours.urls)}]
        vus2, uniq2 = set(), []
        for u in secours.urls:
            cle = normaliser_url(u)
            if cle and cle not in vus2:
                vus2.add(cle)
                uniq2.append(u)
        secours.urls = uniq2
        return secours

    return ResultatCrawl(uniques, "+".join(strategies_ok) or declaree, erreurs,
                         t_in, t_out, apports=apports, pages_lues=pages_lues,
                         arret_anticipe=arret_anticipe)

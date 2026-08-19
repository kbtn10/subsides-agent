"""Chargement d'une page -> texte principal nettoyé.

Stratégie : httpx d'abord (rapide, léger). On ne sort Playwright que si la page
est manifestement rendue en JS — soit parce que la source le déclare
(rendu_js=True), soit parce que le HTML statique donne un texte ridiculement
court. Sur hub.brussels le HTML statique suffit ; sur kbs-frb.be (recherche
Swiftype) il ne contient aucun résultat, d'où le fallback.
"""

import asyncio
import logging
import os

import httpx
import trafilatura
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

MAX_CARACTERES = 12_000
# En dessous, on considère que le HTML statique n'a rien donné d'exploitable
# et qu'il vaut la peine de payer un rendu JS.
SEUIL_TEXTE_MAIGRE = 500

BALISES_A_JETER = [
    "script", "style", "noscript", "nav", "header", "footer", "aside",
    "form", "iframe", "svg", "button",
]

# Bandeaux cookies / menus : classes et ids courants (Drupal, Cookiebot, OneTrust...).
SELECTEURS_BRUIT = [
    "[class*='cookie']", "[id*='cookie']", "[class*='consent']", "[id*='consent']",
    "[class*='banner']", "[class*='breadcrumb']", "[class*='menu']",
    "[class*='navigation']", "[class*='skip-link']", "[role='navigation']",
    "[role='banner']", "[role='contentinfo']", "[aria-hidden='true']",
]

_playwright = None
_browser = None
_lock = asyncio.Lock()


def user_agent() -> str:
    contact = os.getenv("CONTACT_EMAIL", "contact-non-configure")
    return f"SubsidesAgentBot/0.1 (projet personnel; contact: {contact})"


async def _get_browser():
    """Un seul Chromium pour tout le process, démarré à la première demande."""
    global _playwright, _browser
    async with _lock:
        if _browser is None or not _browser.is_connected():
            from playwright.async_api import async_playwright

            _playwright = await async_playwright().start()
            _browser = await _playwright.chromium.launch(headless=True)
            log.info("Chromium démarré")
    return _browser


async def fermer_browser():
    global _playwright, _browser
    async with _lock:
        if _browser is not None:
            try:
                await _browser.close()
            except Exception:
                pass
            _browser = None
        if _playwright is not None:
            try:
                await _playwright.stop()
            except Exception:
                pass
            _playwright = None
    log.info("Chromium arrêté")


async def charger_html(url: str, *, rendu_js: bool = False, timeout: float = 30) -> str | None:
    """HTML brut de la page. None si inatteignable."""
    if not rendu_js:
        try:
            async with httpx.AsyncClient(
                headers={"User-Agent": user_agent(), "Accept-Language": "fr-BE,fr;q=0.9"},
                timeout=timeout,
                follow_redirects=True,
            ) as client:
                r = await client.get(url)
                r.raise_for_status()
                if "html" not in r.headers.get("content-type", "").lower():
                    log.warning("%s n'est pas du HTML (%s)", url, r.headers.get("content-type"))
                    return None
                return r.text
        except httpx.HTTPError as e:
            log.warning("httpx a échoué sur %s (%s) — tentative Playwright", url, e)

    try:
        browser = await _get_browser()
        page = await browser.new_page(
            user_agent=user_agent(),
            extra_http_headers={"Accept-Language": "fr-BE,fr;q=0.9"},
        )
        try:
            # "networkidle" ne se déclenche jamais sur les pages à analytics ou
            # polling : on attendait 30s pour rien. "domcontentloaded" + un court
            # délai de stabilisation suffit à laisser le JS peupler le DOM.
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
            try:
                await page.wait_for_load_state("networkidle", timeout=5_000)
            except Exception:
                pass  # tant pis, le DOM est déjà là
            await page.wait_for_timeout(1_500)
            return await page.content()
        finally:
            await page.close()
    except Exception as e:
        log.error("Playwright a échoué sur %s : %s", url, e)
        return None


def nettoyer_html(html: str, url: str = None) -> str:
    """HTML -> texte principal. trafilatura d'abord, repli sur <main>/<body>."""
    if not html:
        return ""

    texte = trafilatura.extract(
        html,
        url=url,
        include_comments=False,
        include_tables=True,
        favor_precision=False,
        no_fallback=False,
    )
    if texte and len(texte.strip()) >= SEUIL_TEXTE_MAIGRE:
        return _tronquer(texte.strip())

    # Repli : trafilatura rend parfois vide sur les pages très "applicatives".
    soup = BeautifulSoup(html, "lxml")
    for balise in soup(BALISES_A_JETER):
        balise.decompose()
    for sel in SELECTEURS_BRUIT:
        for el in soup.select(sel):
            el.decompose()

    racine = soup.find("main") or soup.find("article") or soup.body or soup
    brut = racine.get_text(separator="\n", strip=True)
    lignes = [l.strip() for l in brut.splitlines() if l.strip()]
    repli = "\n".join(lignes)

    return _tronquer(repli if len(repli) > len(texte or "") else (texte or "").strip())


def _tronquer(texte: str) -> str:
    if len(texte) <= MAX_CARACTERES:
        return texte
    coupe = texte[:MAX_CARACTERES]
    # Coupe sur la dernière fin de phrase/ligne pour ne pas laisser un mot en deux.
    for sep in ("\n", ". "):
        i = coupe.rfind(sep)
        if i > MAX_CARACTERES * 0.8:
            return coupe[: i + len(sep)].strip()
    return coupe.strip()


async def recuperer_texte(url: str, *, rendu_js: bool = False) -> tuple[str | None, str | None]:
    """(texte_nettoye, html_brut). texte est None si la page n'a rien donné."""
    html = await charger_html(url, rendu_js=rendu_js)
    if html is None:
        return None, None

    texte = nettoyer_html(html, url)

    # Le HTML statique n'a rien donné : la page est probablement rendue en JS.
    if not rendu_js and len(texte) < SEUIL_TEXTE_MAIGRE:
        log.info("Texte maigre (%d car.) sur %s — nouvelle tentative avec Playwright",
                 len(texte), url)
        html_js = await charger_html(url, rendu_js=True)
        if html_js:
            texte_js = nettoyer_html(html_js, url)
            if len(texte_js) > len(texte):
                return texte_js, html_js

    return (texte or None), html

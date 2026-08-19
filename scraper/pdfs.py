"""Annexes PDF : les conditions détaillées vivent souvent dans un règlement.

Principe : le code décide QUELS PDF valent la peine (domaine, ancre, taille), le
LLM ne voit que du texte. Aucune OCR dans ce lot — un PDF scanné est logué et
sauté, jamais deviné.

Contraintes tenues :
    - robots.txt et Crawl-delay respectés pour les PDF comme pour les pages
    - 2 PDF maximum par fiche, 10 Mo maximum par PDF
    - hash sur le TEXTE extrait, pas sur les octets : un PDF regénéré à chaque
      requête (date de production dans les métadonnées) ne doit pas faire passer
      la fiche pour « modifiée » à chaque run
"""

import asyncio
import io
import logging
import re
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from scraper import robots
from scraper.fetcher import user_agent

log = logging.getLogger(__name__)

MAX_PDF_PAR_FICHE = 2
# UNE page intermédiaire, pas deux. Mesuré sur un run réel : sur un site à
# Crawl-delay 10 s (hub.brussels, ccf.brussels, kbs-frb.be), chaque page de saut
# coûte 10 s de politesse — la cadence observée était de 29,4 s par fiche, dont
# 20 s de saut. Le cas qui justifie le saut (ccf.brussels : l'appel renvoie vers
# la page du dispositif) est servi par le PREMIER candidat.
MAX_PAGES_SAUT = 1
MAX_OCTETS = 10 * 1024 * 1024          # 10 Mo
TIMEOUT = 45
# Budget de texte total envoyé au LLM pour une fiche. On tronque les PDF,
# JAMAIS la page : la page est la source primaire, l'annexe est un complément.
BUDGET_CARACTERES = 20_000
MIN_CARACTERES_UTILES = 400            # en dessous : PDF probablement scanné

_EST_PDF = re.compile(r"\.pdf($|[?#])", re.I)

# Ancres qui annoncent un document normatif. Sert à CLASSER les candidats,
# pas à les exclure : un PDF sans ancre parlante reste éligible en second choix.
_ANCRE_FORTE = re.compile(
    r"r[eè]glement|conditions?|appel\s|cahier\s+des\s+charges|circulaire|"
    r"formulaire|modalit[eé]s|crit[eè]res|vade[- ]?mecum|arr[eê]t[eé]|d[eé]cret|"
    r"guide|notice|dossier\s+de\s+candidature|mandat|proc[ée]dure",
    re.I,
)
# Sous-ensemble EXIGÉ pour un PDF trouvé après un saut de page : à distance de
# la fiche, le contexte ne garantit plus rien. Vérifié en réel : sans ça, le
# saut depuis un appel equal.brussels atterrissait sur /charte-graphique/ et
# ramenait un « guide des couleurs ». « guide » et « notice » sont donc absents
# d'ici, trop passe-partout.
_ANCRE_FORTE_SAUT = re.compile(
    r"r[eè]glement|conditions?|cahier\s+des\s+charges|circulaire|formulaire|"
    r"modalit[eé]s|crit[eè]res|arr[eê]t[eé]|d[eé]cret|appel\s+[àa]\s|"
    r"dossier\s+de\s+candidature|mandat|proc[ée]dure",
    re.I,
)
_ANCRE_EXCLUE = re.compile(
    r"rapport\s+d.activit|bilan|comptes?\s+annuels?|organigramme|plan\s+du\s+site|"
    r"politique\s+de\s+confidentialit|mentions?\s+l[eé]gales?|charte\s+graphique|"
    r"logo|newsletter|communiqu[eé]\s+de\s+presse|couleurs?|typographi",
    re.I,
)
# Pages sans rapport avec un dispositif : on n'y saute jamais.
_PAGE_EXCLUE = re.compile(
    r"/(charte|logo|presse|cookies?|mentions|confidentialit|accessibilit|contact|"
    r"newsletter|plan-du-site|sitemap|rgpd|privacy|category|tag|author)", re.I,
)
# Au-delà, ce n'est plus un règlement d'appel mais un document de politique
# générale (equal.brussels lie des plans de 200 000 caractères) : hors sujet,
# et il écraserait le budget de texte. Constaté en réel, pas théorique.
MAX_CARACTERES_ANNEXE = 60_000


def _meme_organisme(url_pdf: str, url_fiche: str) -> bool:
    """Même domaine, ou sous-domaine évident du même organisme.

    ccf.brussels et spma.ccf.brussels : oui. ccf.brussels et facebook.com : non.
    """
    h1 = (urlsplit(url_pdf).hostname or "").lower()
    h2 = (urlsplit(url_fiche).hostname or "").lower()
    if not h1 or not h2:
        return False
    if h1 == h2:
        return True
    return h1.endswith("." + h2) or h2.endswith("." + h1)


def _zone_contenu(html: str):
    """Le corps de la fiche, sans nav/footer. On ne suit QUE des liens d'ici :
    sinon on part sur « Rapports d'activités » et autres liens de pied de page."""
    soup = BeautifulSoup(html, "lxml")
    for balise in soup(["nav", "header", "footer", "aside", "script", "style"]):
        balise.decompose()
    return soup.find("main") or soup.find("article") or soup.body or soup


def candidats_pdf(html: str, url_fiche: str) -> list[tuple[str, str]]:
    """[(url_pdf, ancre)] triés par pertinence décroissante, dédupliqués."""
    zone = _zone_contenu(html)
    vus, forts, faibles = set(), [], []

    for a in zone.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        absolue = urljoin(url_fiche, href)
        ancre = a.get_text(strip=True) or a.get("title", "") or ""

        # Les gestionnaires de téléchargement WordPress servent des PDF depuis
        # des URLs sans extension (/download/xxx/?wpdmdl=123) : l'ancre le dit.
        ressemble_pdf = bool(_EST_PDF.search(absolue)) or (
            ("wpdmdl" in absolue.lower() or "/download/" in absolue.lower())
            and "pdf" in ancre.lower()
        )
        if not ressemble_pdf or not _meme_organisme(absolue, url_fiche):
            continue
        if _ANCRE_EXCLUE.search(ancre):
            continue
        if absolue in vus:
            continue
        vus.add(absolue)
        (forts if _ANCRE_FORTE.search(ancre) else faibles).append((absolue, ancre))

    return forts + faibles


def liens_internes_contenu(html: str, url_fiche: str, limite: int = 6) -> list[str]:
    """Pages du même organisme liées DEPUIS LE CORPS de la fiche.

    Pourquoi : sur ccf.brussels, l'appel renvoie vers une page de service qui,
    elle, porte le règlement PDF. Sans ce saut unique, on rate le document que
    l'on est justement venu chercher. Bornes strictes : corps de page seulement,
    même organisme, `limite` pages maximum.
    """
    zone = _zone_contenu(html)
    base = url_fiche.split("#")[0].rstrip("/")
    vus, sorties = set(), []
    for a in zone.find_all("a", href=True):
        absolue = urljoin(url_fiche, a["href"].strip()).split("#")[0]
        if (not absolue.startswith(("http://", "https://"))
                or _EST_PDF.search(absolue)
                or not _meme_organisme(absolue, url_fiche)
                or _PAGE_EXCLUE.search(absolue)
                or absolue.rstrip("/") == base
                or absolue in vus):
            continue
        vus.add(absolue)
        sorties.append(absolue)
        if len(sorties) >= limite:
            break
    return sorties


def extraire_texte_pdf(octets: bytes) -> str:
    """Texte natif d'un PDF. Chaîne vide si illisible ou sans couche texte."""
    try:
        from pypdf import PdfReader
    except ImportError:  # dépendance absente : on dégrade, on ne casse pas
        log.warning("pypdf non installé — annexes PDF ignorées")
        return ""
    try:
        lecteur = PdfReader(io.BytesIO(octets))
        morceaux = []
        for page in lecteur.pages:
            try:
                morceaux.append(page.extract_text() or "")
            except Exception:
                continue
        return "\n".join(morceaux).strip()
    except Exception as e:
        log.warning("PDF illisible : %s: %s", type(e).__name__, e)
        return ""


async def _telecharger(client: httpx.AsyncClient, url: str) -> bytes | None:
    ua = user_agent()
    if not robots.autorise(url, ua):
        log.info("robots.txt interdit le PDF %s — ignoré", url)
        return None
    try:
        async with client.stream("GET", url) as r:
            r.raise_for_status()
            ct = r.headers.get("content-type", "").lower()
            if "pdf" not in ct and not _EST_PDF.search(url):
                log.info("%s n'est pas un PDF (%s) — ignoré", url, ct[:40])
                return None
            taille = int(r.headers.get("content-length") or 0)
            if taille > MAX_OCTETS:
                log.info("PDF trop lourd (%d Mo) : %s — ignoré", taille // 1024 // 1024, url)
                return None
            octets = bytearray()
            async for bloc in r.aiter_bytes():
                octets.extend(bloc)
                if len(octets) > MAX_OCTETS:      # pas de content-length annoncé
                    log.info("PDF > 10 Mo en flux : %s — abandon", url)
                    return None
            return bytes(octets)
    except httpx.HTTPError as e:
        log.warning("Téléchargement PDF KO %s : %s", url, e)
        return None


async def collecter_annexes(html: str, url_fiche: str, source: dict) -> list[dict]:
    """[{url, ancre, texte, caracteres}] pour les PDF exploitables de la fiche.

    Cherche d'abord dans la fiche ; si elle n'en porte aucun, tente UN saut vers
    les pages de service qu'elle référence. Les PDF sans couche texte (scans)
    sont logués et sautés — pas d'OCR dans ce lot.
    """
    if not source.get("pdf_annexes", True):
        return []

    ua = user_agent()
    delai = source.get("delai_secondes", 1.5)
    annexes: list[dict] = []

    async with httpx.AsyncClient(
        headers={"User-Agent": ua}, timeout=TIMEOUT, follow_redirects=True
    ) as client:
        candidats = candidats_pdf(html, url_fiche)

        # Saut unique vers une page de service : sur ccf.brussels le règlement
        # n'est pas sur l'appel mais sur la page du dispositif qu'il référence.
        # PLAFOND À 2 PAGES, mesuré : sans lui, une fiche sans annexe (le cas de
        # toutes celles de culture.be) payait 6 chargements à 5 s de délai, soit
        # ~20 s par fiche — 9 heures sur le backfill complet, pour rien.
        if not candidats and source.get("pdf_saut", True):
            for page in liens_internes_contenu(html, url_fiche)[:MAX_PAGES_SAUT]:
                if not robots.autorise(page, ua):
                    continue
                await asyncio.sleep(robots.delai_effectif(page, ua, delai))
                try:
                    r = await client.get(page)
                    r.raise_for_status()
                except httpx.HTTPError:
                    continue
                if "html" not in r.headers.get("content-type", "").lower():
                    continue
                # À un saut de la fiche, on n'accepte QUE des ancres
                # explicitement normatives (cf. _ANCRE_FORTE_SAUT).
                trouves = [(u, a) for u, a in candidats_pdf(r.text, page)
                           if _ANCRE_FORTE_SAUT.search(a)]
                if trouves:
                    log.info("Annexes trouvées à un saut de %s (via %s)", url_fiche, page)
                    candidats = trouves
                    break

        for url_pdf, ancre in candidats:
            if len(annexes) >= MAX_PDF_PAR_FICHE:
                break
            await asyncio.sleep(robots.delai_effectif(url_pdf, ua, delai))
            octets = await _telecharger(client, url_pdf)
            if not octets:
                continue
            texte = await asyncio.to_thread(extraire_texte_pdf, octets)
            if len(texte) < MIN_CARACTERES_UTILES:
                log.info("PDF sans texte exploitable (%d car., probablement scanné) : %s "
                         "— ignoré (pas d'OCR dans ce lot)", len(texte), url_pdf)
                continue
            if len(texte) > MAX_CARACTERES_ANNEXE:
                log.info("PDF de %d car. : document de politique générale plutôt que "
                         "règlement d'appel — ignoré (%s)", len(texte), url_pdf)
                continue
            annexes.append({"url": url_pdf, "ancre": ancre or "annexe",
                            "texte": texte, "caracteres": len(texte)})

    return annexes


def composer_texte(texte_page: str, annexes: list[dict]) -> str:
    """Texte de la page + annexes, dans la limite de BUDGET_CARACTERES.

    On tronque les PDF, jamais la page : si la page consomme déjà tout le
    budget, aucune annexe n'est ajoutée plutôt que d'amputer la source primaire.
    """
    texte = texte_page or ""
    reste = BUDGET_CARACTERES - len(texte)
    if reste <= 0 or not annexes:
        return texte

    morceaux = [texte]
    for a in annexes:
        entete = f"\n\n--- ANNEXE PDF : {a['ancre']} ---\n"
        dispo = reste - len(entete)
        if dispo < MIN_CARACTERES_UTILES:
            break
        extrait = a["texte"][:dispo]
        morceaux.append(entete + extrait)
        reste -= len(entete) + len(extrait)
    return "".join(morceaux)

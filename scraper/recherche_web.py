"""Recherche web : d'un TITRE de subside (indexé par Brulocalis) vers l'URL de sa
FICHE OFFICIELLE (source primaire).

Pourquoi : Brulocalis est une base subsides d'intérêt général MAIS protégée par
un anti-bot (BunkerWeb) qui signale ne pas vouloir de crawlers de contenu. On
l'utilise donc uniquement comme INDEX (des titres), puis on va chercher la
source officielle — communes, région, FWB… — qui, elle, fait foi et est
scrapable proprement. C'est la « voie primaire » recommandée (cf. README).

Backend : une API de recherche (clé fournie par l'exploitant via SEARCH_API_KEY).
Par défaut Brave Search (REST simple, JSON). Sans clé, chercher_officiel() renvoie
None : la fonctionnalité est alors inerte, jamais un résultat inventé.
"""

import logging
import os
from urllib.parse import urlsplit

import httpx

log = logging.getLogger(__name__)

# Domaines à NE JAMAIS retenir comme « source officielle » : l'index lui-même,
# les agrégateurs, et le bruit social/encyclopédique.
_EXCLUS = {
    "brulocalis.brussels", "www.brulocalis.brussels",
    "monasbl.be", "www.monasbl.be", "enmieux.be", "www.enmieux.be",
    "facebook.com", "www.facebook.com", "linkedin.com", "www.linkedin.com",
    "twitter.com", "x.com", "youtube.com", "www.youtube.com",
    "instagram.com", "wikipedia.org", "fr.wikipedia.org", "google.com",
}

# Un domaine officiel belge plausible : *.brussels, *.be (hors exclus).
def _officiel(host: str) -> bool:
    host = (host or "").lower()
    if host in _EXCLUS:
        return False
    return host.endswith(".brussels") or host.endswith(".be")


def _est_fiche(url: str) -> bool:
    """Rejette les racines de domaine (on veut une fiche, pas une home)."""
    p = urlsplit(url)
    return bool(p.path) and p.path.strip("/") != "" and len(p.path.strip("/")) > 3


def _brave(query: str, cle: str, n: int = 8) -> list[str]:
    r = httpx.get(
        "https://api.search.brave.com/res/v1/web/search",
        params={"q": query, "count": n, "country": "be", "search_lang": "fr"},
        headers={"X-Subscription-Token": cle, "Accept": "application/json"},
        timeout=20,
    )
    r.raise_for_status()
    return [item.get("url") for item in (r.json().get("web", {}).get("results") or [])
            if item.get("url")]


# Fournisseurs branchables. On implémente Brave ; en ajouter un autre = une
# fonction (query, cle) -> list[url] + une entrée dans _fournisseur().
def _fournisseur(nom: str):
    # Résolution par NOM du symbole module (pas une référence figée) pour rester
    # patchable en test et extensible.
    return {"brave": _brave}.get(nom, _brave)


def chercher_officiel(titre: str, *, indice: str = "Bruxelles subside appel à projets") -> str | None:
    """URL de la fiche officielle la plus plausible pour ce titre, ou None.

    None si : pas de clé (SEARCH_API_KEY), aucune réponse, ou aucun résultat sur
    un domaine officiel belge. On NE renvoie JAMAIS une URL inventée : à défaut,
    None (et l'appelant n'ingère rien)."""
    cle = os.getenv("SEARCH_API_KEY")
    if not cle:
        log.info("recherche_web : SEARCH_API_KEY absente — recherche désactivée")
        return None
    try:
        urls = _fournisseur(os.getenv("SEARCH_API_PROVIDER", "brave").lower())(f"{titre} {indice}", cle)
    except Exception as e:
        log.error("recherche_web KO pour %r : %s", titre[:60], e)
        return None
    for u in urls:
        host = urlsplit(u).hostname
        if _officiel(host) and _est_fiche(u):
            log.info("recherche_web : %r -> %s", titre[:50], u)
            return u
    log.info("recherche_web : aucune source officielle trouvée pour %r", titre[:50])
    return None

"""Respect du robots.txt : cache par host, autorisation, et résolution du délai.

Pourquoi ce module existe plutôt qu'un urllib.robotparser inline :

1. urllib.robotparser n'exploite que le PREMIER groupe qui matche, alors que la
   spec robots.txt demande de FUSIONNER tous les groupes d'un même user-agent.
   kbs-frb.be déclare deux groupes `User-agent: *` : le premier (Allow: /) sans
   Crawl-delay, le second avec `Crawl-delay: 10` et des `Disallow: /admin/`...
   Conséquence mesurée : robotparser renvoie crawl_delay=None ET considère
   /admin/ autorisé. On re-scanne donc le fichier pour fusionner les groupes,
   côté délai (max) comme côté autorisation (règle la plus spécifique gagne).
2. Le robots.txt de subsides.brussels renvoie une page 404 en HTML. Une 404 vaut
   "pas de restrictions" (convention), mais il ne faut pas parser le HTML comme
   des règles.
"""

import logging
import re
import urllib.robotparser
from urllib.parse import urlsplit

import httpx

log = logging.getLogger(__name__)

_cache: dict[str, "RobotsHost"] = {}


class RobotsHost:
    def __init__(self, host_racine: str, user_agent: str):
        self.host_racine = host_racine
        self.user_agent = user_agent
        self.parser = urllib.robotparser.RobotFileParser()
        self.crawl_delay_declare: float | None = None
        # Content-Signal du groupe qui nous concerne (extension Cloudflare).
        self.signaux_contenu: dict[str, str] = {}
        # Règles fusionnées de TOUS les groupes qui nous concernent : [(autorise, motif)]
        self.regles: list[tuple[bool, str]] = []
        self.charge = False
        self._load()

    def _load(self):
        url = f"{self.host_racine}/robots.txt"
        try:
            r = httpx.get(
                url,
                headers={"User-Agent": self.user_agent},
                timeout=15,
                follow_redirects=True,
            )
        except httpx.HTTPError as e:
            # Injoignable : on n'invente pas de permission, mais on ne bloque pas
            # tout non plus. Convention : pas de robots.txt = pas de restriction.
            log.warning("robots.txt injoignable (%s) : %s — aucune restriction appliquée", url, e)
            self.parser.parse([])
            self.charge = True
            return

        ct = r.headers.get("content-type", "")
        if r.status_code >= 400 or "html" in ct.lower():
            log.info("robots.txt absent sur %s (HTTP %s, %s) — aucune restriction",
                     self.host_racine, r.status_code, ct.split(";")[0] or "?")
            self.parser.parse([])
            self.charge = True
            return

        lignes = r.text.splitlines()
        self.parser.parse(lignes)
        self._scanner(lignes)
        self.charge = True
        log.info("robots.txt chargé pour %s (Crawl-delay: %s, %d règle(s) fusionnée(s))",
                 self.host_racine, self.crawl_delay_declare, len(self.regles))

    def _scanner(self, lignes):
        """Fusionne Crawl-delay et Allow/Disallow de TOUS les groupes qui nous visent.

        Contourne la limite d'urllib.robotparser (premier groupe seulement).
        """
        delais: list[float] = []
        regles: list[tuple[bool, str]] = []
        signaux: dict[str, str] = {}
        groupe_nous_concerne = False
        ua_court = self.user_agent.split("/")[0].strip().lower()

        for ligne in lignes:
            ligne = ligne.split("#", 1)[0].strip()
            if not ligne or ":" not in ligne:
                continue
            cle, _, val = ligne.partition(":")
            cle, val = cle.strip().lower(), val.strip()

            if cle == "user-agent":
                ua = val.lower()
                groupe_nous_concerne = ua in ("*", ua_court) or ua in ua_court
            elif not groupe_nous_concerne:
                continue
            elif cle == "content-signal":
                # Extension Cloudflare (voir kbs-frb.be) : « search=yes,
                # ai-train=no, use=reference ». Ce n'est pas du robots.txt
                # standard, ça ne bloque rien techniquement — mais ça exprime une
                # volonté, et on veut être prévenus quand elle change.
                for morceau in val.split(","):
                    nom, _, valeur = morceau.partition("=")
                    if nom.strip():
                        signaux[nom.strip().lower()] = valeur.strip().lower()
            elif cle == "crawl-delay":
                try:
                    delais.append(float(val))
                except ValueError:
                    pass
            elif cle in ("allow", "disallow"):
                if cle == "disallow" and not val:
                    continue  # "Disallow:" vide = tout autorisé, pas une règle
                if val:
                    regles.append((cle == "allow", val))

        self.crawl_delay_declare = max(delais) if delais else None
        self.regles = regles
        self.signaux_contenu = signaux

    @staticmethod
    def _matche(motif: str, chemin: str) -> int:
        """Longueur du motif s'il matche le chemin, -1 sinon. Gère * et $."""
        ancre_fin = motif.endswith("$")
        brut = motif[:-1] if ancre_fin else motif
        regex = "".join(".*" if c == "*" else re.escape(c) for c in brut)
        if re.match(regex + ("$" if ancre_fin else ""), chemin):
            return len(brut)
        return -1

    def autorise(self, url: str) -> bool:
        """La règle la plus spécifique (motif le plus long) gagne ; à longueur
        égale, Allow l'emporte — c'est la convention robots.txt.

        On n'utilise PAS can_fetch() comme veto : urllib.robotparser applique
        "première règle qui matche" au lieu de "règle la plus spécifique", donc
        un `Disallow: /a/` placé avant un `Allow: /a/ok/` lui fait interdire
        /a/ok/ à tort. Il ne sert donc que de repli quand notre scan n'a produit
        aucune règle (robots.txt vide, absent, ou illisible).
        """
        if not self.regles:
            return self.parser.can_fetch(self.user_agent, url)

        parts = urlsplit(url)
        chemin = parts.path or "/"
        if parts.query:
            chemin += "?" + parts.query

        meilleur_allow = meilleur_disallow = -1
        for autorise, motif in self.regles:
            longueur = self._matche(motif, chemin)
            if longueur < 0:
                continue
            if autorise:
                meilleur_allow = max(meilleur_allow, longueur)
            else:
                meilleur_disallow = max(meilleur_disallow, longueur)

        return meilleur_disallow <= meilleur_allow if meilleur_disallow >= 0 else True

    def delai_effectif(self, delai_configure: float) -> float:
        """Le site a toujours le dernier mot s'il demande plus lent que nous."""
        if self.crawl_delay_declare is None:
            return delai_configure
        return max(delai_configure, self.crawl_delay_declare)


def pour_url(url: str, user_agent: str) -> RobotsHost:
    parts = urlsplit(url)
    racine = f"{parts.scheme}://{parts.netloc}"
    if racine not in _cache:
        _cache[racine] = RobotsHost(racine, user_agent)
    return _cache[racine]


def autorise(url: str, user_agent: str) -> bool:
    try:
        return pour_url(url, user_agent).autorise(url)
    except Exception as e:  # un robots.txt cassé ne doit pas tuer le run
        log.warning("Vérification robots.txt impossible pour %s : %s", url, e)
        return True


def signaux_contenu(url: str, user_agent: str) -> dict[str, str]:
    """Content-Signal déclarés pour nous sur ce host (dict vide si aucun)."""
    try:
        return dict(pour_url(url, user_agent).signaux_contenu)
    except Exception as e:
        log.warning("Lecture des Content-Signal impossible pour %s : %s", url, e)
        return {}


# Signaux dont un « no » nous concerne DIRECTEMENT.
#   ai-input : « donner le contenu à un modèle » — c'est exactement notre
#              extraction. S'il passe à no, on doit s'arrêter sur cette source.
#   search   : indexation et extraits — notre cas d'usage produit un lien + un
#              résumé, donc un no est également disqualifiant.
# ai-train n'y figure pas : nous n'entraînons rien, un « no » ne nous vise pas.
SIGNAUX_BLOQUANTS = ("ai-input", "search")


def signaux_defavorables(url: str, user_agent: str) -> list[str]:
    """Signaux passés à « no » qui devraient nous faire cesser sur ce host.

    Un Content-Signal ne bloque RIEN techniquement : c'est une déclaration de
    volonté (Cloudflare), que son préambule rattache à l'article 4 de la
    directive UE 2019/790. On ne l'applique donc pas tout seul — on alerte, et
    un humain tranche. Voir README § Conformité.
    """
    sig = signaux_contenu(url, user_agent)
    return [nom for nom in SIGNAUX_BLOQUANTS if sig.get(nom) == "no"]


def delai_effectif(url: str, user_agent: str, delai_configure: float) -> float:
    try:
        return pour_url(url, user_agent).delai_effectif(delai_configure)
    except Exception:
        return delai_configure


def reset_cache():
    _cache.clear()

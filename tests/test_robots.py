"""Tests de la fusion des groupes robots.txt.

Le cas de référence est le vrai robots.txt de kbs-frb.be : DEUX groupes
`User-agent: *`, dont seul le second porte le Crawl-delay et les Disallow.
urllib.robotparser seul ne voit que le premier — d'où ce module.
"""

import pytest

from scraper.robots import RobotsHost

UA = "SubsidesAgentBot/0.1 (projet personnel; contact: a@b.be)"

# Forme réelle de kbs-frb.be, réduite.
KBS = """
User-agent: *
Content-Signal: search=yes,ai-train=no,use=reference
Allow: /

User-agent: ClaudeBot
Disallow: /

User-agent: GPTBot
Disallow: /

User-agent: *
Crawl-delay: 10
Allow: /misc/*.css$
Disallow: /admin/
Disallow: /search/
Disallow: /user/login/
"""

SIMPLE = """
User-agent: *
Disallow: /prive/
Crawl-delay: 2
"""


def host(texte, ua=UA):
    """RobotsHost sans I/O réseau."""
    h = RobotsHost.__new__(RobotsHost)
    h.host_racine = "https://exemple.be"
    h.user_agent = ua
    import urllib.robotparser
    h.parser = urllib.robotparser.RobotFileParser()
    h.crawl_delay_declare = None
    h.regles = []
    lignes = texte.splitlines()
    h.parser.parse(lignes)
    h._scanner(lignes)
    h.charge = True
    return h


# --- Fusion des groupes (le bug qu'on corrige) -----------------------------

def test_crawl_delay_du_second_groupe_est_vu():
    assert host(KBS).crawl_delay_declare == 10.0


def test_disallow_du_second_groupe_est_applique():
    h = host(KBS)
    # robotparser seul dit True (il ne lit que le 1er groupe `Allow: /`)
    assert h.parser.can_fetch(UA, "https://exemple.be/admin/") is True
    # nos règles fusionnées corrigent
    assert h.autorise("https://exemple.be/admin/") is False


@pytest.mark.parametrize("chemin,attendu", [
    ("/fr/un-appel-a-projets", True),      # ce qu'on veut vraiment crawler
    ("/fr/rechercher?type_id=call", True),  # pas /search/ : autorisé
    ("/admin/", False),
    ("/admin/config", False),               # préfixe
    ("/search/x", False),
    ("/user/login/", False),
    ("/user/profil", True),                 # seul /user/login/ est bloqué
])
def test_regles_fusionnees_kbs(chemin, attendu):
    assert host(KBS).autorise("https://exemple.be" + chemin) is attendu


# --- Sémantique des motifs -------------------------------------------------

def test_allow_le_plus_specifique_gagne_sur_disallow():
    h = host("User-agent: *\nDisallow: /a/\nAllow: /a/ok/\n")
    assert h.autorise("https://exemple.be/a/bloque") is False
    assert h.autorise("https://exemple.be/a/ok/x") is True


def test_wildcard_etoile():
    h = host("User-agent: *\nDisallow: /*.pdf\n")
    assert h.autorise("https://exemple.be/doc/x.pdf") is False
    assert h.autorise("https://exemple.be/doc/x.html") is True


def test_ancre_fin_dollar():
    h = host("User-agent: *\nDisallow: /x$\n")
    assert h.autorise("https://exemple.be/x") is False
    assert h.autorise("https://exemple.be/xyz") is True


def test_disallow_vide_nest_pas_une_regle():
    # "Disallow:" (vide) = tout autorisé
    h = host("User-agent: *\nDisallow:\n")
    assert h.regles == []
    assert h.autorise("https://exemple.be/nimporte") is True


def test_groupe_dun_autre_ua_ignore():
    h = host("User-agent: ClaudeBot\nDisallow: /\n\nUser-agent: *\nAllow: /\n")
    # On n'est pas ClaudeBot : le Disallow: / ne nous vise pas.
    assert h.autorise("https://exemple.be/x") is True


def test_notre_ua_nomme_est_respecte():
    h = host("User-agent: SubsidesAgentBot\nDisallow: /interdit/\n")
    assert h.autorise("https://exemple.be/interdit/x") is False
    assert h.autorise("https://exemple.be/ok") is True


# --- Délai effectif --------------------------------------------------------

def test_le_site_gagne_sil_est_plus_lent():
    assert host(KBS).delai_effectif(1.5) == 10.0


def test_notre_config_gagne_si_elle_est_plus_lente():
    assert host(SIMPLE).delai_effectif(5.0) == 5.0   # site=2s, nous=5s


def test_sans_crawl_delay_on_garde_la_config():
    h = host("User-agent: *\nAllow: /\n")
    assert h.crawl_delay_declare is None
    assert h.delai_effectif(1.5) == 1.5


def test_robots_vide():
    h = host("")
    assert h.autorise("https://exemple.be/x") is True
    assert h.delai_effectif(1.5) == 1.5

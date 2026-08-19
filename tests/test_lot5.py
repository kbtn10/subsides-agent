"""Lot 5 : profondeur des sources.

Couvre ce que le lot ajoute et qui peut casser en silence : fusion/dédup de
plusieurs points d'entrée, arrêt anticipé du crawl paginé, hash page+PDF sur le
TEXTE, remap des zones, run ciblé sur une source, alerte source muette.

Aucun réseau, aucun LLM : tout est mocké.
"""

import asyncio
import importlib
import json

import pytest


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "lot5.db"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-faux")
    import db as dbm
    importlib.reload(dbm)
    dbm.init_db()
    yield dbm
    conn = getattr(dbm._local, "conn", None)
    if conn:
        conn.close()
        dbm._local.conn = None


# --- Partie 3 : fusion et dédup de plusieurs points d'entrée ----------------

def test_points_entree_fusionnes_et_dedupliques(env, monkeypatch):
    """Une fiche vue par DEUX stratégies n'est traitée qu'une fois, et l'apport
    propre de chacune est mesuré."""
    from scraper import crawler

    source = {
        "id": "s", "nom": "S", "strategie": "sitemap", "delai_secondes": 0,
        "start_urls": ["https://x.be/sitemap.xml"],
        "decouverte": [
            {"nom": "sitemap", "strategie": "sitemap"},
            {"nom": "flux RSS", "strategie": "rss", "start_urls": ["https://x.be/feed/"]},
        ],
    }

    async def faux_sitemap(s):
        return crawler.ResultatCrawl(["https://x.be/a", "https://x.be/b"], "sitemap")

    async def faux_rss(s):
        # /b est un doublon (avec un slash final et un utm_ : même fiche),
        # /c est l'apport propre du flux.
        return crawler.ResultatCrawl(
            ["https://x.be/b/?utm_source=rss", "https://x.be/c"], "rss")

    monkeypatch.setitem(crawler.STRATEGIES, "sitemap", faux_sitemap)
    monkeypatch.setitem(crawler.STRATEGIES, "rss", faux_rss)

    res = asyncio.run(crawler.decouvrir(source))

    assert len(res.urls) == 3, res.urls          # a, b, c — b n'est pas dupliqué
    apports = {a["nom"]: a for a in res.apports}
    assert apports["sitemap"]["en_propre"] == 2
    assert apports["flux RSS"]["trouvees"] == 2
    assert apports["flux RSS"]["en_propre"] == 1  # seul /c est neuf


def test_point_entree_en_echec_nempeche_pas_les_autres(env, monkeypatch):
    from scraper import crawler

    source = {
        "id": "s", "nom": "S", "strategie": "sitemap", "delai_secondes": 0,
        "start_urls": ["https://x.be/s.xml"],
        "decouverte": [
            {"nom": "cassé", "strategie": "sitemap"},
            {"nom": "flux", "strategie": "rss", "start_urls": ["https://x.be/feed/"]},
        ],
    }

    async def sitemap_ko(s):
        raise RuntimeError("503")

    async def rss_ok(s):
        return crawler.ResultatCrawl(["https://x.be/a"], "rss")

    monkeypatch.setitem(crawler.STRATEGIES, "sitemap", sitemap_ko)
    monkeypatch.setitem(crawler.STRATEGIES, "rss", rss_ok)

    res = asyncio.run(crawler.decouvrir(source))
    assert res.urls == ["https://x.be/a"]
    assert any("503" in e for e in res.erreurs)


def test_source_sans_decouverte_garde_son_comportement(env, monkeypatch):
    """Non-régression : sans clé `decouverte`, rien ne change."""
    from scraper import crawler

    vues = []

    async def faux_sitemap(s):
        vues.append(s["id"])
        return crawler.ResultatCrawl(["https://x.be/a"], "sitemap")

    monkeypatch.setitem(crawler.STRATEGIES, "sitemap", faux_sitemap)
    res = asyncio.run(crawler.decouvrir(
        {"id": "s", "nom": "S", "strategie": "sitemap", "start_urls": ["u"],
         "delai_secondes": 0}))
    assert res.urls == ["https://x.be/a"] and vues == ["s"]


# --- Partie 2 : pagination TYPO3, arrêt anticipé ----------------------------

def _page_html(ids, page_courante, total_pages=5):
    """Fausse page de listing TYPO3 : des fiches + des liens de pagination."""
    fiches = "".join(
        f'<a href="/detail/?tx_ttnews%5Btt_news%5D={i}&cHash=abc">Fiche {i}</a>'
        for i in ids)
    pages = "".join(
        f'<a href="/liste/?tx_ttnews%5Bpointer%5D={p}&cHash=h{p}">page {p}</a>'
        for p in range(total_pages) if p != page_courante)
    return f"<html><body><main>{fiches}{pages}</main></body></html>"


def test_arret_anticipe_quand_la_page_est_deja_connue(env, monkeypatch):
    from db import normaliser_url
    from scraper import crawler

    pages = {
        0: _page_html([10, 11], 0),
        1: _page_html([12, 13], 1),   # 100 % déjà connu -> stop ici
        2: _page_html([14, 15], 2),   # ne doit JAMAIS être chargée
    }
    chargees = []

    async def faux_charger(url, **kw):
        import re
        m = re.search(r"pointer%5D=(\d+)", url)
        n = int(m.group(1)) if m else 0
        chargees.append(n)
        return pages[n]

    monkeypatch.setattr(crawler, "charger_html", faux_charger)
    monkeypatch.setattr(crawler.robots, "autorise", lambda *a, **k: True)
    monkeypatch.setattr(crawler.robots, "delai_effectif", lambda *a, **k: 0)

    source = {"id": "c", "nom": "C", "strategie": "pagination_typo3",
              "start_urls": ["https://x.be/liste/"], "delai_secondes": 0,
              "url_pattern": r"tt_news(%5B|\[)?", "max_pages_delta": 5,
              "max_pages_backfill": None, "max_pages": 5}

    connues = {normaliser_url(f"https://x.be/detail/?tx_ttnews%5Btt_news%5D={i}&cHash=abc")
               for i in (12, 13)}

    res = asyncio.run(crawler.decouvrir(source, backfill=False, urls_connues=connues))
    assert res.arret_anticipe is True
    assert chargees == [0, 1], chargees          # la page 2 n'a pas été chargée
    assert res.pages_lues == 2


def test_backfill_ignore_larret_anticipe_et_le_plafond_delta(env, monkeypatch):
    from db import normaliser_url
    from scraper import crawler

    pages = {n: _page_html([10 + n * 2, 11 + n * 2], n) for n in range(5)}
    chargees = []

    async def faux_charger(url, **kw):
        import re
        m = re.search(r"pointer%5D=(\d+)", url)
        n = int(m.group(1)) if m else 0
        chargees.append(n)
        return pages[n]

    monkeypatch.setattr(crawler, "charger_html", faux_charger)
    monkeypatch.setattr(crawler.robots, "autorise", lambda *a, **k: True)
    monkeypatch.setattr(crawler.robots, "delai_effectif", lambda *a, **k: 0)

    source = {"id": "c", "nom": "C", "strategie": "pagination_typo3",
              "start_urls": ["https://x.be/liste/"], "delai_secondes": 0,
              "url_pattern": r"tt_news(%5B|\[)?", "max_pages_delta": 1,
              "max_pages_backfill": None, "max_pages": 5}

    # Tout est déjà connu : en delta on s'arrêterait à la page 0.
    connues = {normaliser_url(f"https://x.be/detail/?tx_ttnews%5Btt_news%5D={i}&cHash=abc")
               for i in range(10, 20)}

    res = asyncio.run(crawler.decouvrir(source, backfill=True, urls_connues=connues))
    assert res.arret_anticipe is False
    assert chargees == [0, 1, 2, 3, 4]
    assert len(res.urls) == 10


def test_delta_respecte_max_pages_delta(env, monkeypatch):
    from scraper import crawler

    pages = {n: _page_html([100 + n], n, total_pages=10) for n in range(10)}
    chargees = []

    async def faux_charger(url, **kw):
        import re
        m = re.search(r"pointer%5D=(\d+)", url)
        n = int(m.group(1)) if m else 0
        chargees.append(n)
        return pages[n]

    monkeypatch.setattr(crawler, "charger_html", faux_charger)
    monkeypatch.setattr(crawler.robots, "autorise", lambda *a, **k: True)
    monkeypatch.setattr(crawler.robots, "delai_effectif", lambda *a, **k: 0)

    source = {"id": "c", "nom": "C", "strategie": "pagination_typo3",
              "start_urls": ["https://x.be/liste/"], "delai_secondes": 0,
              "url_pattern": r"tt_news(%5B|\[)?", "max_pages_delta": 3,
              "max_pages_backfill": None, "max_pages": 10}

    res = asyncio.run(crawler.decouvrir(source, backfill=False, urls_connues=set()))
    assert chargees == [0, 1, 2]                 # le cron nocturne reste court
    assert res.pages_lues == 3


# --- Partie 4 : PDF ---------------------------------------------------------

FICHE_HTML = """
<html><body>
  <nav><a href="/rapports.pdf">Rapports d'activités</a></nav>
  <main>
    <a href="/reglement-2026.pdf">Règlement de la subvention</a>
    <a href="/photo.jpg">une image</a>
    <a href="https://autre-site.be/reglement.pdf">Règlement ailleurs</a>
  </main>
  <footer><a href="/mentions.pdf">Mentions légales</a></footer>
</body></html>
"""


def test_candidats_pdf_filtre_nav_footer_et_domaine():
    from scraper import pdfs
    trouves = pdfs.candidats_pdf(FICHE_HTML, "https://x.be/appel/")
    urls = [u for u, _ in trouves]
    assert urls == ["https://x.be/reglement-2026.pdf"], urls   # nav/footer/hors-domaine écartés


def test_candidats_pdf_classe_les_ancres_parlantes_dabord():
    from scraper import pdfs
    html = """<html><body><main>
      <a href="/annexe.pdf">Document</a>
      <a href="/cond.pdf">Conditions d'éligibilité</a>
    </main></body></html>"""
    urls = [u for u, _ in pdfs.candidats_pdf(html, "https://x.be/a/")]
    assert urls[0].endswith("cond.pdf")


def test_composer_texte_tronque_le_pdf_jamais_la_page():
    from scraper import pdfs
    page = "P" * 19_500
    annexes = [{"url": "u", "ancre": "Règlement", "texte": "A" * 5_000, "caracteres": 5_000}]
    out = pdfs.composer_texte(page, annexes)
    assert out.startswith(page)                       # la page est intacte
    assert len(out) <= pdfs.BUDGET_CARACTERES
    assert "--- ANNEXE PDF : Règlement ---" in out


def test_composer_texte_sans_annexe_ne_change_rien():
    from scraper import pdfs
    assert pdfs.composer_texte("abc", []) == "abc"


def test_page_saturee_najoute_aucune_annexe():
    from scraper import pdfs
    page = "P" * pdfs.BUDGET_CARACTERES
    out = pdfs.composer_texte(page, [{"url": "u", "ancre": "R", "texte": "A" * 999,
                                      "caracteres": 999}])
    assert out == page


def test_hash_couvre_le_texte_du_pdf_pas_ses_octets(env):
    """Un règlement modifié => fiche modifiée. Mais un PDF regénéré à contenu
    identique (métadonnées de date différentes) => hash stable."""
    import db as dbm
    from scraper import pdfs

    page = "Texte de la page."
    h_sans = dbm.hash_texte(pdfs.composer_texte(page, []))
    h_v1 = dbm.hash_texte(pdfs.composer_texte(
        page, [{"url": "u", "ancre": "R", "texte": "Article 1. Montant 3000 EUR.",
                "caracteres": 27}]))
    h_v2 = dbm.hash_texte(pdfs.composer_texte(
        page, [{"url": "u", "ancre": "R", "texte": "Article 1. Montant 5000 EUR.",
                "caracteres": 27}]))
    # Même texte extrait, octets sources différents : on ne hashe QUE le texte.
    h_v1_bis = dbm.hash_texte(pdfs.composer_texte(
        page, [{"url": "u", "ancre": "R", "texte": "Article 1. Montant 3000 EUR.",
                "caracteres": 27}]))

    assert h_sans != h_v1                # l'annexe compte dans le hash
    assert h_v1 != h_v2                  # un règlement modifié = fiche modifiée
    assert h_v1 == h_v1_bis              # PDF regénéré à contenu égal = stable


def test_annexes_pdf_stockees_sur_la_fiche(env):
    import db as dbm
    dbm.upsert_subside(
        {"url_source": "https://x.be/a", "titre": "T"}, "s",
        annexes_pdf=[{"url": "https://x.be/r.pdf", "ancre": "Règlement", "caracteres": 4200}])
    row = dbm.connect().execute(
        "SELECT annexes_pdf FROM subsides WHERE url_source='https://x.be/a'").fetchone()
    annexes = json.loads(row["annexes_pdf"])
    assert annexes[0]["url"] == "https://x.be/r.pdf"
    assert annexes[0]["caracteres"] == 4200


def test_annexes_absentes_conservent_lexistant(env):
    """Un run qui ne regarde pas les PDF (annexes_pdf=None) ne doit pas effacer
    ce qu'un backfill précédent a trouvé."""
    import db as dbm
    dbm.upsert_subside({"url_source": "https://x.be/a", "titre": "T"}, "s",
                       annexes_pdf=[{"url": "https://x.be/r.pdf", "ancre": "R", "caracteres": 10}])
    dbm.upsert_subside({"url_source": "https://x.be/a", "titre": "T2"}, "s")  # None
    row = dbm.connect().execute(
        "SELECT annexes_pdf FROM subsides WHERE url_source='https://x.be/a'").fetchone()
    assert json.loads(row["annexes_pdf"])[0]["url"] == "https://x.be/r.pdf"


# --- Partie 5 : remap zones -------------------------------------------------

def test_remap_zones_corrige_et_est_idempotent(env):
    import db as dbm
    from scripts import remap_zones

    conn = dbm.connect()
    dbm.upsert_subside({"url_source": "https://x.be/1", "titre": "A",
                        "zone_geographique": "Scheldevallei"}, "kbs_frb")
    # On simule l'ancien mapping (avant que « Scheldevallei » soit reconnu).
    conn.execute("UPDATE subsides SET zone_categorie='inconnue' WHERE url_source='https://x.be/1'")
    dbm.upsert_subside({"url_source": "https://x.be/2", "titre": "B",
                        "zone_geographique": "Bruxelles", "zone_categorie": "bruxelles"}, "cocof")
    conn.commit()

    changements = remap_zones.calculer()
    assert len(changements) == 1
    assert changements[0]["avant"] == "inconnue" and changements[0]["apres"] == "flandre"

    remap_zones.appliquer(changements)
    assert conn.execute(
        "SELECT zone_categorie FROM subsides WHERE url_source='https://x.be/1'"
    ).fetchone()[0] == "flandre"

    assert remap_zones.calculer() == []          # idempotent


def test_remap_zones_filtre_par_source(env):
    import db as dbm
    from scripts import remap_zones
    conn = dbm.connect()
    for i, src in ((1, "kbs_frb"), (2, "cocof")):
        dbm.upsert_subside({"url_source": f"https://x.be/{i}", "titre": "T",
                            "zone_geographique": "Gent"}, src)
    conn.execute("UPDATE subsides SET zone_categorie='inconnue'")
    conn.commit()
    assert len(remap_zones.calculer("kbs_frb")) == 1
    assert len(remap_zones.calculer()) == 2


# --- Partie 5 : santé des sources + source muette ---------------------------

def test_source_muette_detectee_seulement_apres_un_succes(env):
    import db as dbm

    base = {"source_id": "s", "nom": "S", "nouveaux": 0, "modifies": 0,
            "echecs": 0, "statut": "ok", "erreurs": [], "apports": []}

    # Premier passage à 0 : on ne crie pas (peut-être une source neuve).
    assert dbm.enregistrer_sante_source({**base, "fiches_trouvees": 0}) is False
    # Un passage fructueux…
    assert dbm.enregistrer_sante_source({**base, "fiches_trouvees": 12}) is False
    # …puis plus rien : LÀ c'est une alerte.
    assert dbm.enregistrer_sante_source({**base, "fiches_trouvees": 0}) is True

    sante = dbm.sante_sources()["s"]
    assert sante["urls_decouvertes"] == 0
    assert sante["dernier_succes"] is not None   # on garde la trace du dernier succès


def test_sante_sources_persiste_les_apports(env):
    import db as dbm
    dbm.enregistrer_sante_source({
        "source_id": "cocof", "fiches_trouvees": 7, "nouveaux": 2, "modifies": 1,
        "echecs": 0, "statut": "ok", "erreurs": [],
        "apports": [{"nom": "listing curé", "strategie": "llm_links",
                     "trouvees": 5, "en_propre": 5},
                    {"nom": "flux RSS", "strategie": "rss",
                     "trouvees": 4, "en_propre": 2}],
    })
    strategies = dbm.sante_sources()["cocof"]["strategies"]
    assert {s["nom"] for s in strategies} == {"listing curé", "flux RSS"}
    assert next(s for s in strategies if s["nom"] == "flux RSS")["en_propre"] == 2


# --- Partie 1 : run ciblé ---------------------------------------------------

def test_scrape_cible_une_seule_source(env, monkeypatch):
    import jobs

    traitees = []

    async def faux_traiter_source(job, source, budget, **kw):
        traitees.append((source["id"], budget, kw.get("backfill")))
        return {"source_id": source["id"], "nom": source["nom"], "statut": "ok",
                "traitees": 0, "nouveaux": 0, "modifies": 0, "inchanges": 0,
                "echecs": 0, "a_verifier": 0, "fiches_trouvees": 1,
                "tokens_in": 0, "tokens_out": 0, "erreurs": []}

    monkeypatch.setattr(jobs, "_traiter_source", faux_traiter_source)
    monkeypatch.setattr(jobs, "fermer_browser", lambda: asyncio.sleep(0))
    monkeypatch.setenv("MAX_FICHES_PAR_RUN", "200")

    async def scenario():
        jid = await jobs.creer_job(source_id="cocof", backfill=True)
        for _ in range(200):
            if jobs.get_job(jid)["statut"] != "running":
                break
            await asyncio.sleep(0.01)
        return jobs.get_job(jid)

    job = asyncio.run(scenario())
    assert job["statut"] == "done"
    # Une seule source, et elle a TOUT le budget (pas de partage).
    assert [t[0] for t in traitees] == ["cocof"]
    assert traitees[0][1] == 200
    assert traitees[0][2] is True                # backfill propagé


def test_scrape_source_inconnue_refuse(env):
    import jobs
    with pytest.raises(LookupError):
        asyncio.run(jobs.creer_job(source_id="nexiste_pas"))


def test_scrape_source_inactive_refuse(env):
    import jobs
    with pytest.raises(LookupError):
        asyncio.run(jobs.creer_job(source_id="vgc"))     # actif=False dans la config


def test_backfill_traite_dabord_les_fiches_jamais_vues(env, monkeypatch):
    """Sans cet ordre, un backfill plafonné par le budget rejouerait les mêmes
    N premières fiches à chaque run et n'avancerait jamais dans les archives."""
    import db as dbm
    import jobs
    from scraper import crawler

    # 3 fiches déjà connues, vérifiées à des dates différentes.
    for i, date in ((1, "2026-07-01"), (2, "2026-05-01"), (3, "2026-06-01")):
        dbm.upsert_subside({"url_source": f"https://x.be/{i}", "titre": "T"}, "s")
        dbm.connect().execute(
            "UPDATE subsides SET derniere_verification=? WHERE url_source=?",
            (date, f"https://x.be/{i}"))
    dbm.connect().commit()

    async def faux_decouvrir(source, **kw):
        # /9 est neuve, les autres sont connues.
        return crawler.ResultatCrawl(
            [f"https://x.be/{i}" for i in (1, 2, 3, 9)], "sitemap")

    traitees = []

    async def faux_fiche(url, source, rapport, **kw):
        traitees.append(url)
        return "nouveaux"

    monkeypatch.setattr(jobs.crawler, "decouvrir", faux_decouvrir)
    monkeypatch.setattr(jobs, "_traiter_fiche", faux_fiche)
    monkeypatch.setattr(jobs.robots, "autorise", lambda *a, **k: True)
    monkeypatch.setattr(jobs.robots, "delai_effectif", lambda *a, **k: 0)

    source = {"id": "s", "nom": "S", "strategie": "sitemap", "delai_secondes": 0}
    job = {"source_en_cours": None, "fiches_total_estime": 0, "fiches_traitees": 0}

    # Budget de 2 : on doit servir la jamais-vue, puis la plus ancienne.
    asyncio.run(jobs._traiter_source(job, source, 2, backfill=True))
    assert traitees == ["https://x.be/9", "https://x.be/2"], traitees


def test_verrou_inter_process_bloque_un_second_scrape(env, monkeypatch):
    """Le verrou en mémoire ne voit que les jobs du process courant. Un script
    lancé à côté de l'API pouvait donc démarrer un 2e scrape : deux crawlers sur
    les mêmes sites. La base est le seul terrain commun."""
    import db as dbm
    import jobs

    run_id = dbm.debuter_scrape_run()          # comme si un autre process scrapait
    assert dbm.scrape_run_en_cours() is not None

    with pytest.raises(RuntimeError, match="scrape tourne déjà"):
        asyncio.run(jobs.creer_job())

    dbm.cloturer_scrape_run(run_id, {"ok": True})
    assert dbm.scrape_run_en_cours() is None    # libéré


def test_run_orphelin_ne_bloque_pas_indefiniment(env):
    """Un process tué en vol laisse une ligne ouverte : elle ne doit pas
    interdire tout scrape ultérieur."""
    import db as dbm
    from datetime import datetime, timedelta, timezone

    dbm.debuter_scrape_run()
    vieux = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat(timespec="seconds")
    dbm.connect().execute("UPDATE scrape_runs SET debut = ?", (vieux,))
    dbm.connect().commit()

    assert dbm.scrape_run_en_cours() is None            # orphelin -> ne bloque plus
    assert dbm.cloturer_runs_orphelins() == 1           # et on peut le refermer
    assert dbm.cloturer_runs_orphelins() == 0


# --- Correctif budget : la veille doit PROGRESSER d'un run à l'autre ---------

def _source_fictive(n_urls):
    return ({"id": "s", "nom": "S", "strategie": "sitemap", "delai_secondes": 0},
            [f"https://x.be/{i:03d}" for i in range(n_urls)])


def test_run_suivant_atteint_les_fiches_que_le_precedent_na_pas_pu_traiter(env, monkeypatch):
    """LE test du correctif.

    L'ordre du sitemap est stable : sans tri « jamais vue d'abord », le cron
    reprenait chaque nuit les mêmes N premières fiches et les suivantes étaient
    inatteignables À VIE. Constaté en réel sur hub.brussels : 40 traitées sur
    109, et 0 des 69 autres n'était jamais entrée en base.
    """
    import db as dbm
    import jobs
    from scraper import crawler

    source, urls = _source_fictive(10)

    async def faux_decouvrir(s, **kw):
        return crawler.ResultatCrawl(list(urls), "sitemap")

    traitees = []

    async def faux_fiche(url, s, rapport, **kw):
        traitees.append(url)
        dbm.upsert_subside({"url_source": url, "titre": "T"}, "s", text_hash="h")
        return "nouveaux"

    monkeypatch.setattr(jobs.crawler, "decouvrir", faux_decouvrir)
    monkeypatch.setattr(jobs, "_traiter_fiche", faux_fiche)
    monkeypatch.setattr(jobs.robots, "autorise", lambda *a, **k: True)
    monkeypatch.setattr(jobs.robots, "delai_effectif", lambda *a, **k: 0)

    job = {"source_en_cours": None, "fiches_total_estime": 0, "fiches_traitees": 0}

    # Run N : budget 4 -> les 4 premières jamais vues.
    asyncio.run(jobs._traiter_source(job, source, 4))
    run_n = list(traitees)
    assert len(run_n) == 4

    # Run N+1 : le tri doit servir des fiches NEUVES, pas rejouer les mêmes.
    traitees.clear()
    asyncio.run(jobs._traiter_source(job, source, 4))
    run_n1 = list(traitees)

    assert set(run_n1).isdisjoint(run_n), (
        f"le run N+1 rejoue les mêmes fiches : {sorted(set(run_n1) & set(run_n))}")
    assert len(set(run_n) | set(run_n1)) == 8      # la veille progresse vraiment


def test_fiche_court_circuitee_par_le_hash_ne_consomme_pas_le_budget(env, monkeypatch):
    """Le budget est un garde-fou de COÛT : un hash-skip ne coûte aucun token,
    il ne doit donc pas voler sa place à une fiche jamais extraite."""
    import db as dbm
    import jobs
    from scraper import crawler

    source, urls = _source_fictive(10)
    # Les 5 premières sont déjà connues et inchangées.
    for u in urls[:5]:
        dbm.upsert_subside({"url_source": u, "titre": "T"}, "s", text_hash="h")

    async def faux_decouvrir(s, **kw):
        return crawler.ResultatCrawl(list(urls), "sitemap")

    extraites = []

    async def faux_fiche(url, s, rapport, **kw):
        if dbm.hash_connu(url) == "h":                 # inchangée -> hash-skip
            rapport["ignorees_hash"] += 1
            return "inchanges"
        extraites.append(url)
        dbm.upsert_subside({"url_source": url, "titre": "T"}, "s", text_hash="h")
        return "nouveaux"

    monkeypatch.setattr(jobs.crawler, "decouvrir", faux_decouvrir)
    monkeypatch.setattr(jobs, "_traiter_fiche", faux_fiche)
    monkeypatch.setattr(jobs.robots, "autorise", lambda *a, **k: True)
    monkeypatch.setattr(jobs.robots, "delai_effectif", lambda *a, **k: 0)

    job = {"source_en_cours": None, "fiches_total_estime": 0, "fiches_traitees": 0}
    r = asyncio.run(jobs._traiter_source(job, source, 5))

    # Budget 5 : on veut 5 EXTRACTIONS, pas 5 visites.
    assert r["extractions"] == 5
    assert len(extraites) == 5
    assert r["ignorees_hash"] == 0 or r["traitees"] > 5   # les skips sont en plus


def test_plafond_de_visites_borne_le_temps_passe(env, monkeypatch):
    """Contrepartie : sans plafond de visites, une source aux milliers d'URLs
    déjà connues passerait la nuit à les revisiter (Crawl-delay oblige)."""
    import db as dbm
    import jobs
    from scraper import crawler

    source, urls = _source_fictive(50)
    for u in urls:                       # tout est connu et inchangé
        dbm.upsert_subside({"url_source": u, "titre": "T"}, "s", text_hash="h")

    async def faux_decouvrir(s, **kw):
        return crawler.ResultatCrawl(list(urls), "sitemap")

    async def faux_fiche(url, s, rapport, **kw):
        rapport["ignorees_hash"] += 1
        return "inchanges"

    monkeypatch.setattr(jobs.crawler, "decouvrir", faux_decouvrir)
    monkeypatch.setattr(jobs, "_traiter_fiche", faux_fiche)
    monkeypatch.setattr(jobs.robots, "autorise", lambda *a, **k: True)
    monkeypatch.setattr(jobs.robots, "delai_effectif", lambda *a, **k: 0)

    job = {"source_en_cours": None, "fiches_total_estime": 0, "fiches_traitees": 0}
    r = asyncio.run(jobs._traiter_source(job, source, 5))

    assert r["extractions"] == 0                              # rien n'a coûté
    assert r["traitees"] == 5 * jobs.FACTEUR_VISITES          # mais on s'est arrêté


# --- Surveillance des Content-Signal ----------------------------------------

ROBOTS_KBS = """\
User-agent: *
Content-Signal: search=yes,ai-train=no,use=reference
Allow: /

User-agent: ClaudeBot
Disallow: /

User-agent: *
Crawl-delay: 10
Disallow: /admin/
"""


def _monter_robots(monkeypatch, texte):
    from scraper import robots

    class FausseReponse:
        status_code = 200
        headers = {"content-type": "text/plain"}
        text = texte

    robots.reset_cache()
    monkeypatch.setattr(robots.httpx, "get", lambda *a, **k: FausseReponse())


def test_signaux_contenu_lus_sur_le_groupe_qui_nous_concerne(env, monkeypatch):
    from scraper import robots
    _monter_robots(monkeypatch, ROBOTS_KBS)
    sig = robots.signaux_contenu("https://kbs-frb.be/fr/x", "SubsidesAgentBot/0.1")
    assert sig == {"search": "yes", "ai-train": "no", "use": "reference"}
    # État actuel : rien qui nous vise. ai-train=no ne nous concerne pas, on
    # n'entraîne aucun modèle.
    assert robots.signaux_defavorables("https://kbs-frb.be/fr/x", "SubsidesAgentBot/0.1") == []


def test_alerte_si_ai_input_passe_a_no(env, monkeypatch):
    """LE scénario surveillé : le jour où le site interdit explicitement de
    donner son contenu à un modèle, on doit le voir."""
    from scraper import robots
    _monter_robots(monkeypatch, ROBOTS_KBS.replace(
        "search=yes,ai-train=no,use=reference", "search=yes,ai-input=no,ai-train=no"))
    assert robots.signaux_defavorables("https://kbs-frb.be/fr/x", "SubsidesAgentBot/0.1") \
        == ["ai-input"]


def test_alerte_si_search_passe_a_no(env, monkeypatch):
    from scraper import robots
    _monter_robots(monkeypatch, ROBOTS_KBS.replace("search=yes", "search=no"))
    assert "search" in robots.signaux_defavorables("https://kbs-frb.be/fr/x",
                                                   "SubsidesAgentBot/0.1")


def test_absence_de_signal_ne_declenche_rien(env, monkeypatch):
    """La plupart des sites n'en déclarent aucun : silence, pas d'alarme."""
    from scraper import robots
    _monter_robots(monkeypatch, "User-agent: *\nDisallow: /admin/\n")
    assert robots.signaux_contenu("https://ccf.brussels/x", "SubsidesAgentBot/0.1") == {}
    assert robots.signaux_defavorables("https://ccf.brussels/x", "SubsidesAgentBot/0.1") == []


def test_signal_defavorable_remonte_dans_le_rapport_de_source(env, monkeypatch):
    import jobs
    from scraper import crawler, robots

    _monter_robots(monkeypatch, ROBOTS_KBS.replace("ai-train=no", "ai-input=no"))

    async def faux_decouvrir(s, **kw):
        return crawler.ResultatCrawl([], "llm_links")

    monkeypatch.setattr(jobs.crawler, "decouvrir", faux_decouvrir)
    job = {"source_en_cours": None, "fiches_total_estime": 0, "fiches_traitees": 0}
    r = asyncio.run(jobs._traiter_source(
        job, {"id": "kbs_frb", "nom": "KBS", "strategie": "llm_links",
              "start_urls": ["https://kbs-frb.be/fr/rechercher"], "delai_secondes": 0}, 10))

    assert r["signaux_defavorables"] == ["ai-input"]
    assert any("ai-input=no" in e for e in r["erreurs"])

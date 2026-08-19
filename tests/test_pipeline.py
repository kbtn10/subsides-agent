"""Câblage de bout en bout, API Anthropic simulée.

Ces tests ne touchent ni le réseau ni l'API. Ils vérifient (a) que la requête
envoyée à Claude a la forme attendue, et (b) que crawl -> fetch -> extract ->
valide -> stocke s'enchaîne correctement, y compris quand ça casse.
"""

import importlib
import json
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-faux")
    monkeypatch.setenv("EXTRACTION_MODEL", "claude-haiku-4-5")
    monkeypatch.setenv("CONTACT_EMAIL", "test@example.com")
    import db as db_module
    importlib.reload(db_module)
    db_module.init_db()
    from scraper import extractor
    extractor.CLIENT = None      # forcer la reconstruction avec la clé factice
    yield db_module
    extractor.CLIENT = None
    conn = getattr(db_module._local, "conn", None)
    if conn:
        conn.close()
        db_module._local.conn = None


FICHE_JSON = {
    "titre": "Prime à l'embauche",
    "organisme": "Actiris",
    "description": "Aide à l'engagement d'un premier travailleur.",
    "montant": "5 000 €",
    "deadline": "2026-12-31",
    "permanent": False,
    "public_cible": "ASBL bruxelloises",
    "criteres_eligibilite": ["Siège en RBC"],
    "secteurs": ["Emploi"],
    "lien_candidature": "https://actiris.be/form",
    "langue": "fr",
}


def faux_message(payload, tokens_in=1200, tokens_out=180, stop_reason="end_turn"):
    bloc = MagicMock()
    bloc.type = "text"
    bloc.text = json.dumps(payload, ensure_ascii=False)
    msg = MagicMock()
    msg.content = [bloc]
    msg.stop_reason = stop_reason
    msg.usage.input_tokens = tokens_in
    msg.usage.output_tokens = tokens_out
    return msg


# --- Forme de la requête envoyée à Claude ----------------------------------

def test_forme_de_la_requete_extraction(env):
    from scraper import extractor

    faux = MagicMock()
    faux.messages.create.return_value = faux_message(FICHE_JSON)
    with patch.object(extractor, "_client", return_value=faux):
        res = extractor.extraire("texte de la fiche", "https://a.be/f")

    assert res.ok
    kwargs = faux.messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-haiku-4-5"
    # structured outputs : le JSON est contraint par le schéma
    fmt = kwargs["output_config"]["format"]
    assert fmt["type"] == "json_schema"
    assert fmt["schema"]["additionalProperties"] is False
    # url_source n'est PAS demandée au modèle (on la connaît déjà)
    assert "url_source" not in fmt["schema"]["properties"]
    # claude-haiku-4-5 ne supporte pas `effort` : il ne doit pas être envoyé
    assert "effort" not in kwargs.get("output_config", {})
    assert "thinking" not in kwargs
    assert "N'invente JAMAIS" in kwargs["system"]


def test_tokens_sont_comptes(env):
    from scraper import extractor
    faux = MagicMock()
    faux.messages.create.return_value = faux_message(FICHE_JSON, 999, 42)
    with patch.object(extractor, "_client", return_value=faux):
        res = extractor.extraire("texte", "https://a.be/f")
    assert (res.tokens_in, res.tokens_out) == (999, 42)


def test_temperature_zero_sur_haiku(env, monkeypatch):
    """Déterminisme : temperature=0 envoyée sur claude-haiku-4-5."""
    monkeypatch.setenv("EXTRACTION_MODEL", "claude-haiku-4-5")
    from scraper import extractor
    faux = MagicMock()
    faux.messages.create.return_value = faux_message(FICHE_JSON)
    with patch.object(extractor, "_client", return_value=faux):
        extractor.extraire("texte", "https://a.be/f")
    assert faux.messages.create.call_args.kwargs.get("temperature") == 0


def test_pas_de_temperature_sur_modele_46plus(env, monkeypatch):
    """opus-4-8 a retiré temperature -> ne pas l'envoyer (sinon 400)."""
    monkeypatch.setenv("EXTRACTION_MODEL", "claude-opus-4-8")
    from scraper import extractor
    faux = MagicMock()
    faux.messages.create.return_value = faux_message(FICHE_JSON)
    with patch.object(extractor, "_client", return_value=faux):
        extractor.extraire("texte", "https://a.be/f")
    assert "temperature" not in faux.messages.create.call_args.kwargs


def test_zone_geographique_dans_le_schema(env):
    from scraper.extractor import SCHEMA_SUBSIDE
    assert "zone_geographique" in SCHEMA_SUBSIDE["properties"]
    assert "zone_geographique" in SCHEMA_SUBSIDE["required"]


def test_client_retries_sdk_configures(env):
    """Les retries 429/5xx sont délégués au SDK : max_retries=2."""
    from scraper import extractor
    with patch("anthropic.Anthropic") as ctor:
        extractor.CLIENT = None
        extractor._client()
    assert ctor.call_args.kwargs["max_retries"] == 2


@pytest.mark.parametrize("stop_reason,motif", [
    ("refusal", "refus"),
    ("max_tokens", "tronquée"),
])
def test_stop_reasons_problematiques(env, stop_reason, motif):
    from scraper import extractor
    faux = MagicMock()
    faux.messages.create.return_value = faux_message(FICHE_JSON, stop_reason=stop_reason)
    with patch.object(extractor, "_client", return_value=faux):
        res = extractor.extraire("texte", "https://a.be/f")
    assert not res.ok and motif in res.erreur


def test_erreur_api_ne_leve_pas(env):
    import anthropic
    from scraper import extractor
    faux = MagicMock()
    faux.messages.create.side_effect = anthropic.APIConnectionError(request=MagicMock())
    with patch.object(extractor, "_client", return_value=faux):
        res = extractor.extraire("texte", "https://a.be/f")
    assert not res.ok and "api_connection" in res.erreur


# --- Anti-hallucination sur le tri des liens -------------------------------

def test_urls_inventees_par_le_llm_sont_ecartees(env):
    from scraper import extractor
    liens = [("https://a.be/vrai", "Appel à projets X")]
    faux = MagicMock()
    faux.messages.create.return_value = faux_message(
        {"urls": ["https://a.be/vrai", "https://a.be/INVENTE"]}
    )
    with patch.object(extractor, "_client", return_value=faux):
        res = extractor.identifier_liens_fiches(liens, "https://a.be/listing")
    assert res.data["urls"] == ["https://a.be/vrai"]   # l'URL inventée a sauté


# --- Pipeline complet ------------------------------------------------------

@pytest.mark.asyncio
async def test_pipeline_nominal(env):
    import jobs
    from scraper import crawler

    rapport = {"tokens_in": 0, "tokens_out": 0, "erreurs": [], "a_verifier": 0}
    faux = MagicMock()
    faux.messages.create.return_value = faux_message(FICHE_JSON)

    with patch("jobs.recuperer_texte", return_value=("texte long de la fiche", "<html/>")), \
         patch("scraper.extractor._client", return_value=faux):
        statut = await jobs._traiter_fiche("https://a.be/fiche", {"id": "s1"}, rapport)

    assert statut == "nouveaux"
    ligne = env.lister_subsides()[0]
    assert ligne["titre"] == "Prime à l'embauche"
    assert ligne["statut"] == "nouveau"
    assert ligne["deadline"] == "2026-12-31"
    assert rapport["tokens_in"] == 1200


@pytest.mark.asyncio
async def test_court_circuit_hash_evite_l_appel_llm(env):
    """Hash identique au run précédent -> 'inchange' SANS appeler l'extracteur."""
    import jobs

    faux = MagicMock()
    faux.messages.create.return_value = faux_message(FICHE_JSON)
    rapport = {"tokens_in": 0, "tokens_out": 0, "erreurs": [], "a_verifier": 0}

    # 1er passage : extraction + stockage du hash
    with patch("jobs.recuperer_texte", return_value=("texte identique", "<html/>")), \
         patch("scraper.extractor._client", return_value=faux):
        s1 = await jobs._traiter_fiche("https://a.be/f", {"id": "s1"}, rapport)
    assert s1 == "nouveaux"
    assert faux.messages.create.call_count == 1

    # 2e passage : même texte -> même hash -> pas de nouvel appel
    with patch("jobs.recuperer_texte", return_value=("texte identique", "<html/>")), \
         patch("scraper.extractor._client", return_value=faux):
        s2 = await jobs._traiter_fiche("https://a.be/f", {"id": "s1"}, rapport)
    assert s2 == "inchanges"
    assert faux.messages.create.call_count == 1      # AUCUN appel supplémentaire
    assert rapport["ignorees_hash"] == 1


@pytest.mark.asyncio
async def test_texte_modifie_declenche_reextraction(env):
    import jobs
    faux = MagicMock()
    faux.messages.create.return_value = faux_message(FICHE_JSON)
    rapport = {"tokens_in": 0, "tokens_out": 0, "erreurs": [], "a_verifier": 0}

    with patch("jobs.recuperer_texte", return_value=("texte v1", "<html/>")), \
         patch("scraper.extractor._client", return_value=faux):
        await jobs._traiter_fiche("https://a.be/f", {"id": "s1"}, rapport)

    # Texte différent -> hash différent -> ré-extraction (2e appel)
    with patch("jobs.recuperer_texte", return_value=("texte v2 modifié", "<html/>")), \
         patch("scraper.extractor._client", return_value=faux):
        await jobs._traiter_fiche("https://a.be/f", {"id": "s1"}, rapport)
    assert faux.messages.create.call_count == 2


@pytest.mark.asyncio
async def test_forcer_ignore_le_hash(env):
    """Le backfill (forcer=True) ré-extrait même si le hash est identique."""
    import jobs
    faux = MagicMock()
    faux.messages.create.return_value = faux_message(FICHE_JSON)
    rapport = {"tokens_in": 0, "tokens_out": 0, "erreurs": [], "a_verifier": 0}

    with patch("jobs.recuperer_texte", return_value=("texte", "<html/>")), \
         patch("scraper.extractor._client", return_value=faux):
        await jobs._traiter_fiche("https://a.be/f", {"id": "s1"}, rapport)
        await jobs._traiter_fiche("https://a.be/f", {"id": "s1"}, rapport, forcer=True)
    assert faux.messages.create.call_count == 2      # forcé -> 2e appel malgré hash identique


@pytest.mark.asyncio
async def test_zone_bout_en_bout(env):
    """La zone extraite est catégorisée et stockée."""
    import jobs
    faux = MagicMock()
    faux.messages.create.return_value = faux_message(
        {**FICHE_JSON, "zone_geographique": "Région de Bruxelles-Capitale"})
    rapport = {"tokens_in": 0, "tokens_out": 0, "erreurs": [], "a_verifier": 0}
    with patch("jobs.recuperer_texte", return_value=("texte", "<html/>")), \
         patch("scraper.extractor._client", return_value=faux):
        await jobs._traiter_fiche("https://a.be/f", {"id": "s1"}, rapport)
    ligne = env.lister_subsides()[0]
    assert ligne["zone_categorie"] == "bruxelles"
    assert ligne["zone_geographique"] == "Région de Bruxelles-Capitale"


@pytest.mark.asyncio
async def test_page_illisible_donne_echec_extraction(env):
    import jobs
    rapport = {"tokens_in": 0, "tokens_out": 0, "erreurs": [], "a_verifier": 0}
    with patch("jobs.recuperer_texte", return_value=(None, None)):
        statut = await jobs._traiter_fiche("https://a.be/mort", {"id": "s1"}, rapport)
    assert statut == "echecs"
    assert env.lister_subsides()[0]["statut"] == "echec_extraction"


@pytest.mark.asyncio
async def test_json_malforme_stocke_le_brut(env):
    import jobs
    from scraper import extractor

    bloc = MagicMock(); bloc.type = "text"; bloc.text = "je ne suis pas du JSON"
    msg = MagicMock(); msg.content = [bloc]; msg.stop_reason = "end_turn"
    msg.usage.input_tokens = 10; msg.usage.output_tokens = 5
    faux = MagicMock(); faux.messages.create.return_value = msg

    rapport = {"tokens_in": 0, "tokens_out": 0, "erreurs": [], "a_verifier": 0}
    with patch("jobs.recuperer_texte", return_value=("le texte brut", "<html/>")), \
         patch("scraper.extractor._client", return_value=faux):
        statut = await jobs._traiter_fiche("https://a.be/f", {"id": "s1"}, rapport)

    assert statut == "echecs"
    s = env.get_subside(env.lister_subsides()[0]["id"])
    assert s["statut"] == "echec_extraction"
    assert s["raw_text"] == "le texte brut"      # brut conservé pour inspection


@pytest.mark.asyncio
async def test_deadline_aberrante_marque_a_verifier(env):
    import jobs
    from scraper import extractor

    faux = MagicMock()
    faux.messages.create.return_value = faux_message({**FICHE_JSON, "deadline": "1999-01-01"})
    rapport = {"tokens_in": 0, "tokens_out": 0, "erreurs": [], "a_verifier": 0}
    with patch("jobs.recuperer_texte", return_value=("texte", "<html/>")), \
         patch("scraper.extractor._client", return_value=faux):
        await jobs._traiter_fiche("https://a.be/f", {"id": "s1"}, rapport)

    ligne = env.lister_subsides()[0]
    assert ligne["a_verifier"] is True
    # Une date hors bornes mais bien formée est CONSERVÉE et signalée : la jeter
    # en silence serait pire que l'afficher avec un badge "à vérifier".
    assert ligne["deadline"] == "1999-01-01"
    assert rapport["a_verifier"] == 1
    assert any("antérieure" in e for e in ligne["erreurs_validation"])


@pytest.mark.asyncio
async def test_une_source_qui_explose_ne_tue_pas_le_job(env):
    """Tolérance aux pannes : la source 2 doit tourner même si la source 1 explose."""
    import jobs

    appels = []

    # **_ : la signature de production accepte désormais `backfill` (lot 5).
    async def faux_traiter_source(job, source, budget, **_):
        appels.append(source["id"])
        if source["id"] == "boom":
            raise RuntimeError("source cassée")
        return {"source_id": source["id"], "nom": source["nom"], "statut": "ok",
                "traitees": 1, "nouveaux": 1, "modifies": 0, "inchanges": 0,
                "echecs": 0, "a_verifier": 0, "fiches_trouvees": 1,
                "tokens_in": 0, "tokens_out": 0, "erreurs": []}

    sources = [
        {"id": "boom", "nom": "Cassée", "strategie": "sitemap"},
        {"id": "ok", "nom": "Saine", "strategie": "sitemap"},
    ]
    with patch("jobs.sources_actives", return_value=sources), \
         patch("jobs._traiter_source", side_effect=faux_traiter_source), \
         patch("jobs.fermer_browser"):
        job_id = await jobs.creer_job()
        job = jobs.get_job(job_id)
        while job["statut"] == "running":
            import asyncio
            await asyncio.sleep(0.02)

    assert appels == ["boom", "ok"]           # la 2e source a bien tourné
    assert job["statut"] == "done"            # pas de crash global
    rapports = {r["source_id"]: r for r in job["rapport"]["sources"]}
    assert rapports["boom"]["statut"] == "echec"
    assert rapports["ok"]["statut"] == "ok"
    assert job["rapport"]["total_nouveaux"] == 1


@pytest.mark.asyncio
async def test_un_seul_job_a_la_fois(env):
    import jobs
    with patch("jobs.sources_actives", return_value=[]), patch("jobs.fermer_browser"):
        job_id = await jobs.creer_job()
        jobs.get_job(job_id)["statut"] = "running"   # fige l'état
        with pytest.raises(RuntimeError, match="déjà en cours"):
            await jobs.creer_job()
        jobs.get_job(job_id)["statut"] = "done"


def test_estimation_cout(env):
    import jobs
    # haiku 4.5 : $1/MTok in, $5/MTok out
    assert jobs._estimer_cout(1_000_000, 0) == 1.0
    assert jobs._estimer_cout(0, 1_000_000) == 5.0
    assert jobs._estimer_cout(0, 0) == 0.0


# --- Budget par source (le fond corrigé) -----------------------------------

async def _run_budget(monkeypatch, budget, fiches_par_source):
    """Lance un job en simulant N fiches trouvées par source, renvoie
    {source_id: nb_traitees}. Aucun réseau ni API : _traiter_source est câblé
    à travers _traiter_fiche mockée."""
    import jobs
    monkeypatch.setenv("MAX_FICHES_PAR_RUN", str(budget))

    sources = [{"id": sid, "nom": sid, "strategie": "sitemap", "delai_secondes": 0,
                "rendu_js": False} for sid in fiches_par_source]

    async def faux_decouvrir(source, **_):
        from scraper.crawler import ResultatCrawl
        n = fiches_par_source[source["id"]]
        return ResultatCrawl([f"https://{source['id']}.be/{i}" for i in range(n)], "sitemap")

    async def faux_fiche(url, source, rapport, **_):
        return "nouveaux"

    import asyncio
    # delai_effectif mocké à 0 -> les asyncio.sleep(0) de la boucle sont instantanés,
    # inutile (et dangereux) de patcher asyncio.sleep lui-même.
    with patch("jobs.sources_actives", return_value=sources), \
         patch("jobs.crawler.decouvrir", side_effect=faux_decouvrir), \
         patch("jobs._traiter_fiche", side_effect=faux_fiche), \
         patch("jobs.robots.autorise", return_value=True), \
         patch("jobs.robots.delai_effectif", return_value=0), \
         patch("jobs.fermer_browser"):
        job_id = await jobs.creer_job()
        job = jobs.get_job(job_id)
        while job["statut"] == "running":
            await asyncio.sleep(0.01)

    return {r["source_id"]: r["traitees"] for r in job["rapport"]["sources"]}, job


async def test_petit_budget_ne_prive_pas_la_seconde_source(env, monkeypatch):
    """Le cas qui a motivé le correctif : budget=5, hub a 109 fiches, KBS 15.
    Avant, hub mangeait les 5 et KBS était 'ignoree'. Maintenant KBS a sa part."""
    traitees, job = await _run_budget(monkeypatch, 5, {"hub": 109, "kbs": 15})
    assert traitees["kbs"] >= 2               # KBS n'est plus affamé
    assert traitees["hub"] >= 2
    assert sum(traitees.values()) <= 5        # plafond global respecté
    assert all(r["statut"] != "ignoree" for r in job["rapport"]["sources"])


async def test_budget_realiste_les_deux_sources_servies(env, monkeypatch):
    traitees, _ = await _run_budget(monkeypatch, 150, {"hub": 109, "kbs": 15})
    assert traitees["hub"] == 75              # plancher 150//2, hub en a assez
    assert traitees["kbs"] == 15              # KBS prend tout ce qu'il a


async def test_source_sobre_laisse_le_rab_a_la_suivante(env, monkeypatch):
    """hub ne trouve que 3 fiches -> KBS peut dépasser son plancher grâce au rab."""
    traitees, _ = await _run_budget(monkeypatch, 20, {"hub": 3, "kbs": 100})
    assert traitees["hub"] == 3
    assert traitees["kbs"] == 17              # 20 - 3, au-delà du plancher de 10
    assert sum(traitees.values()) == 20


async def test_plafond_global_jamais_depasse(env, monkeypatch):
    traitees, _ = await _run_budget(monkeypatch, 10, {"a": 50, "b": 50, "c": 50})
    assert sum(traitees.values()) <= 10
    # 10//3 = 3 de plancher chacune, aucune affamée
    assert all(v >= 3 for v in traitees.values())


async def test_budget_cinq_sources_toutes_servies(env, monkeypatch):
    """Critère d'acceptation lot 2 : avec 5 sources et MAX=30, la répartition
    tient et aucune source n'est affamée."""
    fiches = {"hub": 109, "kbs": 8, "cocof": 40, "equal": 5, "culture": 7}
    traitees, job = await _run_budget(monkeypatch, 30, fiches)
    assert sum(traitees.values()) <= 30
    assert all(r["statut"] != "ignoree" for r in job["rapport"]["sources"])
    # plancher 30//5 = 6 ; chaque source prend min(6+rab, ce qu'elle a)
    assert traitees["equal"] == 5      # en a moins que le plancher -> tout pris
    assert all(v >= 1 for v in traitees.values())

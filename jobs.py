"""Gestion des jobs de scraping : un seul à la fois, tolérant aux pannes.

Règle centrale : une source qui explose ne fait pas tomber le run. Son erreur est
capturée, consignée dans le rapport, et les sources suivantes s'exécutent.
"""

import asyncio
import logging
import os
import time
import uuid
from datetime import datetime, timezone

import db
from config.sources import sources_actives
from scraper import crawler, extractor, pdfs, robots, validator
from scraper.fetcher import fermer_browser, recuperer_texte, user_agent

log = logging.getLogger(__name__)

# Tarifs claude-haiku-4-5 ($ / million de tokens), pour l'estimation de coût.
# À ajuster si tu changes EXTRACTION_MODEL (voir README § Coûts).
TARIFS = {
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-opus-4-8": (5.00, 25.00),
}

# Visites autorisées par place de budget. Le budget compte les extractions
# (coût LLM) ; ce facteur borne le temps passé à revisiter des fiches déjà
# connues, dont le hash montrera qu'elles n'ont pas bougé.
FACTEUR_VISITES = 3

_jobs: dict[str, dict] = {}
_lock = asyncio.Lock()


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def job_en_cours() -> str | None:
    for jid, j in _jobs.items():
        if j["statut"] == "running":
            return jid
    return None


def get_job(job_id: str):
    return _jobs.get(job_id)


def _estimer_cout(tokens_in: int, tokens_out: int) -> float:
    prix_in, prix_out = TARIFS.get(extractor.modele(), (0.0, 0.0))
    return round(tokens_in / 1e6 * prix_in + tokens_out / 1e6 * prix_out, 4)


async def creer_job(source_id: str | None = None, backfill: bool = False) -> str:
    """Lance un scrape. `source_id` le limite à une source (backfills ciblés),
    `backfill` relit tout en profondeur et ignore le court-circuit du hash."""
    from config.sources import get_source

    if source_id:
        s = get_source(source_id)
        if s is None:
            raise LookupError(f"source inconnue : {source_id}")
        if not s.get("actif"):
            raise LookupError(f"source inactive : {source_id}")

    async with _lock:
        if (existant := job_en_cours()):
            raise RuntimeError(f"Un job est déjà en cours ({existant})")
        # Verrou inter-process : `_jobs` ne connaît que les jobs de CE process.
        # Un script lancé à côté de l'API démarrerait sinon un second scrape, et
        # deux crawlers taperaient les mêmes sites en parallèle.
        if (autre := db.scrape_run_en_cours()):
            raise RuntimeError(
                f"Un scrape tourne déjà (run {autre['id']}, démarré il y a "
                f"{autre['age_minutes']} min, peut-être dans un autre process)")
        job_id = str(uuid.uuid4())
        _jobs[job_id] = {
            "job_id": job_id,
            "statut": "running",
            "source_en_cours": None,
            "source_ciblee": source_id,
            "backfill": bool(backfill),
            "fiches_traitees": 0,
            "fiches_total_estime": 0,
            "erreurs": [],
            "rapport": None,
            "demarre_a": _now(),
        }
    asyncio.create_task(_executer(job_id, source_id=source_id, backfill=bool(backfill)))
    return job_id


async def _traiter_source(job: dict, source: dict, budget_restant: int,
                          backfill: bool = False) -> dict:
    """Scrape une source. Ne lève jamais : encapsule tout dans son rapport."""
    rapport = {
        "source_id": source["id"],
        "nom": source["nom"],
        "strategie": source["strategie"],
        "strategie_utilisee": None,
        "fiches_trouvees": 0,
        "traitees": 0,
        "nouveaux": 0,
        "modifies": 0,
        "inchanges": 0,
        "a_verifier": 0,
        "echecs": 0,
        "ignorees_robots": 0,
        "ignorees_hash": 0,   # fiches inchangées détectées par le hash (0 appel LLM)
        "extractions": 0,     # appels LLM réels — c'est CE compteur que le budget plafonne
        "tokens_in": 0,
        "tokens_out": 0,
        "erreurs": [],
        "statut": "ok",
        # Lot 5
        "backfill": bool(backfill),
        "apports": [],            # apport propre de chaque point d'entrée
        "pages_listing": 0,
        "arret_anticipe": False,
        "fiches_avec_pdf": 0,
        "pdf_exploites": 0,
        "pdf_ignores": 0,
        "caracteres_pdf": 0,      # pour chiffrer le surcoût de tokens
    }

    job["source_en_cours"] = source["nom"]
    ua = user_agent()

    # Surveillance des Content-Signal (lot 5). Ils ne bloquent rien
    # techniquement, mais ils disent ce que le site veut. On relève l'état à
    # chaque run et on crie si un signal qui nous concerne passe à « no » —
    # c'est un humain qui décide ensuite d'arrêter la source, pas le code.
    for depart in source.get("start_urls", []):
        rapport["signaux_contenu"] = robots.signaux_contenu(depart, ua)
        defavorables = robots.signaux_defavorables(depart, ua)
        if defavorables:
            msg = (f"le site déclare désormais {', '.join(f'{s}=no' for s in defavorables)} "
                   f"— ce signal vise directement notre usage")
            log.error("!!! SIGNAL DE CONTENU DÉFAVORABLE sur %s : %s. "
                      "Décision humaine requise : passer la source en actif=False "
                      "ou contacter l'organisme. Voir README § Conformité.",
                      source["id"], msg)
            rapport["erreurs"].append(msg)
            rapport["signaux_defavorables"] = defavorables
        break  # le robots.txt vaut pour le host, une URL de départ suffit

    try:
        # L'arrêt anticipé du mode delta a besoin de savoir ce qu'on connaît déjà.
        connues = None if backfill else db.urls_connues(source["id"])
        res = await crawler.decouvrir(source, backfill=backfill, urls_connues=connues)
    except Exception as e:
        log.exception("[%s] découverte KO", source["id"])
        rapport["statut"] = "echec"
        rapport["erreurs"].append(f"découverte: {type(e).__name__}: {e}")
        return rapport

    rapport["strategie_utilisee"] = res.strategie_utilisee
    rapport["fiches_trouvees"] = len(res.urls)
    rapport["tokens_in"] += res.tokens_in
    rapport["tokens_out"] += res.tokens_out
    rapport["erreurs"].extend(res.erreurs)
    rapport["apports"] = res.apports
    rapport["pages_listing"] = res.pages_lues
    rapport["arret_anticipe"] = res.arret_anticipe
    for a in res.apports:
        log.info("[%s]   point d'entrée '%s' : %d trouvée(s), %d en propre",
                 source["id"], a["nom"], a["trouvees"], a["en_propre"])

    # TRI, en delta comme en backfill : d'abord ce qu'on n'a jamais vu, puis le
    # plus anciennement vérifié. Sans lui, l'ordre du sitemap est stable et le
    # cron reprend chaque nuit les MÊMES N premières fiches : hub.brussels
    # revisitait ses 40 premières sur 109 et les 69 autres étaient inatteignables
    # à vie (vérifié : 40/40 des premières en base, 0/69 des suivantes).
    deja_vues = db.dates_verification(source["id"])
    ordonnees = sorted(res.urls, key=lambda u: deja_vues.get(db.normaliser_url(u)) or "")
    jamais_vues = sum(1 for u in res.urls if db.normaliser_url(u) not in deja_vues)
    if jamais_vues:
        log.info("[%s] %d URL(s) dont %d jamais vue(s) — les neuves d'abord",
                 source["id"], len(res.urls), jamais_vues)

    # Le budget plafonne les EXTRACTIONS, pas les visites : une fiche
    # court-circuitée par le hash ne coûte aucun token, elle n'a donc pas à
    # consommer une place du garde-fou de coût. Un plafond de visites reste
    # nécessaire, sinon une source à 5 000 URLs connues passerait la nuit à les
    # revisiter pour rien (le temps, lui, se paie en Crawl-delay).
    plafond_visites = budget_restant * FACTEUR_VISITES
    extractions, visites = 0, 0

    job["fiches_total_estime"] += min(len(ordonnees), plafond_visites)

    for url in ordonnees:
        if extractions >= budget_restant:
            restantes = len(ordonnees) - visites
            msg = (f"budget MAX_FICHES_PAR_RUN atteint : {restantes} fiche(s) non "
                   f"traitée(s) sur cette source — le prochain run les prendra "
                   f"en premier")
            log.warning("[%s] %s", source["id"], msg)
            rapport["erreurs"].append(msg)
            break
        if visites >= plafond_visites:
            msg = (f"plafond de visites atteint ({plafond_visites}) : "
                   f"{len(ordonnees) - visites} fiche(s) non revisitée(s)")
            log.info("[%s] %s", source["id"], msg)
            break

        if not robots.autorise(url, ua):
            log.warning("robots.txt interdit %s — ignorée", url)
            rapport["ignorees_robots"] += 1
            continue

        avant_hash = rapport["ignorees_hash"]
        try:
            statut = await _traiter_fiche(url, source, rapport, forcer=backfill)
            if statut:
                rapport[statut] = rapport.get(statut, 0) + 1
        except Exception as e:
            log.exception("Fiche KO %s", url)
            rapport["echecs"] += 1
            rapport["erreurs"].append(f"{url}: {type(e).__name__}: {e}")

        # Court-circuitée par le hash = aucun appel LLM = hors budget.
        if rapport["ignorees_hash"] == avant_hash:
            extractions += 1
        visites += 1
        rapport["traitees"] += 1
        job["fiches_traitees"] += 1

        delai = robots.delai_effectif(url, ua, source.get("delai_secondes", 1.5))
        await asyncio.sleep(delai)

    rapport["extractions"] = extractions

    if rapport["echecs"] and rapport["echecs"] == rapport["traitees"] and rapport["traitees"]:
        rapport["statut"] = "echec"
    elif rapport["erreurs"]:
        rapport["statut"] = "partiel"
    return rapport


async def _traiter_fiche(url: str, source: dict, rapport: dict,
                         forcer: bool = False) -> str | None:
    """Charge -> (hash) -> extrait -> valide -> stocke. Renvoie la clé de compteur.

    `forcer=True` ignore le court-circuit du hash (utilisé par le backfill).
    """
    texte, html = await recuperer_texte(url, rendu_js=source.get("rendu_js", False))
    if not texte:
        db.upsert_subside({"url_source": url}, source["id"], raw_text=None,
                          echec_extraction=True, erreurs=["page vide ou illisible"])
        rapport["erreurs"].append(f"{url}: page vide ou illisible")
        return "echecs"

    # Annexes PDF (lot 5) : le règlement porte souvent les vrais critères.
    annexes = []
    if html:
        try:
            annexes = await pdfs.collecter_annexes(html, url, source)
        except Exception as e:      # une annexe ne doit JAMAIS tuer une fiche
            log.warning("Annexes PDF KO sur %s : %s: %s", url, type(e).__name__, e)
            rapport["erreurs"].append(f"{url}: annexes PDF: {type(e).__name__}")

    if annexes:
        rapport["fiches_avec_pdf"] = rapport.get("fiches_avec_pdf", 0) + 1
        rapport["pdf_exploites"] = rapport.get("pdf_exploites", 0) + len(annexes)
        rapport["caracteres_pdf"] = rapport.get("caracteres_pdf", 0) + sum(
            a["caracteres"] for a in annexes)

    texte_complet = pdfs.composer_texte(texte, annexes)

    # Court-circuit hash : si le texte source n'a pas bougé depuis le dernier
    # run réussi, inutile de repayer un appel LLM — on marque juste 'inchange'.
    # C'est ce qui rend un re-run quasi gratuit (critère d'acceptation).
    # Le hash couvre page + annexes, mais via le TEXTE EXTRAIT : un PDF
    # regénéré à chaque requête (date de production dans les métadonnées) a des
    # octets différents à contenu identique — hasher les octets ferait passer la
    # fiche pour « modifiée » à chaque run.
    text_hash = db.hash_texte(texte_complet)
    if not forcer and db.hash_connu(url) == text_hash:
        rapport["ignorees_hash"] = rapport.get("ignorees_hash", 0) + 1
        return {"inchange": "inchanges"}.get(db.toucher(url))

    # L'appel SDK est bloquant -> thread, pour ne pas geler la boucle asyncio.
    res = await asyncio.to_thread(extractor.extraire, texte_complet, url)
    rapport["tokens_in"] += res.tokens_in
    rapport["tokens_out"] += res.tokens_out

    if not res.ok:
        db.upsert_subside({"url_source": url}, source["id"], raw_text=texte,
                          echec_extraction=True, erreurs=[res.erreur])
        rapport["erreurs"].append(f"{url}: extraction: {res.erreur}")
        return "echecs"

    val = validator.valider(res.data, url)
    if not val.ok:
        # Échec dur : on garde le brut pour pouvoir inspecter ce qui a foiré.
        db.upsert_subside({"url_source": url}, source["id"], raw_text=texte,
                          echec_extraction=True, erreurs=val.erreurs)
        rapport["erreurs"].append(f"{url}: validation: {'; '.join(val.erreurs)}")
        return "echecs"

    statut = db.upsert_subside(
        val.subside, source["id"],
        raw_text=texte_complet if val.a_verifier else None,
        a_verifier=val.a_verifier,
        erreurs=val.erreurs,
        text_hash=text_hash,
        # Liste vide = « on a regardé, il n'y a pas d'annexe » : on écrase
        # l'ancienne valeur, sinon un règlement retiré resterait affiché.
        annexes_pdf=[{"url": a["url"], "ancre": a["ancre"],
                      "caracteres": a["caracteres"]} for a in annexes],
    )
    # Une fiche qui change invalide ses jugements de matching : ils seront
    # re-calculés à la prochaine consultation des profils concernés.
    if statut == "modifie":
        import matching
        sub_id = db.id_par_url(url)
        if sub_id is not None:
            n = matching.invalider_pour_subside(sub_id)
            if n:
                rapport["matchings_invalides"] = rapport.get("matchings_invalides", 0) + n
    if val.a_verifier:
        rapport["a_verifier"] += 1
    return {"nouveau": "nouveaux", "modifie": "modifies", "inchange": "inchanges"}.get(statut)


async def _executer(job_id: str, source_id: str | None = None, backfill: bool = False):
    job = _jobs[job_id]
    debut = time.monotonic()
    budget = int(os.getenv("MAX_FICHES_PAR_RUN", "200"))
    rapports = []
    run_id = db.debuter_scrape_run()  # persiste début/fin pour « données à jour il y a X h »

    log.info("=== Job %s démarré (budget: %d fiches, modèle: %s%s%s) ===",
             job_id, budget, extractor.modele(),
             f", source ciblée: {source_id}" if source_id else "",
             ", BACKFILL" if backfill else "")

    try:
        sources = sources_actives()
        # Source ciblée : elle est seule, donc elle prend tout le budget (la
        # répartition équitable n'a plus d'objet).
        if source_id:
            sources = [s for s in sources if s["id"] == source_id]
        if not sources:
            job["erreurs"].append(
                f"source '{source_id}' introuvable ou inactive" if source_id
                else "aucune source active dans config/sources.py")

        # Budget PAR SOURCE avec réserve. Chaque source active a un plancher
        # garanti (budget // n) ; une source qui en utilise moins laisse le rab
        # aux suivantes, mais jamais au point d'affamer une source pas encore
        # traitée. Sans ça, la 1re source (hub.brussels, 109 fiches) mangeait
        # tout le budget et KBS était systématiquement sauté.
        n = len(sources)
        plancher = budget // n if n else 0
        budget_restant = budget
        log.info("Budget %d réparti sur %d source(s) : plancher %d/source",
                 budget, n, plancher)

        for i, source in enumerate(sources):
            # On garde de côté le plancher de chaque source qui vient APRÈS.
            reserve = plancher * (n - i - 1)
            cap_source = budget_restant - reserve
            if cap_source <= 0:
                # N'arrive que si budget < n (impossible de répartir 1 place
                # sur 2 sources). Au-delà, la réserve garantit cap_source >= plancher.
                log.warning("Budget insuffisant — source %s non traitée", source["id"])
                rapports.append({
                    "source_id": source["id"], "nom": source["nom"],
                    "statut": "ignoree", "traitees": 0, "nouveaux": 0, "modifies": 0,
                    "inchanges": 0, "echecs": 0, "a_verifier": 0, "fiches_trouvees": 0,
                    "tokens_in": 0, "tokens_out": 0,
                    "erreurs": [f"budget trop petit ({budget}) pour {n} sources — "
                                f"augmente MAX_FICHES_PAR_RUN"],
                })
                continue

            # Filet de sécurité : _traiter_source capture déjà tout, mais on ne
            # veut sous aucun prétexte qu'une source fasse tomber le job entier.
            try:
                r = await _traiter_source(job, source, cap_source, backfill=backfill)
            except Exception as e:
                log.exception("[%s] source KO", source["id"])
                r = {
                    "source_id": source["id"], "nom": source["nom"], "statut": "echec",
                    "traitees": 0, "nouveaux": 0, "modifies": 0, "inchanges": 0,
                    "echecs": 0, "a_verifier": 0, "fiches_trouvees": 0,
                    "tokens_in": 0, "tokens_out": 0,
                    "erreurs": [f"{type(e).__name__}: {e}"],
                }
            rapports.append(r)
            budget_restant -= r.get("extractions", r["traitees"])
            job["erreurs"].extend(f"[{r['source_id']}] {e}" for e in r["erreurs"])

            # Santé persistante + alerte « source morte » : 0 URL découverte
            # alors qu'un passage précédent en trouvait = structure du site
            # probablement cassée. C'est le signal le plus utile qu'on ait.
            try:
                if db.enregistrer_sante_source(r):
                    log.error(
                        "!!! SOURCE MUETTE : %s (%s) n'a découvert AUCUNE URL alors "
                        "qu'elle en trouvait aux runs précédents. Structure du site "
                        "probablement modifiée — vérifie config/sources.py.",
                        r["source_id"], r.get("nom", ""))
                    job["erreurs"].append(
                        f"[{r['source_id']}] source muette : 0 URL découverte "
                        f"(elle en trouvait avant)")
            except Exception:
                log.exception("Enregistrement santé source KO (%s)", r.get("source_id"))

        t_in = sum(r["tokens_in"] for r in rapports)
        t_out = sum(r["tokens_out"] for r in rapports)
        car_pdf = sum(r.get("caracteres_pdf", 0) for r in rapports)
        job["rapport"] = {
            "duree_secondes": round(time.monotonic() - debut, 1),
            "modele": extractor.modele(),
            "source_ciblee": source_id,
            "backfill": backfill,
            "total_fiches": sum(r["traitees"] for r in rapports),
            "total_nouveaux": sum(r["nouveaux"] for r in rapports),
            "total_modifies": sum(r["modifies"] for r in rapports),
            "total_inchanges": sum(r["inchanges"] for r in rapports),
            "total_a_verifier": sum(r["a_verifier"] for r in rapports),
            "total_echecs": sum(r["echecs"] for r in rapports),
            "tokens_in": t_in,
            "tokens_out": t_out,
            "cout_estime_usd": _estimer_cout(t_in, t_out),
            # Surcoût PDF : les caractères d'annexe passés au LLM, convertis en
            # tokens (~4 car./token) au prix d'entrée. Chiffre le prix réel de
            # la partie 4 sur chaque run.
            "pdf_fiches_enrichies": sum(r.get("fiches_avec_pdf", 0) for r in rapports),
            "pdf_exploites": sum(r.get("pdf_exploites", 0) for r in rapports),
            "pdf_caracteres": car_pdf,
            "pdf_surcout_usd": _estimer_cout(car_pdf // 4, 0),
            "sources": rapports,
        }
        job["statut"] = "done"
        log.info("=== Job %s terminé en %.1fs : %d nouveaux, %d modifiés, %d échecs "
                 "| %d tokens in / %d out (~$%.4f) ===",
                 job_id, job["rapport"]["duree_secondes"], job["rapport"]["total_nouveaux"],
                 job["rapport"]["total_modifies"], job["rapport"]["total_echecs"],
                 t_in, t_out, job["rapport"]["cout_estime_usd"])

    except Exception as e:
        log.exception("Job %s : échec global", job_id)
        job["statut"] = "error"
        job["erreurs"].append(f"échec global: {type(e).__name__}: {e}")
        job["rapport"] = {
            "duree_secondes": round(time.monotonic() - debut, 1),
            "sources": rapports,
            "erreur": str(e),
        }
    finally:
        job["source_en_cours"] = None
        job["termine_a"] = _now()
        db.cloturer_scrape_run(run_id, job.get("rapport") or {})
        await fermer_browser()


# ==================== Jobs de MATCHING (lot 3) ====================

_matching_jobs: dict[str, dict] = {}
JUGEMENTS_CONCURRENTS = 4


def matching_en_cours(profil_id) -> str | None:
    for jid, j in _matching_jobs.items():
        if j["statut"] == "running" and j["profil_id"] == profil_id:
            return jid
    return None


def get_matching_job(job_id: str):
    return _matching_jobs.get(job_id)


async def creer_job_matching(profil_id: int) -> str:
    import profils
    async with _lock:
        if matching_en_cours(profil_id):
            raise RuntimeError(f"un matching tourne déjà pour le profil {profil_id}")
        profil = profils.get_profil(profil_id)
        if profil is None:
            raise LookupError(f"profil {profil_id} inconnu")
        job_id = str(uuid.uuid4())
        _matching_jobs[job_id] = {
            "job_id": job_id, "profil_id": profil_id, "statut": "running",
            "total_candidats": 0, "traites": 0, "matchs": 0,
            "resultats": [], "erreurs": [],
            "tokens_in": 0, "tokens_out": 0, "cout_estime_usd": 0.0,
            "demarre_a": _now(),
        }
    asyncio.create_task(_executer_matching(job_id, profil))
    return job_id


async def _juger_candidat(job, profil, subside, semaphore):
    """Cache → sinon jugement LLM. Met à jour le job au fil de l'eau."""
    import matching
    async with semaphore:
        cache = matching.matching_cache(profil, subside)
        if cache is not None:
            m = cache
        else:
            v = await asyncio.to_thread(matching.juger_un, profil, subside)
            ti, to = v.pop("_tokens", (0, 0))
            job["tokens_in"] += ti
            job["tokens_out"] += to
            m = matching.stocker_matching(profil, subside, v)

        # Enrichit pour l'affichage (comme matching.resultats)
        m = dict(m)
        m["subside"] = {k: subside.get(k) for k in (
            "id", "titre", "organisme", "source_id", "deadline", "permanent",
            "montant", "url_source", "zone_categorie", "expire")}
        m["depuis_cache"] = cache is not None
        job["resultats"].append(m)
        job["traites"] += 1
        if m.get("verdict") in ("probablement_eligible", "eligible_sous_conditions"):
            job["matchs"] += 1


async def _executer_matching(job_id: str, profil: dict):
    import matching
    job = _matching_jobs[job_id]
    debut = time.monotonic()
    cap = int(os.getenv("MAX_JUGEMENTS_PAR_MATCHING", "40"))

    try:
        candidats = matching.pre_filtrer(profil)
        if len(candidats) > cap:
            job["erreurs"].append(
                f"{len(candidats) - cap} candidat(s) au-delà du plafond "
                f"MAX_JUGEMENTS_PAR_MATCHING={cap} non jugé(s)")
            candidats = candidats[:cap]
        job["total_candidats"] = len(candidats)
        log.info("Matching profil=%s : %d candidat(s) après pré-filtre", profil["id"], len(candidats))

        sem = asyncio.Semaphore(JUGEMENTS_CONCURRENTS)
        # gather : les jugements partent par lots de JUGEMENTS_CONCURRENTS ;
        # les résultats s'ajoutent à job["resultats"] au fur et à mesure (streaming).
        await asyncio.gather(
            *[_juger_candidat(job, profil, s, sem) for s in candidats],
            return_exceptions=True,
        )

        job["cout_estime_usd"] = _estimer_cout(job["tokens_in"], job["tokens_out"])
        job["statut"] = "done"
        log.info("Matching profil=%s terminé en %.1fs : %d jugés, %d matchs, ~$%.4f",
                 profil["id"], time.monotonic() - debut, job["traites"], job["matchs"],
                 job["cout_estime_usd"])
    except Exception as e:
        log.exception("Matching profil=%s : échec global", profil["id"])
        job["statut"] = "error"
        job["erreurs"].append(f"{type(e).__name__}: {e}")
    finally:
        job["termine_a"] = _now()

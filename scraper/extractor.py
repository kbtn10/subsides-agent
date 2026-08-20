"""Extraction LLM : texte d'une fiche -> JSON structuré, via l'API Anthropic.

Deux choix qui méritent une explication :

1. `output_config.format` (structured outputs) contraint le modèle à produire du
   JSON conforme au schéma — pas de "voici le JSON :" ni de ```json à éplucher.
   claude-haiku-4-5 le supporte. On garde quand même le parsing tolérant de
   validator.py : la contrainte porte sur la FORME, jamais sur la véracité.

2. `url_source` n'est PAS demandée au modèle. On connaît déjà l'URL qu'on vient
   de charger ; la faire recracher par le LLM n'ajoute rien et ouvre une porte à
   l'hallucination. Elle est injectée par le validateur.

Les retries 429/5xx sont ceux du SDK (max_retries=2, backoff exponentiel) — voir
CLIENT ci-dessous. Inutile de les réécrire à la main.
"""

import logging
import os

import anthropic

log = logging.getLogger(__name__)

MODELE_DEFAUT = "claude-haiku-4-5"
MAX_TOKENS = 2048

# Modèles qui ont RETIRÉ temperature (famille 4.6+ / 5) : leur envoyer
# temperature renvoie 400. Pour tous les autres (dont claude-haiku-4-5 par
# défaut), on force temperature=0 pour rendre l'extraction déterministe et
# éviter les faux "modifié" de reformulation d'un run à l'autre.
_MODELES_SANS_TEMPERATURE = (
    "claude-opus-4-8", "claude-opus-4-7", "claude-opus-4-6",
    "claude-sonnet-5", "claude-fable-5", "claude-mythos-5",
)


def _params_sampling(model: str) -> dict:
    return {} if any(model.startswith(m) for m in _MODELES_SANS_TEMPERATURE) else {"temperature": 0}

# Contraintes non supportées par les structured outputs (maxLength, etc.) : on ne
# les met pas ici, c'est validator.py qui borne titre/description côté client.
SCHEMA_SUBSIDE = {
    "type": "object",
    "properties": {
        "titre": {
            "type": "string",
            "description": "Intitulé exact du subside tel qu'il apparaît sur la page.",
        },
        "organisme": {
            "type": ["string", "null"],
            "description": "Organisme qui octroie le subside (ex: Actiris, Innoviris, Bruxelles Économie et Emploi).",
        },
        "description": {
            "type": ["string", "null"],
            "description": "Résumé fidèle en 2-4 phrases, max 1000 caractères. Aucune information qui ne soit dans le texte.",
        },
        "montant": {
            "type": ["string", "null"],
            "description": "Montant en texte libre, repris du texte ('5 000 €', 'max 50% du budget', 'jusqu'à 80 000 €').",
        },
        "deadline": {
            "type": ["string", "null"],
            "description": "Date limite de candidature au format ISO YYYY-MM-DD. null si permanent, non précisé, ou si tu devrais deviner.",
        },
        "permanent": {
            "type": "boolean",
            "description": "true seulement si le texte indique explicitement que le subside est ouvert en continu / sans date limite.",
        },
        "public_cible": {
            "type": ["string", "null"],
            "description": "À qui s'adresse le subside (ASBL, PME, indépendants, communes...).",
        },
        "criteres_eligibilite": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Conditions d'éligibilité, une par entrée, reprises du texte. Liste vide si non précisé.",
        },
        "secteurs": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Secteurs/thématiques concernés. Liste vide si non précisé.",
        },
        "lien_candidature": {
            "type": ["string", "null"],
            "description": "URL absolue du formulaire ou de la procédure de candidature, si présente dans le texte. Sinon null.",
        },
        "langue": {
            "type": "string",
            "enum": ["fr", "nl", "en"],
            "description": "Langue de la page.",
        },
        "zone_geographique": {
            "type": ["string", "null"],
            "description": (
                "Zone géographique d'éligibilité TELLE QU'ÉNONCÉE dans le texte "
                "(ex: 'Région de Bruxelles-Capitale', 'Fédération Wallonie-Bruxelles', "
                "'Flandre', 'Belgique', 'commune d'Ixelles'). null si le texte ne "
                "précise rien. N'infère JAMAIS la zone depuis le nom de l'organisme "
                "ou la langue de la page — uniquement depuis une mention explicite."
            ),
        },
        "type_beneficiaire": {
            "type": ["array", "null"],
            "items": {"type": "string",
                      "enum": ["asbl", "individu", "entreprise", "ecole",
                               "pouvoir_public", "autre"]},
            "description": (
                "Types de bénéficiaires éligibles TELS QU'ÉNONCÉS dans le texte "
                "(un appel peut en viser plusieurs). Ex : 'ASBL et clubs sportifs' "
                "→ ['asbl'] ; 'artistes' → ['individu'] ; 'écoles ou organisations "
                "socio-culturelles' → ['ecole','asbl'] ; 'communes' → ['pouvoir_public']. "
                "null si le texte ne précise pas. N'infère pas."
            ),
        },
        "nature": {
            "type": ["string", "null"],
            "enum": ["appel_a_projets", "dispositif_permanent", "prix_concours",
                     "financement_instrument", None],
            "description": (
                "Nature du soutien telle qu'elle ressort du texte : "
                "appel_a_projets si candidature datée avec procédure ; "
                "prix_concours si prix/concours/bourse avec jury ; "
                "dispositif_permanent si aide/agrément/subvention accessible en "
                "continu sur demande ; financement_instrument si prêt, garantie, "
                "prise de participation (pas un subside à proprement parler). "
                "null si indéterminable."
            ),
        },
    },
    "required": [
        "titre", "organisme", "description", "montant", "deadline", "permanent",
        "public_cible", "criteres_eligibilite", "secteurs", "lien_candidature",
        "langue", "zone_geographique", "type_beneficiaire", "nature",
    ],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """Tu extrais les informations d'une fiche de subside ou d'appel à projets (Région de Bruxelles-Capitale) vers du JSON structuré.

Règles absolues :
- Tu ne rapportes QUE ce qui est écrit dans le texte fourni.
- Si une information est absente du texte, mets null (ou une liste vide pour les tableaux).
- N'invente JAMAIS une date, un montant ou un critère. Ne déduis pas, ne complète pas avec tes connaissances générales, ne devine pas à partir du contexte.
- Une date ne va dans `deadline` que si le texte la présente explicitement comme la date limite de candidature. Une date de publication, de mise à jour ou de début de programme n'est PAS une deadline : dans ce cas, deadline = null.
- Si le texte ne décrit pas un subside/appel à projets (page d'accueil, liste, erreur 404), mets un titre vide.
- `permanent` = true uniquement si le texte dit que le dispositif est ouvert en continu.
- `zone_geographique` : uniquement si le texte mentionne explicitement une zone d'éligibilité. Ne la déduis pas du nom de l'organisme ni de la langue de la page.
- `type_beneficiaire` : uniquement les types explicitement visés par le texte. null si non précisé. N'infère pas (ne déduis pas "asbl" du simple fait que l'organisme subventionne habituellement des ASBL).
- `nature` : la nature du soutien telle qu'elle ressort du texte. appel_a_projets = candidature datée avec procédure ; prix_concours = prix/concours/bourse jugé par un jury ; dispositif_permanent = aide/agrément/subvention accessible en continu, sur simple demande, sans appel formel ; financement_instrument = prêt, garantie, avance récupérable, prise de participation (ce n'est pas un subside). null si le texte ne permet pas de trancher.

Tu réponds uniquement par le JSON demandé."""

CLIENT = None


def _client():
    global CLIENT
    if CLIENT is None:
        cle = os.getenv("ANTHROPIC_API_KEY")
        if not cle:
            raise RuntimeError(
                "ANTHROPIC_API_KEY absente. Copie .env.example vers .env et renseigne ta clé."
            )
        # max_retries=2 : le SDK retente 429/408/409/5xx et les erreurs réseau
        # avec un backoff exponentiel. C'est exactement la politique demandée.
        CLIENT = anthropic.Anthropic(api_key=cle, max_retries=2, timeout=60.0)
    return CLIENT


def modele() -> str:
    return os.getenv("EXTRACTION_MODEL") or MODELE_DEFAUT


class ResultatExtraction:
    def __init__(self, ok, data=None, erreur=None, tokens_in=0, tokens_out=0):
        self.ok = ok
        self.data = data
        self.erreur = erreur
        self.tokens_in = tokens_in
        self.tokens_out = tokens_out


def extraire(texte: str, url: str) -> ResultatExtraction:
    """Appelle Claude. Ne lève pas : renvoie toujours un ResultatExtraction."""
    if not texte or not texte.strip():
        return ResultatExtraction(False, erreur="texte vide")

    try:
        reponse = _client().messages.create(
            model=modele(),
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            output_config={"format": {"type": "json_schema", "schema": SCHEMA_SUBSIDE}},
            messages=[
                {
                    "role": "user",
                    "content": f"Fiche à extraire (source : {url}) :\n\n<fiche>\n{texte}\n</fiche>",
                }
            ],
            **_params_sampling(modele()),  # temperature=0 sur les modèles qui l'acceptent
        )
    except anthropic.APIStatusError as e:
        # Le SDK a déjà retenté 2x les 429/5xx : arriver ici = échec définitif.
        log.error("Extraction KO (HTTP %s) pour %s : %s", e.status_code, url, e.message)
        return ResultatExtraction(False, erreur=f"api_status_{e.status_code}: {e.message}")
    except anthropic.APIConnectionError as e:
        log.error("Extraction KO (réseau) pour %s : %s", url, e)
        return ResultatExtraction(False, erreur=f"api_connection: {e}")
    except Exception as e:
        log.exception("Extraction KO (inattendu) pour %s", url)
        return ResultatExtraction(False, erreur=f"{type(e).__name__}: {e}")

    usage = reponse.usage
    tokens_in, tokens_out = usage.input_tokens, usage.output_tokens
    log.info(
        "Extraction %s | modèle=%s | tokens in=%d out=%d | stop=%s",
        url, modele(), tokens_in, tokens_out, reponse.stop_reason,
    )

    if reponse.stop_reason == "refusal":
        return ResultatExtraction(False, erreur="refus du modèle",
                                  tokens_in=tokens_in, tokens_out=tokens_out)
    if reponse.stop_reason == "max_tokens":
        # JSON tronqué : inexploitable, autant le dire clairement.
        return ResultatExtraction(False, erreur="réponse tronquée (max_tokens)",
                                  tokens_in=tokens_in, tokens_out=tokens_out)

    brut = next((b.text for b in reponse.content if b.type == "text"), None)
    if not brut:
        return ResultatExtraction(False, erreur="réponse sans bloc texte",
                                  tokens_in=tokens_in, tokens_out=tokens_out)

    # Renvoyé brut : c'est validator.py qui parse et juge.
    return ResultatExtraction(True, data=brut, tokens_in=tokens_in, tokens_out=tokens_out)


PROMPT_LIENS = """Voici les liens d'une page de listing (souvent un fil d'actualités qui MÊLE
appels à projets et autres publications).

Ton critère UNIQUE : garde un lien si, et seulement si, il pointe vers la fiche
d'une OPPORTUNITÉ DE FINANCEMENT OU DE SOUTIEN qu'une organisation (ASBL,
association, opérateur) peut DEMANDER en déposant une candidature / un dossier.

GARDE (opportunités à candidater) :
- appel à projets, appel à candidatures
- subvention, subside, aide ou soutien financier
- bourse
- prix ou concours DOTÉ (récompense en argent/soutien) ouvert aux candidatures

EXCLUS SANS EXCEPTION (ce ne sont PAS des opportunités à demander) :
- actualités, communiqués, annonces de résultats ou de lauréats
- événements : journées, rencontres, festivals, colloques, cérémonies, agenda
- enquêtes, sondages, consultations
- pages d'information ou de sensibilisation générales
- navigation, menus, catégories, filtres, pagination, contact, mentions
  légales, réseaux sociaux, changement de langue, connexion

En cas de doute sérieux sur le fait qu'on puisse CANDIDATER pour un financement,
EXCLUS le lien. Mieux vaut manquer un appel douteux que polluer la base d'actus.

Si aucun lien ne correspond, renvoie une liste vide. N'invente aucune URL :
chaque URL renvoyée doit apparaître telle quelle dans la liste fournie."""

SCHEMA_LIENS = {
    "type": "object",
    "properties": {
        "urls": {
            "type": "array",
            "items": {"type": "string"},
            "description": "URLs absolues des fiches individuelles, reprises telles quelles de la liste fournie.",
        }
    },
    "required": ["urls"],
    "additionalProperties": False,
}


def identifier_liens_fiches(liens: list[tuple[str, str]], url_listing: str) -> ResultatExtraction:
    """Stratégie llm_links : (url, texte_ancre)[] -> URLs de fiches individuelles."""
    if not liens:
        return ResultatExtraction(True, data={"urls": []})

    lignes = "\n".join(f"- {texte[:120]} -> {url}" for url, texte in liens)
    try:
        reponse = _client().messages.create(
            model=modele(),
            max_tokens=4096,
            system=PROMPT_LIENS,
            output_config={"format": {"type": "json_schema", "schema": SCHEMA_LIENS}},
            messages=[
                {"role": "user", "content": f"Page de listing : {url_listing}\n\nLiens :\n{lignes}"}
            ],
        )
    except Exception as e:
        log.error("identifier_liens_fiches KO pour %s : %s", url_listing, e)
        return ResultatExtraction(False, erreur=str(e))

    log.info(
        "Tri des liens %s | tokens in=%d out=%d",
        url_listing, reponse.usage.input_tokens, reponse.usage.output_tokens,
    )
    brut = next((b.text for b in reponse.content if b.type == "text"), None)
    if not brut:
        return ResultatExtraction(False, erreur="réponse sans bloc texte")

    import json

    try:
        data = json.loads(brut)
    except json.JSONDecodeError as e:
        return ResultatExtraction(False, erreur=f"JSON malformé: {e}",
                                  tokens_in=reponse.usage.input_tokens,
                                  tokens_out=reponse.usage.output_tokens)

    # Garde-fou anti-hallucination : on ne garde que des URLs réellement présentes.
    proposees = data.get("urls") or []
    connues = {u for u, _ in liens}
    retenues = [u for u in proposees if u in connues]
    if len(retenues) != len(proposees):
        log.warning("%d URL(s) inventée(s) par le modèle, écartée(s)",
                    len(proposees) - len(retenues))

    return ResultatExtraction(
        True,
        data={"urls": retenues},
        tokens_in=reponse.usage.input_tokens,
        tokens_out=reponse.usage.output_tokens,
    )

"""Validation programmatique du JSON renvoyé par le LLM. Aucun appel LLM ici.

Le principe : le LLM peut se tromper, donc rien de ce qu'il renvoie n'est cru sur
parole. On distingue deux niveaux d'échec :

  - échec DUR (JSON illisible, titre vide, url_source invalide) -> ok=False,
    la fiche est stockée en `echec_extraction` avec son texte brut.
  - échec DOUX (deadline aberrante, lien de candidature pourri) -> ok=True mais
    a_verifier=True : la donnée est exploitable, elle mérite juste un œil humain.
"""

import json
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Literal, Optional
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, ValidationError, field_validator

TITRE_MAX = 300
DESCRIPTION_MAX = 1000

# Bornes de plausibilité des deadlines (spec) : hors de cet intervalle, la date
# est probablement une hallucination ou une date de publication mal lue.
ANNEE_MIN = 2020
ANS_DANS_LE_FUTUR_MAX = 3

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class Subside(BaseModel):
    """Schéma d'un subside. `url_source` est injectée par le crawler, pas par le LLM."""

    model_config = {"extra": "ignore"}

    titre: str
    organisme: Optional[str] = None
    description: Optional[str] = None
    montant: Optional[str] = None
    deadline: Optional[str] = None
    permanent: bool = False
    public_cible: Optional[str] = None
    criteres_eligibilite: list[str] = Field(default_factory=list)
    secteurs: list[str] = Field(default_factory=list)
    lien_candidature: Optional[str] = None
    url_source: str
    langue: Literal["fr", "nl", "en"] = "fr"

    @field_validator("titre")
    @classmethod
    def _titre_non_vide(cls, v):
        v = (v or "").strip()
        if not v:
            raise ValueError("titre vide")
        return v[:TITRE_MAX]

    @field_validator("description")
    @classmethod
    def _description_bornee(cls, v):
        if v is None:
            return None
        v = v.strip()
        return v[:DESCRIPTION_MAX] if v else None

    @field_validator("organisme", "montant", "public_cible", "deadline", "lien_candidature")
    @classmethod
    def _vide_vers_null(cls, v):
        """Le LLM renvoie parfois "", "N/A" ou "null" au lieu de null."""
        if v is None:
            return None
        v = v.strip()
        return None if v.lower() in ("", "n/a", "na", "null", "none", "inconnu") else v

    zone_geographique: Optional[str] = None
    type_beneficiaire: list[str] = Field(default_factory=list)

    @field_validator("criteres_eligibilite", "secteurs", mode="before")
    @classmethod
    def _liste_propre(cls, v):
        if v is None:
            return []
        if isinstance(v, str):  # le LLM renvoie parfois une string au lieu d'une liste
            v = [v]
        return [str(x).strip() for x in v if str(x).strip()]

    @field_validator("type_beneficiaire", mode="before")
    @classmethod
    def _types_valides(cls, v):
        """Ne garde que les valeurs de l'énumération ; le reste (y compris une
        valeur libre hallucinée) est écarté silencieusement."""
        autorises = {"asbl", "individu", "entreprise", "ecole", "pouvoir_public", "autre"}
        if v is None:
            return []
        if isinstance(v, str):
            v = [v]
        return [t for t in (str(x).strip().lower() for x in v) if t in autorises]

    @field_validator("zone_geographique")
    @classmethod
    def _zone_vide_vers_null(cls, v):
        if v is None:
            return None
        v = v.strip()
        return None if v.lower() in ("", "n/a", "na", "null", "none", "inconnu", "inconnue") else v


@dataclass
class ResultatValidation:
    ok: bool
    subside: Optional[dict] = None
    a_verifier: bool = False
    erreurs: list[str] = field(default_factory=list)


def url_valide(url) -> bool:
    """http(s) + host présent. Rejette javascript:, mailto:, chemins relatifs, ..."""
    if not url or not isinstance(url, str):
        return False
    try:
        p = urlsplit(url.strip())
    except ValueError:
        return False
    return p.scheme in ("http", "https") and bool(p.hostname) and "." in p.hostname


def parser_json_llm(brut: str):
    """Parse la réponse du LLM. Tolère les ```json ... ``` et le texte autour.

    Renvoie (data, erreur). data est None si illisible.
    """
    if not brut or not brut.strip():
        return None, "réponse vide"
    txt = brut.strip()

    # Retire une éventuelle clôture markdown ```json ... ```
    fence = re.match(r"^```(?:json)?\s*\n?(.*?)\n?```$", txt, re.DOTALL)
    if fence:
        txt = fence.group(1).strip()

    try:
        return json.loads(txt), None
    except json.JSONDecodeError as e:
        premiere_erreur = str(e)

    # Dernier recours : isoler le premier objet {...} équilibré du texte.
    debut = txt.find("{")
    if debut != -1:
        profondeur, dans_chaine, echap = 0, False, False
        for i, c in enumerate(txt[debut:], start=debut):
            if echap:
                echap = False
                continue
            if c == "\\" and dans_chaine:
                echap = True
                continue
            if c == '"':
                dans_chaine = not dans_chaine
            elif not dans_chaine:
                if c == "{":
                    profondeur += 1
                elif c == "}":
                    profondeur -= 1
                    if profondeur == 0:
                        try:
                            return json.loads(txt[debut : i + 1]), None
                        except json.JSONDecodeError:
                            break
    return None, f"JSON malformé: {premiere_erreur}"


# --- Catégorisation de la zone géographique (mapping mot-clé, aucun LLM) ------
#
# Valeurs fermées : bruxelles | fwb | flandre | wallonie | national | autre | inconnue.
# L'ORDRE des tests compte : "Fédération Wallonie-Bruxelles" contient à la fois
# "Bruxelles" et "Wallonie", donc fwb DOIT être testé avant bruxelles/wallonie.
# La liste flamande est pragmatique (grandes villes/régions), pas exhaustive.

_ZONE_FWB = (
    "fédération wallonie-bruxelles", "federation wallonie-bruxelles",
    "wallonie-bruxelles", "communauté française", "communaute francaise",
    "communauté francophone", "fwb", "cfwb",
)
_ZONE_BRUXELLES = (
    "bruxell", "brussel", "bhg", "région de bruxelles-capitale", "rbc",
    # les 19 communes (fragments distinctifs)
    "anderlecht", "auderghem", "berchem-sainte-agathe", "etterbeek", "evere",
    "forest", "ganshoren", "ixelles", "jette", "koekelberg", "molenbeek",
    "saint-gilles", "saint-josse", "schaerbeek", "uccle", "watermael",
    "woluwe", "boitsfort",
)
_ZONE_FLANDRE = (
    "flandre", "flamand", "vlaander", "vlaams", "vlaanderen", "vlaams-brabant",
    "gent", "gand", "gentse", "antwerp", "anvers", "leuven", "brugge", "bruges",
    "hasselt", "mechelen", "malines", "waasland", "waas", "limburg",
    "oost-vlaanderen", "west-vlaanderen", "kortrijk", "oostende", "ostende",
    "aalst", "genk", "sint-niklaas", "roeselare",
    # régions/pays flamands vus dans les vrais appels KBS (lot 2)
    "scheldevallei", "denderstreek", "kempen",
    # Lot 5 : les EXONYMES FRANÇAIS. L'extraction traduit parfois le nom de la
    # région — le fonds « Een hart voor Scheldevallei » était stocké avec
    # zone_geographique = « vallée de l'Escaut » et tombait donc en 'autre'.
    # On reste sur des expressions à plusieurs mots : « escaut » seul attraperait
    # Tournai (Wallonie), « lys » seul est ambigu.
    "vallée de l'escaut", "vallee de l'escaut", "ardennes flamandes",
    "meetjesland", "pays de waes", "campine", "brabant flamand",
)
_ZONE_WALLONIE = (
    "wallonie", "wallon", "liège", "liege", "namur", "charleroi", "mons",
    "tournai", "verviers", "la louvière", "louvain-la-neuve", "ottignies",
    "nivelles", "arlon", "brabant wallon",
)
_ZONE_NATIONAL = (
    "belgique", "belgië", "belgie", "belge", "fédéral", "federal", "national",
    "tout le pays", "ensemble du territoire", "l'ensemble de la belgique",
)


def categoriser_zone(zone) -> str:
    """Zone libre -> catégorie fermée. Renvoie 'inconnue' si zone vide/null."""
    if not zone or not str(zone).strip():
        return "inconnue"
    z = str(zone).casefold()
    if any(m in z for m in _ZONE_FWB):
        return "fwb"
    if any(m in z for m in _ZONE_BRUXELLES):
        return "bruxelles"
    if any(m in z for m in _ZONE_FLANDRE):
        return "flandre"
    if any(m in z for m in _ZONE_WALLONIE):
        return "wallonie"
    if any(m in z for m in _ZONE_NATIONAL):
        return "national"
    return "autre"


def valider_deadline(deadline, aujourdhui: date = None):
    """(deadline_normalisée, a_verifier, erreurs).

    None est valide (subside permanent ou date inconnue). Une date hors bornes
    est conservée mais signalée : mieux vaut une date suspecte affichée avec un
    badge qu'une date silencieusement jetée.
    """
    if deadline is None:
        return None, False, []
    if not _ISO_DATE.match(deadline):
        return None, True, [f"deadline non ISO (YYYY-MM-DD): {deadline!r}"]
    try:
        d = date.fromisoformat(deadline)
    except ValueError:
        return None, True, [f"deadline impossible: {deadline!r}"]

    aujourdhui = aujourdhui or date.today()
    erreurs = []
    if d.year < ANNEE_MIN:
        erreurs.append(f"deadline antérieure à {ANNEE_MIN}: {deadline}")
    elif d.year > aujourdhui.year + ANS_DANS_LE_FUTUR_MAX:
        erreurs.append(f"deadline > {ANS_DANS_LE_FUTUR_MAX} ans dans le futur: {deadline}")
    return deadline, bool(erreurs), erreurs


def valider(data, url_source: str, aujourdhui: date = None) -> ResultatValidation:
    """Valide un dict (ou une string JSON brute) contre le schéma + les règles métier."""
    erreurs = []

    if isinstance(data, str):
        data, err = parser_json_llm(data)
        if err:
            return ResultatValidation(ok=False, erreurs=[err])
    if not isinstance(data, dict):
        return ResultatValidation(ok=False, erreurs=[f"attendu un objet JSON, reçu {type(data).__name__}"])

    if not url_valide(url_source):
        return ResultatValidation(ok=False, erreurs=[f"url_source invalide: {url_source!r}"])

    data = dict(data)
    data["url_source"] = url_source  # jamais celle du LLM : on connaît la vraie.

    try:
        subside = Subside(**data)
    except ValidationError as e:
        return ResultatValidation(
            ok=False,
            erreurs=[f"{'.'.join(str(x) for x in d['loc'])}: {d['msg']}" for d in e.errors()],
        )

    d = subside.model_dump()

    d["deadline"], deadline_suspecte, erreurs_deadline = valider_deadline(d["deadline"], aujourdhui)
    erreurs += erreurs_deadline

    if d["lien_candidature"] and not url_valide(d["lien_candidature"]):
        erreurs.append(f"lien_candidature invalide, ignoré: {d['lien_candidature']!r}")
        d["lien_candidature"] = None

    # Incohérence bénigne mais utile à signaler : une date de clôture ET "permanent".
    if d["permanent"] and d["deadline"]:
        erreurs.append("marqué permanent mais porte une deadline")

    # Catégorie fermée dérivée de la zone libre (code pur, pas de LLM).
    d["zone_categorie"] = categoriser_zone(d.get("zone_geographique"))

    return ResultatValidation(
        ok=True,
        subside=d,
        a_verifier=deadline_suspecte or bool(erreurs),
        erreurs=erreurs,
    )

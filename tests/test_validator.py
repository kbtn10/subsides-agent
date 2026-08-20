from datetime import date

import pytest

from scraper.validator import (
    parser_json_llm,
    url_valide,
    valider,
    valider_deadline,
)

URL = "https://info.hub.brussels/subsides/finexpo"
AUJOURDHUI = date(2026, 7, 17)


def fiche(**over):
    base = {
        "titre": "Prime à l'embauche",
        "organisme": "Actiris",
        "description": "Une aide à l'engagement.",
        "montant": "5 000 €",
        "deadline": "2026-12-31",
        "permanent": False,
        "public_cible": "ASBL bruxelloises",
        "criteres_eligibilite": ["Siège en RBC"],
        "secteurs": ["Emploi"],
        "lien_candidature": "https://actiris.be/form",
        "langue": "fr",
    }
    base.update(over)
    return base


# --- JSON malformé ---------------------------------------------------------

def test_json_valide():
    data, err = parser_json_llm('{"titre": "X"}')
    assert err is None and data == {"titre": "X"}


def test_json_dans_backticks():
    data, err = parser_json_llm('```json\n{"titre": "X"}\n```')
    assert err is None and data == {"titre": "X"}


def test_json_backticks_sans_langage():
    data, err = parser_json_llm('```\n{"titre": "X"}\n```')
    assert err is None and data == {"titre": "X"}


def test_json_avec_bavardage_autour():
    data, err = parser_json_llm('Voici le JSON :\n{"titre": "X"}\nVoilà !')
    assert err is None and data == {"titre": "X"}


def test_json_accolade_dans_une_chaine():
    # L'extraction d'objet équilibré ne doit pas se faire piéger par un } littéral.
    data, err = parser_json_llm('{"titre": "a } b", "montant": "50%"}')
    assert err is None and data["titre"] == "a } b"


def test_json_malforme():
    data, err = parser_json_llm('{"titre": ')
    assert data is None and "malformé" in err


def test_json_vide():
    data, err = parser_json_llm("")
    assert data is None and err == "réponse vide"


def test_valider_rejette_json_malforme():
    r = valider('{"titre":', URL)
    assert not r.ok and r.subside is None


def test_valider_rejette_non_objet():
    r = valider("[1, 2, 3]", URL)
    assert not r.ok


# --- URLs ------------------------------------------------------------------

@pytest.mark.parametrize("url", [
    "https://ok.be", "http://ok.be/x?y=1", "https://sub.ok.be/a/b",
])
def test_urls_valides(url):
    assert url_valide(url)


@pytest.mark.parametrize("url", [
    "", None, "ftp://ok.be", "javascript:alert(1)", "mailto:a@b.be",
    "/relatif", "pas une url", "https://", "https://localhost", 42,
])
def test_urls_invalides(url):
    assert not url_valide(url)


def test_url_source_invalide_echec_dur():
    r = valider(fiche(), "javascript:alert(1)")
    assert not r.ok and "url_source invalide" in r.erreurs[0]


def test_lien_candidature_invalide_est_neutralise_pas_fatal():
    r = valider(fiche(lien_candidature="javascript:void(0)"), URL)
    assert r.ok                              # la fiche reste exploitable
    assert r.subside["lien_candidature"] is None
    assert r.a_verifier


def test_url_source_du_llm_est_ignoree():
    r = valider(fiche(url_source="https://hallucination.example"), URL, AUJOURDHUI)
    assert r.subside["url_source"] == URL


# --- Deadlines -------------------------------------------------------------

def test_deadline_none_est_valide():
    d, verif, errs = valider_deadline(None, AUJOURDHUI)
    assert (d, verif, errs) == (None, False, [])


def test_deadline_iso_ok():
    d, verif, errs = valider_deadline("2026-12-31", AUJOURDHUI)
    assert d == "2026-12-31" and not verif


@pytest.mark.parametrize("mauvaise", [
    "31/12/2026", "2026-13-01", "2026-02-30", "décembre 2026", "2026", "2026-1-1",
])
def test_deadlines_invalides(mauvaise):
    d, verif, errs = valider_deadline(mauvaise, AUJOURDHUI)
    assert d is None and verif and errs


def test_deadline_trop_ancienne():
    d, verif, errs = valider_deadline("2019-01-01", AUJOURDHUI)
    assert verif and "antérieure" in errs[0]


def test_deadline_trop_lointaine():
    d, verif, errs = valider_deadline("2040-01-01", AUJOURDHUI)
    assert verif and "futur" in errs[0]


def test_deadline_limite_haute_acceptee():
    d, verif, errs = valider_deadline("2029-12-31", AUJOURDHUI)  # 2026 + 3 ans
    assert d == "2029-12-31" and not verif


def test_deadline_invalide_ne_tue_pas_la_fiche():
    r = valider(fiche(deadline="31/12/2026"), URL, AUJOURDHUI)
    assert r.ok and r.a_verifier and r.subside["deadline"] is None


# --- Schéma ----------------------------------------------------------------

def test_titre_vide_echec_dur():
    assert not valider(fiche(titre="   "), URL).ok


def test_titre_tronque_a_300():
    r = valider(fiche(titre="A" * 500), URL, AUJOURDHUI)
    assert r.ok and len(r.subside["titre"]) == 300


def test_description_tronquee_a_1000():
    r = valider(fiche(description="B" * 2000), URL, AUJOURDHUI)
    assert len(r.subside["description"]) == 1000


def test_langue_invalide_echec_dur():
    assert not valider(fiche(langue="de"), URL).ok


def test_placeholders_llm_vers_null():
    r = valider(fiche(montant="N/A", organisme="null", public_cible=""), URL, AUJOURDHUI)
    assert r.subside["montant"] is None
    assert r.subside["organisme"] is None
    assert r.subside["public_cible"] is None


def test_criteres_string_devient_liste():
    r = valider(fiche(criteres_eligibilite="Siège en RBC"), URL, AUJOURDHUI)
    assert r.subside["criteres_eligibilite"] == ["Siège en RBC"]


def test_criteres_null_devient_liste_vide():
    r = valider(fiche(criteres_eligibilite=None, secteurs=None), URL, AUJOURDHUI)
    assert r.subside["criteres_eligibilite"] == [] and r.subside["secteurs"] == []


def test_permanent_avec_deadline_signale():
    r = valider(fiche(permanent=True, deadline="2026-12-31"), URL, AUJOURDHUI)
    assert r.ok and r.a_verifier


def test_fiche_nominale_sans_alerte():
    r = valider(fiche(), URL, AUJOURDHUI)
    assert r.ok and not r.a_verifier and r.erreurs == []


# --- Catégorisation de zone ------------------------------------------------

from scraper.validator import categoriser_zone  # noqa: E402


@pytest.mark.parametrize("zone,attendu", [
    # bruxelles
    ("Région de Bruxelles-Capitale", "bruxelles"),
    ("commune d'Ixelles", "bruxelles"),
    ("Schaerbeek", "bruxelles"),
    ("bruxellois", "bruxelles"),
    ("Brussels Hoofdstedelijk Gewest", "bruxelles"),
    # fwb (doit gagner sur bruxelles ET wallonie)
    ("Fédération Wallonie-Bruxelles", "fwb"),
    ("Communauté française", "fwb"),
    ("FWB", "fwb"),
    # flandre (dont les régions vues dans les vrais appels KBS)
    ("Flandre", "flandre"),
    ("Waasland", "flandre"),
    ("Vlaanderen", "flandre"),
    ("Gent", "flandre"),
    ("provincie Antwerpen", "flandre"),
    ("Scheldevallei", "flandre"),
    ("Denderstreek", "flandre"),
    ("de Kempen", "flandre"),
    ("Vlaams-Brabant", "flandre"),
    ("Gentse jongeren", "flandre"),
    # wallonie
    ("Wallonie", "wallonie"),
    ("province de Liège", "wallonie"),
    # national
    ("Belgique", "national"),
    ("niveau fédéral", "national"),
    ("tout le pays", "national"),
    # autre / inconnue
    ("Union européenne", "autre"),
    ("Québec", "autre"),
    (None, "inconnue"),
    ("", "inconnue"),
    ("   ", "inconnue"),
])
def test_categoriser_zone(zone, attendu):
    assert categoriser_zone(zone) == attendu


def test_zone_priorite_fwb_avant_bruxelles():
    # "Wallonie-Bruxelles" contient "Bruxelles" mais doit rester fwb.
    assert categoriser_zone("Fédération Wallonie-Bruxelles") == "fwb"
    assert categoriser_zone("toute la Fédération Wallonie-Bruxelles (FWB)") == "fwb"


def test_valider_remplit_zone_categorie():
    r = valider(fiche(zone_geographique="Région de Bruxelles-Capitale"), URL, AUJOURDHUI)
    assert r.subside["zone_categorie"] == "bruxelles"
    assert r.subside["zone_geographique"] == "Région de Bruxelles-Capitale"


def test_valider_zone_absente_donne_inconnue():
    r = valider(fiche(), URL, AUJOURDHUI)   # fiche() n'a pas de zone
    assert r.subside["zone_categorie"] == "inconnue"
    assert r.subside["zone_geographique"] is None


def test_valider_zone_placeholder_vers_null():
    r = valider(fiche(zone_geographique="N/A"), URL, AUJOURDHUI)
    assert r.subside["zone_geographique"] is None
    assert r.subside["zone_categorie"] == "inconnue"


# --- type_beneficiaire -----------------------------------------------------

def test_type_beneficiaire_liste_valide():
    r = valider(fiche(type_beneficiaire=["asbl", "ecole"]), URL, AUJOURDHUI)
    assert r.subside["type_beneficiaire"] == ["asbl", "ecole"]


def test_type_beneficiaire_absent_donne_liste_vide():
    r = valider(fiche(), URL, AUJOURDHUI)
    assert r.subside["type_beneficiaire"] == []


def test_type_beneficiaire_valeurs_hallucinees_ecartees():
    # "individu" est valide, "licorne" ne l'est pas -> écartée.
    r = valider(fiche(type_beneficiaire=["individu", "licorne"]), URL, AUJOURDHUI)
    assert r.subside["type_beneficiaire"] == ["individu"]


def test_type_beneficiaire_string_devient_liste():
    r = valider(fiche(type_beneficiaire="asbl"), URL, AUJOURDHUI)
    assert r.subside["type_beneficiaire"] == ["asbl"]


def test_type_beneficiaire_casse_normalisee():
    r = valider(fiche(type_beneficiaire=["ASBL", "Entreprise"]), URL, AUJOURDHUI)
    assert r.subside["type_beneficiaire"] == ["asbl", "entreprise"]


# --- Nature du soutien (lot 9) ---------------------------------------------

@pytest.mark.parametrize("valeur", [
    "appel_a_projets", "dispositif_permanent", "prix_concours", "financement_instrument",
])
def test_nature_valide_conservee(valeur):
    r = valider(fiche(nature=valeur), URL, AUJOURDHUI)
    assert r.ok and r.subside["nature"] == valeur


@pytest.mark.parametrize("valeur", [None, "", "autre_chose", "subvention", "APPEL"])
def test_nature_invalide_ou_absente_vers_none(valeur):
    # "APPEL" n'est pas dans l'énum → None ; None/""/valeur libre → None.
    r = valider(fiche(nature=valeur), URL, AUJOURDHUI)
    assert r.ok and r.subside["nature"] is None


def test_nature_casse_normalisee():
    r = valider(fiche(nature="Dispositif_Permanent"), URL, AUJOURDHUI)
    assert r.ok and r.subside["nature"] == "dispositif_permanent"


def test_nature_absente_du_json_vaut_none():
    f = fiche()
    f.pop("nature", None)  # une fiche sans le champ (fiche d'avant le lot 9)
    r = valider(f, URL, AUJOURDHUI)
    assert r.ok and r.subside["nature"] is None


def test_schema_extraction_inclut_nature():
    from scraper.extractor import SCHEMA_SUBSIDE, SYSTEM_PROMPT
    assert "nature" in SCHEMA_SUBSIDE["properties"]
    assert "nature" in SCHEMA_SUBSIDE["required"]
    # Pas d'enum dans le schéma (structured outputs refusent enum+null) : les
    # valeurs autorisées sont dans la description et bornées par pydantic.
    desc = SCHEMA_SUBSIDE["properties"]["nature"]["description"]
    for v in ("appel_a_projets", "dispositif_permanent", "prix_concours",
              "financement_instrument"):
        assert v in desc
    assert "nature" in SYSTEM_PROMPT  # la consigne est bien passée au modèle

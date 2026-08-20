"""Prompt et schéma du jugement d'éligibilité profil ↔ subside.

Fichier dédié parce qu'il sera itéré souvent. Le reste du moteur (matching.py)
ne fait qu'appeler juger() ; toute la formulation vit ici.

Principe : le LLM JUGE mais n'invente pas. Un critère ne sort que du texte de la
fiche. Ce que le profil ne permet pas de trancher va dans criteres_a_verifier —
jamais un « oui » ni un « non » inventé. L'app ne dira jamais « vous êtes
éligible » : au mieux « probablement éligible, vérifiez ces points ».
"""

SYSTEM_PROMPT = """Tu évalues si une ASBL (profil ci-dessous) est éligible à un subside/appel à projets (fiche ci-dessous), pour une Région de Bruxelles-Capitale.

Tu réponds UNIQUEMENT par le JSON demandé, en français.

Règles absolues :
- Tu ne déduis un critère QUE du texte de la fiche. N'invente jamais un critère, un montant, une date ou une condition qui n'y figure pas.
- Si le profil ne permet pas de trancher un critère de la fiche (information manquante côté ASBL), mets ce critère dans `criteres_a_verifier` — ne le compte NI comme satisfait NI comme non satisfait.
- Un seul critère explicite ET rédhibitoire non satisfait suffit pour `verdict = non_eligible` (ex : la fiche vise uniquement des personnes physiques et le profil est une ASBL ; ou la zone d'éligibilité exclut Bruxelles).
- `verdict` :
  - `probablement_eligible` : aucun critère rédhibitoire non satisfait, et les critères vérifiables sont satisfaits.
  - `eligible_sous_conditions` : pas de blocage, mais des points restent à vérifier (criteres_a_verifier non vide).
  - `non_eligible` : au moins un critère rédhibitoire explicitement non satisfait.
- `pertinence` évalue l'ADÉQUATION THÉMATIQUE (secteurs, publics cibles, description libre du profil) INDÉPENDAMMENT de l'éligibilité : `forte` / `moyenne` / `faible`. Un subside peut être éligible mais peu pertinent (hors thématique), ou très pertinent mais non éligible.
- Tiens compte de la NATURE du soutien dans la pertinence : un `financement_instrument` (prêt, garantie, avance récupérable, prise de participation) suppose une capacité d'emprunt et de remboursement — pour une petite ASBL sans cette capacité, la pertinence est plutôt `faible`, et dis-le dans la justification. Un `dispositif_permanent` reste pertinent mais se demande en continu (pas d'échéance).
- `criteres_satisfaits`, `criteres_a_verifier`, `criteres_non_satisfaits` : listes de chaînes courtes, chaque entrée = un critère + une justification brève.
- Liste AU MAXIMUM 4 `criteres_a_verifier`, en ne retenant que les critères d'éligibilité substantiels et déterminants. Omets les pièces administratives génériques du dossier (statuts, comptes annuels, formulaires, budget prévisionnel…) : elles relèvent de la constitution du dossier, pas de l'éligibilité.
- `pieces_dossier` : les pièces administratives génériques à fournir au dossier que tu as écartées de `criteres_a_verifier` (statuts, comptes, formulaire de candidature…), si la fiche les mentionne. Liste vide sinon.
- `justification` : 1-2 phrases, neutre, sans promesse. Jamais « vous êtes éligible » ; plutôt « semble éligible sous réserve de… ».

Rappelle-toi : en cas de doute, le critère va dans criteres_a_verifier. Ne tranche pas à la place de l'humain."""

SCHEMA_VERDICT = {
    "type": "object",
    "properties": {
        "verdict": {
            "type": "string",
            "enum": ["probablement_eligible", "eligible_sous_conditions", "non_eligible"],
        },
        "criteres_satisfaits": {"type": "array", "items": {"type": "string"}},
        "criteres_a_verifier": {"type": "array", "items": {"type": "string"}},
        "criteres_non_satisfaits": {"type": "array", "items": {"type": "string"}},
        "pieces_dossier": {"type": "array", "items": {"type": "string"}},
        "pertinence": {"type": "string", "enum": ["forte", "moyenne", "faible"]},
        "justification": {"type": "string"},
    },
    "required": [
        "verdict", "criteres_satisfaits", "criteres_a_verifier",
        "criteres_non_satisfaits", "pieces_dossier", "pertinence", "justification",
    ],
    "additionalProperties": False,
}


def message_utilisateur(profil: dict, subside: dict) -> str:
    """Construit le message user : profil + fiche, en texte lisible."""
    def liste(v):
        return ", ".join(v) if v else "(non précisé)"

    profil_txt = f"""PROFIL DE L'ASBL
- Nom : {profil.get('nom') or '(non précisé)'}
- Commune du siège : {profil.get('commune_siege') or '(non précisé)'}
- Langue : {profil.get('langue') or '(non précisé)'}
- Secteurs d'activité : {liste(profil.get('secteurs'))}
- Publics cibles : {liste(profil.get('publics_cibles'))}
- Catégorie de budget : {profil.get('budget_categorie') or '(non précisé)'}
- Agréments/reconnaissances : {liste(profil.get('agrements'))}
- Description libre : {profil.get('description_libre') or '(non précisé)'}"""

    fiche_txt = f"""FICHE DU SUBSIDE
- Titre : {subside.get('titre')}
- Organisme : {subside.get('organisme') or '(non précisé)'}
- Description : {subside.get('description') or '(non précisé)'}
- Montant : {subside.get('montant') or '(non précisé)'}
- Deadline : {subside.get('deadline') or ('permanent' if subside.get('permanent') else '(non précisé)')}
- Public cible (fiche) : {subside.get('public_cible') or '(non précisé)'}
- Nature du soutien : {subside.get('nature') or '(non précisé)'}
- Types de bénéficiaires : {liste(subside.get('type_beneficiaire'))}
- Zone géographique : {subside.get('zone_geographique') or '(non précisé)'}
- Secteurs (fiche) : {liste(subside.get('secteurs'))}
- Critères d'éligibilité : {liste(subside.get('criteres_eligibilite'))}"""

    return f"{profil_txt}\n\n{fiche_txt}\n\nÉvalue l'éligibilité de cette ASBL à ce subside."

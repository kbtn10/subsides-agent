"""Prompt et schéma de la checklist des pièces du dossier (lot 7, étage 3).

Fichier dédié, itéré souvent. Principe cardinal : Subsidia STRUCTURE, n'invente
pas. Chaque pièce listée doit être EXIGÉE explicitement par le texte (fiche +
annexes PDF), avec la citation d'appui. Si le texte est muet, liste vide — on ne
devine pas des pièces « habituelles ».
"""

SYSTEM_PROMPT = """Tu aides une ASBL à préparer un dossier de subside. À partir du texte d'un appel à projets (fiche + éventuelles annexes PDF), tu établis la liste des PIÈCES et CONDITIONS DE FORME que le dossier doit contenir.

Tu réponds UNIQUEMENT par le JSON demandé, en français.

Règles absolues :
- Tu ne listes QUE ce que le texte EXIGE explicitement. N'invente aucune pièce, même « habituelle » (statuts, comptes…) : si le texte ne la demande pas, elle n'y est pas.
- Chaque item porte une `source_citation` : un court extrait VERBATIM du texte qui montre que cette pièce est exigée. Pas de citation = pas d'item.
- `type` :
  - `document` : une pièce à joindre (statuts, comptes annuels, budget, devis, attestation…).
  - `formulaire` : un formulaire officiel à remplir/signer.
  - `condition_forme` : une exigence de forme du dossier (nombre d'exemplaires, langue, format PDF, signature, date limite d'envoi, plafond de pages…).
- Ne mets PAS dans la liste les critères d'ÉLIGIBILITÉ (être une ASBL, avoir son siège en RBC…) : ici on ne s'occupe que de ce qu'il faut FOURNIR, pas de qui peut candidater.
- Regroupe les doublons. Intitulés courts et concrets.
- Si le texte ne détaille AUCUNE pièce ni condition de forme, renvoie une liste vide (le code affichera un message honnête invitant à consulter la fiche officielle). Ne comble jamais ce vide par des suppositions.

Tu n'écris pas le dossier et ne le soumets pas : tu aides seulement l'ASBL à savoir quoi rassembler."""

SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "intitule": {"type": "string", "description": "Pièce ou condition, formulation courte."},
                    "type": {"type": "string", "enum": ["document", "formulaire", "condition_forme"]},
                    "source_citation": {"type": "string", "description": "Extrait verbatim du texte exigeant cette pièce."},
                },
                "required": ["intitule", "type", "source_citation"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}


def message_utilisateur(titre: str, texte: str) -> str:
    return (f"Appel à projets : {titre}\n\n"
            f"<texte_officiel>\n{texte}\n</texte_officiel>\n\n"
            "Établis la liste des pièces et conditions de forme EXIGÉES, avec citation.")

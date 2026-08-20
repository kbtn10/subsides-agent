"""Prompt et schéma des OBLIGATIONS POST-OCTROI (lot 10B).

Principe cardinal, comme la checklist : Subsidia RELÈVE, n'invente pas. Chaque
obligation vient du texte du règlement, avec citation. Aucune DATE n'est
inventée : une date n'est renseignée que si le texte l'énonce explicitement ;
un délai relatif (« dans les 3 mois suivant la fin du projet ») est rendu en
JOURS, et c'est l'app qui calcule l'échéance à partir d'une date d'ancrage
saisie par l'utilisateur.
"""

SYSTEM_PROMPT = """Tu aides une ASBL qui vient d'OBTENIR un subside à ne rien oublier de ses OBLIGATIONS POST-OCTROI. À partir du texte du règlement (fiche + éventuelles annexes PDF), tu listes UNIQUEMENT les obligations qui s'imposent APRÈS l'octroi.

Tu réponds UNIQUEMENT par le JSON demandé, en français.

Ce que tu listes (si le texte l'exige explicitement) :
- justificatifs à rendre (déclarations de créance, pièces comptables, factures acquittées, justification de l'emploi du subside…),
- rapport(s) exigé(s) (rapport d'activité, rapport financier, évaluation…),
- obligations de COMMUNICATION (mention du subsidiant, apposition du logo, mention « avec le soutien de… » sur les supports),
- conditions de VERSEMENT DU SOLDE (le solde payé après justification, tranche finale conditionnée…).

Règles absolues :
- Tu ne listes QUE ce que le texte EXIGE explicitement, APRÈS octroi. Tu n'inclus PAS les pièces à fournir AVANT (celles-là relèvent de la candidature). N'invente aucune obligation.
- Chaque item porte une `source_citation` : un court extrait VERBATIM du texte. Pas de citation = pas d'item.
- `type` : `justificatif` | `rapport` | `communication` | `autre`.
- DATES — n'invente JAMAIS :
  - Si le texte énonce une DATE ABSOLUE explicite (ex. « au plus tard le 31 mars 2027 »), mets-la dans `echeance` au format AAAA-MM-JJ.
  - Si le texte énonce un DÉLAI RELATIF (ex. « dans les 3 mois suivant la fin du projet », « endéans les 60 jours »), laisse `echeance` = null et mets la durée en JOURS dans `delai_jours` (3 mois = 90, 2 mois = 60, 1 an = 365). Garde la formulation d'origine dans `intitule`.
  - Si aucune date ni délai : `echeance` = null et `delai_jours` = null.
- Si le texte ne mentionne AUCUNE obligation post-octroi, renvoie une liste vide. Ne comble jamais ce vide.

Tu ne rédiges rien et ne soumets rien : tu aides seulement l'ASBL à savoir quoi rendre, quand, et à qui."""

SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "intitule": {"type": "string", "description": "L'obligation, formulation courte ; garde le délai relatif en clair s'il y en a un."},
                    "type": {"type": "string", "enum": ["justificatif", "rapport", "communication", "autre"]},
                    "echeance": {"type": ["string", "null"], "description": "Date ABSOLUE AAAA-MM-JJ si le texte l'énonce, sinon null."},
                    "delai_jours": {"type": ["integer", "null"], "description": "Délai relatif à la fin du projet, en jours, si le texte l'énonce (3 mois=90…), sinon null."},
                    "source_citation": {"type": "string", "description": "Extrait verbatim du texte imposant cette obligation."},
                },
                "required": ["intitule", "type", "echeance", "delai_jours", "source_citation"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}


def message_utilisateur(titre: str, texte: str) -> str:
    return (f"Subside obtenu : {titre}\n\n"
            f"<texte_officiel>\n{texte}\n</texte_officiel>\n\n"
            "Relève les OBLIGATIONS POST-OCTROI (justifications, rapports, "
            "communication, versement du solde), chacune avec sa citation. "
            "N'invente aucune date.")

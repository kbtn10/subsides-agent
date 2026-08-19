"""Package scraper.

Injecte le trust store du système d'exploitation dans la couche SSL de Python
dès l'import. Motif : certains sites publics (ex. equal.brussels) présentent un
certificat signé par une autorité (GÉANT / Hellenic Academic CA) présente dans
le magasin de l'OS et des navigateurs, mais ABSENTE du bundle certifi qu'utilise
httpx par défaut -> "unable to get local issuer certificate". truststore aligne
Python sur le magasin de l'OS (c'est ce que fait pip lui-même).

On NE désactive PAS la vérification TLS : on vérifie simplement contre le même
magasin que le navigateur avec lequel les URLs ont été validées à la main.
Si truststore est absent, on retombe silencieusement sur certifi (les sites à
chaîne complète continuent de marcher ; seul equal.brussels en pâtirait).
"""

import logging

log = logging.getLogger(__name__)

try:
    import truststore

    truststore.inject_into_ssl()
except Exception as e:  # pragma: no cover - dépend de l'environnement
    log.warning("truststore indisponible (%s) — vérification TLS via certifi", e)

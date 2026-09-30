from django.core.cache import cache
from django.utils import timezone


DEMARCHE_NUMERIQUE_STATUS_CACHE_KEY = "demarche_numerique_api_indisponible"
DEMARCHE_NUMERIQUE_STATUS_TTL_SECONDS = 10 * 60
DEMARCHE_NUMERIQUE_HEALTHCHECK_CACHE_KEY = "demarche_numerique_api_healthcheck"
DEMARCHE_NUMERIQUE_HEALTHCHECK_TTL_SECONDS = 60


def signaler_indisponibilite_demarche_numerique(status_code=None):
    """Mémorise temporairement une indisponibilité de l'API Démarche Numérique."""
    cache.set(
        DEMARCHE_NUMERIQUE_STATUS_CACHE_KEY,
        {
            "status_code": status_code,
            "detected_at": timezone.now(),
        },
        timeout=DEMARCHE_NUMERIQUE_STATUS_TTL_SECONDS,
    )


def signaler_disponibilite_demarche_numerique():
    """Supprime l'alerte dès qu'un appel GraphQL aboutit à nouveau."""
    cache.delete(DEMARCHE_NUMERIQUE_STATUS_CACHE_KEY)


def get_statut_demarche_numerique():
    return cache.get(DEMARCHE_NUMERIQUE_STATUS_CACHE_KEY)


def get_dernier_controle_demarche_numerique():
    """Retourne le dernier contrôle actif, partagé brièvement entre les pages."""
    return cache.get(DEMARCHE_NUMERIQUE_HEALTHCHECK_CACHE_KEY)


def memoriser_controle_demarche_numerique(statut):
    cache.set(
        DEMARCHE_NUMERIQUE_HEALTHCHECK_CACHE_KEY,
        statut,
        timeout=DEMARCHE_NUMERIQUE_HEALTHCHECK_TTL_SECONDS,
    )

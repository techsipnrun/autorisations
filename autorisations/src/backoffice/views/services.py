"""Suivi des services externes dans le Back Office."""
import logging

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse

from DS.graphql_client import verifier_disponibilite_demarche_numerique
from declaration_manifestations.get_methods import (
    verifier_disponibilite_declaration_manifestations,
    verifier_disponibilite_declaration_manifestations_preprod,
)
from backoffice.services.externes import (
    get_etat_expiration_token_dn, verifier_acces_bdd_developpement,
    verifier_acces_bdd_production,
)

logger = logging.getLogger("ORM_DJANGO")


def _executer_controle_externe(nom, controle):
    """Empêche un contrôle isolé de faire échouer tout le tableau de suivi."""
    try:
        return controle()
    except Exception:
        logger.exception("Échec inattendu du contrôle du service externe %s", nom)
        return {
            "disponible": False,
            "configure": True,
            "detail": "Le contrôle de ce service a rencontré une erreur inattendue.",
        }


@login_required
def back_office_services_status(request):
    """Exécute les contrôles externes après le rendu du Back Office."""
    if not request.user.is_superuser:
        raise PermissionDenied("Cette page est réservée aux administrateurs.")

    etat_token_dn = _executer_controle_externe(
        "jeton Démarche Numérique", get_etat_expiration_token_dn
    )
    if etat_token_dn.get("expiration"):
        etat_token_dn["expiration"] = etat_token_dn["expiration"].isoformat()

    return JsonResponse({
        "demarche_numerique": _executer_controle_externe(
            "Démarche Numérique", verifier_disponibilite_demarche_numerique
        ),
        "declaration_manifestations_preprod": _executer_controle_externe(
            "Déclaration Manifestations préproduction",
            verifier_disponibilite_declaration_manifestations_preprod,
        ),
        "declaration_manifestations_prod": _executer_controle_externe(
            "Déclaration Manifestations production",
            verifier_disponibilite_declaration_manifestations,
        ),
        "bdd_developpement": _executer_controle_externe(
            "BDD développement", verifier_acces_bdd_developpement
        ),
        "bdd_production": _executer_controle_externe(
            "BDD production", verifier_acces_bdd_production
        ),
        "token_dn": etat_token_dn,
    })

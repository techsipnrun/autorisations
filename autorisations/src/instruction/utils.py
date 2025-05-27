import logging
from autorisations.models.models_instruction import EtapeDossier

logger = logging.getLogger('ORM_DJANGO')

def format_etat_dossier(etat_technique):
    mapping = {
        "sans_suite": "Sans suite",
        "refuse": "Refusé",
        "en_instruction": "En instruction",
        "en_construction": "En pré-instruction",
        "accepte": "Accepté"
    }
    return mapping.get(etat_technique, etat_technique.replace("_", " ").capitalize())


def changer_etape_si_differente(dossier, nom_etape):
    """
    Met à jour l'étape du dossier uniquement si elle est différente de l'étape actuelle.

    Args:
        dossier (Dossier): instance Django du dossier à modifier.
        nom_etape (str): nom exact de l'étape cible (champ `etape` de EtapeDossier).

    Returns:
        bool: True si modification effectuée, False sinon.
    """
    nouvelle_etape = EtapeDossier.objects.filter(etape=nom_etape).first()

    if not nouvelle_etape:
        logger.warning(f"[ÉTAPE] Étape '{nom_etape}' introuvable en base.")
        return False

    if dossier.id_etape_dossier != nouvelle_etape:
        logger.info(f"[ÉTAPE] Dossier {dossier.numero} : étape changée → {nom_etape}")
        dossier.id_etape_dossier = nouvelle_etape
        dossier.save()
        return True

    logger.debug(f"[ÉTAPE] Dossier {dossier.numero} : déjà à l'étape '{nom_etape}', pas de changement.")
    return False

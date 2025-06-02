import logging
from autorisations.models.models_instruction import EtapeDossier, EtatDossier

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


def changer_etape_si_differente(dossier, nom_etape, user):
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
        logger.error(f"[DOSSIER {dossier.numero}] Étape '{nom_etape}' introuvable en base.")
        return False

    if dossier.id_etape_dossier != nouvelle_etape:

        dossier.id_etape_dossier = nouvelle_etape
        dossier.save()

        logger.info(f"[DOSSIER {dossier.numero}] Passe à l'étape --> '{nom_etape}' par {user}")
        return True

    logger.debug(f"[DOSSIER {dossier.numero}] Déjà à l'étape '{nom_etape}' : pas de changement.")
    return False



def changer_etat_si_different(dossier, nom_etat, user):
    """
    Met à jour l'état du dossier uniquement si différent de l'état actuel.

    Args:
        dossier (Dossier): instance Django du dossier à modifier.
        nom_etat (str): nom (insensible à la casse) de l'état cible.
        user (User, optional): utilisateur Django à l'origine du changement.

    Returns:
        bool: True si modification effectuée, False sinon.
    """
    nouvel_etat = EtatDossier.objects.filter(nom__iexact=nom_etat).first()

    if not nouvel_etat:
        logger.error(f"[DOSSIER {dossier.numero}] Échec de changement d'état : '{nom_etat}' introuvable.")
        return False

    if dossier.id_etat_dossier != nouvel_etat:
        dossier.id_etat_dossier = nouvel_etat
        dossier.save()
 
        logger.info(f"[DOSSIER {dossier.numero}] Passage à l'état --> '{nouvel_etat.nom.capitalize()}' par {user}")
        return True

    logger.debug(f"[DOSSIER {dossier.numero}] État inchangé (déjà '{dossier.id_etat_dossier.nom}').")
    return False

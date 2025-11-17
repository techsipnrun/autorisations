# instruction/services/avis_utils.py
import logging
import os
from autorisations.models.models_instruction import Message
from autorisations.models.models_avis import AvisDocument, DossierAvis
from autorisations.utils.nas_fonctions import creer_dossier_sur_nas
from instruction.views.avis import enregistrer_document  # à ajouter en haut


logger = logging.getLogger("ORM_DJANGO")


def get_expert_label(avis, num_dossier: int) -> str:
    """
    Retourne le libellé expert (interne/externe) pour un avis.
    Ne lève pas d'exception : loggue et renvoie 'N/A' en cas de souci.
    """
    expert = "N/A"

    try:
        nature = avis.id_avis_nature.nature if avis.id_avis_nature else None

        if nature == "Demande à une instance":
            if avis.id_expert and avis.id_expert.id_contact_externe:
                expert = str(avis.id_expert.id_contact_externe)

        elif nature == "Consultation en interne":
            if avis.id_expert and avis.id_expert.id_instructeur:
                expert = f"{avis.id_expert.id_instructeur}"

        else:
            logger.warning(
                f"[AVIS {avis.id}] Consultation Dossier {num_dossier} — "
                f"Nature d'avis inattendue : {nature}"
            )

    except Exception as e:
        logger.error(
            f"[AVIS {avis.id}] Consultation Dossier {num_dossier} — "
            f"Erreur extraction expert : {e}"
        )

    return expert or "N/A"


def get_email_expert(avis, num_dossier: int) -> str | None:
    """
    Retourne l'email de l'expert (interne ou externe).
    Log en cas d’erreur et renvoie None si introuvable.
    """
    email_expert = None

    try:
        if avis.id_expert and avis.id_expert.est_interne:
            if avis.id_expert.id_instructeur:
                email_expert = avis.id_expert.id_instructeur.email
        elif avis.id_expert:
            email_expert = avis.id_expert.id_contact_externe.email

    except Exception as e:
        logger.error(
            f"[AVIS {avis.id}] Consultation Dossier {num_dossier} — "
            f"Erreur lecture email expert : {e}"
        )

    if not email_expert:
        logger.warning(
            f"[AVIS {avis.id}] Consultation Dossier {num_dossier} — "
            f"Email expert introuvable."
        )

    return email_expert


def count_unread_messages_for_avis(avis, email_expert: str | None, num_dossier: int) -> int:
    """
    Compte les messages non lus pour un avis donné, envoyés par l'expert.
    Ne lève pas d'exception, renvoie 0 en cas de problème.
    """
    if not email_expert:
        return 0

    try:
        return Message.objects.filter(
            id_avis=avis, lu=False, email_emetteur=email_expert
        ).count()
    except Exception as e:
        logger.error(
            f"[AVIS {avis.id}] Consultation Dossier {num_dossier} — "
            f"Erreur lors du calcul des messages non lus : {e}"
        )
        return 0


def get_demandeur_label(avis, num_dossier: int) -> str:
    """
    Retourne le nom complet du demandeur (instructeur).
    Ne lève pas d'exception.
    """
    demandeur = "N/A"

    try:
        if avis.id_instructeur and avis.id_instructeur.id_agent_autorisations:
            aa = avis.id_instructeur.id_agent_autorisations
            demandeur = f"{aa.nom} {aa.prenom}"
    except Exception as e:
        logger.error(
            f"[AVIS {avis.id}] Consultation Dossier {num_dossier} — "
            f"Erreur extraction demandeur : {e}"
        )

    return demandeur


def get_reponse_label(avis) -> str:
    """
    Traduit avis.favorable / statut en libellé lisible.
    """
    if avis.favorable is True:
        return "Favorable"
    if avis.favorable is False:
        return "Défavorable"
    if avis.statut == "Envoyé":
        return "En attente"
    return ""



def count_avis_with_unread_messages_for_dossier(dossier, num_dossier: int | None = None) -> int:
    """
    Retourne le nombre d'avis du dossier ayant au moins un message non lu
    de la part de l'expert.

    Ne lève pas d'exception : en cas d'erreur, log et renvoie 0.
    """
    compteur = 0
    dossier_id = num_dossier or getattr(dossier, "numero", None) or getattr(dossier, "id", None)

    try:
        dossiers_avis = DossierAvis.objects.filter(id_dossier=dossier).select_related(
            "id_avis",
            "id_avis__id_expert",
            "id_avis__id_expert__id_instructeur",
            "id_avis__id_expert__id_contact_externe",
        )
    except Exception as e:
        logger.error(
            f"[DOSSIER {dossier_id}] Erreur lors de la récupération des DossierAvis "
            f"pour le calcul des avis avec nouveaux messages : {e}"
        )
        return 0

    for da in dossiers_avis:
        avis = da.id_avis
        if not avis or not avis.id_expert:
            continue

        email_expert = get_email_expert(avis, dossier_id)
        nb_non_lus_avis = count_unread_messages_for_avis(avis, email_expert, dossier_id)

        if nb_non_lus_avis > 0:
            compteur += 1

    return compteur



def attach_pj_to_avis(avis, fichiers, emplacement_avis, request, dossier_numero = None):
    """
    Gère entièrement les pièces jointes à un avis.
    """
    if not fichiers:
        return

    full_path = f"{os.getenv('NAS_ROOT')}{emplacement_avis}Annexes/"
    creer_dossier_sur_nas(full_path)

    for pj in fichiers:
        doc = enregistrer_document(
            fichier=pj,
            nature_str="Annexe avis",
            description=f"Pièce jointe pour la demande d'avis {avis.id} effectuée hors application",
            request=request,
            emplacement_avis=emplacement_avis,
        )

        if doc:
            AvisDocument.objects.create(id_avis=avis, id_document=doc)
        else:
            if dossier_numero :
                logger.warning(f"[DOSSIER {dossier_numero}] Avis {avis.id} : impossible d'attacher une PJ.")
            else :
                logger.warning(f"[AVIS {avis.id}] Impossible d'attacher une PJ.")



def delete_pj_from_avis(avis_document: AvisDocument, email_user: str):
    """
    Supprime proprement :
    - la relation AvisDocument
    - le document associé (physique en base)
    - loggue chaque étape
    """

    avis = avis_document.id_avis
    doc = avis_document.id_document

    titre_doc = getattr(doc, "titre", f"document_{doc.id}")
    avis_id = avis.id if avis else "???"

    logger.info(
        f"[PJ_AVIS_DELETE] Suppression PJ '{titre_doc}' — avis={avis_id}, user={email_user}"
    )

    # Suppression relation
    try:
        avis_document.delete()
    except Exception as e:
        logger.error(
            f"[PJ_AVIS_DELETE] Erreur suppression lien AvisDocument — avis={avis_id}, doc={doc.id} : {e}"
        )
        raise

    # Suppression document
    try:
        doc.delete()
    except Exception as e:
        logger.error(
            f"[PJ_AVIS_DELETE] Erreur suppression document — avis={avis_id}, doc={doc.id} : {e}"
        )
        raise

    logger.info(f"[AVIS {avis_id}] Pièce jointe {doc.id} ({doc.titre}) supprimée par {request.user}")


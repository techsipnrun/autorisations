# instruction/services/avis_utils.py
import logging
import os
from pathlib import Path
from autorisations.models.models_instruction import Message
from autorisations.models.models_avis import AvisDocument, AvisThematique, DossierAvis, Expert
from autorisations.models.models_utilisateurs import ContactExterne, Instructeur
from autorisations.utils.nas_fonctions import creer_dossier_sur_nas
from instruction.utils_instru import enregistrer_document
from synchronisation.utils.fichiers import nettoyer_nom_fichier


logger = logging.getLogger("ORM_DJANGO")

GROUPES_PUBLICATION_RAA_CS = (
    "Publication RAA CS",
    "Publication RAA Avis CS",
)


def utilisateur_est_publicateur_raa_cs(user):
    return bool(
        user
        and user.is_authenticated
        and user.groups.filter(name__in=GROUPES_PUBLICATION_RAA_CS).exists()
    )


def avis_est_conseil_scientifique(avis):
    expert = getattr(avis, "id_expert", None)
    contact = getattr(expert, "id_contact_externe", None) if expert else None
    if not expert or expert.est_interne or not contact:
        return False

    valeurs_identite = (
        contact.raison_sociale,
        contact.organisation,
    )
    return any(
        (valeur or "").strip().casefold() == "conseil scientifique"
        for valeur in valeurs_identite
    )


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


def get_email_expert(avis, num_dossier = None) -> str | None:
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
        if num_dossier :
            logger.error(f"[AVIS {avis.id}] Dossier {num_dossier} — Erreur lecture email expert : {e}")
        else :
            logger.error(f"[AVIS {avis.id}] Erreur lecture email expert : {e}")

    if not email_expert:
        if num_dossier :
            logger.warning(f"[AVIS {avis.id}] Dossier {num_dossier} — Email expert introuvable.")
        else :
            logger.warning(f"[AVIS {avis.id}] Email expert introuvable.")


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

    logger.info(f"[AVIS {avis_id}] Pièce jointe {doc.id} ({doc.titre}) supprimée.")



def get_or_create_expert_from_form(request):
    """
    Détermine l'expert (interne ou externe) et renvoie un tuple : (expert_obj, nom_expert_normalise)

    Cette fonction :
    - lit les champs POST : expert_interne / expert_externe
    - récupère l'objet Instructeur ou ContactExterne correspondant
    - crée un Expert si nécessaire (get_or_create)
    - normalise un nom prédictible pour construire les chemins NAS
    - renvoie l'expert et son nom normalisé

    Lève :
        ValueError — si aucun expert n'est fourni dans le formulaire.
    """
    expert_interne_id = request.POST.get("expert_interne")
    expert_externe_id = request.POST.get("expert_externe")

    if expert_interne_id:
        instru = Instructeur.objects.get(id=expert_interne_id)
        expert, created = Expert.objects.get_or_create(
            id_instructeur=instru,
            defaults={"est_interne": True},
        )
        if created:
            logger.info(f"[EXPERT] Nouveau expert interne créé : {instru}")

        # Normalisation nom/prénom pour l’arborescence NAS
        nom_expert = nettoyer_nom_fichier(f"{instru.id_agent_autorisations.nom}_{instru.id_agent_autorisations.prenom}")
        # email_expert = instru.email
        return expert, nom_expert

    if expert_externe_id:
        contact = ContactExterne.objects.get(id=expert_externe_id)
        expert, created = Expert.objects.get_or_create(
            id_contact_externe=contact,
            defaults={"est_interne": False},
        )
        if created:
            logger.info(f"[EXPERT] Nouvel expert externe créé : {contact}")

        if contact.nom and contact.prenom:
            nom = f"{contact.nom}_{contact.prenom}"
        else:
            nom = contact.raison_sociale or contact.organisation or "Expert"

        # Normalisation nom/prénom pour l’arborescence NAS
        nom_expert = nettoyer_nom_fichier(nom)
        # email_expert = contact.email

        return expert, nom_expert

    raise ValueError("Aucun expert interne/externe fourni.")



def get_expert_from_user(user):
    """Retourne l’expert interne ou externe correspondant au user."""

    expert = Expert.objects.filter(id_instructeur__email=user.email).first()
    if not expert:
        expert = Expert.objects.filter(id_contact_externe__email=user.email).first()
    return expert




def build_avis_for_dossier(dossier):
    """Retourne toutes les infos relatives aux avis d'un dossier."""

    # Querysets principaux
    avis_du_dossier = DossierAvis.objects.filter(id_dossier=dossier).select_related(
        "id_avis__id_avis_nature",
        "id_avis__id_expert",
    )

    avis_a_valider = avis_du_dossier.filter(id_avis__statut="À valider")
    avis_a_envoyer = avis_du_dossier.filter(id_avis__statut="À envoyer")
    avis_statut_brouillon = avis_du_dossier.filter(id_avis__statut="Brouillon")
    avis_envoye = avis_du_dossier.filter(id_avis__statut="Envoyé")

    # Nombre d'avis envoyés
    nb_avis_envoyes = avis_envoye.count()

    # Ajouter les documents "Avis instance" aux avis envoyés
    for da in avis_envoye:
        da.id_avis.documents = [
            ad.id_document
            for ad in AvisDocument.objects
                .select_related("id_document__id_nature")
                .filter(id_avis=da.id_avis,
                        id_document__id_nature__nature="Avis instance")
        ]

    # Messages non lus envoyés par les experts
    nb_avis_avec_nouveau_mess = 0

    for da in avis_du_dossier:
        avis = da.id_avis
        if not avis or not avis.id_expert:
            continue

        # Déterminer l'email de l’expert ou instructeur interne
        if avis.id_expert.est_interne:
            email_expert = avis.id_expert.id_instructeur.email
        else:
            email_expert = avis.id_expert.id_contact_externe.email

        # Nombre de messages non lus associés à cet avis
        nb_non_lus = Message.objects.filter(
            id_avis=avis,
            lu=False,
            email_emetteur=email_expert,
        ).count()

        if nb_non_lus > 0:
            nb_avis_avec_nouveau_mess += 1

    # Objet final retourné
    return {
        "avis_du_dossier": avis_du_dossier,
        "avis_a_valider": avis_a_valider,
        "avis_a_envoyer": avis_a_envoyer,
        "avis_statut_brouillon": avis_statut_brouillon,
        "avis_envoye": avis_envoye,
        "nb_avis_envoyes": nb_avis_envoyes,
        "nb_avis_avec_nouveau_mess": nb_avis_avec_nouveau_mess,
    }



def thematiques_avis_liees_a_demarche(demarche):
    """
    Retourne les thématiques d'avis liées à une démarche donnée.
    Inclut toujours 'Tous' et 'Autre'.
    """

    if not demarche or not demarche.type:
        return AvisThematique.objects.all().order_by("thematique")

    type_demarche = demarche.type.lower()

    # Mapping métier
    mapping = {
        "activités agricoles": "Activités agricoles",
        "activités commerciales": "Activités commerciales",
        "courses d'arêtes": "Courses d'arêtes",
        "document": "Documents de planification et d'urbanisme",
        "drone": "Drone - Prise de vue",
        "manifestation publique": "Manifestations publiques",
        "manifestation sportive": "Manifestations sportives",
        "mission scientifique": "Mission scientifique",
        "survol": "Survol hélicoptère",
        "travaux": "Travaux",
    }

    demarche_cible = None
    for key, value in mapping.items():
        if key in type_demarche:
            demarche_cible = value
            break

    valeurs = ["Autre"]

    if demarche_cible:
        valeurs.append(demarche_cible)

    return AvisThematique.objects.filter(demarche__in=valeurs).order_by("thematique")

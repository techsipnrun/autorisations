from pathlib import Path
import re
import smtplib
import unicodedata
from django.db import DatabaseError, IntegrityError, connection
from django.shortcuts import get_object_or_404
from django.utils import timezone
import logging

import smbclient
from autorisations.models.models_instruction import Action, Dossier, DossierAction, EtapeDossier, EtatDossier, Message
# import pythoncom
# import win32com.client
import os
import subprocess
import tempfile
import shutil
from django.contrib import messages


from autorisations.models.models_utilisateurs import DossierEnvoiActe, DossierInstructeur, DossierIntermediaireSignature, DossierPublicationRAA, DossierRelecteur, DossierRelecteurQualite, DossierSignataire, DossierValideur, EmailOutbox, Instructeur
from autorisations.models.models_documents import Document, DocumentFormat, DocumentNature, MessageDocument
from autorisations.utils.nas_fonctions import creer_dossier_sur_nas, ecrire_file_sur_nas
from notifications.service import compute_dedupe_key, create_EmailOutbox, envoi_mail, envoi_notification_par_mail
from psycopg2.errors import UniqueViolation
# import smbclient
# from smbprotocol import exceptions as smb_exceptions

# loggerApp = logging.getLogger("APP")
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


def template_mail_name_from_etape(label):
    """
    Transforme un label d'étape en nom d'URL Django, ex :
    "Passer en pré-instruction" -> "passer_en_pre_instruction_url"
    """
    label = unicodedata.normalize('NFD', label).encode('ascii', 'ignore').decode("utf-8")
    label = re.sub(r"[^a-zA-Z0-9]+", "_", label.strip().lower())
    return label



def changer_etape_si_differente(dossier, nom_etape, user, request):
    """
    Change l'étape du dossier si elle est différente.
    Envoie aussi une notification mail si nécessaire.
    Lève des exceptions en cas d'erreur.
    """

    # --- Récupération étape cible ---
    nouvelle_etape = EtapeDossier.objects.filter(etape=nom_etape).first()
    if not nouvelle_etape:
        raise ValueError(f"[DOSSIER {dossier.numero}] Étape '{nom_etape}' introuvable en base.")

    # --- Déjà à la bonne étape → rien à faire ---
    if dossier.id_etape_dossier == nouvelle_etape:
        logger.warning(f"[DOSSIER {dossier.numero}] Étape inchangée par {user}. Le dossier est déjà à l'étape '{nom_etape}'.")
        return


    # --- Tentative de changement d'étape ---
    try :
        dossier.id_etape_dossier = nouvelle_etape

        # Si acceptation/refus → date de fin d'instruction
        if nouvelle_etape.etape == 'Accepté' or nouvelle_etape.etape == 'Refusé' or nouvelle_etape.etape == 'Non soumis à autorisation' :
            dossier.date_fin_instruction = timezone.now()
            
        dossier.save()
        logger.info(f"[DOSSIER {dossier.numero}] Passage à l'étape --> '{nom_etape}' par {user}")

    except Exception as e:
        raise Exception(f"[DOSSIER {dossier.numero}] Erreur lors du changement d'étape vers '{nom_etape}' par {user} : {e}")


    #######################
    # NOTIFICATION PAR MAIL 
    #######################

    # --- Étapes finales → pas de notification mail pour le moment ---
    if nouvelle_etape.etape == 'Accepté' or nouvelle_etape.etape == 'Refusé' or nouvelle_etape.etape == 'Non soumis à autorisation' :
        return
    
    
    # --- Notification mail pour les autres étapes ---
    user_faisant_le_changement = Instructeur.objects.filter(email=user.email).first()
    users_ayant_une_action_a_faire = get_instructeurs_a_actionner(dossier)
    

    # Aucun user désigné pour faire la prochaine action
    if not users_ayant_une_action_a_faire :
        logger.error(f"[DOSSIER {dossier.numero}] Passage à l'étape --> '{nom_etape}' par {user}. Aucun user désigné pour réaliser la prochaine action.")
        return

    # print(f"Users ayant une action à faire sur le dossier : {users_ayant_une_action_a_faire}")

    # On ne notifie pas le user ayant fait le changement d'étape
    if not (len(users_ayant_une_action_a_faire) == 1 and user_faisant_le_changement in users_ayant_une_action_a_faire) :

        # On recup les mails des users avec une action à faire
        # emails_norm = [i.email for i in users_ayant_une_action_a_faire if i and i != user_faisant_le_changement]
        # print(f"Mails des users ayant une action à faire suite au changement d'étape : {emails_norm2}")

        emails_norm = ["louis.calu@reunion-parcnational.fr"]
        emails_txt = ", ".join(emails_norm)

        if not emails_norm:
            messages.error(request, f"L'email de notification à {users_ayant_une_action_a_faire} n'a pas été envoyé. Contactez le support pour en savoir plus.")
            logger.error(f"[DOSSIER {dossier.numero}] Passage à l'étape --> '{nom_etape}' par {user}. Aucun user notifié parmi {users_ayant_une_action_a_faire} : Email introuvable")
            return

        sujet = f"Dossier {dossier.numero} - Action à faire"
        context = {
            "dossier_numero": dossier.numero,
            "demarche_type": dossier.id_demarche.type,
            "dossier_etape": dossier.id_etape_dossier.etape,
            "url": f"{os.getenv('URL_APPLI')}instruction/{dossier.numero}/"
        }
        template_name = "changement_etape"


        try :
            dedupe = compute_dedupe_key(emails_norm, sujet, template_name, context)

        except Exception as e:
            messages.error(request, f"L'email de notification à {emails_txt} n'a pas été envoyé. Contactez le support pour en savoir plus.")
            logger.error(f"[DOSSIER {dossier.numero}] Échec de la notification par mail suite au passage à l'étape '{nom_etape}' par {user} : Erreur lors de la création de la clé unique (compute_dedupe_key) : {e}")
            return

        outbox = create_EmailOutbox(emails_norm, sujet, template_name, dedupe, context, dossier, type_mail = "Notification")
        
        if outbox :
            ok, err = envoi_mail(outbox.id)
        else :
            logger.error(f"[DOSSIER {dossier.numero}] Erreur lors de la création de l'EmailOutbox, personne n'a été notifié du changement d'étape à '{nouvelle_etape.etape}'")
            messages.error(request, f"{emails_txt} n'a pas été notifié du changement d'étape à '{nouvelle_etape.etape}'. Contactez le support pour en savoir plus.")
            return

        if ok:
            logger.info(f"[DOSSIER {dossier.numero}] Notification Email {outbox.id} ({outbox.sujet}) envoyée à {', '.join(outbox.to)} ")
        else:
            logger.error(f"[DOSSIER {dossier.numero}] Échec envoi notification email {outbox.id} ({outbox.sujet}) à {', '.join(outbox.to)} : {err}")
            messages.error(request, f"{emails_txt} n'a pas été notifié du changement d'étape à '{nouvelle_etape.etape}'. Contactez le support pour en savoir plus.")

    return




def changer_etat_si_different(dossier, nom_etat, user):
    """
    Met à jour l'état du dossier uniquement si différent.
    Lève toujours une exception en cas d'erreur.
    """
    nouvel_etat = EtatDossier.objects.filter(nom__iexact=nom_etat).first()

    if not nouvel_etat:
        raise ValueError(f"[DOSSIER {dossier.numero}] Échec de changement d'état : Etat '{nom_etat}' introuvable en base.")

    # --- Mise à jour état ---
    if dossier.id_etat_dossier != nouvel_etat:
        try:
            dossier.id_etat_dossier = nouvel_etat
            dossier.save()
            logger.info(f"[DOSSIER {dossier.numero}] Passage à l'état --> '{nouvel_etat.nom.capitalize()}' par {user}")

        except Exception as e:
            raise Exception(f"[DOSSIER {dossier.numero}] Erreur lors de la modification de l'état '{dossier.id_etat_dossier}' → '{nom_etat}' par {user} : {e}")
    # logger.debug(f"[DOSSIER {dossier.numero}] État inchangé (déjà '{dossier.id_etat_dossier.nom}').")



def enregistrer_action(dossier, instructeur, nom_action, description=None, date=None):

    action_obj = Action.objects.filter(action=nom_action).first()
    if not action_obj:
        raise ValueError(f"Action '{nom_action}' introuvable en base.")
    
    if action_obj and instructeur :
        try:
            DossierAction.objects.create(
                id_dossier=dossier,
                id_instructeur=instructeur,
                id_action=action_obj,
                description=description,
                date=date
            )

        except Exception as e:
            raise Exception(f"Erreur lors de la création du DossierAction ({action_obj}) : {e}")



def dossiers_action_a_faire(dossiers, obj_instructeur):
    """
    Retourne les dossiers où l'utilisateur doit réaliser une action,
    en fonction de son rôle implicite selon l'étape du dossier.
    """
    dossiers_a_traiter_ids = set()

    for dossier in dossiers:
        etape = dossier.id_etape_dossier.etape if dossier.id_etape_dossier else None

        # Vérifications par rôle
        est_instructeur = DossierInstructeur.objects.filter(id_dossier=dossier, id_instructeur=obj_instructeur).exists()
        est_valideur = DossierValideur.objects.filter(id_dossier=dossier, id_instructeur=obj_instructeur).exists()
        est_relecteur_qualite = DossierRelecteurQualite.objects.filter(id_dossier=dossier, id_instructeur=obj_instructeur).exists()
        est_relecteur = DossierRelecteur.objects.filter(id_dossier=dossier, id_instructeur=obj_instructeur).exists()
        est_signataire = DossierSignataire.objects.filter(id_dossier=dossier, id_instructeur=obj_instructeur).exists()
        est_intermediaire_signature = DossierIntermediaireSignature.objects.filter(id_dossier=dossier, id_instructeur=obj_instructeur).exists()
        est_envoyeur_acte_signe = DossierEnvoiActe.objects.filter(id_dossier=dossier, id_instructeur=obj_instructeur).exists()
        est_publieur_RAA = DossierPublicationRAA.objects.filter(id_dossier=dossier, id_instructeur=obj_instructeur).exists()

        
        # === Mapping Étape -> Rôle attendu ===
        if est_relecteur :
            drj = DossierRelecteur.objects.filter(id_dossier=dossier, id_instructeur=obj_instructeur).first()
            # Si relecture pas encore faite --> action à faire
            if not drj.relu and etape not in ["Non soumis à autorisation", "Refusé", "Accepté"]  :
                dossiers_a_traiter_ids.add(dossier.id)

        if etape in ["À valider avant signature", "À valider avant demande d'avis"] :
            # Rôle : Valideur
            if est_valideur:  
                dossiers_a_traiter_ids.add(dossier.id)

        elif etape in ["Non soumis à autorisation", "Refusé", "Accepté"]:
            # Nb messages non lus côté pétitionnaire
            nb_messages_non_lus = Message.objects.filter(
                id_dossier=dossier,
                lu=False
            ).exclude(
                email_emetteur__in=[
                    "contact@demarches-simplifiees.fr",
                    "contact@demarche.numerique.gouv.fr",
                ]
            ).exclude(
                email_emetteur__endswith='reunion-parcnational.fr'
            ).count()

            # Rôle : Instructeur et messages non lus
            if est_instructeur and nb_messages_non_lus > 0:
                dossiers_a_traiter_ids.add(dossier.id)

        elif etape in ["En instruction", "En pré-instruction", "En attente réponse d'avis", "En attente de compléments", "Avis à envoyer"]:
            # Rôle : Instructeur
            if est_instructeur:
                dossiers_a_traiter_ids.add(dossier.id)

        elif etape in ["En relecture qualité"]:
            # Rôle : Relecteur Qualité
            if est_relecteur_qualite:
                dossiers_a_traiter_ids.add(dossier.id)
        
        elif etape in ["À publier au RAA"]:
            # Rôle : Publieur RAA
            if est_publieur_RAA:
                dossiers_a_traiter_ids.add(dossier.id)

            
        elif etape in ["Acte à envoyer"]:
            # Rôle : Envoyeur de l'acte signé
            if est_envoyeur_acte_signe:
                dossiers_a_traiter_ids.add(dossier.id)

        elif etape in ["En attente de signature"]:
            # Rôle : Intermédiaire signature
            if est_intermediaire_signature:
                dossiers_a_traiter_ids.add(dossier.id)

            # Pour "À publier au RAA" et "Acte à envoyer" si délib CA et que le user appartient au groupe 'Intermédiaire CA' alors dossiers_a_traiter_ids.add(dossier.id)

        # elif etape == "En attente de signature": #(pour le moment la signature se fait en dehors)
        #     # Rôle : Signataire
        #     if est_signataire: 
        #         dossiers_a_traiter_ids.add(dossier.id)

    return Dossier.objects.filter(id__in=dossiers_a_traiter_ids)



def dossiers_reception_action_a_faire(dossiers, user):
    """
    Retourne les dossiers où l'utilisateur doit affecter le dossier qui est en reception
    POUR LE MOMENT ON EXCLU LES DOSSIERS DE MANIFESTATIONS SPORTIVES
    """
    if not user.is_authenticated:
        return set()
    
    # Exclure les démarches "Manifestations sportives"
    dossiers = dossiers.exclude(id_demarche__type__icontains="manifestations sportives")

    dossiers_a_traiter_ids = set()

    # Vérification rôle Reception
    est_receptionniste_SAADD = False
    est_receptionniste_SPPN = False

    if user.groups.filter(name="Réception SAADD").exists():
        est_receptionniste_SAADD = True
    if user.groups.filter(name="Réception SPPN").exists():
        est_receptionniste_SPPN = True


    for dossier in dossiers:
        # SPPN
        if dossier.id_demarche and dossier.id_demarche.type and "mission scientifique" in dossier.id_demarche.type.lower():
            if est_receptionniste_SPPN :
                dossiers_a_traiter_ids.add(dossier.id)
        # SAADD
        else :
            if est_receptionniste_SAADD :
                dossiers_a_traiter_ids.add(dossier.id)

    return Dossier.objects.filter(id__in=dossiers_a_traiter_ids)



def create_message_avis_bdd(body, email_emetteur, avis_obj,
                            document_file=None,  # fichier ouvert, ou None
                            document_title=None,  # titre affiché (nom d'origine)
                            document_format_str=None,  # ex: 'pdf', 'jpg'
                            document_nature_str="Pièce jointe message",
                            document_description=None,
                        ):
    """
    Crée un message (et éventuellement une pièce jointe) dans la base de données.

    Args:
        body (str): Contenu textuel du message.
        email_emetteur (str): Email de l'expéditeur.
        dossier_obj (Dossier): Instance du dossier lié au message.
        document_file (UploadedFile, optional): Fichier joint (format Django), ou None.
        document_title (str, optional): Nom d’origine de la pièce jointe (ex: "photo.pdf").
        document_format_str (str, optional): Format du document (ex: "pdf", "jpg").
        document_nature_str (str, optional): Nature du document (défaut: "Pièce jointe message").
        document_description (str, optional): Description libre du document.

    Returns:
        Tuple[Message, Optional[Document]]: 
            Le message créé et, s’il y en a une, la pièce jointe associée.

    Raises:
        Exception: En cas d’erreur lors de la création du document ou du lien.
    """
    try:

        # 1. Création du message (sans pièce jointe pour l'instant)
        msg = Message.objects.create(
            body=body,
            date_envoi=timezone.now(),
            piece_jointe=bool(document_file),
            email_emetteur=email_emetteur,
            id_avis=avis_obj,
            lu=False,
        )

        logger.info(f"[AVIS {avis_obj.id}] Message {msg.id} enregistré en BDD par {email_emetteur}")

        doc = None
        if document_file:

            try:

                # 2. Créer le Document
                # Récupérer ou créer le format et la nature
                doc_format, _ = DocumentFormat.objects.get_or_create(format=document_format_str)
                doc_nature, _ = DocumentNature.objects.get_or_create(nature=document_nature_str)

                # Répertoire cible
                repertoire_annexes = os.path.join(os.environ.get("NAS_ROOT"), avis_obj.emplacement, "Annexes")
                creer_dossier_sur_nas(repertoire_annexes)

                # Séparation du nom et extension
                nom_base, ext = os.path.splitext(document_title)
                titre_final = nom_base
                i = 1

                # Boucle jusqu'à trouver un nom de fichier et d'enregistrement non existant
                while True:
                    emplacement = os.path.join(repertoire_annexes, f"{titre_final}{ext}")
                    rel_emplacement = os.path.join(avis_obj.emplacement, "Annexes/")  # Pour la BDD

                    fichier_existe = smbclient.path.exists(emplacement)
                    enregistrement_existe = Document.objects.filter(emplacement=rel_emplacement, titre=f"{titre_final}{ext}").exists()

                    if not fichier_existe and not enregistrement_existe:
                        break  # nom libre

                    i += 1
                    titre_final = f"{nom_base}_{i}"

                # Écriture du fichier sur le NAS
                if not ecrire_file_sur_nas(document_file, emplacement):
                    logger.error(f"[NAS] ❌ Échec de l’écriture du fichier {document_file.name} sur {emplacement}")

                # Création du document en base
                doc = Document.objects.create(
                    id_format=doc_format,
                    id_nature=doc_nature,
                    emplacement=rel_emplacement,
                    titre=f"{titre_final}{ext}",
                    description=document_description or "",
                )

                logger.info(f"[AVIS {avis_obj.id}] - Document {doc.id} ({document_nature_str}) créé")

                # 3. Créer le lien message-document
                MessageDocument.objects.create(
                    id_message=msg,
                    id_document=doc
                )


            except Exception as e_doc:
                logger.error(f"[AVIS {avis_obj.id}] Erreur lors de la création de la pièce jointe pour Message {msg.id} : {e_doc}")
                msg.delete()  # rollback du message si le document échoue
                raise Exception(f"Erreur lors de la création du document : {e_doc}")

        return msg, doc
    

    except Exception as e:
        logger.error(f"[AVIS {avis_obj.id}] {avis_obj} - Échec de création du message : {e}")
        raise



# def dossier_etape_action_a_faire(dossier, obj_instructeur):
#     """
#     Retourne True si c'est au user en question de faire évoluer l'étape du dossier
#     False sinon
#     """

#     etape = dossier.id_etape_dossier.etape if dossier.id_etape_dossier else None

#     # Vérifications par rôle
#     est_instructeur = DossierInstructeur.objects.filter(id_dossier=dossier, id_instructeur=obj_instructeur).exists()
#     est_valideur = DossierValideur.objects.filter(id_dossier=dossier, id_instructeur=obj_instructeur).exists()
#     est_relecteur_qualite = DossierRelecteurQualite.objects.filter(id_dossier=dossier, id_instructeur=obj_instructeur).exists()
#     est_signataire = DossierSignataire.objects.filter(id_dossier=dossier, id_instructeur=obj_instructeur).exists()


#     if etape in ["À valider avant signature", "À valider avant demande d'avis"] :
#         # Rôle : Valideur
#         if est_valideur:  
#             return True

#     elif etape in ["En instruction", "En Pré-instruction", "En attente réponse d'avis", "En attente de compléments", "Avis à envoyer", "En attente de compléments"]:
#         # Rôle : Instructeur
#         if est_instructeur:
#             return True

#     elif etape in ["À affecter", "En relecture qualité", "À publier au RAA", "Acte à envoyer", "En attente de signature"]:
#         # Rôle : Relecteur Qualité
#         if est_relecteur_qualite:
#             return True

#     elif etape == "En attente de signature":
#         # Rôle : Signataire
#         if est_signataire: 
#             return True

#     return False


def get_instructeurs_a_actionner(dossier):
    """
    Retourne la liste des instructeurs (objets Instructeur)
    ayant une action à faire sur le dossier donné,
    selon l’étape actuelle.
    """

    etape = dossier.id_etape_dossier.etape if dossier.id_etape_dossier else None
    if not etape:
        logger.error(f"[DOSSIER {dossier.numero}] Erreur lors de l'envoi de mail pour notifier le changement d'étape (Etape '{dossier.id_etape_dossier}') introuvable")
        return []

    # Étapes où les INSTRUCTEURS agissent
    if etape in ["En instruction", "En pré-instruction", "En attente réponse d'avis", "En attente de compléments", "Avis à envoyer"]:
        instructeurs = (DossierInstructeur.objects.filter(id_dossier=dossier).select_related("id_instructeur").values_list("id_instructeur", flat=True))

    # Étapes où les VALIDEURS agissent
    elif etape in ["À valider avant signature", "À valider avant demande d'avis"]:
        instructeurs = (DossierValideur.objects.filter(id_dossier=dossier).select_related("id_instructeur").values_list("id_instructeur", flat=True))

    # Étapes où les RELECTEURS QUALITÉ agissent
    elif etape in ["En relecture qualité"]:
        instructeurs = (DossierRelecteurQualite.objects.filter(id_dossier=dossier).select_related("id_instructeur").values_list("id_instructeur", flat=True))

    # Étapes où les PUBLIEURS RAA agissent
    elif etape in ["À publier au RAA"]:
        instructeurs = (DossierPublicationRAA.objects.filter(id_dossier=dossier).select_related("id_instructeur").values_list("id_instructeur", flat=True))

    # Étapes où les ENVOYEURS D'ACTE agissent
    elif etape in ["Acte à envoyer"]:
        instructeurs = (DossierEnvoiActe.objects.filter(id_dossier=dossier).select_related("id_instructeur").values_list("id_instructeur", flat=True))

    # Étapes où les INTERMEDIAIRES SIGNATURE agissent
    elif etape in ["En attente de signature"]:
        instructeurs = (DossierIntermediaireSignature.objects.filter(id_dossier=dossier).select_related("id_instructeur").values_list("id_instructeur", flat=True))

    # Étapes où les SIGNATAIRES agissent (pour le moment la signature se fait en dehors)
    # elif etape == "En attente de signature":
    #     instructeurs = (DossierSignataire.objects.filter(id_dossier=dossier).select_related("id_instructeur").values_list("id_instructeur", flat=True))

    # Si liste vide alors on mets des "actionneurs" par défaut
    if not instructeurs :
        logger.warning(f"[DOSSIER {dossier.numero}] Aucun user désigné pour faire la prochaine action suite au changement d'étape ('{etape}')")
        
        # Instructeurs
        instructeurs = (DossierInstructeur.objects.filter(id_dossier=dossier).select_related("id_instructeur").values_list("id_instructeur", flat=True))
        if instructeurs :
            instructeurs_str = ", ".join(Instructeur.objects.filter(id=i).first() for i in instructeurs)
            logger.warning(f"[DOSSIER {dossier.numero}] {instructeurs_str} désigné.s par défaut pour faire la prochaine action suite au changement d'étape ('{etape}')")
        else :

            # Relecteurs qualité
            instructeurs = (DossierRelecteurQualite.objects.filter(id_dossier=dossier).select_related("id_instructeur").values_list("id_instructeur", flat=True))
            if instructeurs :
                instructeurs_str = ", ".join(Instructeur.objects.filter(id=i).first() for i in instructeurs)
                logger.warning(f"[DOSSIER {dossier.numero}] {instructeurs_str} désigné.s par défaut pour faire la prochaine action suite au changement d'étape ('{etape}')")
            else :
                logger.error(f"[DOSSIER {dossier.numero}] Changement d'étape '{etape}' : Aucun user désigné pour faire la prochaine action (aucun instructeur et aucun relecteur qualité sur le dossier).")

    # On retourne la liste des objets `Instructeur` correspondants
    return list(Instructeur.objects.filter(id__in=instructeurs))




def enregistrer_document(fichier, nature_str, description, request, emplacement_avis, annexe=True):
    if not fichier:
        return None

    # Extension du fichier
    nom, extension = os.path.splitext(fichier.name)
    extension = extension.lstrip('.').lower()

    # Récupération du format
    format_obj = DocumentFormat.objects.filter(format__iexact=extension).first()
    if not format_obj:
        messages.error(request, f"Format {extension} non reconnu. Contactez le support.")
        return None

    # Récupération de la nature
    nature_obj = DocumentNature.objects.filter(nature__iexact=nature_str).first()
    if not nature_obj:
        messages.error(request, f"Nature '{nature_str}' introuvable. Contactez le support.")
        return None

    # Emplacement et chemin
    if annexe :
        emplacement_annexes = f"{emplacement_avis}Annexes/"
    else :
        emplacement_annexes = emplacement_avis

    chemin_complet = f"{os.getenv('NAS_ROOT')}{emplacement_annexes}"
    filepath = os.path.join(chemin_complet, fichier.name)

    # Maj de l'ancien doc s’il existe
    doc = Document.objects.filter(emplacement=emplacement_annexes, titre=fichier.name).first()
    if doc:
        try :

            # Mise à jour plutôt que suppression
            doc.id_format = format_obj
            doc.id_nature = nature_obj
            doc.description = description
            doc.save(update_fields=["id_format", "id_nature", "description"])
        except Exception as e:
            logger.error(f"[MAJ DOCUMENT] Erreur lors de la mise à jour du document {filepath} : {e}")
            messages.error(request, f"Erreur lors de la mise à jour du document {fichier.name}. Contactez le support.")
            return None
    else:
        try :
            # Création
            doc = Document.objects.create(
                id_format=format_obj,
                id_nature=nature_obj,
                emplacement=emplacement_annexes,
                titre=fichier.name,
                description=description,
            )
        except Exception as e:
            logger.error(f"[CREATE DOCUMENT] Erreur lors de la création du document {filepath} : {e}")
            messages.error(request, f"Erreur lors de la création du document {fichier.name}. Contactez le support.")
            return None

    if not doc :
        messages.error(request, f"Erreur lors de la création du document {fichier.name} en base. Contactez le support.")
        return None

    # Sauvegarde physique
    

    if not ecrire_file_sur_nas(fichier, filepath) :
        # logger.error(f"❌ Échec de l’écriture du fichier {fichier.name} sur {filepath}")
        messages.error(request, f"Erreur lors de l’écriture du fichier {fichier.name}. Contactez le support.")
        return None
    
    return doc

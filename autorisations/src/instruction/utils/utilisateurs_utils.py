import logging
import os

from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.shortcuts import redirect
from autorisations.models.models_documents import DossierDocument
from autorisations.models.models_instruction import Dossier, DossierManifSportive
from django.contrib import messages

from autorisations.models.models_utilisateurs import ContactExterne, Groupeinstructeur, GroupeinstructeurInstructeur, Instructeur, TypeContactExterne
from autorisations.settings import EMAIL_NOTIF_TEST, NOTIFS_PROD
from instruction.utils.dossier_utils import redirect_error
from notifications.service import compute_dedupe_key, create_EmailOutbox, create_EmailOutbox_DM, envoi_mail

logger = logging.getLogger("ORM_DJANGO")



def get_instructeur_or_redirect(request, numero_dossier, action):
    instructeur = Instructeur.objects.filter(email=request.user.email).first()
    if not instructeur:
        logger.warning(f"[DOSSIER {numero_dossier}] Tentative d'action ({action}) du User {request.user} sans profil Instructeur.")
        messages.error(request, "Vous devez disposer d’un profil Instructeur. Contactez le support.")
        return None, redirect(request.META.get("HTTP_REFERER", "/"))
    return instructeur, None


def _get_group_instructeurs(group_name: str):
    group = Group.objects.filter(name=group_name).first()
    if not group:
        return Instructeur.objects.none()

    emails = [u.email for u in group.user_set.all() if u.email]
    return Instructeur.objects.filter(email__in=emails).select_related("id_agent_autorisations")


def _merge_without_duplicates(primary, extra):
    """Fusionne deux listes/Querysets d'instructeurs sans doublon."""
    primary_ids = {i.id for i in primary}
    return list(primary) + [i for i in extra if i.id not in primary_ids]


def _add_intermediaire_CA_if_needed(documents_du_dossier, base_list, intermediaires_CA):
    """Ajoute les intermédiaires CA si une délibération CA est présente dans les documents."""
    
    # Parcourir les DossierDocument
    for dd in documents_du_dossier:
        doc = dd.id_document
        if doc.id_nature.nature.lower() == "déliberation ca":
            for inter in intermediaires_CA:
                if inter not in base_list:
                    base_list.append(inter)
    return base_list




def build_roles_for_dossier(dossier):
    """Construit tous les rôles (intermédiaires, envoyeurs, publieurs, validants...)"""

    # Instructeurs du dossier
    instructeurs_du_dossier = Instructeur.objects.filter(dossierinstructeur__id_dossier=dossier).select_related("id_agent_autorisations")

    # DossierDocument du Dossier
    documents_du_dossier = DossierDocument.objects.filter(
        id_dossier=dossier
    ).select_related("id_document__id_nature", "id_document__id_statut")


    # --- INTERMEDIAIRE CA ---
    intermediaires_CA = _get_group_instructeurs("Intermédiaire CA")

    # --- POUR SIGNATURE SAADD / SPPN ---
    inter_saadd = _get_group_instructeurs("Envoi pour signature SAADD")
    inter_sppn = _get_group_instructeurs("Envoi pour signature SPPN")

    inter_saadd_fusion = _merge_without_duplicates(inter_saadd, instructeurs_du_dossier)
    inter_sppn_fusion = _merge_without_duplicates(inter_sppn, instructeurs_du_dossier)

    # Ajouter intermédiaire CA si délibération CA
    inter_saadd_fusion = _add_intermediaire_CA_if_needed(documents_du_dossier, inter_saadd_fusion, intermediaires_CA)
    inter_sppn_fusion = _add_intermediaire_CA_if_needed(documents_du_dossier, inter_sppn_fusion, intermediaires_CA)

    # --- INTERMEDIAIRES DU DOSSIER ---
    intermediaires_signature_du_dossier = Instructeur.objects.filter(dossierintermediairesignature__id_dossier=dossier).select_related("id_agent_autorisations")

    # --- ENVOYEURS D'ACTE ---
    envoyeurs_dossier = Instructeur.objects.filter(dossierenvoiacte__id_dossier=dossier).select_related("id_agent_autorisations")

    env_saadd = _get_group_instructeurs("Envoi de l'acte SAADD")
    env_sppn = _get_group_instructeurs("Envoi de l'acte SPPN")

    env_saadd_fusion = _merge_without_duplicates(env_saadd, instructeurs_du_dossier)
    env_sppn_fusion = _merge_without_duplicates(env_sppn, instructeurs_du_dossier)

    env_saadd_fusion = _add_intermediaire_CA_if_needed(documents_du_dossier, env_saadd_fusion, intermediaires_CA)
    env_sppn_fusion = _add_intermediaire_CA_if_needed(documents_du_dossier, env_sppn_fusion, intermediaires_CA)

    # --- PUBLIEURS RAA ---
    publieurs_dossier = Instructeur.objects.filter(dossierpublicationraa__id_dossier=dossier).select_related("id_agent_autorisations")

    publieur_saadd = _get_group_instructeurs("Publication RAA SAADD")
    publieur_sppn = _get_group_instructeurs("Publication RAA SPPN")

    publ_saadd_fusion = _merge_without_duplicates(publieur_saadd, instructeurs_du_dossier)
    publ_sppn_fusion = _merge_without_duplicates(publieur_sppn, instructeurs_du_dossier)

    publ_saadd_fusion = _add_intermediaire_CA_if_needed(documents_du_dossier, publ_saadd_fusion, intermediaires_CA)
    publ_sppn_fusion = _add_intermediaire_CA_if_needed(documents_du_dossier, publ_sppn_fusion, intermediaires_CA)

    # --- VALIDANTS ---
    val_saadd = _get_group_instructeurs("Validant-e SAADD")
    val_sppn = _get_group_instructeurs("Validant-e SPPN")

    validants_dossier = Instructeur.objects.filter(dossiervalideur__id_dossier=dossier).select_related("id_agent_autorisations")

    # --- RELECTEURS ---
    if dossier.id_demarche.service == 'SPPN':
        relecteurs_group = _get_group_instructeurs("Relecteur-rice qualité SPPN")
    else:
        relecteurs_group = _get_group_instructeurs("Relecteur-rice qualité SAADD")

    relecteurs_dossier = Instructeur.objects.filter(dossierrelecteurqualite__id_dossier=dossier).select_related("id_agent_autorisations")

    # Fusion dossier + instructeurs du groupe
    relecteurs_fusion = _merge_without_duplicates(relecteurs_group, instructeurs_du_dossier)

    # --- Signataires ---
    signataires_group = _get_group_instructeurs("Signataire")

    return {
        "intermediaires_CA": intermediaires_CA,
        "intermediaires_dir_saadd": inter_saadd,
        "intermediaires_dir_sppn": inter_sppn,
        "intermediaires_dir_saadd_et_instructeurs": inter_saadd_fusion,
        "intermediaires_dir_sppn_et_instructeurs": inter_sppn_fusion,
        "intermediaires_signature_du_dossier": intermediaires_signature_du_dossier,

        "envoyeurs_actes_du_dossier": envoyeurs_dossier,
        "envoyeurs_acte_saadd": env_saadd,
        "envoyeurs_acte_sppn": env_sppn,
        "envoyeurs_saadd_et_instructeurs": env_saadd_fusion,
        "envoyeurs_sppn_et_instructeurs": env_sppn_fusion,

        "publieurs_RAA_du_dossier": publieurs_dossier,
        "publieurs_RAA_saadd": publieur_saadd,
        "publieurs_RAA_sppn": publieur_sppn,
        "publieurs_RAA_saadd_et_instructeurs": publ_saadd_fusion,
        "publieurs_RAA_sppn_et_instructeurs": publ_sppn_fusion,

        "validants_SAADD": val_saadd,
        "validants_SPPN": val_sppn,
        "validants": validants_dossier,

        "relecteurs_qualite": relecteurs_group,
        "relecteurs_qualite_du_dossier": relecteurs_dossier,
        "relecteurs_qualite_et_instructeurs": relecteurs_fusion,

        "signataires": signataires_group,
    }





def extraire_donnees_copie_mail(request):
    """
    Extrait du POST les données liées à l'envoi en copie par mail.

    Returns:
        dict: {
            "partager_par_mail": str,
            "emails": list[str],
            "emails_nouveaux": list[str],
            "emails_selectionnes_lower": set[str],
            "noms": list[str],
            "prenoms": list[str],
            "types": list[str],
            "raisons": list[str],
            "motivation_copie_mail": str | None,
        }
    """
    emails = request.POST.getlist("emails_copie[]")

    return {
        "partager_par_mail": request.POST.get("partager_par_mail"),
        "emails": emails,
        "emails_nouveaux": request.POST.getlist("email_contact[]"),
        "emails_selectionnes_lower": {(e or "").strip().lower() for e in emails},
        "noms": request.POST.getlist("nom_contact[]"),
        "prenoms": request.POST.getlist("prenom_contact[]"),
        "types": request.POST.getlist("type_contact[]"),
        "raisons": request.POST.getlist("raison_sociale[]"),
        "motivation_copie_mail": request.POST.get("motivation_copie_mail"),
    }




def creer_nouveaux_contacts_externes_depuis_formulaire(*, request, dossier_numero, emails_nouveaux, emails_selectionnes_lower, noms, prenoms, types, raisons, logger,):
    """
    Crée les nouveaux ContactExterne saisis dans le formulaire, uniquement
    s'ils sont encore sélectionnés pour l'envoi.

    Ne lève pas d'exception métier si un email est invalide : il est ignoré.
    """
    for i, email in enumerate(emails_nouveaux):
        email_clean = (email or "").strip()
        if not email_clean:
            continue

        try:
            validate_email(email_clean)
        except ValidationError:
            logger.warning(f"[DOSSIER {dossier_numero}] Envoi document ({request.user}) - Email invalide ignoré : {email}")
            continue

        # Si la chip a été supprimée, on ignore
        if email_clean.lower() not in emails_selectionnes_lower:
            continue

        nom = (noms[i] if i < len(noms) else "").strip()
        prenom = (prenoms[i] if i < len(prenoms) else "").strip()
        raison = (raisons[i] if i < len(raisons) else "").strip()
        type_id = types[i] if i < len(types) else None

        type_obj = None
        if type_id:
            type_obj = TypeContactExterne.objects.filter(id=type_id).first()

        if not type_obj:
            type_obj, _ = TypeContactExterne.objects.get_or_create(type="Autre")

        contact, created = ContactExterne.objects.get_or_create(
            email=email_clean,
            id_type=type_obj,
            defaults={
                "nom": nom,
                "prenom": prenom,
                "raison_sociale": raison,
            }
        )

        if created:
            logger.info(f"[DOSSIER {dossier_numero}] Envoi document par mail : Nouveau ContactExterne créé via formulaire : {contact}")




def normaliser_emails_destinataires(*, request, dossier_numero, emails, logger):
    """
    Nettoie, valide et dédoublonne une liste d'emails.

    Returns:
        list[str]: emails valides, nettoyés, sans doublons.
    """
    emails_norm = []
    seen = set()

    for e in emails:
        e_norm = (e or "").strip()
        if not e_norm:
            continue

        e_key = e_norm.lower()
        if e_key in seen:
            continue

        try:
            validate_email(e_norm)
        except ValidationError:
            logger.warning(f"[DOSSIER {dossier_numero}] Envoi document ({request.user}) - Email invalide ignoré : {e_norm}")
            continue

        seen.add(e_key)
        emails_norm.append(e_norm)

    return emails_norm



def envoyer_copie_document_par_mail( *, request, dossier, document, nature_document, logger, type_mail="Envoi de l'acte", libelle_log="Envoi acte", template_name="mail_en_copie",):
    """
    Gère l'envoi en copie par mail d'un document depuis les données du formulaire.

    Étapes :
    - extraction des données POST
    - création éventuelle de nouveaux contacts externes
    - normalisation/dédoublonnage des emails
    - création EmailOutbox
    - envoi du mail

    Returns:
        HttpResponseRedirect | None:
            - None si tout va bien ou si aucun envoi demandé
            - redirect_error(...) en cas d'erreur métier bloquante
    """
    donnees_mail = extraire_donnees_copie_mail(request)

    if donnees_mail["partager_par_mail"] != "oui":
        return None

    creer_nouveaux_contacts_externes_depuis_formulaire(
        request=request,
        dossier_numero=dossier.numero,
        emails_nouveaux=donnees_mail["emails_nouveaux"],
        emails_selectionnes_lower=donnees_mail["emails_selectionnes_lower"],
        noms=donnees_mail["noms"],
        prenoms=donnees_mail["prenoms"],
        types=donnees_mail["types"],
        raisons=donnees_mail["raisons"],
        logger=logger,
    )

    emails_norm = normaliser_emails_destinataires(
        request=request,
        dossier_numero=dossier.numero,
        emails=donnees_mail["emails"],
        logger=logger,
    )

    if not emails_norm:
        logger.warning(
            f"[DOSSIER {dossier.numero}] {libelle_log} ({request.user}) - "
            f"Aucun email valide sélectionné pour l’envoi en copie. "
            f"Liste des emails transmis : {donnees_mail['emails']}"
        )
        return None

    sujet = f"{nature_document} – Dossier {dossier.numero}"
    context = {"body": donnees_mail["motivation_copie_mail"]}
    emails_txt = ", ".join(emails_norm)

    try:
        dedupe = compute_dedupe_key(emails_norm, sujet, template_name, context)
    except Exception as e:
        logger.error(
            f"[DOSSIER {dossier.numero}] {libelle_log} ({request.user}) - "
            f"Échec de la création de la clé unique (compute_dedupe_key) : {e}"
        )
        return redirect_error(request, f"L'email de notification à {emails_txt} n'a pas été envoyé. Contactez le support.")

    outbox = create_EmailOutbox(
        emails_norm,
        sujet,
        template_name,
        dedupe,
        context,
        dossier,
        type_mail=type_mail,
        document=document,
    )

    if not outbox:
        logger.error(
            f"[DOSSIER {dossier.numero}] {libelle_log} ({request.user}) - "
            f"Erreur lors de la création de l'EmailOutbox. "
            f"Destinataires non notifiés : {emails_txt}"
        )
        return redirect_error( request, f"L'email de notification à {emails_txt} n'a pas été envoyé. Contactez le support.")

    ok, err = envoi_mail(outbox.id)

    if ok:
        logger.info(f"[DOSSIER {dossier.numero}] {libelle_log} ({request.user}) - Envoi en copie par mail ({outbox.id}) à {', '.join(outbox.to)}")
        return None

    logger.error(f"[DOSSIER {dossier.numero}] {libelle_log} ({request.user}) - Échec envoi mail ({outbox.id}) à {', '.join(outbox.to)} : {err}")
    return redirect_error(request, f"L'envoi en copie par mail à {', '.join(outbox.to)} a échoué. Contactez le support.")



# Pas fini
# def envoyer_notif_mail_dm( *, request, dossier_dm, document, nature_document, logger, type_mail="Envoi du document", libelle_log="Envoi notification", template_name="mail_en_copie",):
#     """
#     Gère l'envoi du mail de notif suite au classement comme 'non soumis' ou 'non repondu' d'un dossier DM.

#     Étapes :
#     - extraction des données POST
#     - création éventuelle de nouveaux contacts externes
#     - normalisation/dédoublonnage des emails
#     - création EmailOutbox
#     - envoi du mail

#     Returns:
#         HttpResponseRedirect | None:
#             - None si tout va bien ou si aucun envoi demandé
#             - redirect_error(...) en cas d'erreur métier bloquante
#     """
#     donnees_mail = extraire_donnees_copie_mail(request)

#     num_doss_dm = dossier_dm.numero_dossier_declaration_manifestations

#     if donnees_mail["partager_par_mail"] != "oui":
#         return None

#     creer_nouveaux_contacts_externes_depuis_formulaire(
#         request=request,
#         dossier_numero=num_doss_dm,
#         emails_nouveaux=donnees_mail["emails_nouveaux"],
#         emails_selectionnes_lower=donnees_mail["emails_selectionnes_lower"],
#         noms=donnees_mail["noms"],
#         prenoms=donnees_mail["prenoms"],
#         types=donnees_mail["types"],
#         raisons=donnees_mail["raisons"],
#         logger=logger,
#     )

#     emails_norm = normaliser_emails_destinataires(
#         request=request,
#         dossier_numero=num_doss_dm,
#         emails=donnees_mail["emails"],
#         logger=logger,
#     )

#     if not emails_norm:
#         logger.warning(
#             f"[DOSSIER DM {num_doss_dm}] {libelle_log} ({request.user}) - "
#             f"Aucun email valide sélectionné pour l’envoi en copie. "
#             f"Liste des emails transmis : {donnees_mail['emails']}"
#         )
#         return None

#     sujet = f"{nature_document} – Dossier {num_doss_dm}"
#     context = {"body": donnees_mail["motivation_copie_mail"]}
#     emails_txt = ", ".join(emails_norm)

#     try:
#         dedupe = compute_dedupe_key(emails_norm, sujet, template_name, context)
#     except Exception as e:
#         logger.error(
#             f"[DOSSIER DM {num_doss_dm}] {libelle_log} ({request.user}) - "
#             f"Échec de la création de la clé unique (compute_dedupe_key) : {e}"
#         )
#         return redirect_error(request, f"L'email de notification à {emails_txt} n'a pas été envoyé. Contactez le support.")

#     outbox = create_EmailOutbox_DM(
#         emails_norm,
#         sujet,
#         template_name,
#         dedupe,
#         context,
#         dossier_dm,
#         type_mail=type_mail,
#         document=document,
#     )

#     if not outbox:
#         logger.error(
#             f"[DOSSIER DM {num_doss_dm}] {libelle_log} ({request.user}) - "
#             f"Erreur lors de la création de l'EmailOutbox. "
#             f"Destinataires non notifiés : {emails_txt}"
#         )
#         return redirect_error( request, f"L'email de notification à {emails_txt} n'a pas été envoyé. Contactez le support.")

#     ok, err = envoi_mail(outbox.id)

#     if ok:
#         logger.info(f"[DOSSIER DM {num_doss_dm}] {libelle_log} ({request.user}) - Envoi en copie par mail ({outbox.id}) à {', '.join(outbox.to)}")
#         return None

#     logger.error(f"[DOSSIER DM {num_doss_dm}] {libelle_log} ({request.user}) - Échec envoi mail ({outbox.id}) à {', '.join(outbox.to)} : {err}")
#     return redirect_error(request, f"L'envoi en copie par mail à {', '.join(outbox.to)} a échoué. Contactez le support.")





def envoi_auto_mail_relance(dossier_dm : DossierManifSportive):
    """

    Envoi automatique du mail de relance pour les nouveaux dossiers DM non liés et qui intersecte le coeur de parc.

    returns :
        True si bien envoyé, False sinon
    
    """
    try :
        logger.info(dossier_dm.email_structure)
        logger.warning(dossier_dm.email_structure)
        
        numero_dossier_dm = None
        nom_manif = dossier_dm.nom_dossier
        LIEN_FORM_MANIF_SPORTIVE = os.getenv('LIEN_FORM_MANIF_SPORTIVE')

        if not LIEN_FORM_MANIF_SPORTIVE :
            logger.error(
                f"[NOUVEAU DOSSIER DM {numero_dossier_dm}] Intersection avec le coeur de parc - Erreur lors de l'envoi du mail de relance : "
                f"Échec de la récupération de la variable d'environnement LIEN_FORM_MANIF_SPORTIVE"
            )
            return False

        if NOTIFS_PROD :
            if not dossier_dm.email_structure :
                logger.info(f"[NOUVEAU DOSSIER DM {numero_dossier_dm}] Intersection avec le coeur de parc - Aucun email de structure renseigné. Pas d'envoi de mail de relance.")
                return False
            emails_norm = [dossier_dm.email_structure]
        else :
            
            if not dossier_dm.email_structure :
                logger.info(f"[NOUVEAU DOSSIER DM {numero_dossier_dm}] Intersection avec le coeur de parc - Aucun email de structure renseigné. Pas d'envoi de mail de relance.")
                return False
            emails_norm = [EMAIL_NOTIF_TEST]

        sujet = f"{nom_manif} : formulaire du Parc national de La Réunion à compléter"
        
        context = {
            "date_depot": dossier_dm.date_depot.strftime("%d/%m/%Y") if dossier_dm.date_depot else "",
            "nom_manif": nom_manif,
            "date_debut": dossier_dm.date_debut_evenement.strftime("%d/%m/%Y") if dossier_dm.date_debut_evenement else "",
            "lien_formulaire": LIEN_FORM_MANIF_SPORTIVE,
        }
        
        emails_txt = ", ".join(emails_norm)
        template_name = "mail_relance_manif_sportive"
        type_mail = "Relance"

        numero_dossier_dm = dossier_dm.numero_dossier_declaration_manifestations
        try:
            # Contraintes unicité que pour les mails 'À envoyer' ou 'Échec'
            dedupe = compute_dedupe_key(emails_norm, sujet, template_name, context)

        except Exception as e:
            logger.error(
                f"[NOUVEAU DOSSIER DM {numero_dossier_dm}] Intersection avec le coeur de parc - Erreur lors de l'envoi du mail de relance : "
                f"Échec de la création de la clé unique (compute_dedupe_key) : {e}"
            )
            return False

        outbox = create_EmailOutbox_DM(
            emails_norm,
            sujet,
            template_name,
            dedupe,
            context,
            dossier_dm,
            type_mail=type_mail,
            # document=document,
        )

        if not outbox:
            logger.error(
                f"[DOSSIER DM {numero_dossier_dm}] Email de relance automatique - "
                f"Erreur lors de la création de l'EmailOutbox. Destinataires non notifiés : {emails_txt}"
            )
            return False

        ok, err = envoi_mail(outbox.id)

        if ok:
            logger.info(f"[DOSSIER DM {numero_dossier_dm}]  - Envoi automatique mail de relance ({outbox.id}) à {', '.join(outbox.to)}")
            return True

        logger.error(f"[DOSSIER DM {numero_dossier_dm}]  - Échec envoi mail de relance automatique ({outbox.id}) à {', '.join(outbox.to)} : {err}")
        return False
    

    except Exception as e :
        logger.error(f"[NOUVEAU DOSSIER DM {numero_dossier_dm}] Intersection avec le coeur de parc - Erreur lors de l'envoi du mail de relance : {e}")
        return False


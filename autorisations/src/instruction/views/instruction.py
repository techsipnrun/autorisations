import ast
from datetime import date, timedelta
import json
import logging
import os
from django.db.models import Q, Count
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib.auth.decorators import login_required
from django.urls import reverse
import smbclient
from autorisations.models.models_instruction import Demarche, Dossier, DossierAction, DossierManifestationLiaison, EtapeDossier, EtatDossier, Message
from autorisations.models.models_utilisateurs import ContactExterne, DossierBeneficiaire, DossierEnvoiActe, DossierInstructeur, DossierInterlocuteur, DossierIntermediaireSignature, DossierPublicationRAA, DossierRelecteur, DossierRelecteurQualite, DossierSignataire, DossierValideur, EmailOutbox, Groupeinstructeur, GroupeinstructeurInstructeur, Instructeur, TypeContactExterne
from autorisations.settings import EMAIL_NOTIF_TEST, NOTIFS_PROD
from DS.graphql_client import GraphQLClient
from autorisations.models.models_documents import Document, DocumentFormat, DocumentNature, DocumentStatut, DossierDocument, DossierRelecteurDocument
from autorisations.models.models_avis import AvisDocument, DossierAvis
from autorisations.utils.nas_fonctions import creer_dossier_sur_nas, ecrire_file_sur_nas
from instruction.utils.avis_utils import build_avis_for_dossier
from instruction.utils.document_utils import build_documents_for_dossier
from instruction.utils.dossier_utils import build_champs_prepares, build_timeline_for_dossier, count_unread_messages_for_dossier, get_beneficiaire_for_dossier, get_etapes_custom, redirect_error, safe_enregistrer_action
from instruction.utils.files_utils import load_geojson
from instruction.utils.utilisateurs_utils import build_roles_for_dossier
from notifications.service import compute_dedupe_key, create_EmailOutbox, envoi_mail
from declaration_manifestations.call_api_dm import recup_un_seul_dossier
from synchronisation.src.normalisation.norma_declaration_manifestations import dossiers_declaration_manifestations_normalize
from synchronisation.src.synchro.sync_declaration_manifestations import sync_declaration_manifestations
from synchronisation.src.normalisation.norma_contacts_externes import contact_externe_normalize
from synchronisation.src.normalisation.norma_demandes import demande_normalize
from synchronisation.src.normalisation.norma_dossier_champs import dossiers_champs_normalize
from synchronisation.src.normalisation.norma_dossier_document import dossier_document_normalize
from synchronisation.src.normalisation.norma_dossier_interlocuteur import dossier_interlocuteur_normalize
from synchronisation.src.normalisation.norma_messages import message_normalize
from synchronisation.src.synchro.sync_dossiers import sync_dossiers
from synchronisation.src.utils.fichiers import construire_emplacement_dossier
from synchronisation.src.normalisation.norma_dossier import dossier_normalize
from instruction.utils_instru import dossiers_action_a_faire, enregistrer_action, format_etat_dossier
from autorisations.models.models_instruction import DossierNote
from django.utils import timezone
from datetime import datetime
from django.db.models import Min
from django.views.decorators.http import require_POST
from django.http import Http404
from django.contrib import messages
from django.contrib.auth.models import Group, User
from django.contrib.auth import get_user_model


logger = logging.getLogger('ORM_DJANGO')
loggerSynchro = logging.getLogger('SYNCHRONISATION')
loggerDM = logging.getLogger("API_DM")


def get_dossiers_instructeur(instructeur):
    """Retourne un queryset de tous les dossiers où l’instructeur intervient (SAUF SI LE DOSSIER EST EN RECEPTION), tous rôles confondus."""

    if not instructeur:
        return Dossier.objects.none()
    
    User = get_user_model()
    user = User.objects.filter(email__iexact=instructeur.email).first()


    # Base : rôles instructeur
    filtre = (
        Q(dossierinstructeur__id_instructeur=instructeur) |
        Q(dossierrelecteurqualite__id_instructeur=instructeur) |
        Q(dossiervalideur__id_instructeur=instructeur) |
        Q(dossierrelecteur__id_instructeur=instructeur) |
        Q(dossiersignataire__id_instructeur=instructeur) |
        Q(dossierintermediairesignature__id_instructeur=instructeur) |
        Q(dossierpublicationraa__id_instructeur=instructeur) |
        Q(dossierenvoiacte__id_instructeur=instructeur)
    )

    # ➕ Ajout des 2 conditions supplémentaires (même échantillon)
    if user :
        if user.groups.filter(name="Réception SPPN").exists():
            filtre |= Q(id_demarche__type__icontains="Mission scientifique")

        if user.groups.filter(name="Réception SAADD").exists():
            filtre |= ~Q(id_demarche__type__icontains="Mission scientifique")

    return (
        Dossier.objects
        .filter(filtre)
        .exclude(id_etape_dossier__etape="À affecter")
        .distinct()
    )

    # return (
    #     Dossier.objects.filter(
    #         Q(dossierinstructeur__id_instructeur=instructeur) |
    #         Q(dossierrelecteurqualite__id_instructeur=instructeur) |
    #         Q(dossiervalideur__id_instructeur=instructeur) |
    #         Q(dossierrelecteur__id_instructeur=instructeur) |
    #         Q(dossiersignataire__id_instructeur=instructeur) |
    #         Q(dossierintermediairesignature__id_instructeur=instructeur) |
    #         Q(dossierpublicationraa__id_instructeur=instructeur) |
    #         Q(dossierenvoiacte__id_instructeur=instructeur)
    #     )
    #     .exclude(id_etape_dossier__etape__in=["À affecter"])
    #     .distinct()
    # )


def get_dossier_counts(demarche, etape_a_affecter, etapes_instruction, etapes_termines, current_year, instructeur=None):
    """
    Retourne le résumé des compteurs pour une démarche.
    """

    # Requêtes de base
    dossiers = Dossier.objects.filter(id_demarche=demarche)

    nb_reception = dossiers.filter(id_etape_dossier=etape_a_affecter).count()
    nb_suivis = dossiers.filter(id_etape_dossier__in=etapes_instruction).count()
    nb_traites = dossiers.filter(id_etape_dossier__in=etapes_termines, date_fin_instruction__year=current_year).count()

    # Dossiers où l'instructeur intervient
    dossiers_instructeur = get_dossiers_instructeur(instructeur).filter(id_demarche=demarche)

    nb_suivis_user = dossiers_action_a_faire(dossiers_instructeur, instructeur).count()
    

    return {
        "demarche": demarche,
        "nb_reception": nb_reception,
        "nb_suivis": nb_suivis,
        "nb_traites": nb_traites,
        "nb_suivis_user": nb_suivis_user,
    }



def get_role_sur_dossier(dossier, instructeur, action_a_faire=False):
    """Retourne le rôle exact de l'instructeur sur un dossier."""

    etape = dossier.id_etape_dossier.etape if dossier.id_etape_dossier else ""

    # Cas où une action est à faire
    if action_a_faire:

        # Rôles directs liés à l'étape
        mapping_action = {
            "À valider avant signature": "Valideur.se",
            "À valider avant demande d'avis": "Valideur.se",
            "À publier au RAA": "Publieur.se au RAA",
            "Acte à envoyer": "Envoyeur.se de l'acte",
            "En attente de signature": "Intermédiaire signature",
            "À affecter": "Relecteur.rice qualité",
            "En relecture qualité": "Relecteur.rice qualité",
        }
        if etape in mapping_action:
            return mapping_action[etape]

        # Cas particulier : relecteur
        if DossierRelecteur.objects.filter(id_dossier=dossier, id_instructeur=instructeur, relu=False).exists():
            return "Relecteur.rice"

        return "Instructeur.rice"

    # Cas général : aucun action à faire
    mapping_roles = [
        (DossierInstructeur, "Instructeur.rice"),
        (DossierValideur, "Valideur.se"),
        (DossierSignataire, "Signataire"),
        (DossierRelecteurQualite, "Relecteur.rice qualité"),
        (DossierEnvoiActe, "Envoyeur.se de l'acte"),
        (DossierIntermediaireSignature, "Intermédiaire signature"),
        (DossierPublicationRAA, "Publieur.se au RAA"),
        (DossierRelecteur, "Relecteur.rice"),
    ]

    for model, role in mapping_roles:
        if model.objects.filter(id_dossier=dossier, id_instructeur=instructeur).exists():
            return role

    return "Inconnu"



@login_required
def accueil(request):

    etapes_instruction = EtapeDossier.objects.exclude(etape__in=["Non soumis à autorisation", "Refusé", "Accepté", "À affecter"])
    etapes_termines = EtapeDossier.objects.filter(etape__in=["Non soumis à autorisation", "Refusé", "Accepté"])
    etape_a_affecter = EtapeDossier.objects.get(etape="À affecter")

    # Instructeur
    instructeur = Instructeur.objects.filter(email=request.user.email).first()
    if not instructeur:
        messages.warning(request, f"Attention, vous n'avez pas de profil 'Instructeur.rice' : Contactez le support si besoin.")

    # POUR LE MOMENT ON EXCLU MANIFESTATIONS SPORTIVES
    demarches = Demarche.objects.all().order_by("titre")
    demarches = demarches.exclude(type__icontains="manifestations sportives")

    current_year = date.today().year

    dossier_infos = [
        get_dossier_counts(d, etape_a_affecter, etapes_instruction, etapes_termines, current_year, instructeur)
        for d in demarches
    ]

    return render(request, 'instruction/instruction.html', {
                                                            "dossier_infos": dossier_infos,
                                                            "instructeur":instructeur,
                                                            })


@login_required
def mesdossiers(request):

    instructeur = Instructeur.objects.filter(email=request.user.email).first()

    if not instructeur:
        messages.error(request, f"❌ Aucun profil 'Instructeur.rice' existant pour l'utilisateur.rice {request.user} : Contactez le support si besoin.")
        return render(request, "instruction/mesdossiers.html", { "dossiers_par_demarche": [] })
    
    # Étapes exclues
    etapes_termines_et_a_affecter = EtapeDossier.objects.filter(etape__in=["Non soumis à autorisation", "Refusé", "Accepté", "À affecter"])

    # Tous les dossiers où l'instructeur intervient (Hors étape 'À affecter')
    base_query = get_dossiers_instructeur(instructeur)

    # Liste dossiers liés à instructeur. Exclusion étapes ["Non soumis à autorisation", "Refusé", "Accepté", "À affecter"]
    dossiers = base_query.exclude(id_etape_dossier__in=etapes_termines_et_a_affecter)

    # Liste dossiers avec action à faire (Hors étape 'À affecter')
    dossier_action_a_faire = dossiers_action_a_faire(base_query, instructeur)

    dossiers = dossiers.union(dossier_action_a_faire)

    dossiers_par_demarche = {}
    for dossier in dossiers:

        # Bénéficiaire
        beneficiaire = get_beneficiaire_for_dossier(dossier)

        # Messages non lus DOSSIER
        nb_messages_non_lus = count_unread_messages_for_dossier(dossier, dossier.numero)

        # Déterminer rôle
        action = dossier in dossier_action_a_faire
        role = get_role_sur_dossier(dossier, instructeur, action)

        # Structurer les infos
        dossiers_par_demarche.setdefault(dossier.id_demarche.type, []).append({
            "nom_dossier": dossier.nom_dossier,
            "numero": dossier.numero,
            "beneficiaire": f"{beneficiaire.prenom} {beneficiaire.nom}" if beneficiaire else "N/A",
            "date_depot": dossier.date_depot,
            "mon_role": role,
            "etape": dossier.id_etape_dossier.etape if dossier.id_etape_dossier else "Non défini",
            "nb_messages_non_lus": nb_messages_non_lus,
            "action_a_faire": action,
        })


    return render(request, "instruction/mesdossiers.html", {
        "dossiers_par_demarche": dossiers_par_demarche,
        "instructeur": instructeur,
    })



@login_required
def instruction_demarche(request, num_demarche):

    demarche = Demarche.objects.filter(numero=num_demarche).first()
    if not demarche:
        logger.error(f"[INSTRUCTION DEMARCHE] Erreur lors de l'affichage de la page par {request.user} : Démarche {num_demarche} introuvable.")
        return redirect_error(request, f"❌ La démarche {num_demarche} est introuvable en base. Contactez le support")


    etapes_termines = EtapeDossier.objects.filter(etape__in=["Non soumis à autorisation", "Refusé", "Accepté"])

    instructeur = Instructeur.objects.filter(email=request.user.email).first()
    if not instructeur:
        messages.warning(request, f"⚠️ Attention, vous n'avez pas de profil 'Instructeur.rice' : Contactez le support si besoin.")


    # Tous les dossiers liés à l'instructeur (hors 'À affecter')
    dossiers_instructeur = get_dossiers_instructeur(instructeur)

    # Dossiers où j'ai une action à faire
    dossiers_actions = set(dossiers_action_a_faire(dossiers_instructeur, instructeur))


    # ============================
    #    DOSSIERS EN INSTRUCTION
    # ============================
    dossiers = (
        Dossier.objects
        .filter(id_demarche=demarche)
        .exclude(id_etape_dossier__etape__in=["Accepté", "Refusé", "Non soumis à autorisation", "À affecter"])
        .select_related("id_groupeinstructeur")
        .order_by("date_depot")
    )

    dossier_infos = []
    for dossier in dossiers:

        # Bénéficiaire
        beneficiaire = get_beneficiaire_for_dossier(dossier)

        # Messages non lus
        nb_messages_non_lus = count_unread_messages_for_dossier(dossier, dossier.numero)

        dossier_infos.append({
            "nom_dossier": dossier.nom_dossier,
            "obj_doss": dossier,
            "numero": dossier.numero,
            "beneficiaire": f"{beneficiaire.prenom} {beneficiaire.nom}" if beneficiaire else "N/A",
            "date_depot": dossier.date_depot,
            "groupe": dossier.id_groupeinstructeur.nom if dossier.id_groupeinstructeur else "N/A",
            "etape": dossier.id_etape_dossier.etape if dossier.id_etape_dossier.etape else "Non défini",
            "nb_messages_non_lus": nb_messages_non_lus,
            "action_a_faire": dossier in dossiers_actions,
        })


    # ============================
    #         ARCHIVES
    # ============================
    annee_selectionnee = int(request.GET.get("annee", datetime.now().year))

    # Années disponibles
    min_depot = Dossier.objects.filter(id_demarche=demarche).aggregate(min_date=Min("date_depot")).get("min_date")
    annee_min = min_depot.year if min_depot else annee_selectionnee
    annees_disponibles = list(range(annee_min, datetime.now().year + 1))

    dossiers_archives = Dossier.objects.filter(
        id_etape_dossier__in=etapes_termines,
        id_demarche=demarche,
        date_depot__year=annee_selectionnee
    ).select_related("id_groupeinstructeur").order_by("-date_depot")


    dossier_archives_infos = []
    for dossier in dossiers_archives:

        # Bénéficiaire
        beneficiaire = get_beneficiaire_for_dossier(dossier)


        # Messages non lus
        nb_messages_non_lus = count_unread_messages_for_dossier(dossier, dossier.numero)

        dossier_archives_infos.append({
            "nom_dossier": dossier.nom_dossier,
            "obj_doss": dossier,
            "numero": dossier.numero,
            "beneficiaire": f"{beneficiaire.prenom} {beneficiaire.nom}" if beneficiaire else "N/A",
            "date_depot": dossier.date_depot,
            "groupe": dossier.id_groupeinstructeur.nom if dossier.id_groupeinstructeur else "N/A",
            "etape": dossier.id_etape_dossier.etape if dossier.id_etape_dossier else "Non défini",
            "nb_messages_non_lus": nb_messages_non_lus,
            "action_a_faire": dossier in dossiers_actions,
        })

    # Tri : dossiers avec action en premier, puis par nb de messages non lus
    dossier_archives_infos.sort(key=lambda d: (not d["action_a_faire"], -d["nb_messages_non_lus"]))


    return render(request, "instruction/instruction_demarche.html", {
    "demarche": demarche,
    "dossiers": dossier_infos,
    "annees_disponibles": annees_disponibles,
    "annee_selectionnee": annee_selectionnee,
    "dossiers_archives": dossier_archives_infos,
    "instructeur": instructeur,
})





@login_required
def instruction_dossier(request, num_dossier):

    dossier = Dossier.objects.filter(numero=num_dossier).first()
    if not dossier:
        logger.error(f"[INSTRUCTION DOSSIER] Erreur lors de l'affichage de la page par {request.user} : Dossier {num_dossier} introuvable.")
        return redirect_error(request, f"❌ Le dossier {num_dossier} est introuvable en base. Contactez le support")
    
    demarche = dossier.id_demarche


    ####################################
    # Charger les fonds de carte GeoJSON
    ####################################
    fond_coeur_de_parc = load_geojson("instruction/static/instruction/carto/fond_coeur_de_parc.geojson")
    fond_aire_adhesion = load_geojson("instruction/static/instruction/carto/aire_adhesion.geojson")
    fond_mafate = load_geojson("instruction/static/instruction/carto/COT_MAFATE.geojson")
    pois_json = load_geojson("instruction/static/instruction/carto/pois.json")


    ####################################
    # Champs du formulaire DS
    ####################################
    champs_prepares, nb_cartes = build_champs_prepares(dossier)


    ####################################
    # Groupe Instructeurs
    ####################################
    # Groupes Instructeurs de la Démarche
    groupes_instructeurs = Groupeinstructeur.objects.filter(groupeinstructeurdemarche__id_demarche=dossier.id_demarche).order_by("nom")

    # Instructeurs du Dossier
    instructeurs_dossier = set(DossierInstructeur.objects.filter(id_dossier=dossier).values_list("id_instructeur_id", flat=True))

    # Instructeur connecté
    instructeur_connecte = (Instructeur.objects.filter(email=request.user.email).select_related("id_agent_autorisations").first())
    
    # Membres du groupe instructeur associé au Dossier
    membres_groupe = []
    if dossier.id_groupeinstructeur:
        membres_groupe = [
            m.id_instructeur
            for m in dossier.id_groupeinstructeur
                .groupeinstructeurinstructeur_set
                .select_related("id_instructeur__id_agent_autorisations")
        ]


    ####################################
    # Bouton 'Se déclarer Instructeur'
    ####################################
    peut_se_declarer = False
               
    if dossier.id_groupeinstructeur and instructeur_connecte:
        instructeurs_du_groupe = set(
            dossier.id_groupeinstructeur
            .groupeinstructeurinstructeur_set
            .values_list("id_instructeur_id", flat=True)
        )

        # Si aucun instructeur du groupe n'est affecté au dossier, et que l'utilisateur connecté fait partie du groupe : il peut se déclarer
        if not instructeurs_dossier & instructeurs_du_groupe and instructeur_connecte.id in instructeurs_du_groupe:
            peut_se_declarer = True


    ###################################################
    # Infos sur le bénéficiaire/demandeur intermediaire
    ###################################################
    beneficiaire = get_beneficiaire_for_dossier(dossier)
    demandeur_intermediaire = None
    interlocuteur = DossierInterlocuteur.objects.filter(id_dossier=dossier).first()
    if interlocuteur and interlocuteur.id_demandeur_intermediaire:
        demandeur_intermediaire = interlocuteur.id_demandeur_intermediaire



    ########################################
    # Menu déroulant avec les choix d'étapes
    ########################################
    etapes_possibles = EtapeDossier.objects.all().order_by("etape")
    etape_actuelle = dossier.id_etape_dossier if hasattr(dossier, "id_etape_dossier") else None

    dossier_sppn = "mission scientifique" in dossier.id_demarche.titre.lower()
    etapes_custom = get_etapes_custom(
        present_sur_ds=dossier.present_sur_ds,
        dossier_sppn=dossier_sppn,
        etape_actuelle=etape_actuelle.etape if etape_actuelle else "",
        demarche_type=demarche.type
    )
    
    
    #####################################################
    # TIMELINE : Mapping entre les actions et leurs logos
    #####################################################
    dossier_actions = build_timeline_for_dossier(dossier)


    ################################
    #  Notes & Annexes Instructeur
    ################################
    notes_queryset = DossierNote.objects.filter(id_dossier=dossier).select_related("id_instructeur__id_agent_autorisations").order_by("-date")
    notes = [
        {
            "id": n.id,
            "note": n.note,
            "date": n.date,
            "instructeur_id": n.id_instructeur.id,
            "instructeur": f"{n.id_instructeur.id_agent_autorisations.prenom} {n.id_instructeur.id_agent_autorisations.nom}" 
                            if n.id_instructeur.id_agent_autorisations 
                            else n.id_instructeur.email,
        }
        for n in notes_queryset
    ]


    #############################
    # Documents
    #############################
    documents_data = build_documents_for_dossier(dossier)

   
    ###############################
    # Liste d'instructeurs par rôle
    ###############################

    # Relecteur du dossier 
    relecteurs_du_dossier = DossierRelecteur.objects.filter(id_dossier=dossier)
    instructeurs = Instructeur.objects.select_related("id_agent_autorisations").order_by("id_agent_autorisations__nom","id_agent_autorisations__prenom")

    roles = build_roles_for_dossier(dossier)

    # Type contacts externes
    types_contacts = TypeContactExterne.objects.all()

    # Instructeur.rices du dossier
    instructeurs_du_dossier = Instructeur.objects.filter(
        dossierinstructeur__id_dossier=dossier
    ).select_related("id_agent_autorisations")


    ###############################
    # Messages non lus
    ###############################
    nb_messages_non_lus = count_unread_messages_for_dossier(dossier, dossier.numero)

    
    ####################################
    # Dossier Déclaration Manifestations
    ####################################
    doss_manif_sportive = None
    if dossier.id_demarche.type == "Manifestations sportives":
        liaison = DossierManifestationLiaison.objects.filter(id_dossier=dossier).select_related("id_dossier_manif").first()
        if liaison:
            doss_manif_sportive = liaison.id_dossier_manif

     # Récupération de l'avis lié (OneToOne → un seul)
    try:
        avis_manif_sportive = doss_manif_sportive.avis  # grâce à related_name='avis'
    except Exception:
        avis_manif_sportive = None  # Aucun avis encore associé
 

    ################
    #    Emails
    ################
    emails_contacts = ContactExterne.objects.filter(
        email__isnull=False
    ).exclude(email__exact="").values_list("email", flat=True).distinct()

    emails_instructeurs = Instructeur.objects.filter(
        email__isnull=False
    ).exclude(email__exact="").values_list("email", flat=True).distinct()

    # Fusionner et dédoublonner
    emails_uniques = sorted(set(emails_contacts) | set(emails_instructeurs))

    # Liste tous les emails (envoi acte en copie) liés à ce dossier
    emails_dossiers = EmailOutbox.objects.filter(id_dossier=dossier.id, type_mail="Envoi de l'acte").order_by("-date_creation")


    ##################
    #  AVIS 
    ##################
    avis_data = build_avis_for_dossier(dossier)
    

    return render(request, 'instruction/instruction_dossier.html', {
        # Dossier
        "demarche": demarche,
        "dossier": dossier,
        "etat_dossier": format_etat_dossier(dossier.id_etat_dossier.nom),
        "champs": champs_prepares,
        "etapes_possibles": etapes_possibles,
        "etape_actuelle": etape_actuelle,
        "etapes_custom": etapes_custom,
        "dossier_actions": dossier_actions,
        "notes": notes,
        "doss_manif_sportive": doss_manif_sportive,
        "avis_manif_sportive": avis_manif_sportive,
        "emails_uniques": emails_uniques,
        "emails_dossiers": emails_dossiers,
        "nb_messages_non_lus": nb_messages_non_lus,

        # Carto
        "coeurData": fond_coeur_de_parc,
        "adhesionData": fond_aire_adhesion,
        "mafateData": fond_mafate,
        "nb_cartes": nb_cartes,
        "pois_json": pois_json,

        # Instructeurs
        "groupes_instructeurs": groupes_instructeurs,
        "instructeurs": instructeurs,
        "membres_groupe": membres_groupe,
        "instructeurs_dossier_ids": instructeurs_dossier,
        "instructeurs_du_dossier": instructeurs_du_dossier,
        "peut_se_declarer": peut_se_declarer,
        "instructeur_connecte": instructeur_connecte,
        "relecteurs_du_dossier": relecteurs_du_dossier,

        # Contacts
        "beneficiaire": beneficiaire,
        "demandeur_intermediaire": demandeur_intermediaire,
        "types_contacts": types_contacts,
        
        # Settings
        "NAS_ROOT": os.getenv('NAS_ROOT'),
        "is_formulaire_active": True,
        "is_messagerie_active": False,
        "retirer_instructeur_message": request.session.pop("retirer_instructeur_message", None),
        "changer_valideur_message": request.session.pop("changer_valideur_message", None),
        "changer_relecteur_qualite_message": request.session.pop("changer_relecteur_qualite_message", None),
        "relecteur_message": request.session.pop("relecteur_message", None),

        **roles,
        **avis_data,
        **documents_data,
    })




@login_required
def actualiser_dossier(request, num_dossier):

    dossier = Dossier.objects.filter(numero=num_dossier).first()
    if not dossier:
        logger.error(f"[ACTUALISER DOSSIER] Dossier {num_dossier} introuvable — User : {request.user}")
        return redirect_error(request, f"❌ Le dossier {num_dossier} est introuvable. Contactez le support.")

    client = GraphQLClient()

    try:
        # 1. Appel de l'API DS pour récupérer toute la démarche associée
        result = client.execute_query("DS/queries/get_dossier.graphql", {"number": num_dossier})

        try:
            result = client.execute_query("DS/queries/get_dossier.graphql", {"number": num_dossier})
        except Exception as api_err:
            logger.error(f"[ACTUALISER DOSSIER {num_dossier}] Erreur API DS (get_dossier.graphql) : {api_err}")
            return redirect_error(request, "❌ Erreur lors de l'appel à l'API DS. Contactez le support.")

        if "errors" in result and result["errors"]:
            raise Exception(f"Erreur(s) GraphQL lors de l'actualisation du dossier {num_dossier} : {result['errors']}")
        
        # 2. Normalisation des données
        doss = result["data"].get("dossier")

        contact_beneficiaire = doss.get("demandeur")

        demarche = dossier.id_demarche
        id_demarche = demarche.id
        titre_demarche = demarche.titre

        # Mettre à un autre endroit car si le nom du doss change on créer une deuxieme dossier ici (au lieu de le renommer) A VERIF
        try :
            emplacement_dossier = construire_emplacement_dossier(doss, contact_beneficiaire, titre_demarche)

        except Exception as e:
            logger.error(f"[ACTUALISER DOSSIER {num_dossier}] User {request.user} - Erreur lors du calcul de l'emplacement du dossier : {e}")
            return redirect_error(request, f"❌ Erreur lors du calcul de l'emplacement du dossier {num_dossier}. Contactez le support.")


        # Manif sportives - Déclaration manifestations
        liaison = DossierManifestationLiaison.objects.filter(id_dossier=dossier.id).first()

        if liaison:
            doss_dm = recup_un_seul_dossier(liaison.id_dossier_manif.numero_dossier_declaration_manifestations)
            doss_dm_norma = dossiers_declaration_manifestations_normalize(doss_dm)
            loggerSynchro.info("\n\n")
            loggerSynchro.info(f"###### SYNCHRONISATION {doss_dm_norma[0]['nom_dossier']} (Déclaration Manifestations) ######")

            for ddm in doss_dm_norma :
                sync_declaration_manifestations(ddm, loggerSynchro)
            loggerSynchro.info("------------------------------------------------")

        try :

            dico_dossier = {
                "dossier": dossier_normalize(id_demarche, doss, emplacement_dossier),
                "contacts_externes": contact_externe_normalize(doss, None),
                "dossier_interlocuteur": dossier_interlocuteur_normalize(doss),
                "dossier_champs": dossiers_champs_normalize(doss, emplacement_dossier, None)[0],
                "dossier_document": dossier_document_normalize(doss, emplacement_dossier),
                "messages": message_normalize(doss, emplacement_dossier),
                "demandes": demande_normalize(id_demarche, titre_demarche, doss)
            }

        except Exception as e:
            logger.error(f"[ACTUALISER DOSSIER {num_dossier}] User {request.user} - Erreur lors de la normalisation du dossier : {e}")
            return redirect_error(request, f"❌ Erreur lors de la normalisation du dossier. Contactez le support.")

        # 3. Synchronisation en base
        try :
            if liaison:
                loggerSynchro.info("\n")
                loggerSynchro.info(f"###### SYNCHRONISATION DOSSIER {doss_dm_norma[0]['nom_dossier']} (Démarches Simplifiées) ######")
            else:
                loggerSynchro.info("\n")
                loggerSynchro.info(f"###### SYNCHRONISATION DOSSIER {dico_dossier['dossier']['nom_dossier']} (Démarches Simplifiées) ######")

            dico_notifs = {}  #Est ce que on envoi vraiment une notif pour l'actualisation d'un dossier ? je ne pense pas
            sync_dossiers([dico_dossier], demarche.numero, True, dico_notifs)
        
        except Exception as sync_err:
            logger.error(f"[ACTUALISER DOSSIER {num_dossier}] User {request.user} - Échec lors de la synchronisation : {sync_err}")
            return redirect_error(request, f"❌ Erreur lors de la synchronisation du dossier. Contactez le support.")
        
        
        return redirect(request.META.get("HTTP_REFERER", "/"))

    except Exception as e:
        logger.error(f"[DOSSIER] Échec de l'actualisation complète du dossier {num_dossier} par {request.user} - : {e}")
        return redirect_error(request, f"❌ Erreur lors de l'actualisation du dossier. Contactez le support.")



@login_required
def sauvegarder_note_dossier(request):
    
    dossier_id = request.POST.get("dossierId")
    note_id = request.POST.get("noteId")
    contenu = request.POST.get("note")

    dossier = Dossier.objects.filter(id_ds=dossier_id).first()
    if not dossier:
        logger.error(f"[SAUVEGARDE NOTE DOSSIER] Dossier (id_ds={dossier_id}) introuvable — User : {request.user}")
        return redirect_error(request, f"❌ Le dossier est introuvable. Contactez le support.")
    
    instructeur = Instructeur.objects.filter(email=request.user.email).first()
    if not instructeur:
        logger.warning(f"[DOSSIER {dossier.numero}] Le user {request.user} a tenté de sauvegarder la note sans profil instructeur.")
        return redirect_error(request, "❌ Vous n’avez pas de profil 'Instructeur'. Contactez le support.")
    
    if not contenu:
        logger.warning(f"[DOSSIER {dossier.numero}] Le user {request.user} a tenté de sauvegarder une note vide.")
        return redirect_error(request, "La note est vide.")

    try :
        if note_id:  # Modification d'une note existante
            note = DossierNote.objects.filter(id=note_id, id_instructeur=instructeur).first()
            if not note:
                logger.error(f"[DOSSIER {dossier.numero}] Échec de la modification d'une note existante par {request.user} : Note {note_id} (instructeur={instructeur}) introuvable.")
                return redirect_error(request, "Erreur : Vous n'êtes pas autorisé à modifier la note. Contactez le support si besoin.")

            note.note = contenu
            note.date = timezone.now()
            note.save()
            logger.info(f"[DOSSIER {dossier.numero}] Note modifiée par {instructeur}")

        else:  # Création d'une nouvelle note
            DossierNote.objects.create(
                id_dossier=dossier,
                id_instructeur=instructeur,
                note=contenu,
                date=timezone.now()
            )
            logger.info(f"[DOSSIER {dossier.numero}] Nouvelle note ajoutée par {instructeur}")

    except Exception as e:
        logger.exception(f"[DOSSIER {dossier.numero}] Erreur lors de la sauvegarde de la note {note_id} par {request.user} : {e}")
        return redirect_error(request, "❌ Une erreur est survenue lors de l’enregistrement de la note. Contactez le support.")

    return redirect(request.META.get("HTTP_REFERER", "/"))



@login_required
def supprimer_note_dossier(request):
    dossier_id = request.POST.get("dossierId")
    note_id = request.POST.get("noteId")

    dossier = Dossier.objects.filter(id_ds=dossier_id).first()
    if not dossier:
        logger.error(f"[SUPPRIMER NOTE] Dossier id_ds={dossier_id} introuvable — User : {request.user}")
        return redirect_error(request, "❌ Le dossier est introuvable. Contactez le support.")

    instructeur = Instructeur.objects.filter(email=request.user.email).first()
    if not instructeur:
        logger.warning(f"[DOSSIER {dossier.numero}] Le user {request.user} a tenté de supprimer une note sans profil instructeur.")
        return redirect_error(request, "❌ Vous n’avez pas de profil 'Instructeur'. Contactez le support.")
    

    note = DossierNote.objects.filter(id=note_id, id_instructeur=instructeur).first()
    if not note:
        logger.error(f"[DOSSIER {dossier.numero}] Suppression échouée : note {note_id} introuvable ou non autorisée pour {instructeur}.")
        return redirect_error(request, "Vous n'êtes pas autorisé à supprimer cette note. Contactez le support si besoin.")
  
    # Suppression si tout est OK
    try:
        note.delete()
        logger.info(f"[DOSSIER {dossier.numero}] Note {note_id} supprimée par {instructeur}")

    except Exception as e:
        logger.error(f"[DOSSIER {dossier.numero}] Erreur lors de la suppression de la note {note_id} par {request.user} : {e}")
        return redirect_error(request, "❌ Une erreur est survenue lors de la suppression de la note. Contactez le support.")


    return redirect(request.META.get("HTTP_REFERER", "/"))




@require_POST
@login_required
def ajouter_relecteur_dossier(request):
    dossier_id = request.POST.get("dossier_id")
    relecteur_id = request.POST.get("relecteur_id")
    objet_demande = request.POST.get("objet_demande")
    files = request.FILES.getlist("pj_relecture")


    dossier = Dossier.objects.filter(id=dossier_id).first()
    if not dossier:
        logger.error(f"[NOUVELLE DEMANDE RELECTURE] Dossier (id={dossier_id}) introuvable — User= : {request.user}")
        return redirect_error(request, "❌ Le dossier est introuvable. Contactez le support.")

    relecteur = Instructeur.objects.filter(id=relecteur_id).first()
    if not relecteur:
        logger.error(f"[DOSSIER {dossier.numero}] Nouvelle demande de relecture. Relecteur {relecteur_id} introuvable — User : {request.user}")
        return redirect_error(request, "❌ Le relecteur indiqué est introuvable. Contactez le support.")


    for f in files:
        if f.size > 20 * 1024 * 1024:  # 20 Mo
            msg = f"Le fichier {f.name} dépasse la limite de 20 Mo."
            logger.warning(f"[DOSSIER {dossier.numero}] Nouvelle demande de relecture faite par {request.user} : {msg}")
            request.session["relecteur_message"] = msg
            return redirect(request.META.get("HTTP_REFERER", "/"))


    # Évite les doublons
    existant = DossierRelecteur.objects.filter(id_dossier=dossier, id_instructeur=relecteur).exists()

    if existant:
        request.session["relecteur_message"] = (
            "Ce.tte relecteur.rice a déjà une relecture "
            + ("réalisée." if existant.relu else "en cours.")
        )
        return redirect(request.META.get("HTTP_REFERER", "/"))


    try : 
        dossier_relecteur = DossierRelecteur.objects.create(id_dossier=dossier, id_instructeur=relecteur, demande_relecture=objet_demande)

    except Exception as e:
        logger.exception(f"[DOSSIER {dossier.numero}] Nouvelle demande de relecture faite par {request.user} - Erreur création DossierRelecteur : {e}")
        request.session["relecteur_message"] = "La demande de relecture a échoué. Contactez le support."
        return redirect(request.META.get("HTTP_REFERER", "/"))

 
    for f in files :

        # Extension du fichier
        nom, extension = os.path.splitext(f.name)
        extension = extension.lstrip('.').lower()

        # Récupérer le format
        format_obj = DocumentFormat.objects.filter(format__iexact=extension).first()
        if not format_obj:
            request.session["relecteur_message"] = (f"PJ refusée car le format n'est pas reconnu : {f.name}.{extension}.")
            logger.warning(f"[DOSSIER {dossier.numero}] Nouvelle demande de relecture faite par {request.user} : PJ refusée car le format n'est pas reconnu : {f.name}.{extension}")
            return redirect(request.META.get("HTTP_REFERER", "/"))
        


        # Ecriture du fichier
        emplacement = f"{dossier.emplacement}Annexes/Relecture/{f.name}"
        chemin_complet = f"{os.getenv('NAS_ROOT')}{emplacement}"
        creer_dossier_sur_nas(chemin_complet)

        # Évite les doublons → incrémente _2, _3...
        base_nom, ext = os.path.splitext(f.name)
        compteur = 1
        while smbclient.path.exists(chemin_complet):
            compteur += 1
            nouveau_nom = f"{base_nom}_{compteur}{ext}"
            emplacement = emplacement = f"{dossier.emplacement}Annexes/Relecture/{nouveau_nom}"
            f.name = nouveau_nom
            chemin_complet = os.path.join(os.getenv("NAS_ROOT"), emplacement)

        try:

            if not ecrire_file_sur_nas(f, chemin_complet): 
                logger.error(f"[NAS] ❌ Échec de l’écriture du fichier {nouveau_nom} sur {chemin_complet}")
                raise Exception(f"Échec de l’écriture du fichier {nouveau_nom} sur {chemin_complet}")
            

            logger.info(f"[DOSSIER {dossier.numero}] Demande de relecture : PJ {f.name} ajoutée avec succès par {request.user}")

        except Exception as e:
            logger.error(f"[DOSSIER {dossier.numero}] Demande de relecture : Erreur lors de l'écriture de la PJ {f.name} : {e}")
            request.session["relecteur_message"] = (f"Une erreur est survenue lors de l’enregistrement du fichier : {f.name}.{extension}")
            return redirect(request.META.get("HTTP_REFERER", "/"))


        # Création du Document
        try:
            document = Document.objects.create(
                id_format=format_obj,  
                id_nature=DocumentNature.objects.get(nature="Pièce jointe à relire"),
                id_statut=None,
                emplacement=f"{dossier.emplacement}Annexes/Relecture/",
                titre=f.name,
                description="Document joint à une demande de relecture"
            )

            # Liaison avec la demande de relecture
            DossierRelecteurDocument.objects.create(
                id_dossier_relecteur=dossier_relecteur,
                id_document=document
            )

        except Exception as e:
            logger.error(f"[DOSSIER {dossier.numero}] Nouvelle demande de relecture faite par {request.user} - Échec création Document pour {f.name} : {e}")
            request.session["relecteur_message"] = "❌ Erreur lors de la création du document en base. Contactez le support."
            return redirect(request.META.get("HTTP_REFERER", "/"))
        

    ####################################
    # NOTIFICATION PAR MAIL AU RELECTEUR 
    ####################################

    if request.user.email != relecteur.email :

        # On notifie les agents dans le cadre d'une vraie instruction
        if NOTIFS_PROD :
            emails_norm = [relecteur.email]
        # Test de notification par mail à EMAIL_NOTIF_TEST   
        else :
            emails_norm = [EMAIL_NOTIF_TEST]

        emails_txt = ", ".join(emails_norm)

        sujet = f"Dossier {dossier.numero} - Relecture demandée"

        context = {
                    "dossier_numero": dossier.numero,
                    "demarche_type": dossier.id_demarche.type,
                    "url": f"{os.getenv('URL_APPLI')}instruction/{dossier.numero}/"
                }
        template_name = "demande_relecture"

        try :
            dedupe = compute_dedupe_key(emails_norm, sujet, template_name, context)

        except Exception as e:
            logger.error(f"[DOSSIER {dossier.numero}] Nouvelle demande de relecture faite par {request.user} - Erreur lors de la création de la clé unique (compute_dedupe_key) : {e}")
            return redirect_error(request, f"L'email de notification à {emails_txt} n'a pas été envoyé. Contactez le support pour en savoir plus.")


        # Vérifie si un mail identique a déjà été créé dans les 2 dernières heures (pour éviter le spam)
        existe_deja = EmailOutbox.objects.filter(
            dedupe_key=dedupe,
            date_creation__gte= timezone.now() - timedelta(hours=2)
        ).exists()

        if not existe_deja:
            outbox = create_EmailOutbox(emails_norm, sujet, template_name, dedupe, context, dossier, type_mail = "Notification")

            if outbox :
                ok, err = envoi_mail(outbox.id)
            else :
                logger.error(f"[DOSSIER {dossier.numero}] Demande de relecture faite par {request.user} : Erreur lors de la création de l'EmailOutbox, {emails_txt} n'a pas été notifié de la demande de relecture par mail.")
                request.session["relecteur_message"] = (f"L'email de notification à {emails_txt} n'a pas été envoyé. Contactez le support pour en savoir plus.")
                return redirect(reverse("instruction_dossier", kwargs={"num_dossier": dossier.numero}))

            if ok:
                logger.info(f"[DOSSIER {dossier.numero}] Notification Email {outbox.id} (Demande de relecture faite par {request.user}) envoyée à {', '.join(outbox.to)} ")
            else:
                logger.error(f"[DOSSIER {dossier.numero}] Échec envoi notification email {outbox.id} (Demande de relecture faite par {request.user}) à {', '.join(outbox.to)} : {err}")
                request.session["relecteur_message"] = (f"L'email de notification à {emails_txt} n'a pas été envoyé. Contactez le support pour en savoir plus.")
                return redirect(reverse("instruction_dossier", kwargs={"num_dossier": dossier.numero}))

    
    return redirect(reverse("instruction_dossier", kwargs={"num_dossier": dossier.numero}))



@require_POST
@login_required
def relecture_faite(request):
    dossier_id = request.POST.get("dossier_id")
    relecteur_entry_id = request.POST.get("relecteur_id")
    reponse_demande = request.POST.get("reponse_demande")

    dossier = Dossier.objects.filter(id=dossier_id).first()
    if not dossier:
        logger.error(f"[RELECTURE FAITE] Dossier {dossier_id} introuvable — User : {request.user}")
        return redirect_error(request, "❌ Le dossier est introuvable. Contactez le support.")
    
    entry = DossierRelecteur.objects.filter(id=relecteur_entry_id, id_dossier=dossier).first()
    if not entry:
        logger.error(f"[DOSSIER {dossier.numero}] Relecture faite par {request.user} - Entrée DossierRelecteur id={relecteur_entry_id} introuvable — User={request.user}")
        return redirect_error(request, "❌ La demande de relecture est introuvable. Contactez le support.")
    
    instructeur = Instructeur.objects.filter(email=request.user.email).first()
    if not instructeur:
        logger.warning(f"[DOSSIER {dossier.numero}] User={request.user} a tenté de valider une relecture sans profil instructeur.")
        return redirect_error(request, "❌ Vous n’avez pas de profil 'Instructeur'. Contactez le support.")
    
    if request.user.email == entry.id_instructeur.email:
        try:
            entry.relu = True
            entry.reponse_relecture = reponse_demande
            entry.save()

            # Dossier Action
            nom_prenom = instructeur.id_agent_autorisations.nom + " " + instructeur.id_agent_autorisations.prenom
            safe_enregistrer_action(dossier, instructeur, "Relecture", request, description = nom_prenom)

        except Exception as e:
            logger.exception(f"[DOSSIER {dossier.numero}] Erreur lors de la validation de la relecture (entry={entry.id}) par {request.user} : {e}")
            request.session["relecteur_message"] = ("Une erreur est survenue lors de la validation de la relecture. Contactez le support.")
    else:
        request.session["relecteur_message"] = ("Vous n’êtes pas autorisé.e à valider cette relecture.")

    return redirect(reverse("instruction_dossier", kwargs={"num_dossier": dossier.numero}))



@require_POST
@login_required
def retirer_relecteur(request):

    drj_id = request.POST.get("dossier_relecture_id")

    drj = DossierRelecteur.objects.filter(id=drj_id).select_related("id_dossier", "id_instructeur").first()
    if not drj:
        logger.error(f"[RETIRER RELECTEUR] DossierRelecteur id={drj_id} introuvable — User : {request.user}")
        return redirect_error(request, "❌ La demande de relecture est introuvable en base. Contactez le support.")

    dossier = drj.id_dossier

    # Vérification Instructeur
    instructeur = Instructeur.objects.filter(email=request.user.email).first()
    if not instructeur:
        logger.warning(f"[DOSSIER {dossier.numero}] Le user {request.user} tente de retirer un relecteur sans profil instructeur.")
        return redirect_error(request, "❌ Vous n’avez pas de profil 'Instructeur'. Contactez le support.")
    
    # Vérification autorisation à supprimer
    instructeurs_du_dossier = DossierInstructeur.objects.filter(
        id_dossier=dossier
    ).values_list("id_instructeur_id", flat=True)

    # Relecteur lui meme ou bien un des instructeurs du dossier
    if instructeur.id != drj.id_instructeur.id and instructeur.id not in instructeurs_du_dossier and not request.user.is_superuser :
        logger.warning(f"[DOSSIER {dossier.numero}] Retrait refusé : {request.user} n'est pas autorisé à retirer le relecteur {drj.id_instructeur.id}.")
        request.session["relecteur_message"] = "Vous n’êtes pas autorisé.e à retirer ce.ette relecteur.rice."
        return redirect(reverse("instruction_dossier", kwargs={"num_dossier": dossier.numero}))
    
    # Suppression
    try :
        drj.delete()
    except :
        request.session["relecteur_message"] = ("Le relecteur n'as pas pu être retiré du dossier. Contactez le support.")
    
    return redirect(reverse("instruction_dossier", kwargs={"num_dossier": dossier.numero}))
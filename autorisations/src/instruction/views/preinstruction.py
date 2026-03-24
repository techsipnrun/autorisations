from django.http import HttpResponseBadRequest
from django.urls import reverse
from django.utils import timezone
import json, os
from django.shortcuts import get_object_or_404, render, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
from autorisations.models.models_instruction import Demarche, Dossier, DossierAction, DossierChamp, DossierManifSportive, DossierManifestationLiaison, DossierNote, EtapeDossier, EtatDossier, Message, SynchronisationEtat
from autorisations.models.models_utilisateurs import DossierInstructeur, Groupeinstructeur, GroupeinstructeurDemarche, DossierInterlocuteur, DossierBeneficiaire, Instructeur
from autorisations import settings
from autorisations.models.models_documents import DossierDocument
from autorisations.utils.nas_fonctions import _normalize_unc_path
from instruction.utils.dossier_utils import build_champs_prepares, build_timeline_for_dossier, count_unread_messages_for_dossier, get_beneficiaire_for_dossier, get_demandeur_for_dossier, redirect_error, safe_enregistrer_action, get_etapes_custom
from instruction.utils.files_utils import load_geojson
from instruction.utils_instru import dossiers_reception_action_a_faire, enregistrer_action, format_etat_dossier
from DS.call_DS import change_groupe_instructeur_ds, passer_en_instruction_ds
import logging
import ast
from collections import defaultdict


logger = logging.getLogger("ORM_DJANGO")

@login_required
def preinstruction(request):

    etape_affecter = EtapeDossier.objects.filter(etape="À affecter").first()
    if not etape_affecter:
        logger.error("[PREINSTRUCTION] Étape 'À affecter' introuvable.")
        return redirect_error(request, "❌ Erreur interne : étape 'À affecter' introuvable.")

    dossiers = Dossier.objects.filter(id_etape_dossier=etape_affecter).select_related("id_demarche").order_by("date_depot")

    
    instructeur = Instructeur.objects.filter(email=request.user.email).first()
    if not instructeur:
        logger.warning(f"[PREINSTRUCTION] User {request.user} sans profil Instructeur.")
        messages.warning(request, "⚠️ Vous n’avez pas de profil 'Instructeur'. Contactez le support si besoin.")

    dossiers_actions = set(dossiers_reception_action_a_faire(dossiers, request.user))
    # dossiers_actions = dossiers_reception_action_a_faire(dossiers, request.user)

    # Infos sur les dossiers
    dossier_infos = []
    for dossier in dossiers:

        if dossier.id_demarche.type == "Manifestations sportives":
            # On ne les affiche pas dans cette première partie
            continue


        # Chercher le demandeur via DossierInterlocuteur
        interlocuteur = DossierInterlocuteur.objects.filter(id_dossier=dossier).select_related("id_demandeur_intermediaire").first()
        # demandeur = interlocuteur.id_demandeur_intermediaire if interlocuteur else None

        demandeur = get_demandeur_for_dossier(dossier)
        
        # On affiche le nom et prenom du beneficiaire si jamais le demandeur intermédiaire ne les a pas de renseignés
        # if not demandeur or not(demandeur.prenom and demandeur.nom):
        #     benef = DossierBeneficiaire.objects.filter(id_dossier_interlocuteur=interlocuteur).select_related("id_beneficiaire").first()
        #     demandeur = benef.id_beneficiaire if benef else None

        dossier_infos.append({
            "demarche": dossier.id_demarche.type,
            "date_depot": dossier.date_depot,
            # "demandeur": f"{demandeur.prenom} {demandeur.nom}" if demandeur else "N/A",
            "demandeur": demandeur,
            "nom_dossier": dossier.nom_dossier,
            "nom_dossier_plus_parlant": dossier.nom_dossier_plus_parlant,
            "numero": dossier.numero,
            "action_a_faire": True if dossier in dossiers_actions else False
        })


    # ==================================
    # MANIFESTATIONS SPORTIVES 
    # ==================================
    demarche_manif = Demarche.objects.filter(type="Manifestations sportives").first()
    if not demarche_manif:
        logger.error("[PREINSTRUCTION] Démarche 'Manifestations sportives' introuvable.")
        return redirect_error(request, "❌ Erreur interne : démarche Manif Sportive introuvable.")

    num_demarche_manif_sportive = demarche_manif.numero


    # ---------------------------------------------
    # Dossier DM non liés à un Dossier DS
    # ---------------------------------------------
    dossiers_manif_sportive_DM = (
        DossierManifSportive.objects.exclude(id__in=DossierManifestationLiaison.objects.values_list("id_dossier_manif", flat=True))
        .exclude(archive=True)
        .order_by("-date_debut_evenement")
    )


    # ----------------------------------------------
    # Dossiers DS non liés à un Dossier DM
    # ----------------------------------------------
    dossiers_manif_sportive_DS = (
        Dossier.objects.filter(id_demarche__type="Manifestations sportives")
        .exclude(id__in=DossierManifestationLiaison.objects.values_list("id_dossier", flat=True))
        .order_by("-date_depot")
    )

    dossiers_manif_sportive_DS_infos = []
    for dossier in dossiers_manif_sportive_DS:

        # --- 1. Bénéficiaire ---
        interlocuteur = DossierInterlocuteur.objects.filter(id_dossier=dossier).first()
        beneficiaire = None
        if interlocuteur:
            dossier_benef = DossierBeneficiaire.objects.filter(id_dossier_interlocuteur=interlocuteur).select_related("id_beneficiaire").first()
            beneficiaire = dossier_benef.id_beneficiaire if dossier_benef else None

        nom_demandeur = f"{beneficiaire.nom} {beneficiaire.prenom}" if beneficiaire else "N/A"

        # --- 2. Numéro de dossier DM ---
        champ_numero_dm = DossierChamp.objects.filter(
            id_dossier=dossier,
            id_champ__nom="Numéro du dossier sur la plateforme déclaration-manifestations"
        ).first()
        numero_dm = champ_numero_dm.valeur if champ_numero_dm and champ_numero_dm.valeur else "N/A"


        # --- 3. Nom de la manifestation ---
        champ_nom_manifestation = DossierChamp.objects.filter(
            id_dossier=dossier,
            id_champ__nom="Nom de la manifestation"
        ).first()
        nom_manifestation = champ_nom_manifestation.valeur if champ_nom_manifestation and champ_nom_manifestation.valeur else "N/A"

        dossiers_manif_sportive_DS_infos.append({
            "dossier": dossier,
            "nom_demandeur": nom_demandeur,
            "numero_dm": numero_dm,
            "nom_manifestation": nom_manifestation,
        })



    # -----------------------------------------
    # Dossiers DS liés à au moins un Dossier DM
    # -----------------------------------------
    dossiers_manif_sportive_complet = Dossier.objects.filter(
        id_demarche__type="Manifestations sportives",
        id__in=DossierManifestationLiaison.objects.values_list("id_dossier", flat=True),
        id_etape_dossier__etape="À affecter"
    )

    # Récupération des liaisons
    liaisons = DossierManifestationLiaison.objects.filter(id_dossier__in=dossiers_manif_sportive_complet).select_related("id_dossier_manif")



    # Création d’un dictionnaire : dossier → dossier_manif
    dossiers_manif_sportive_complet_map = { liaison.id_dossier: liaison.id_dossier_manif for liaison in liaisons }

    # Conversion en liste de tuples pour itération dans le template
    # dossiers_manif_sportive_complet_list = list(dossiers_manif_sportive_complet_map.items())
    # # Trier par date de début de la course décroissante
    # dossiers_manif_sportive_complet_list = sorted(
    #     dossiers_manif_sportive_complet_list,
    #     key=lambda pair: pair[1].date_debut_evenement or timezone.datetime.min,
    #     reverse=True
    # )

    # Tri (date début de course décroissante)
    dossiers_manif_sportive_complet_list = sorted(
        dossiers_manif_sportive_complet_map.items(),
        key=lambda pair: pair[1].date_debut_evenement or timezone.datetime.min,
        reverse=True
    )

    

    return render(request, 'instruction/preinstruction.html', {
        "dossier_infos": dossier_infos,
        "num_demarche_manif_sportive": num_demarche_manif_sportive,
        "dossiers_manif_sportive_DM": dossiers_manif_sportive_DM,
        "dossiers_manif_sportive_DS_infos": dossiers_manif_sportive_DS_infos,
        "dossiers_manif_sportive_complet": dossiers_manif_sportive_complet_list,
        "instructeur": instructeur,
        "django_env" : settings.ENVIRONMENT,
        })



@login_required
def preinstruction_dossier(request, numero):

    dossier = Dossier.objects.filter(numero=numero).first()
    if not dossier:
        logger.error(f"[PREINSTRUCTION DOSSIER] Erreur lors de l'affichage de la page par {request.user} : Dossier {numero} introuvable.")
        return redirect_error(request, f"❌ Le dossier {numero} est introuvable en base. Contactez le support")

    # Normalisation du path complet
    chemin_complet = dossier.emplacement
    if not chemin_complet.startswith(os.getenv('NAS_ROOT')):
        chemin_complet = os.path.join(os.getenv('NAS_ROOT'), chemin_complet)
    chemin_complet = _normalize_unc_path(chemin_complet)
    
    ########################################
    # Menu déroulant avec les choix d'étapes
    ########################################

    etape_actuelle = dossier.id_etape_dossier if hasattr(dossier, "id_etape_dossier") else None

    dossier_sppn = dossier.id_demarche.service == 'SPPN'
    etapes_custom = get_etapes_custom(
        present_sur_ds=dossier.present_sur_ds,
        dossier_sppn=dossier_sppn,
        etape_actuelle=etape_actuelle.etape if etape_actuelle else "",
        demarche_type=dossier.id_demarche.type
    )


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


    ###################################################
    # Infos sur le bénéficiaire/demandeur intermediaire
    ###################################################
    beneficiaire = get_beneficiaire_for_dossier(dossier)
    demandeur_intermediaire = None
    interlocuteur = DossierInterlocuteur.objects.filter(id_dossier=dossier).first()
    if interlocuteur and interlocuteur.id_demandeur_intermediaire:
        demandeur_intermediaire = interlocuteur.id_demandeur_intermediaire


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
                            else n.id_instructeur.email
        }
        for n in notes_queryset
    ]


    # -----------------------------------
    # Documents du dossier
    # -----------------------------------
    dossier_documents = DossierDocument.objects.filter(id_dossier=dossier).select_related("id_document")
    emplacements_documents = [ f"{doc.id_document.emplacement}{doc.id_document.titre}" for doc in dossier_documents]


    # Documents de nature "Annexe instructeur"
    annexes_instructeur = [
        dd.id_document
        for dd in dossier_documents
        if (dd.id_document.id_nature and (dd.id_document.id_nature.nature or "").lower() == "annexe instructeur")
    ]

    # Résumé PDF du dossier
    resume_pdf_titre = f"dossier-{dossier.numero}.pdf"


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


    ###############################
    # Messages non lus
    ###############################
    nb_messages_non_lus = count_unread_messages_for_dossier(dossier, dossier.numero)

    ###############################
    # Infos sur la synchro
    ###############################
    etat_global = SynchronisationEtat.objects.filter(id=1).values("en_cours").first()


    return render(request, 'instruction/preinstruction_dossier.html', {
        # Dossier
        "dossier": dossier,
        "etat_dossier": format_etat_dossier(dossier.id_etat_dossier.nom),
        "etape_actuelle": etape_actuelle,
        "etapes_custom": etapes_custom,
        "chemin_complet": chemin_complet,
        "etape_dossier": dossier.id_etape_dossier.etape if dossier.id_etape_dossier else "N/A",
        "dossier_actions": dossier_actions,
        "champs": champs_prepares,
        "doss_manif_sportive": doss_manif_sportive,
        "avis_manif_sportive": avis_manif_sportive,
        "notes": notes,
        "nb_messages_non_lus": nb_messages_non_lus,
        "synchro_globale_en_cours": etat_global["en_cours"] if etat_global else False,
        
        # Carto
        "coeurData": fond_coeur_de_parc,
        "adhesionData": fond_aire_adhesion,
        "mafateData": fond_mafate,
        "nb_cartes": nb_cartes,
        "pois_json": pois_json,
        
        # Instructeurs
        "groupes_instructeurs": groupes_instructeurs,
        "membres_groupe": membres_groupe,
        "instructeurs_dossier_ids": instructeurs_dossier,
        "instructeur_connecte": instructeur_connecte,

        # Documents
        "emplacements_documents": emplacements_documents,
        "annexes_instructeur": annexes_instructeur,
        "resume_pdf_titre": resume_pdf_titre,

        # Contacts
        "beneficiaire": beneficiaire,
        "demandeur_intermediaire": demandeur_intermediaire,
        
        # Settings
        "NAS_ROOT": os.getenv('NAS_ROOT'),
        "is_formulaire_active": True,
        "is_messagerie_active": False,
        "preinstruction_message": request.session.pop("preinstruction_message", None),
        "retirer_instructeur_message": request.session.pop("retirer_instructeur_message", None),
    })



@require_POST
def changer_groupe_instructeur(request):

    dossier_id = request.POST.get("dossierId")
    groupe_id = request.POST.get("groupeInstructeurId")

    # -----------------
    # Vérifications
    # -----------------
    if not dossier_id :
        logger.error(f"[CHANGER GROUPE INSTRUCTEUR] User {request.user} : groupe_id_ds={groupe_id}, dossier_id non transmis via le formulaire.")
        return redirect_error(request, "❌ Paramètres manquants pour changer le groupe instructeur. Contactez le support.")

    if not groupe_id :
        logger.error(f"[CHANGER GROUPE INSTRUCTEUR] User {request.user} : dossier_id_ds={dossier_id}, groupe_id non transmis via le formulaire.")
        return redirect_error(request, "❌ Paramètres manquants pour changer le groupe instructeur. Contactez le support.")


    dossier = Dossier.objects.filter(id_ds=dossier_id).first()
    if not dossier:
        logger.error(f"[CHANGER GROUPE INSTRUCTEUR] Dossier id_ds={dossier_id} introuvable — User {request.user}")
        return redirect_error(request, "❌ Le dossier est introuvable en base. Contactez le support.")

    dossier_num = dossier.numero


    # --------------------------------------
    # Récupération du groupe interne + DS
    # --------------------------------------
    nom_groupe = Groupeinstructeur.objects.filter(id=groupe_id).values_list("nom", flat=True).first()
    if not nom_groupe:
        logger.error(f"[DOSSIER {dossier_num}] Changement de Groupe Instructeur par {request.user} : Groupe id={groupe_id} introuvable.")
        return redirect_error(request, "❌ Groupe instructeur introuvable.")

    groupe_id_ds = GroupeinstructeurDemarche.objects.filter(id_groupeinstructeur=groupe_id).values_list("id_groupeinstructeur_ds", flat=True).first()

    if not groupe_id_ds:
        logger.error(f"[DOSSIER {dossier_num}] Changement de Groupe Instructeur par {request.user} : Groupe instructeur {groupe_id} sans équivalent DS.")
        return redirect_error(request, "❌ Groupe instructeur invalide pour DS. Contactez le support.")

    # ---------------
    # Appel API DS
    # ---------------
    try:
        result = change_groupe_instructeur_ds(dossier_id, groupe_id_ds)
    except Exception as e:
        logger.error(f"[DOSSIER {dossier_num}] Erreur API DS lors du changement de groupe vers {nom_groupe} par {request.user} : {e}")
        return redirect_error(request, "❌ Erreur lors du changement de groupe sur Démarche Numérique. Contactez le support.")


    if not result.get("success"):
        logger.error(f"[DOSSIER {dossier_num}] Echec du changement de Groupe Instructeur vers {nom_groupe} par {request.user} : {result.get('message')}")
        return redirect_error(request, "❌ Erreur lors du changement de groupe sur Démarche Numérique. Contactez le support.")

    logger.info(f"[DOSSIER {dossier_num}] Groupe Instructeur changé avec succès sur DS par {request.user} --> Affecté au groupe {nom_groupe}.")


    # ---------------
    # MAJ EN BDD
    # ---------------
    try:
        dossier.id_groupeinstructeur_id = groupe_id
        dossier.save()

        instructeur = Instructeur.objects.filter(email=request.user.email).first()
        safe_enregistrer_action(dossier, instructeur, "Affectation au groupe", request, description=nom_groupe)

        logger.info(f"[DOSSIER {dossier_num}] Groupe Instructeur mis à jour dans Postgres par {request.user} --> Affecté au groupe {nom_groupe}.")

    except Exception as e:
        logger.error(f"[DOSSIER {dossier_num}] Erreur de mise à jour du Groupe Instructeur en BDD par {request.user} (groupe mis à jour sur DS) : {e}")
        return redirect_error(request,"⚠️ Groupe modifié sur DS mais erreur interne lors de la mise à jour locale. Contactez le support.")
   
    return redirect(request.META.get('HTTP_REFERER', '/'))

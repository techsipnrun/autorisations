from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
import json, os
from django.shortcuts import get_object_or_404, render, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
from autorisations.models.models_instruction import Champ, Dossier, DossierChamp, DossierManifSportive, DossierManifestationLiaison, EtapeDossier, EtatDossier, Message, SynchronisationEtat
from autorisations import settings
from autorisations.models.models_documents import Document, DossierManifSportiveDocument
from autorisations.models.models_utilisateurs import ContactExterne, EmailOutbox, Instructeur, TypeContactExterne
from autorisations.utils.nas_fonctions import _normalize_unc_path, creer_dossier_sur_nas
from declaration_manifestations.get_methods import get_access_token
from instruction.utils.dm import documents_deposes_sur_DM, reception_charger_contexte_avis_dm, reception_lire_donnees_formulaire_avis_dm, reception_preparer_emplacements_dossier_dm, reception_rendre_avis_et_mettre_a_jour_dm, reception_traiter_fichier_avis_dm, reception_verifier_acces_et_fichiers_avis_dm
from instruction.utils.dossier_utils import get_actions_possibles_DM, redirect_error
from instruction.utils.utilisateurs_utils import envoyer_copie_document_par_mail
from synchronisation.utils.instruction import archive_lier_dossier_dm_au_dossier_dn, lier_dossier_dm_au_dossier_dn

import logging

logger = logging.getLogger("ORM_DJANGO")


@login_required
def dossier_manif_sportive_sans_ds(request, numero):
    """
    Affichage en Reception des Dossiers DM (qui ne sont pas liés à un Dossier DN)
    """

    doss_manif_sportive = get_object_or_404(DossierManifSportive, numero_dossier_declaration_manifestations=numero)
    today = timezone.localdate()
    date_evenement_passee = False
    date_evenement_dans_moins_un_mois = False
    if doss_manif_sportive.date_debut_evenement:
        date_evenement = doss_manif_sportive.date_debut_evenement.date()
        date_evenement_passee = date_evenement < today
        date_evenement_dans_moins_un_mois = (
            today <= date_evenement <= today + timedelta(days=30)
        )

    # Récupération de l'avis lié (OneToOne → un seul)
    try:
        avis_manif_sportive = doss_manif_sportive.avis  # grâce à related_name='avis'
    except Exception:
        avis_manif_sportive = None  # Aucun avis associé

    # Charger le fond de carte GeoJSON (une seule fois)
    fond_coeur_de_parc = os.path.join(settings.BASE_DIR, "instruction/static/instruction/carto/fond_coeur_de_parc.geojson")
    with open(fond_coeur_de_parc, encoding="utf-8") as f:
        fond_coeur_de_parc = json.load(f)

    fond_aire_adhesion = os.path.join(settings.BASE_DIR, "instruction/static/instruction/carto/aire_adhesion.geojson")
    with open(fond_aire_adhesion, encoding="utf-8") as f:
        fond_aire_adhesion = json.load(f)

    pois_json = os.path.join(settings.BASE_DIR, "instruction/static/instruction/carto/pois.json")
    with open(pois_json, encoding="utf-8") as f:
        pois_json = json.load(f)

    # Les PJ du demandeur sur Déclaration Manifestations
    # pjs_demandeur_DM = Document.objects.filter(dossiermanifsportivedocument__id_dossier_manif_sportive=doss_manif_sportive, id_nature__nature="Pièce jointe demandeur")


    # -------------------------------------------------------------------
    # CLASSIFICATION DES DOSSIERS DN (lié/pas lié, acte envoyé/pas envoyé)
    # -------------------------------------------------------------------
    dossiers_deja_lies_ids = DossierManifestationLiaison.objects.values_list("id_dossier_id", flat=True)

    etapes_avec_acte_deja_envoye = ["À publier au RAA", "Non soumis à autorisation", "Refusé", "Accepté",]
    
    # DOSSIER DN NON ARCHIVÉ, PAS LIÉ
    dossiers_DN_manif_sportive_non_lie = (
        Dossier.objects
        .filter(id_demarche__type="Manifestations sportives", date_depot__gte=timezone.now() - timedelta(days=365))
        .exclude(id__in=dossiers_deja_lies_ids)
        .exclude(id_etape_dossier__etape__in=etapes_avec_acte_deja_envoye)
        .select_related("id_demarche", "id_etape_dossier")
        .order_by("date_depot")
    )
    for d in dossiers_DN_manif_sportive_non_lie :
        champ_nom_manifestation = DossierChamp.objects.filter(id_dossier=d, id_champ__nom="Nom de la manifestation").first()
        d.nom_manifestation = champ_nom_manifestation.valeur if champ_nom_manifestation and champ_nom_manifestation.valeur else "N/A"


    # DOSSIER DN ARCHIVÉ, PAS LIÉ
    limite_un_an = timezone.now() - timedelta(days=365)

    dossiers_DN_archive_manif_sportive_non_lie = (
        Dossier.objects
        .filter(id_demarche__type="Manifestations sportives", date_depot__gte=timezone.now() - timedelta(days=365), id_etape_dossier__etape__in=etapes_avec_acte_deja_envoye)
        .filter(
            Q(date_fin_instruction__gte=limite_un_an) |
            Q(date_fin_instruction__isnull=True)
        )
        .exclude(id__in=dossiers_deja_lies_ids)
        .select_related("id_demarche", "id_etape_dossier")
        .order_by("date_depot")
    )
    for d in dossiers_DN_archive_manif_sportive_non_lie :
        champ_nom_manifestation = DossierChamp.objects.filter(id_dossier=d, id_champ__nom="Nom de la manifestation").first()
        d.nom_manifestation = champ_nom_manifestation.valeur if champ_nom_manifestation and champ_nom_manifestation.valeur else "N/A"


    dossiers_DN_accepte_manif_sportive_non_lie = (dossiers_DN_archive_manif_sportive_non_lie.filter(id_etape_dossier__etape="Accepté"))
    for d in dossiers_DN_accepte_manif_sportive_non_lie:
        champ_nom_manifestation = DossierChamp.objects.filter(id_dossier=d, id_champ__nom="Nom de la manifestation").first()
        d.nom_manifestation = champ_nom_manifestation.valeur if champ_nom_manifestation and champ_nom_manifestation.valeur else "N/A"


    dossiers_DN_refuse_manif_sportive_non_lie = (dossiers_DN_archive_manif_sportive_non_lie.filter(id_etape_dossier__etape="Refusé"))
    for d in dossiers_DN_refuse_manif_sportive_non_lie:
        champ_nom_manifestation = DossierChamp.objects.filter(id_dossier=d, id_champ__nom="Nom de la manifestation").first()
        d.nom_manifestation = champ_nom_manifestation.valeur if champ_nom_manifestation and champ_nom_manifestation.valeur else "N/A"

        

    

    champ_num_dm = Champ.objects.get(nom="Numéro du dossier sur la plateforme déclaration-manifestations")

    dossier_dn_meme_numero = (
        Dossier.objects
        .filter(
            id_demarche__type="Manifestations sportives",
            dossierchamp__id_champ=champ_num_dm,
            dossierchamp__valeur=str(doss_manif_sportive.numero_dossier_declaration_manifestations),
        )
        .select_related("id_etape_dossier")
        .distinct()
        .first()
    )

    dossier_dn_meme_numero_deja_lie = None
    dossier_dn_meme_numero_pas_lie_acte_envoye = None
    dossier_dn_meme_numero_pas_lie_acte_pas_envoye = None

    if dossier_dn_meme_numero:
        est_deja_lie = DossierManifestationLiaison.objects.filter(id_dossier=dossier_dn_meme_numero).exists()

        if est_deja_lie:
            dossier_dn_meme_numero_deja_lie = dossier_dn_meme_numero
        else:
            if dossier_dn_meme_numero.id_etape_dossier.etape in etapes_avec_acte_deja_envoye:
                dossier_dn_meme_numero_pas_lie_acte_envoye = dossier_dn_meme_numero
            else:
                dossier_dn_meme_numero_pas_lie_acte_pas_envoye = dossier_dn_meme_numero


    # On récupère le path du Dossier DM
    chemin_complet = doss_manif_sportive.emplacement
    if not chemin_complet.startswith(os.getenv('NAS_ROOT')):
        chemin_complet = os.path.join(os.getenv('NAS_ROOT'), chemin_complet)
    chemin_complet = _normalize_unc_path(chemin_complet)

    # Actions possibles
    actions_possibles = get_actions_possibles_DM(doss_manif_sportive)


    # On récupère les actes/annexe déposées sur DM
    # documents_DM = [ d.id_document for d in DossierManifSportiveDocument.objects.filter( id_dossier_manif_sportive=doss_manif_sportive)]

    # actes_natures = {"Avis conforme", "Avis simple", "Déliberation CA", "Arrêté directeur",}

    # actes_deposes_sur_DM = [
    #     doc for doc in documents_DM
    #     if doc.id_nature.nature in actes_natures
    # ]

    # annexes_deposees_sur_DM = [
    #     doc for doc in documents_DM
    #     if doc.id_nature.nature == "Annexe instructeur"
    # ]
    

    docs_DM = documents_deposes_sur_DM(doss_manif_sportive)


    ################
    #    Emails
    ################
    # Les emails de relance concernent les doss DM (non lié) qui intersecte le coeur de parc
    emails_relance = EmailOutbox.objects.filter(id_dossier_dm=doss_manif_sportive.id, type_mail="Relance").order_by("-date_creation")

    # Les emails de notifications concernent les doss DM (non lié) qui ont notifié des personnes suite à un classement comme 'non soumis' ou 'non répondu'
    emails_notifs = EmailOutbox.objects.filter(id_dossier_dm=doss_manif_sportive.id, type_mail="Envoi de l'acte").order_by("-date_creation")

    emails_contacts = ContactExterne.objects.filter(
        email__isnull=False
    ).exclude(email__exact="").values_list("email", flat=True).distinct()

    emails_instructeurs = Instructeur.objects.filter(
        email__isnull=False
    ).exclude(email__exact="").values_list("email", flat=True).distinct()

    # Fusionner et dédoublonner
    emails_uniques = sorted(set(emails_contacts) | set(emails_instructeurs))

    # Liste tous les emails (envoi acte en copie) liés à ce dossier
    # emails_dossiers = EmailOutbox.objects.filter(id_dossier=dossier.id, type_mail="Envoi de l'acte").order_by("-date_creation")


    # Type contacts externes
    types_contacts = TypeContactExterne.objects.all()

    DM_API_URL = os.getenv('DM_API_URL')

    

    return render(request, 'instruction/dossier_manif_sportive_sans_ds.html', {
        "doss_manif_sportive": doss_manif_sportive,
        "date_evenement_passee": date_evenement_passee,
        "date_evenement_dans_moins_un_mois": date_evenement_dans_moins_un_mois,
        # "pjs_demandeur_DM": pjs_demandeur_DM,
        "avis_manif_sportive": avis_manif_sportive,
        "coeurData": fond_coeur_de_parc,
        "adhesionData": fond_aire_adhesion,
        "pois_json": pois_json,
        "dossiers_DN_manif_sportive_non_lie": dossiers_DN_manif_sportive_non_lie,
        "dossiers_DN_archive_manif_sportive_non_lie": dossiers_DN_archive_manif_sportive_non_lie,
        "chemin_complet": chemin_complet,
        "dossier_dn_meme_numero_deja_lie" : dossier_dn_meme_numero_deja_lie,
        "dossier_dn_meme_numero_pas_lie_acte_envoye" : dossier_dn_meme_numero_pas_lie_acte_envoye,
        "dossier_dn_meme_numero_pas_lie_acte_pas_envoye" : dossier_dn_meme_numero_pas_lie_acte_pas_envoye,
        "dossiers_DN_refuse_manif_sportive_non_lie": dossiers_DN_refuse_manif_sportive_non_lie,
        "dossiers_DN_accepte_manif_sportive_non_lie": dossiers_DN_accepte_manif_sportive_non_lie,
        "actions_possibles": actions_possibles,
        "now": timezone.now(),
        # "emails_uniques": emails_uniques,
        "emails_relance": emails_relance,
        "emails_notifs": emails_notifs,
        "lien_form_manif_sportive": os.getenv('LIEN_FORM_MANIF_SPORTIVE'),
        # "actes_deposes_sur_DM": actes_deposes_sur_DM,
        # "annexes_deposees_sur_DM": annexes_deposees_sur_DM,
        **docs_DM,

        "types_contacts": types_contacts,
        "emails_uniques": emails_uniques,
        # "emails_dossiers": emails_dossiers,
        "DM_API_URL": DM_API_URL,
    })




@login_required
@require_POST
def lier_dossier_manif_sportive_a_DN(request):
    """
    Lier manuellement un Dossier DM à un Dossier DN
    """
    
    id_dossier_dm = request.POST.get("id_dossier_dm")
    id_dossier_dn = request.POST.get("id_dossier_dn")

    # ---------------------------------------------------------
    # Liaison faite depuis un Dossier Déclaration Manifestations
    # ---------------------------------------------------------
    if id_dossier_dm :
        # --- Récupération du dossier DM ---
        dossier_manif = get_object_or_404(DossierManifSportive, id=id_dossier_dm)
        # --- Récupération du dossier DN sélectionné ---
        id_dossier_dn = request.POST.get("dossier_dn_id")

        if not id_dossier_dn :
            return redirect(request.META.get("HTTP_REFERER", "/"))
        
        dossier_dn = get_object_or_404(Dossier, id=id_dossier_dn)

    
    # ------------------------------------------------------
    # Liaison faite depuis un Dossier Démarche Numérique
    # ------------------------------------------------------
    elif id_dossier_dn :
        # --- Récupération du dossier DM ---
        id_dossier_dm = request.POST.get("dossier_dm_id")
        # --- Récupération du dossier DN sélectionné ---
        dossier_dn= get_object_or_404(Dossier, id=id_dossier_dn)

        if not id_dossier_dm:
            return redirect(request.META.get("HTTP_REFERER", "/"))

        dossier_manif = get_object_or_404(DossierManifSportive, id=id_dossier_dm)


    else :
        logger.error((f"[RECEPTION] User {request.user} : Tentative de liaison manuelle échouée (Manifestations Sportives). La vue lier_dossier_manif_sportive_a_DN a été appelée sans fournir l'id du Dossier ou l'id du DossierManifSportive"))
        return redirect_error(request, f"Erreur lors de la liaison entre les deux dossiers. Contactez le support.")

    # --- Sécurité : vérifier que Dossier DN "Manifestations sportives" + "À affecter" ---
    if (dossier_dn.id_demarche.type != "Manifestations sportives" or dossier_dn.id_etape_dossier.etape != "À affecter"):
        return redirect(request.META.get("HTTP_REFERER", "/"))


    # --- Création liaison + Déplacement/Suppression des fichiers (0 - En attente d'un dossier Démarche Numérique) ---
    logger.info(f"[RECEPTION] User {request.user} : Tentative de liaison manuelle entre le Dossier DM {dossier_manif.numero_dossier_declaration_manifestations} et le Dossier DN  {dossier_dn.numero} ({dossier_manif.nom_dossier})")
    success = lier_dossier_dm_au_dossier_dn(dossier_manif, dossier_dn, dossier_dn.emplacement, logger)

    if not success :
        return redirect_error(request, f"Erreur lors de la liaison entre les deux dossiers. Contactez le support.")

    # logger.info(f"[RECEPTION] User {request.user} : Liaison manuelle créée entre le Dossier DM {dossier_manif.numero_dossier_declaration_manifestations} et le Dossier DN  {dossier_dn.numero} ({dossier_manif.nom_dossier})")

    # --- Redirection ---
    messages.info(request, f"Liaison créée entre le dossier Déclaration Manifestations {dossier_manif.numero_dossier_declaration_manifestations} et le dossier Démarche Numérique {dossier_dn.numero} ")
    return redirect(reverse("preinstruction_dossier", kwargs={"numero": dossier_dn.numero}))




@login_required
@require_POST
def archive_lier_dossier_manif_sportive_a_DN(request):
    """
    Lier manuellement un Dossier DM archivé à un Dossier DN archivé 
    --> Sans fusionner les emplacements des Dossiers DM-DN
    """
    
    id_dossier_dm = request.POST.get("id_dossier_dm")
    id_dossier_dn = request.POST.get("id_dossier_dn")

    # ---------------------------------------------------------
    # Liaison faite depuis un Dossier Déclaration Manifestations
    # ---------------------------------------------------------
    if id_dossier_dm :
        # --- Récupération du dossier DM ---
        dossier_manif = get_object_or_404(DossierManifSportive, id=id_dossier_dm)
        # --- Récupération du dossier DN sélectionné ---
        id_dossier_dn = request.POST.get("dossier_dn_id")

        if not id_dossier_dn :
            return redirect(request.META.get("HTTP_REFERER", "/"))
        
        dossier_dn = get_object_or_404(Dossier, id=id_dossier_dn)

    
    # ------------------------------------------------------
    # Liaison faite depuis un Dossier Démarche Numérique
    # ------------------------------------------------------
    elif id_dossier_dn :
        # --- Récupération du dossier DM ---
        id_dossier_dm = request.POST.get("dossier_dm_id")
        # --- Récupération du dossier DN sélectionné ---
        dossier_dn= get_object_or_404(Dossier, id=id_dossier_dn)

        if not id_dossier_dm:
            return redirect(request.META.get("HTTP_REFERER", "/"))

        dossier_manif = get_object_or_404(DossierManifSportive, id=id_dossier_dm)


    else :
        logger.error((f"[RECEPTION] User {request.user} : Tentative de liaison manuelle échouée (Manifestations Sportives). La vue lier_dossier_manif_sportive_a_DN a été appelée sans fournir l'id du Dossier ou l'id du DossierManifSportive"))
        return redirect_error(request, f"Erreur lors de la liaison entre les deux dossiers. Contactez le support.")

    
    # --- Sécurité : vérifier que Dossier DN "Manifestations sportives" + dossier archivé ---
    etapes_archive = ["Non répondu", "Non soumis à autorisation", "Refusé", "Accepté"]
    if (dossier_dn.id_demarche.type != "Manifestations sportives" or dossier_dn.id_etape_dossier.etape not in etapes_archive) :
        return redirect_error(request, f"Erreur lors de la liaison entre les deux dossiers. Le dossier Démarche Numérique {dossier_dn.numero} n'est pas archivé. Contactez le support.")
    
    if not dossier_manif.archive :
        return redirect_error(request, f"Erreur lors de la liaison entre les deux dossiers. Le dossier Déclaration Manifestations {dossier_manif.numero_dossier_declaration_manifestations} n'est pas archivé. Contactez le support.")


    # --- Création liaison --> Pas de fusion des emplacements  ---
    logger.info(f"[RECEPTION] User {request.user} : Tentative de liaison manuelle entre le Dossier DM {dossier_manif.numero_dossier_declaration_manifestations} et le Dossier DN  {dossier_dn.numero} ({dossier_manif.nom_dossier})")
    success = archive_lier_dossier_dm_au_dossier_dn(dossier_manif, dossier_dn, logger)

    if not success :
        return redirect_error(request, f"Erreur lors de la liaison entre les deux dossiers. Contactez le support.")


    # --- Redirection ---
    messages.info(request, f"Liaison créée entre le dossier Déclaration Manifestations {dossier_manif.numero_dossier_declaration_manifestations} et le dossier Démarche Numérique {dossier_dn.numero} ")
    return redirect(reverse("instruction_dossier", kwargs={"num_dossier": dossier_dn.numero}))




@login_required
@require_POST
def ajouter_annexe_sur_DM(request, id_dm):
    """
    Ajoute une ou plusieurs PJ sur un Dossier Déclaration Manifestations

    """

    try :
        annexes = request.FILES.getlist("files") # UploadedFile[]
        # acte = request.FILES.get("acte") # UploadedFile
        

        # Récupération du DossierManifSportive
        doss_manif_sportive = get_object_or_404(DossierManifSportive, id=id_dm)
        manif_id = doss_manif_sportive.numero_dossier_declaration_manifestations


        root_folder = os.environ.get("NAS_ROOT")
        if not root_folder :
            logger.error(f"[Dossier DM {manif_id} - Dépôt PJ] User {request.user} : Erreur lors du dépot de pièces jointes sur DM, la variable d'environnement 'NAS_ROOT' est vide.")
            msg = "Erreur lors du dépot de pièces jointes sur Déclaration Manifestations. Le chemin d'accès au NAS n'a pas pu être récupéré. Contactez le support."
            return redirect_error(request, msg)
        

        # Récupération de l'AvisManifSportive lié
        try:
            avis_manif_sportive = doss_manif_sportive.avis  # grâce à related_name='avis'
        except Exception:
            return redirect_error(request, f"Impossible de déposer une pièce jointe sur Déclaration Manifestations pour le dossier {manif_id}, aucun avis trouvé. Contactez le support.")

        avis_id = avis_manif_sportive.id_avis_manif_sportive


        # Récupération du token API
        token = get_access_token()
        

        # Dépôt de l'acte sur DM + écriture NAS + Création Document
        # if acte :
        #     erreur = reception_traiter_fichier_avis_dm(request, fichier=acte, token=token, avis_id=avis_id, dossier_dm=doss_manif_sportive, root_folder=root_folder, nouvel_emplacement=doss_manif_sportive.emplacement, sous_dossier_cible="Actes/", nature_document="Arrêté directeur", description_document="Acte envoyé sur Déclaration Manifestations.", message_erreur_metier="L'acte a bien été transmis sur Déclaration Manifestations. Contactez le support si besoin.", logger=logger,)
        #     if erreur:
        #         return erreur
            

        # Dépôt des annexes sur DM + écriture NAS + Création Document
        if annexes :
            for fichier in annexes:

                erreur = reception_traiter_fichier_avis_dm(request, fichier=fichier, token=token, avis_id=avis_id, dossier_dm=doss_manif_sportive, root_folder=root_folder, nouvel_emplacement=doss_manif_sportive.emplacement, sous_dossier_cible="Annexes/Instruction/", nature_document="Annexe instructeur DM", description_document="Annexe envoyée sur Déclaration Manifestations.", message_erreur_metier="Le fichier a bien été transmis sur Déclaration Manifestations. Contactez le support si besoin.", logger=logger,)
                if erreur:
                    return erreur

        # messages.info(request, f"Les pièces jointes ont bien été ajoutées sur Déclaration Manifestations.")
        return redirect(request.META.get("HTTP_REFERER", "/"))
    
    except Exception as e :
        logger.error(f"[Dossier DM {manif_id} - Dépôt PJ] User {request.user}, Erreur lors du depot d'une PJ sur DM : {e}")
        return redirect_error(request, f"Une erreur est survenue lors du dépot des pièces jointes sur Déclaration Manifestations. Contactez le support si besoin.")
    











##################################################################
###       DECLARATION MANIFESTATIONS  DEPUIS LA RECEPTION      ###
##################################################################

# =========================
# ACCEPTER UN DOSSIER DM
# =========================
@login_required
@require_POST
def declaration_manifestations_accepter(request):

    logger.info("")
    num_dossier_dm = None

    # Récupération des données POST
    donnees, erreur = reception_lire_donnees_formulaire_avis_dm(request, acte_obligatoire=False, label_action="Avis favorable", logger=logger,)
    if erreur:
        return erreur

    prescriptions = donnees["prescriptions"]
    dossier_dm_id = donnees["dossier_dm_id"]
    fichiers = donnees["fichiers"]
    # acte = donnees["acte"]
    fichiers_a_traiter = donnees["fichiers_a_traiter"]
    dossier_dn_accepte_id = donnees["dossier_dn_accepte_id"]

    #######################################
    ###         VÉRIFICATIONS           ###
    #######################################
    erreur = reception_verifier_acces_et_fichiers_avis_dm(request, fichiers=fichiers_a_traiter, label_action="Avis favorable", logger=logger)
    if erreur:
        return erreur

    try:
        ###################################################
        ###     Récupération Avis et Dossier en base    ###
        ###################################################
        with transaction.atomic():
            contexte, erreur = reception_charger_contexte_avis_dm(request, dossier_dm_id=dossier_dm_id, nom_etape_cible="Accepté", label_action="Avis favorable", logger=logger,)
            if erreur:
                return erreur

            dossier_dm = contexte["dossier_dm"]
            avis_id = contexte["avis_id"]
            num_dossier_dm = contexte["num_dossier_dm"]

            # ------- RENDRE AVIS DM -------
            token = reception_rendre_avis_et_mettre_a_jour_dm(prescriptions=prescriptions, code_avis_dm=1, reponse_avis_bdd="favorable", contexte=contexte, logger=logger,)
        


        
        #########################################################################
        ###    DÉPLACEMENT DANS LE DOSSIER > Manifestations_sportives/2026    ###
        #########################################################################
        '''
        # --- Ancien et Nouvel emplacement ---
        paths, erreur = reception_preparer_emplacements_dossier_dm(request, dossier_dm=dossier_dm, sous_dossier_cible=None, label_action="Avis favorable", logger=logger,)
        if erreur:
            return erreur

        root_folder = paths["root_folder"]
        ancien_emplacement_dm = paths["ancien_emplacement_dm"]
        ancien_emplacement_full_path = paths["ancien_emplacement_full_path"]
        nouvel_emplacement = paths["nouvel_emplacement"]
        nouvel_emplacement_full_path = paths["nouvel_emplacement_full_path"]

        # Crée le dossier cible si besoin
        creer_dossier_sur_nas(os.path.join(nouvel_emplacement_full_path, "Annexes", "Declaration Manifestations"))
        creer_dossier_sur_nas(os.path.join(nouvel_emplacement_full_path, "Work"))
        # creer_dossier_sur_nas(os.path.join(nouvel_emplacement_full_path, "Actes"))


        # -----------------------------------
        # On déplace les docs du Dossier DM
        # -----------------------------------
        docs_deplaces = reception_deplacer_documents_dossier_dm(dossier_dm=dossier_dm, root_folder=root_folder, nouvel_emplacement=nouvel_emplacement, logger=logger,)
        logger.info(f"{docs_deplaces} fichiers déplacés -> {nouvel_emplacement}")


        # ----------------------------
        # On déplace le fichier carto
        # ----------------------------
        reception_copier_sous_dossier_dm(ancien_emplacement_full_path=ancien_emplacement_full_path, nouvel_emplacement_full_path=nouvel_emplacement_full_path, nom_sous_dossier="Carto", label_log="CARTO", logger=logger,)


        # ----------------------------
        # On déplace le dossier Work
        # ----------------------------
        reception_copier_sous_dossier_dm(ancien_emplacement_full_path=ancien_emplacement_full_path, nouvel_emplacement_full_path=nouvel_emplacement_full_path, nom_sous_dossier="Work", label_log="DOSSIER WORK", logger=logger,)


        # -----------------------------------------------------------------------------------
        # Si ancien dossier dans "0 - En attente d'un dossier Démarche Numérique", on le supprime
        # -----------------------------------------------------------------------------------
        # reception_supprimer_ancien_dossier_dm_si_necessaire(ancien_emplacement_dm=ancien_emplacement_dm, ancien_emplacement_full_path=ancien_emplacement_full_path, logger=logger,)


        # -----------------------------------
        # MAJ Dossier DM (emplacement) en BDD
        # -----------------------------------
        # reception_mettre_a_jour_emplacement_dossier_dm(dossier_dm=dossier_dm, nouvel_emplacement=nouvel_emplacement, logger=logger,)
        '''


        #########################################################
        ###        DÉPOSER LES PJ SUR DM ET SUR LE NAS        ###
        #########################################################
        logger.info(f"{len(fichiers_a_traiter)} pièce(s) jointe(s) à transmettre sur DM.")

        # if acte :
        #     erreur = reception_traiter_fichier_avis_dm(request, fichier=acte, token=token, avis_id=avis_id, dossier_dm=dossier_dm, root_folder=root_folder, nouvel_emplacement=nouvel_emplacement, sous_dossier_cible="Actes/", nature_document="Arrêté directeur", description_document="Acte d'acceptation envoyé sur Déclaration Manifestations.", message_erreur_metier="L'acte a bien été transmis sur Déclaration Manifestations. Contactez le support si besoin.", logger=logger,)
        #     if erreur:
        #         return erreur


        if fichiers :
            for fichier in fichiers:
                root_folder = os.environ.get("NAS_ROOT")
                nouvel_emplacement = dossier_dm.emplacement
                sous_dossier_cible = "Annexes/Instruction/"

                erreur = reception_traiter_fichier_avis_dm(request, fichier=fichier, token=token, avis_id=avis_id, dossier_dm=dossier_dm, root_folder=root_folder, nouvel_emplacement=nouvel_emplacement, sous_dossier_cible=sous_dossier_cible, nature_document="Annexe instructeur DM", description_document="Annexe envoyée sur Déclaration Manifestations.", message_erreur_metier="Le fichier a bien été transmis sur Déclaration Manifestations. Contactez le support si besoin.", logger=logger,)
                if erreur:
                    return erreur
                

        #######################################################
        ###             RELIER DOSSIER DM ET DN             ###
        #######################################################
        try :
            if dossier_dn_accepte_id :
                dossier_dn = Dossier.objects.get(id=dossier_dn_accepte_id)

                if archive_lier_dossier_dm_au_dossier_dn(dossier_dm=dossier_dm, dossier_dn=dossier_dn, logger_arg=logger) :
                    messages.info(request, f"Le dossier Déclaration Manifestations « {dossier_dm.nom_dossier} » a bien été accepté. La liaison avec le dossier Démarche Numérique {dossier_dn.numero} a bien été faite.")
                    return redirect(reverse("instruction_dossier", kwargs={"num_dossier": dossier_dn.numero}))
                
                else :
                    return redirect_error(request, "La liaison n'a pas pu être faite entre le dossier Déclaration Manifestations et Démarche Numérique. Contactez le support.")

            else :
                logger.error(f"[Dossier DM {num_dossier_dm} - Réception - Avis favorable] Utilisateur : {request.user}. "
                                f"Le dossier Démarche Numérique lié et accepté n'a pas été transmis par le formulaire : {e}")
                return redirect_error(request, "Le dossier Démarche Numérique lié et accepté n'a pas été transmis par le formulaire. ")

        except Exception as e :
            logger.error(f"[Dossier DM {num_dossier_dm} - Réception - Avis favorable] Utilisateur : {request.user}. "
                                f"Erreur lors de la liaison avec le dossier accepté Démarche Numérique (id = {dossier_dn_accepte_id}) : {e}")
            
            return redirect_error(request, "La liaison n'a pas pu être faite entre le dossier Déclaration Manifestations et Démarche Numérique. Contactez le support.")



    except Exception as e:
        identifiant_doss = f"{num_dossier_dm}" if num_dossier_dm else f"(id = {dossier_dm_id})"

        logger.error(f"[Dossier DM {identifiant_doss} - Réception - Avis favorable] Utilisateur : {request.user}. "
                        f"Erreur lors de la soumission d'un avis favorable sur DM : {e}")
            
        return redirect_error(request, f"Une erreur est survenue lors de la soumission de l'avis sur Déclaration Manifestations. Contactez le support si besoin.")





# =========================
# REFUSER UN DOSSIER DM
# =========================
@login_required
@require_POST
def declaration_manifestations_refuser(request):
    logger.info("")
    num_dossier_dm = None

    # Récupération des données POST
    donnees, erreur = reception_lire_donnees_formulaire_avis_dm(request, acte_obligatoire=False, label_action="Avis défavorable", logger=logger,)
    if erreur:
        return erreur

    prescriptions = donnees["prescriptions"]
    dossier_dm_id = donnees["dossier_dm_id"]
    fichiers = donnees["fichiers"]
    # acte = donnees["acte"]
    fichiers_a_traiter = donnees["fichiers_a_traiter"]
    dossier_dn_refuse_id = donnees["dossier_dn_refuse_id"]

    #######################################
    ###         VÉRIFICATIONS           ###
    #######################################
    erreur = reception_verifier_acces_et_fichiers_avis_dm(request, fichiers=fichiers_a_traiter, label_action="Avis défavorable", logger=logger,)
    if erreur:
        return erreur



    try:
        ###################################################
        ###     Récupération Avis et Dossier en base    ###
        ###################################################
        with transaction.atomic():
            contexte, erreur = reception_charger_contexte_avis_dm(request, dossier_dm_id=dossier_dm_id, nom_etape_cible="Refusé", label_action="Avis défavorable", logger=logger,)
            if erreur:
                return erreur

            dossier_dm = contexte["dossier_dm"]
            avis_id = contexte["avis_id"]
            num_dossier_dm = contexte["num_dossier_dm"]



            #################################################
            ###              RENDRE AVIS DM               ###
            #################################################
            token = reception_rendre_avis_et_mettre_a_jour_dm(prescriptions=prescriptions, code_avis_dm=2, reponse_avis_bdd="défavorable", contexte=contexte, logger=logger,)
        

        #########################################################################
        ###    DÉPLACEMENT DANS LE DOSSIER > Manifestations_sportives/2026    ###
        #########################################################################
        '''
        # Récupération des documents liés au dossier DM
        # docs_dm = Document.objects.filter(dossiermanifsportivedocument__id_dossier_manif_sportive=dossier_dm)

        # ----------------------------
        # Ancien et Nouvel emplacement
        # ----------------------------
        paths, erreur = reception_preparer_emplacements_dossier_dm(request, dossier_dm=dossier_dm, sous_dossier_cible=None, label_action="Avis défavorable", logger=logger,)
        if erreur:
            return erreur

        root_folder = paths["root_folder"]
        ancien_emplacement_dm = paths["ancien_emplacement_dm"]
        ancien_emplacement_full_path = paths["ancien_emplacement_full_path"]
        nouvel_emplacement = paths["nouvel_emplacement"]
        nouvel_emplacement_full_path = paths["nouvel_emplacement_full_path"]


        # Crée le dossier cible si besoin
        creer_dossier_sur_nas(os.path.join(nouvel_emplacement_full_path, "Annexes", "Declaration Manifestations"))
        creer_dossier_sur_nas(os.path.join(nouvel_emplacement_full_path, "Work"))
        # creer_dossier_sur_nas(os.path.join(nouvel_emplacement_full_path, "Actes"))


        # -----------------------------------
        # On déplace les docs du Dossier DM
        # -----------------------------------
        docs_deplaces = reception_deplacer_documents_dossier_dm(dossier_dm=dossier_dm, root_folder=root_folder, nouvel_emplacement=nouvel_emplacement, logger=logger,)
        logger.info(f"{docs_deplaces} fichiers déplacés -> {nouvel_emplacement}")


        # ----------------------------
        # On déplace le fichier carto
        # ----------------------------
        reception_copier_sous_dossier_dm(ancien_emplacement_full_path=ancien_emplacement_full_path, nouvel_emplacement_full_path=nouvel_emplacement_full_path, nom_sous_dossier="Carto", label_log="CARTO", logger=logger,)


        # ----------------------------
        # On déplace le dossier Work
        # ----------------------------
        reception_copier_sous_dossier_dm(ancien_emplacement_full_path=ancien_emplacement_full_path, nouvel_emplacement_full_path=nouvel_emplacement_full_path, nom_sous_dossier="Work", label_log="DOSSIER WORK", logger=logger,)


        # -----------------------------------------------------------------------------------
        # Si ancien dossier dans "0 - En attente d'un dossier Démarche Numérique", on le supprime
        # -----------------------------------------------------------------------------------
        # reception_supprimer_ancien_dossier_dm_si_necessaire(ancien_emplacement_dm=ancien_emplacement_dm, ancien_emplacement_full_path=ancien_emplacement_full_path, logger=logger,)


        # -----------------------------------
        # MAJ Dossier DM (emplacement) en BDD
        # -----------------------------------
        # reception_mettre_a_jour_emplacement_dossier_dm(dossier_dm=dossier_dm, nouvel_emplacement=nouvel_emplacement, logger=logger,)
        '''


        #########################################################
        ###        DÉPOSER LES PJ SUR DM ET SUR LE NAS        ###
        #########################################################
        logger.info(f"{len(fichiers_a_traiter)} pièce(s) jointe(s) à transmettre sur DM.")


        if fichiers :
            root_folder = os.environ.get("NAS_ROOT")
            nouvel_emplacement = dossier_dm.emplacement
            sous_dossier_cible = "Annexes/Instruction/"
            for fichier in fichiers:

                erreur = reception_traiter_fichier_avis_dm(request, fichier=fichier, token=token, avis_id=avis_id, dossier_dm=dossier_dm, root_folder=root_folder, nouvel_emplacement=nouvel_emplacement, sous_dossier_cible=sous_dossier_cible, nature_document="Annexe instructeur DM", description_document="Annexe envoyée sur Déclaration Manifestations.", message_erreur_metier="Le fichier a bien été transmis sur Déclaration Manifestations. Contactez le support si besoin.", logger=logger,)
                if erreur:
                    return erreur
                
                

            #######################################################
            ###             RELIER DOSSIER DM ET DN             ###
            #######################################################
            try :
                if dossier_dn_refuse_id :
                    dossier_dn = Dossier.objects.get(id=dossier_dn_refuse_id)

                    if archive_lier_dossier_dm_au_dossier_dn(dossier_dm=dossier_dm, dossier_dn=dossier_dn, logger_arg=logger) :
                        messages.info(request, f"Le dossier Déclaration Manifestations « {dossier_dm.nom_dossier} » a bien été refusé. La liaison avec le dossier Démarche Numérique {dossier_dn.numero} a bien été faite.")
                        return redirect(reverse("instruction_dossier", kwargs={"num_dossier": dossier_dn.numero}))
                    
                    else :
                        return redirect_error(request, "La liaison n'a pas pu être faite entre le dossier Déclaration Manifestations et Démarche Numérique. Contactez le support.")

                else :
                    logger.error(f"[Dossier DM {num_dossier_dm} - Réception - Avis défavorable] Utilisateur : {request.user}. "
                                    f"Le dossier Démarche Numérique lié et refusé n'a pas été transmis par le formulaire : {e}")
                    return redirect_error(request, "Le dossier Démarche Numérique lié et refusé n'a pas été transmis par le formulaire. ")

            except Exception as e :
                logger.error(f"[Dossier DM {num_dossier_dm} - Réception - Avis défavorable] Utilisateur : {request.user}. "
                                    f"Erreur lors de la liaison avec le dossier refusé Démarche Numérique (id = {dossier_dn_refuse_id}) : {e}")
                
                return redirect_error(request, "La liaison n'a pas pu être faite entre le dossier Déclaration Manifestations et Démarche Numérique. Contactez le support.")



        return redirect(request.META.get("HTTP_REFERER", "/"))

    except Exception as e:
        identifiant_doss = f"{num_dossier_dm}" if num_dossier_dm else f"(id = {dossier_dm_id})"

        logger.error(f"[Dossier DM {identifiant_doss} - Réception - Avis défavorable] Utilisateur : {request.user}. "
                        f"Erreur lors de la soumission d'un avis défavorable sur DM : {e}")
            
        return redirect_error(request, f"Une erreur est survenue lors de la soumission de l'avis sur Déclaration Manifestations. Contactez le support si besoin.")





# =========================
# DOSSIER DM NON SOUMIS
# =========================
@login_required
@require_POST
def declaration_manifestations_non_soumis(request):

    logger.info("")
    num_dossier_dm = None

    # Récupération des données POST
    donnees, erreur = reception_lire_donnees_formulaire_avis_dm(request, acte_obligatoire=False, label_action="Non Concerné", logger=logger,)
    if erreur:
        return erreur

    prescriptions = donnees["prescriptions"]
    dossier_dm_id = donnees["dossier_dm_id"]
    fichiers = donnees["fichiers"]


    #######################################
    ###         VÉRIFICATIONS           ###
    #######################################
    erreur = reception_verifier_acces_et_fichiers_avis_dm(request, fichiers=fichiers, label_action="Non Concerné", logger=logger,)
    if erreur:
        return erreur


    try:
        ###################################################
        ###     Récupération Avis et Dossier en base    ###
        ###################################################
        with transaction.atomic():
        
            contexte, erreur = reception_charger_contexte_avis_dm(request, dossier_dm_id=dossier_dm_id, nom_etape_cible="Non soumis à autorisation", label_action="Non Concerné", logger=logger,)
            if erreur:
                return erreur

            dossier_dm = contexte["dossier_dm"]
            avis_id = contexte["avis_id"]
            num_dossier_dm = contexte["num_dossier_dm"]


            #################################################
            ###              RENDRE AVIS DM               ###
            #################################################
            token = reception_rendre_avis_et_mettre_a_jour_dm(prescriptions=prescriptions, code_avis_dm=3, reponse_avis_bdd="non concerné", contexte=contexte, logger=logger,)


        ##################################################################
        ###        DÉPLACEMENT DANS LE DOSSIER > 1 - Hors coeur        ###
        ##################################################################

        '''
        # Récupération des documents liés au dossier DM
        # docs_dm = Document.objects.filter(dossiermanifsportivedocument__id_dossier_manif_sportive=dossier_dm)

        # ----------------------------
        # Ancien et Nouvel emplacement
        # ----------------------------
        paths, erreur = reception_preparer_emplacements_dossier_dm(request, dossier_dm=dossier_dm, sous_dossier_cible="1 - Hors coeur", label_action="Non Concerné", logger=logger,)
        if erreur:
            return erreur

        root_folder = paths["root_folder"]
        ancien_emplacement_dm = paths["ancien_emplacement_dm"]
        ancien_emplacement_full_path = paths["ancien_emplacement_full_path"]
        nouvel_emplacement = paths["nouvel_emplacement"]
        nouvel_emplacement_full_path = paths["nouvel_emplacement_full_path"]


        # Crée le dossier cible si besoin
        creer_dossier_sur_nas(os.path.join(nouvel_emplacement_full_path, "Annexes", "Declaration Manifestations"))
        creer_dossier_sur_nas(os.path.join(nouvel_emplacement_full_path, "Work"))


        # -----------------------------------
        # On déplace les docs du Dossier DM
        # -----------------------------------
        docs_deplaces = reception_deplacer_documents_dossier_dm(dossier_dm=dossier_dm, root_folder=root_folder, nouvel_emplacement=nouvel_emplacement, logger=logger,)
        logger.info(f"{docs_deplaces} fichiers déplacés -> {nouvel_emplacement}")


        # ----------------------------
        # On déplace le fichier carto
        # ----------------------------
        reception_copier_sous_dossier_dm(ancien_emplacement_full_path=ancien_emplacement_full_path, nouvel_emplacement_full_path=nouvel_emplacement_full_path, nom_sous_dossier="Carto", label_log="CARTO", logger=logger,)


        # ----------------------------
        # On déplace le dossier Work
        # ----------------------------
        reception_copier_sous_dossier_dm(ancien_emplacement_full_path=ancien_emplacement_full_path, nouvel_emplacement_full_path=nouvel_emplacement_full_path, nom_sous_dossier="Work", label_log="DOSSIER WORK", logger=logger,)



        # -----------------------------------------------------------------------------------
        # Si ancien dossier dans "0 - En attente d'un dossier Démarche Numérique", on le supprime
        # -----------------------------------------------------------------------------------
        # reception_supprimer_ancien_dossier_dm_si_necessaire(ancien_emplacement_dm=ancien_emplacement_dm, ancien_emplacement_full_path=ancien_emplacement_full_path, logger=logger,)


        # -----------------------------------
        # MAJ Dossier DM (emplacement) en BDD
        # -----------------------------------
        # reception_mettre_a_jour_emplacement_dossier_dm(dossier_dm=dossier_dm, nouvel_emplacement=nouvel_emplacement, logger=logger,)
        '''
  

        #########################################################
        ###        DÉPOSER LES PJ SUR DM ET SUR LE NAS        ###
        #########################################################

        if fichiers :
            logger.info(f"{len(fichiers)} pièce(s) jointe(s) à transmettre sur DM.")

            root_folder = os.environ.get("NAS_ROOT")
            nouvel_emplacement = dossier_dm.emplacement
            sous_dossier_cible = "Annexes/Instruction/"
  
            for fichier in fichiers:

                erreur = reception_traiter_fichier_avis_dm(request, fichier=fichier, token=token, avis_id=avis_id, dossier_dm=dossier_dm, root_folder=root_folder, nouvel_emplacement=nouvel_emplacement, sous_dossier_cible=sous_dossier_cible, nature_document="Annexe instructeur DM", description_document="Annexe envoyée sur Déclaration Manifestations.", message_erreur_metier="Le fichier a bien été transmis sur Déclaration Manifestations. Contactez le support si besoin.", logger=logger,)
                if erreur:
                    return erreur
                

            """ ENVOI MAIL A AJOUTER SI BESOIN """
            # erreur = envoyer_notif_mail_dm(
            #     request=request,
            #     dossier=dossier,
            #     document=document,
            #     nature_document=nature_document,
            #     logger=logger,
            #     type_mail="Envoi de l'acte",
            #     libelle_log="Envoi acte",
            #     template_name="mail_en_copie",
            # )
            # if erreur:
            #     return erreur
        
        

        # Redirection
        messages.info(request, f"Le dossier Déclaration Manifestations « {dossier_dm.nom_dossier} » a bien été classé comme non soumis à autorisations.")
        return redirect(reverse("dossier_manif_sportive_sans_ds_archive", kwargs={"numero": num_dossier_dm}))
    
        # return redirect(request.META.get("HTTP_REFERER", "/"))

    except Exception as e:
        identifiant_doss = f"{num_dossier_dm}" if num_dossier_dm else f"(id = {dossier_dm_id})"

        logger.error(f"[Dossier DM {identifiant_doss} - Réception - Non Concerné] Utilisateur : {request.user}. "
                        f"Erreur lors de la soumission d'un avis 'Non Concerné' sur DM : {e}")
            
        return redirect_error(request, f"Une erreur est survenue lors de la soumission de l'avis sur Déclaration Manifestations. Contactez le support si besoin.")





# =========================
# DOSSIER DM NON REPONDU
# =========================
@login_required
@require_POST
def declaration_manifestations_non_repondu(request):

    logger.info("")
    num_dossier_dm = None

    # Récupération des données POST
    donnees, erreur = reception_lire_donnees_formulaire_avis_dm(request, acte_obligatoire=False, label_action="Non Répondu", logger=logger,)
    if erreur:
        return erreur

    prescriptions = donnees["prescriptions"]
    dossier_dm_id = donnees["dossier_dm_id"]
    fichiers = donnees["fichiers"]


    # VÉRIFICATIONS
    erreur = reception_verifier_acces_et_fichiers_avis_dm(request, fichiers=fichiers, label_action="Non Répondu", logger=logger,)
    if erreur:
        return erreur


    try:
        # Récupération Avis et Dossier en base
        with transaction.atomic():
        
            contexte, erreur = reception_charger_contexte_avis_dm(request, dossier_dm_id=dossier_dm_id, nom_etape_cible="Non répondu", label_action="Non Répondu", logger=logger,)
            if erreur:
                return erreur

            dossier_dm = contexte["dossier_dm"]
            avis_id = contexte["avis_id"]
            num_dossier_dm = contexte["num_dossier_dm"]

            # RENDRE AVIS DM
            token = reception_rendre_avis_et_mettre_a_jour_dm(prescriptions=prescriptions, code_avis_dm=0, reponse_avis_bdd="non répondu", contexte=contexte, logger=logger,)


        # ---------- DÉPLACEMENT DANS LE DOSSIER > 2 - Non répondu ----------
        '''
        # Ancien et Nouvel emplacement
        paths, erreur = reception_preparer_emplacements_dossier_dm(request, dossier_dm=dossier_dm, sous_dossier_cible="2 - Non répondu", label_action="Non Répondu", logger=logger,)
        if erreur:
            return erreur

        root_folder = paths["root_folder"]
        ancien_emplacement_dm = paths["ancien_emplacement_dm"]
        ancien_emplacement_full_path = paths["ancien_emplacement_full_path"]
        nouvel_emplacement = paths["nouvel_emplacement"]
        nouvel_emplacement_full_path = paths["nouvel_emplacement_full_path"]


        # Crée le dossier cible si besoin
        creer_dossier_sur_nas(os.path.join(nouvel_emplacement_full_path, "Annexes", "Declaration Manifestations"))
        creer_dossier_sur_nas(os.path.join(nouvel_emplacement_full_path, "Work"))


        # On déplace les docs du Dossier DM
        docs_deplaces = reception_deplacer_documents_dossier_dm(dossier_dm=dossier_dm, root_folder=root_folder, nouvel_emplacement=nouvel_emplacement, logger=logger,)
        logger.info(f"{docs_deplaces} fichiers déplacés -> {nouvel_emplacement}")


        # On déplace le fichier carto
        reception_copier_sous_dossier_dm(ancien_emplacement_full_path=ancien_emplacement_full_path, nouvel_emplacement_full_path=nouvel_emplacement_full_path, nom_sous_dossier="Carto", label_log="CARTO", logger=logger,)


        # On déplace le dossier Work
        reception_copier_sous_dossier_dm(ancien_emplacement_full_path=ancien_emplacement_full_path, nouvel_emplacement_full_path=nouvel_emplacement_full_path, nom_sous_dossier="Work", label_log="DOSSIER WORK", logger=logger,)


        # Si ancien dossier dans "0 - En attente d'un dossier Démarche Numérique", on le supprime
        reception_supprimer_ancien_dossier_dm_si_necessaire(ancien_emplacement_dm=ancien_emplacement_dm, ancien_emplacement_full_path=ancien_emplacement_full_path, logger=logger,)


        # MAJ Dossier DM (emplacement) en BDD
        reception_mettre_a_jour_emplacement_dossier_dm(dossier_dm=dossier_dm, nouvel_emplacement=nouvel_emplacement, logger=logger,)
        '''



        """ ENVOI MAIL A AJOUTER SI BESOIN """
        # erreur = envoyer_notif_mail_dm(
            #     request=request,
            #     dossier=dossier,
            #     document=document,
            #     nature_document=nature_document,
            #     logger=logger,
            #     type_mail="Envoi de l'acte",
            #     libelle_log="Envoi acte",
            #     template_name="mail_en_copie",
            # )
            # if erreur:
            #     return erreur



        # Redirection
        messages.info(request, f"Le dossier Déclaration Manifestations « {dossier_dm.nom_dossier} » a bien été archivé.")
        return redirect(reverse("dossier_manif_sportive_sans_ds_archive", kwargs={"numero": num_dossier_dm}))
    
        # return redirect(request.META.get("HTTP_REFERER", "/"))

    except Exception as e:
        identifiant_doss = f"{num_dossier_dm}" if num_dossier_dm else f"(id = {dossier_dm_id})"

        logger.error(f"[Dossier DM {identifiant_doss} - Réception - Non Répondu] Utilisateur : {request.user}. "
                        f"Erreur lors de la soumission d'un avis 'Non Répondu' sur DM : {e}")
            
        return redirect_error(request, f"Une erreur est survenue lors de la soumission de l'avis sur Déclaration Manifestations. Contactez le support si besoin.")





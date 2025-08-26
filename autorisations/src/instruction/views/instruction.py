import ast
from datetime import date
import json
import logging
import os
from django.db.models import Q, Count
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib.auth.decorators import login_required
from django.urls import reverse
from autorisations.models.models_instruction import Demarche, Dossier, DossierAction, DossierManifestationLiaison, EtapeDossier, EtatDossier, Message
from autorisations.models.models_utilisateurs import ContactExterne, DossierBeneficiaire, DossierInstructeur, DossierInterlocuteur, DossierRelecteurJuridique, DossierRelecteurQualite, DossierSignataire, DossierValideur, EmailOutbox, Groupeinstructeur, Instructeur
from autorisations import settings
from DS.graphql_client import GraphQLClient
from autorisations.models.models_documents import Document, DocumentFormat, DocumentNature, DocumentStatut, DossierDocument
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
from instruction.utils import dossiers_action_a_faire, enregistrer_action, format_etat_dossier
from autorisations.models.models_instruction import DossierNote
from django.utils import timezone
from datetime import datetime
from django.db.models import Min
from django.views.decorators.http import require_POST
from django.http import Http404
from django.contrib import messages
from django.contrib.auth.models import Group
from django.contrib.auth import get_user_model


logger = logging.getLogger('ORM_DJANGO')
loggerSynchro = logging.getLogger('SYNCHRONISATION')
loggerDM = logging.getLogger("API_DM")

def get_dossier_counts(demarche, etape_a_affecter, etapes_instruction, etapes_termines, current_year, groupes_user=None, instructeur=None):
    ids_etapes_termines = list(etapes_termines.values_list("id", flat=True))
    ids_etapes_instruction = list(etapes_instruction.values_list("id", flat=True))

    query_suivis = Dossier.objects.filter(id_demarche=demarche, id_etape_dossier__in=ids_etapes_instruction)
    query_reception = Dossier.objects.filter(id_demarche=demarche, id_etape_dossier=etape_a_affecter)
    query_traités = Dossier.objects.filter(id_demarche=demarche, id_etape_dossier__in=ids_etapes_termines, date_fin_instruction__year=current_year)

    
    dossiers_query_tous = (
        Dossier.objects.filter(
            id_demarche=demarche,
            id_etape_dossier__in=etapes_instruction,
        )
        .filter(
            Q(dossierinstructeur__id_instructeur=instructeur) |
            Q(dossierrelecteurqualite__id_instructeur=instructeur) |
            Q(dossiervalideur__id_instructeur=instructeur) |
            Q(dossierrelecteurjuridique__id_instructeur=instructeur) |
            Q(dossiersignataire__id_instructeur=instructeur)
        )
        .distinct()
    )


    dossiers_actions = dossiers_action_a_faire(dossiers_query_tous, instructeur).count()



    return {
        "demarche": demarche,
        "nb_reception": query_reception.count(),
        "nb_suivis": query_suivis.count(),
        "nb_traites": query_traités.count(),
        "nb_suivis_user": dossiers_actions
    }


@login_required
def accueil(request):
    etapes_instruction = EtapeDossier.objects.exclude(etape__in=["Non soumis à autorisation", "Refusé", "Accepté", "À affecter"])
    etapes_termines = EtapeDossier.objects.filter(etape__in=["Non soumis à autorisation", "Refusé", "Accepté"])
    etape_a_affecter = EtapeDossier.objects.get(etape="À affecter")

    current_year = date.today().year
    demarches = Demarche.objects.all().order_by("titre")

    # ✅ Sécurisation
    groupes_user = []
    instructeur = Instructeur.objects.get(email=request.user.email)
    if instructeur:
        groupes_user = list(instructeur.groupeinstructeurinstructeur_set.values_list("id_groupeinstructeur_id", flat=True))

    dossier_infos = [
        get_dossier_counts(d, etape_a_affecter, etapes_instruction, etapes_termines, current_year, groupes_user, instructeur)
        for d in demarches
    ]

    return render(request, 'instruction/instruction.html', {"dossier_infos": dossier_infos})



@login_required
def mesdossiers(request):

    instructeur = Instructeur.objects.filter(id_agent_autorisations__mail_1=request.user.email).first()

    if not instructeur:
        messages.error(request, f"❌ L'instructeur.rice {request.user} est introuvable.")
        return redirect(request.META.get("HTTP_REFERER", "/"))
    
    # Étapes terminées
    etapes_termines = EtapeDossier.objects.filter(
        etape__in=["Non soumis à autorisation", "Refusé", "Accepté"]
    )

    # Dossiers où l’utilisateur intervient
    base_query = (
        Dossier.objects.filter(
            Q(dossierinstructeur__id_instructeur=instructeur) |
            Q(dossierrelecteurqualite__id_instructeur=instructeur) |
            Q(dossiervalideur__id_instructeur=instructeur) |
            Q(dossierrelecteurjuridique__id_instructeur=instructeur) |
            Q(dossiersignataire__id_instructeur=instructeur)
        )
        .distinct()
    )

    # Liste avec exclusion des étapes terminées
    dossiers = base_query.exclude(id_etape_dossier__in=etapes_termines)
    # Liste complète (y compris dossiers terminés)
    dossiers_tous = base_query
    dossier_action_a_faire = dossiers_action_a_faire(dossiers_tous, instructeur)

    dossiers = dossiers.union(dossier_action_a_faire)


    dossiers_par_demarche = {}

    for dossier in dossiers:
        # Récupérer le bénéficiaire
        interlocuteur = DossierInterlocuteur.objects.filter(id_dossier=dossier).first()
        beneficiaire = None
        if interlocuteur:
            db = DossierBeneficiaire.objects.filter(id_dossier_interlocuteur=interlocuteur).select_related("id_beneficiaire").first()
            if db:
                beneficiaire = db.id_beneficiaire

        # Messages non lus
        nb_messages_non_lus = Message.objects.filter(
            id_dossier=dossier,
            lu=False
        ).exclude(
            email_emetteur='contact@demarches-simplifiees.fr'
        ).exclude(
            email_emetteur__endswith='reunion-parcnational.fr'
        ).count()

        # Déterminer mon rôle
        if DossierInstructeur.objects.filter(id_dossier=dossier, id_instructeur=instructeur).exists():
            role = "Instructeur.rice"
        elif DossierRelecteurQualite.objects.filter(id_dossier=dossier, id_instructeur=instructeur).exists():
            role = "Relecteur.rice qualité"
        elif DossierValideur.objects.filter(id_dossier=dossier, id_instructeur=instructeur).exists():
            role = "Valideur.se"
        elif DossierRelecteurJuridique.objects.filter(id_dossier=dossier, id_instructeur=instructeur).exists():
            role = "Relecteur.rice juridique"
        elif DossierSignataire.objects.filter(id_dossier=dossier, id_instructeur=instructeur).exists():
            role = "Signataire"
        else:
            role = "Inconnu"

        # Structurer les infos
        dossiers_par_demarche.setdefault(dossier.id_demarche.titre, []).append({
            "nom_dossier": dossier.nom_dossier,
            "numero": dossier.numero,
            "beneficiaire": f"{beneficiaire.prenom} {beneficiaire.nom}" if beneficiaire else "N/A",
            "date_depot": dossier.date_depot,
            "mon_role": role,
            "etape": dossier.id_etape_dossier.etape if dossier.id_etape_dossier else "Non défini",
            "nb_messages_non_lus": nb_messages_non_lus,
            "action_a_faire": True if dossier in dossier_action_a_faire else False
        })

    return render(request, "instruction/mesdossiers.html", {
        "dossiers_par_demarche": dossiers_par_demarche,
    })





@login_required
def instruction_demarche(request, num_demarche):

    demarche = get_object_or_404(Demarche, numero=num_demarche)

    etapes_sans_a_affecter = EtapeDossier.objects.exclude(etape="À affecter")
 
    etapes_termines = EtapeDossier.objects.filter(etape__in=["Non soumis à autorisation", "Refusé", "Accepté"])
    ids_etapes_termines = list(etapes_termines.values_list("id", flat=True))

    mes_dossiers = request.GET.get("mes_dossiers", "1")

    instructeur = Instructeur.objects.filter(id_agent_autorisations__mail_1=request.user.email).first()


    dossiers_query_tous = (
            Dossier.objects.filter(
                Q(dossierinstructeur__id_instructeur=instructeur) |
                Q(dossierrelecteurqualite__id_instructeur=instructeur) |
                Q(dossiervalideur__id_instructeur=instructeur) |
                Q(dossierrelecteurjuridique__id_instructeur=instructeur) |
                Q(dossiersignataire__id_instructeur=instructeur)
            )
            .exclude(id_etape_dossier__etape = 'À affecter')
            .distinct()
        )

    dossiers_actions = dossiers_action_a_faire(dossiers_query_tous, instructeur)

    # Filtre 'Mes dossiers' si case cochée
    if mes_dossiers == "1":
        dossiers_query = dossiers_query_tous.filter(id_demarche=demarche.id).exclude(id_etape_dossier__etape__in=["Accepté", "Refusé", "Non soumis à autorisation"])

    # Si case pas cochée
    else :
        dossiers_query = Dossier.objects.filter(
                id_etape_dossier__in=etapes_sans_a_affecter,
                id_demarche=demarche.id
        ).exclude(
            id_etape_dossier__in=ids_etapes_termines
        )

   
    dossiers = dossiers_query.select_related("id_groupeinstructeur").order_by("date_depot")

    dossier_infos = []

    for dossier in dossiers:

        interlocuteur = DossierInterlocuteur.objects.filter(id_dossier=dossier).select_related("id_demandeur_intermediaire").first()

        # Messages non lus
        nb_messages_non_lus = Message.objects.filter(
            id_dossier=dossier,
            lu=False
        ).exclude(
            email_emetteur='contact@demarches-simplifiees.fr'
        ).exclude(
            email_emetteur__endswith='reunion-parcnational.fr'
        ).count()

        beneficiaire = None
        if interlocuteur:
            dossier_beneficiaire = DossierBeneficiaire.objects.filter(id_dossier_interlocuteur=interlocuteur).select_related("id_beneficiaire").first()
            if dossier_beneficiaire:
                beneficiaire = dossier_beneficiaire.id_beneficiaire

        dossier_infos.append({
            "nom_dossier": dossier.nom_dossier,
            # "type": dossier.id_dossier_type.type if dossier.id_dossier_type else "N/A",
            "numero": dossier.numero,
            "beneficiaire": f"{beneficiaire.prenom} {beneficiaire.nom}" if beneficiaire else "N/A",
            "date_depot": dossier.date_depot,
            "groupe": dossier.id_groupeinstructeur.nom if dossier.id_groupeinstructeur else "N/A",
            "etape": dossier.id_etape_dossier.etape if dossier.id_etape_dossier.etape else "Non défini",
            "nb_messages_non_lus": nb_messages_non_lus,
            "action_a_faire": True if dossier in dossiers_actions else False
        })


    #  Archives
    annee_selectionnee = int(request.GET.get("annee", datetime.now().year))

    min_depot = Dossier.objects.filter(id_demarche=demarche).aggregate(min_date=Min("date_depot"))["min_date"]
    annee_min = min_depot.year if min_depot else annee_selectionnee
    annees_disponibles = list(range(annee_min, datetime.now().year + 1))

    dossiers_archives = Dossier.objects.filter(
        id_etape_dossier__in=etapes_termines,
        id_demarche=demarche,
        date_depot__year=annee_selectionnee
    ).select_related("id_groupeinstructeur").order_by("-date_depot")

    dossier_archives_infos = []

    for dossier in dossiers_archives:
        interlocuteur = DossierInterlocuteur.objects.filter(id_dossier=dossier).select_related("id_demandeur_intermediaire").first()

        beneficiaire = None
        if interlocuteur:
            dossier_beneficiaire = DossierBeneficiaire.objects.filter(id_dossier_interlocuteur=interlocuteur).select_related("id_beneficiaire").first()
            if dossier_beneficiaire:
                beneficiaire = dossier_beneficiaire.id_beneficiaire


        nb_messages_non_lus = Message.objects.filter(
            id_dossier=dossier,
            lu=False
        ).exclude(
            email_emetteur='contact@demarches-simplifiees.fr'
        ).exclude(
            email_emetteur__endswith='reunion-parcnational.fr'
        ).count()

        dossier_archives_infos.append({
            "nom_dossier": dossier.nom_dossier,
            "numero": dossier.numero,
            "beneficiaire": f"{beneficiaire.prenom} {beneficiaire.nom}" if beneficiaire else "N/A",
            "date_depot": dossier.date_depot,
            "groupe": dossier.id_groupeinstructeur.nom if dossier.id_groupeinstructeur else "N/A",
            "etape": dossier.id_etape_dossier.etape if dossier.id_etape_dossier else "Non défini",
            "nb_messages_non_lus": nb_messages_non_lus,
            "action_a_faire": True if dossier in dossiers_actions else False,
        })

        dossier_archives_infos.sort(key=lambda d: (not d["action_a_faire"], -d["nb_messages_non_lus"]))


    return render(request, "instruction/instruction_demarche.html", {
    "demarche": demarche,
    "dossiers": dossier_infos,
    "annees_disponibles": annees_disponibles,
    "annee_selectionnee": annee_selectionnee,
    "dossiers_archives": dossier_archives_infos,
})



@login_required
def instruction_dossier(request, num_dossier):

    dossier = get_object_or_404(Dossier, numero=num_dossier)
    demarche = dossier.id_demarche

    # Charger le fond de carte GeoJSON (une seule fois)
    fond_coeur_de_parc = os.path.join(settings.BASE_DIR, "instruction/static/instruction/carto/fond_coeur_de_parc.geojson")
    with open(fond_coeur_de_parc, encoding="utf-8") as f:
        fond_coeur_de_parc = json.load(f)


    fond_aire_adhesion = os.path.join(settings.BASE_DIR, "instruction/static/instruction/carto/aire_adhesion.geojson")
    with open(fond_aire_adhesion, encoding="utf-8") as f:
        fond_aire_adhesion = json.load(f)

    fond_mafate = os.path.join(settings.BASE_DIR, "instruction/static/instruction/carto/COT_MAFATE.geojson")
    with open(fond_mafate, encoding="utf-8") as f:
        fond_mafate = json.load(f)

    nb_cartes = 0
    champs_prepares = []
    for champ in dossier.dossierchamp_set.select_related("id_champ__id_champ_type").order_by("ordre"):

        ct = champ.id_champ.id_champ_type.type
        nom = champ.id_champ.nom
        if nom.endswith(":"):
            nom = nom.rstrip(":").strip()


        # Ignorer les champs de type explication
        if ct == "explication": continue

        # Exclure seulement les checkbox qui commencent par "Je certifie" ou "J'atteste"
        if ct == "checkbox" and (nom.startswith("Je certifie") or nom.startswith("J'atteste")): continue

        # Traduction spécifique pour les champs Oui/Non
        if ct == "yes_no":
            val = (champ.valeur or "").strip().lower()
            champs_prepares.append({"type": "champ", "nom": nom, "valeur": "Oui" if val == "true" else "Non" if val == "false" else "Non renseigné"})

        elif ct == "carte" and champ.geometrie:
            nb_cartes += 1
            geojson_source = champ.geometrie_modif or champ.geometrie
            champs_prepares.append({"type": "carte", "nom": nom, "geojson": json.dumps(geojson_source), "id":champ.id})

        elif ct == "header_section":
            champs_prepares.append({"type": "header", "titre": nom})

        elif ct == "piece_justificative":
            if champ.id_document :
                emplacement_doc= champ.id_document.emplacement
                # emplacement_doc = os.path.join(os.environ.get("ROOT_FOLDER"), champ.id_document.emplacement, champ.id_document.titre)
                champs_prepares.append({"type": "piece_justificative", "nom": nom, "url": champ.id_document.url_ds, "titre_doc": champ.id_document.titre, "emplacement_doc": emplacement_doc})
            else : 
                champs_prepares.append({"type": "piece_justificative", "nom": nom, "titre_doc": "ERROR PARSING URL DS"})
            # champs_prepares.append({"type": "piece_justificative", "nom": nom, "url": champ.id_document.url_ds, "titre_doc": champ.id_document.titre})

        elif ct == "repetition":
            repetitions = []

            try:
                valeur = ast.literal_eval(champ.valeur) if isinstance(champ.valeur, str) else champ.valeur or {}
            except Exception as e:
                valeur = {}

            for liste in (valeur or {}).values():
                bloc = []
                for item in liste:
                    bloc.append({"nom": item.get("nom"), "valeur": item.get("valeur")})
                repetitions.append(bloc)

            champs_prepares.append({
                "type": "repetition",
                "nom": nom,
                "valeur": repetitions or "Non renseigné"
            })
            
        elif ct == "drop_down_list":
            
            if nom == 'Choix de la méthode pour localiser le projet' and 'Remplir le module de cartographie' not in champ.valeur :
                geojson_source = champ.geometrie_modif or champ.geometrie

                if not (geojson_source) :

                    champs_prepares.append({"type": "drop_down_list", "nom": nom, "valeur": champ.valeur, "geometrie_a_saisir": 'oui', "geojson": json.dumps({}), "id":champ.id})
                else :

                    champs_prepares.append({"type": "drop_down_list", "nom": nom, "valeur": champ.valeur, "geometrie_a_saisir": 'non', "geojson": json.dumps(geojson_source), "id":champ.id})

            else :
                champs_prepares.append({"type": "drop_down_list", "nom": nom,"valeur": champ.valeur, "geometrie_a_saisir": 'non pas concerné'})
        

        else:
            champs_prepares.append({"type": "champ", "nom": nom, "valeur": champ.valeur or "Non renseigné"})

    #Récupérer tous les noms de groupes instructeurs pour la démarche en question
    groupes_instructeurs = Groupeinstructeur.objects.filter(groupeinstructeurdemarche__id_demarche=dossier.id_demarche).order_by("nom")

    membres_groupe = []
    if dossier.id_groupeinstructeur:
        membres_groupe = dossier.id_groupeinstructeur.groupeinstructeurinstructeur_set.select_related("id_instructeur__id_agent_autorisations").values_list("id_instructeur", flat=False)
        membres_groupe = [m.id_instructeur for m in dossier.id_groupeinstructeur.groupeinstructeurinstructeur_set.select_related("id_instructeur__id_agent_autorisations")]

    etapes_possibles = EtapeDossier.objects.all().order_by("etape")
    etape_actuelle = dossier.id_etape_dossier if hasattr(dossier, "id_etape_dossier") else None

    instructeurs_dossier = set(
        DossierInstructeur.objects.filter(id_dossier=dossier)
        .values_list("id_instructeur_id", flat=True)
    )


    '''
        ### pour savoir si on affiche le bouton 'Se déclarer comme l'instructeur du dossier'
    '''
    # Identifier l'instructeur lié à l'utilisateur connecté
    instructeur_connecte = (
        Instructeur.objects
        .filter(id_agent_autorisations__mail_1=request.user.email)
        .select_related("id_agent_autorisations")
        .first()
    )

    # Par défaut, on n'affiche pas le bouton
    peut_se_declarer = False

    if dossier.id_groupeinstructeur and instructeur_connecte:
        instructeurs_du_groupe = set(
            dossier.id_groupeinstructeur
            .groupeinstructeurinstructeur_set
            .values_list("id_instructeur_id", flat=True)
        )

        instructeurs_dossier = set(
            DossierInstructeur.objects.filter(id_dossier=dossier)
            .values_list("id_instructeur_id", flat=True)
        )

        # Si aucun instructeur du groupe n'est affecté au dossier, et que l'utilisateur connecté fait partie du groupe : il peut se déclarer
        if not instructeurs_dossier & instructeurs_du_groupe and instructeur_connecte.id in instructeurs_du_groupe:
            peut_se_declarer = True


    dossier_documents = DossierDocument.objects.filter(id_dossier=dossier).select_related("id_document")
    emplacements_documents = [doc.id_document.emplacement for doc in dossier_documents]

    # Documents de nature "Annexe instructeur"
    annexes_instructeur = [
        doc.id_document for doc in dossier_documents
        if doc.id_document.id_nature.nature.lower() == "annexe instructeur"
    ]

    # Recup des infos sur le bénéficiaire
    beneficiaire = None
    demandeur_intermediaire = None
    interlocuteur = DossierInterlocuteur.objects.filter(id_dossier=dossier).first()

    if interlocuteur:
        dossier_benef = DossierBeneficiaire.objects.filter(id_dossier_interlocuteur=interlocuteur).select_related("id_beneficiaire").first()
        if dossier_benef:
            beneficiaire = dossier_benef.id_beneficiaire

         # Demandeur intermédiaire
        if interlocuteur.id_demandeur_intermediaire:
            demandeur_intermediaire = interlocuteur.id_demandeur_intermediaire

    #Menu déroulant adpaté enfocntion de l'étape en cours du dossier
    etapes_custom = {
        "À affecter": ["Passer en pré-instruction"],
        "En pré-instruction": ["Demander des compléments", "Classer le dossier comme non soumis à autorisation", "Classer le dossier comme refusé", "Passer en instruction"],
        "En attente de compléments": ["Passer en instruction"],
        "En instruction": ["Demander des compléments", "Classer le dossier comme non soumis à autorisation", "Classer le dossier comme refusé", "Envoyer pour validation avant demande d'avis", "Envoyer pour validation avant signature"],
        "À valider avant demande d'avis": ["Repasser en instruction", "Valider le modèle de demande d'avis et le projet d'acte"],
        "À valider avant signature": ["Repasser en instruction", "Valider et envoyer pour relecture qualité"],
        "En relecture qualité": ["Repasser en instruction", "Envoyer pour signature"],
        "En attente réponse d'avis": ["Envoyer les modifications pour validation", "Envoyer pour relecture qualité"],
        "Avis à envoyer":["Avis envoyé"],
        "En attente de signature": ["Repasser en instruction", "Acte prêt à être envoyé"],
        "Acte à envoyer": ["Envoyer l'acte"],
        "À publier au RAA": ["Classer le dossier comme accepté"],  #message de confirmation (publication au RAA faite ?)
        "Non soumis à autorisation": ["Repasser en instruction"],
        "Accepté": ["Repasser en instruction"],
        "Refusé": ["Repasser en instruction"]
    }

    # Suppression de l'action si conditions spécifiques
    if etape_actuelle and etape_actuelle.etape == "En instruction" and demarche.type == "Manifestations sportives":
        actions = etapes_custom.get("En instruction", [])
        etapes_custom["En instruction"] = [a for a in actions if a != "Envoyer pour validation avant demande d'avis"]


    # Mapping entre les actions et leurs logos
    logo_mapping = {
    "Dossier reçu": "recu.png",
    "Instructeur.e retiré.e": "instructeur_retire.png",
    "Instructeur.e ajouté.e": "instructeur_ajoute.png",
    "Classé sans suite": "classe-sans-suite.png",
    "Classé comme refusé": "refuse.png",
    "Classé comme accepté": "accepte.png",
    "Demande de compléments": "demande-de-complements.png",
    "Avis reçu": "recu.png",
    "Avis demandé": "acte-envoye.png",
    "Acte signé": "acte-signe.png",
    "Acte envoyé": "acte-envoye.png",
    "Validé avant demande d'avis": "valide.png",
    "Publié au RAA": "publie_au_raa.png",
    "Envoyé pour signature": "envoye.png",
    "Relecture qualité": "relecture-qualite.png",
    "Validé avant signature": "valide.png",
    "Relecture": "relecture-qualite.png",
    "Passage en instruction": "envoye.png",
    "Repassage en instruction": "envoye.png",
    "Affectation au groupe": "groupe_instructeur.png",
    "Passage en pré-instruction": "envoye.png",
    "Envoyé pour validation": "envoye_pour_validation.png",
    "Envoyé pour relecture qualité": "envoye.png",
    "Avis demandé": "acte-envoye.png",
    "Validant.e changé.e": "changer_validant.png",
    "Relecteur.rice changé.e": "changer_validant.png",
}


    # Dossier Actions
    dossier_actions = DossierAction.objects.filter(id_dossier=dossier).order_by('-date')

    for action in dossier_actions:
        action.logo = logo_mapping.get(action.id_action.action, "timeline.png")

    notes_queryset = DossierNote.objects.filter(id_dossier=dossier).select_related("id_instructeur__id_agent_autorisations").order_by("-date")

    notes = [
        {
            "id": n.id,
            "note": n.note,
            "date": n.date,
            "instructeur_id": n.id_instructeur.id,
            "instructeur": f"{n.id_instructeur.id_agent_autorisations.prenom} {n.id_instructeur.id_agent_autorisations.nom}" if n.id_instructeur.id_agent_autorisations else n.id_instructeur.email,
        }
        for n in notes_queryset
    ]

    documents_actes = Document.objects.filter(
        emplacement=f"{dossier.emplacement}/Actes/"
    ).values_list("titre", flat=True)


    # Récupération des documents liés au dossier
    documents_du_dossier = DossierDocument.objects.filter(id_dossier=dossier).select_related("id_document__id_statut")

    natures_valides = ['Déliberation CA', 'Arrêté directeur', 'Avis simple', 'Avis conforme']

    acte_a_valider = [
        doc.id_document for doc in documents_du_dossier
        if doc.id_document.id_statut and doc.id_document.id_statut.statut.lower() == "à valider" and doc.id_document.id_nature.nature in natures_valides
    ]

    acte_a_relire = [
        doc.id_document for doc in documents_du_dossier
        if doc.id_document.id_statut and doc.id_document.id_statut.statut.lower() == "à relire" and doc.id_document.id_nature.nature in natures_valides
    ]

    acte_a_signer = [
        doc.id_document for doc in documents_du_dossier
        if doc.id_document.id_statut and doc.id_document.id_statut.statut.lower() == "à signer" and doc.id_document.id_nature.nature in natures_valides
    ]

    acte_a_envoyer = [
        doc.id_document for doc in documents_du_dossier
        if doc.id_document.id_statut and doc.id_document.id_statut.statut.lower() == "à envoyer" and doc.id_document.id_nature.nature in natures_valides
    ]

    acte_envoye = [
        doc.id_document for doc in documents_du_dossier
        if doc.id_document.id_statut and doc.id_document.id_statut.statut.lower() == "envoyé" and doc.id_document.id_nature.nature in natures_valides
    ]


    acte_envoye_et_publie = [
        doc.id_document for doc in documents_du_dossier
        if doc.id_document.id_statut and doc.id_document.id_statut.statut.lower() == "envoyé" and doc.id_document.id_nature.nature in natures_valides and doc.id_document.publie_au_raa
    ]

    resume_pdf_titre = f"dossier-{dossier.numero}.pdf"

    titres_documents_actes = list(
        Document.objects.filter(
            emplacement=os.path.join(dossier.emplacement, "Actes/")
        ).values_list("titre", flat=True)
    )
    
    # Validant.e.s SAADD
    groupe = Group.objects.filter(name="Validant-e SAADD").first()
    user_validants_SAADD = groupe.user_set.all() if groupe else []
    emails_validants_SAADD = [user.email for user in user_validants_SAADD if user.email]
    validants_SAADD = Instructeur.objects.filter(email__in=emails_validants_SAADD).select_related("id_agent_autorisations")

    # Validant.e.s SPPN
    groupe = Group.objects.filter(name="Validant-e SPPN").first()
    user_validants_SPPN = groupe.user_set.all() if groupe else []
    emails_validants_SPPN = [user.email for user in user_validants_SPPN if user.email]
    validants_SPPN = Instructeur.objects.filter(email__in=emails_validants_SPPN).select_related("id_agent_autorisations")

    # Validant.e du dossier
    validant_ids = DossierValideur.objects.filter(id_dossier=dossier).values_list("id_instructeur", flat=True)
    validants = Instructeur.objects.filter(id__in=validant_ids).select_related("id_agent_autorisations")

    # Relecteur qualité du dossier
    relecteur_ids = DossierRelecteurQualite.objects.filter(id_dossier=dossier).values_list("id_instructeur", flat=True)
    relecteurs_qualite_du_dossier = Instructeur.objects.filter(id__in=relecteur_ids).select_related("id_agent_autorisations")

    # Relecteur-rice qualité
    groupe = Group.objects.filter(name="Relecteur-rice qualité").first()
    user_relecteur_qualite = groupe.user_set.all() if groupe else []
    emails_relecteur_qualite = [user.email for user in user_relecteur_qualite if user.email]
    relecteurs_qualite = Instructeur.objects.filter(email__in=emails_relecteur_qualite).select_related("id_agent_autorisations")

    # Relecteur juridique du dossier
    relecteurs_juridique_du_dossier = DossierRelecteurJuridique.objects.filter(id_dossier=dossier)
    

    # Relecteur-rice juridique
    groupe = Group.objects.filter(name="Relecteur-rice juridique").first()
    user_relecteur_qualite = groupe.user_set.all() if groupe else []
    emails_relecteur_qualite = [user.email for user in user_relecteur_qualite if user.email]
    relecteurs_juridique = Instructeur.objects.filter(email__in=emails_relecteur_qualite).select_related("id_agent_autorisations")

    # Signataires
    groupe = Group.objects.filter(name="Signataire").first()
    user_signataire = groupe.user_set.all() if groupe else []
    emails_signataire = [user.email for user in user_signataire if user.email]
    signataires = Instructeur.objects.filter(email__in=emails_signataire).select_related("id_agent_autorisations")



    # Fusionner les relecteurs qualité et les instructeurs du groupe instructeur (sans doublon)
    relecteurs_ids = {r.id for r in relecteurs_qualite}
    instructeurs_groupe = []

    if dossier.id_groupeinstructeur:
        instructeurs_groupe = [
            i.id_instructeur for i in 
            dossier.id_groupeinstructeur.groupeinstructeurinstructeur_set.select_related("id_instructeur__id_agent_autorisations")
            if i.id_instructeur.id not in relecteurs_ids
        ]

    relecteurs_qualite_et_instructeurs = list(relecteurs_qualite) + instructeurs_groupe




    # Messages non lus
    nb_messages_non_lus = Message.objects.filter(
        id_dossier=dossier,
        lu=False
    ).exclude(
        email_emetteur='contact@demarches-simplifiees.fr'
    ).exclude(
        email_emetteur__endswith='reunion-parcnational.fr'
    ).count()

    # Dossier Déclaration Manifestations
    doss_manif_sportive = None
    if dossier.id_demarche.type == "Manifestations sportives":
        liaison = DossierManifestationLiaison.objects.filter(id_dossier=dossier).select_related("id_dossier_manif").first()
        if liaison:
            doss_manif_sportive = liaison.id_dossier_manif
 

    # Contacts externes
    contacts_externes = list((
        ContactExterne.objects
        .filter(email__isnull=False)
        .exclude(email__exact='')
        .order_by('nom', 'email')
    ))

    # Liste tous les emails de la table outbox liés à ce dossier
    emails_dossiers = EmailOutbox.objects.filter(id_dossier=dossier.id).order_by("-date_creation")


    return render(request, 'instruction/instruction_dossier.html', {
        "dossier": dossier,
        "etat_dossier": format_etat_dossier(dossier.id_etat_dossier.nom),
        "champs": champs_prepares,
        "coeurData": fond_coeur_de_parc,
        "adhesionData": fond_aire_adhesion,
        "mafateData": fond_mafate,
        "nb_cartes": nb_cartes,
        "is_formulaire_active": True,
        "is_messagerie_active": False,
        "groupes_instructeurs": groupes_instructeurs,
        "membres_groupe": membres_groupe,
        "etapes_possibles": etapes_possibles,
        "etape_actuelle": etape_actuelle,
        "instructeurs_dossier_ids": instructeurs_dossier,
        "peut_se_declarer": peut_se_declarer,
        "instructeur_connecte": instructeur_connecte,
        "ROOT_FOLDER": os.getenv('ROOT_FOLDER'),
        "emplacements_documents": emplacements_documents,
        "annexes_instructeur": annexes_instructeur,
        "demarche": demarche,
        "beneficiaire": beneficiaire,
        "demandeur_intermediaire": demandeur_intermediaire,
        "etapes_custom": etapes_custom,
        "dossier_actions": dossier_actions,
        "notes": notes,
        "retirer_instructeur_message": request.session.pop("retirer_instructeur_message", None),
        "changer_valideur_message": request.session.pop("changer_valideur_message", None),
        "changer_relecteur_qualite_message": request.session.pop("changer_relecteur_qualite_message", None),
        "relecteur_juridique_message": request.session.pop("relecteur_juridique_message", None),
        "titres_documents_actes": list(documents_actes),
        "doc_a_valider": acte_a_valider,
        "doc_a_relire": acte_a_relire,
        "doc_a_signer": acte_a_signer,
        "doc_a_envoyer": acte_a_envoyer,
        "resume_pdf_titre": resume_pdf_titre,
        "doc_envoye": acte_envoye,
        "doc_envoye_et_publie": acte_envoye_et_publie,
        "titres_documents_actes": titres_documents_actes,
        "validants_SAADD": validants_SAADD,
        "validants_SPPN": validants_SPPN,
        "validants": validants,
        "nb_messages_non_lus": nb_messages_non_lus,
        "doss_manif_sportive": doss_manif_sportive,
        "relecteurs_qualite": relecteurs_qualite,
        "relecteurs_qualite_du_dossier": relecteurs_qualite_du_dossier,
        "relecteurs_qualite_et_instructeurs": relecteurs_qualite_et_instructeurs,
        "relecteurs_juridique": relecteurs_juridique,
        "relecteurs_juridique_du_dossier": relecteurs_juridique_du_dossier,
        "signataires": signataires,
        "contacts_externes": contacts_externes,
        "emails_dossiers": emails_dossiers,
    })



@login_required
def actualiser_dossier(request, num_dossier):
    dossier = get_object_or_404(Dossier, numero=num_dossier)
    client = GraphQLClient()

    try:
        # 1. Appel de l'API DS pour récupérer toute la démarche associée
        result = client.execute_query("DS/queries/get_dossier.graphql", {"number": num_dossier})

        if "errors" in result and result["errors"]:
            raise Exception(f"Erreur(s) GraphQL lors de l'actualisation du dossier {num_dossier} : {result['errors']}")
        
        # 2. Normalisation des données
        doss = result["data"]["dossier"]

        contact_beneficiaire = doss["demandeur"]

        demarche = dossier.id_demarche  # objet Django déjà lié au dossier
        id_demarche = demarche.id
        titre_demarche = demarche.titre

        # Mettre à un autre endroit car si le nom du doss change on créer une deuxieme dossier ici (au lieu de le renommer)
        emplacement_dossier = construire_emplacement_dossier(doss, contact_beneficiaire, titre_demarche)

        # Manif sportives - Déclaration manifestations
        liaison = DossierManifestationLiaison.objects.filter(id_dossier=dossier.id).first()
        if liaison:
            doss_dm = recup_un_seul_dossier(liaison.id_dossier_manif.numero_dossier_declaration_manifestations)
            doss_dm_norma = dossiers_declaration_manifestations_normalize(doss_dm)
            loggerSynchro.info("")
            loggerSynchro.info(f"------ DOSSIER {doss_dm_norma[0]["nom_dossier"]} (Déclaration Manifestations) ------")

            for ddm in doss_dm_norma :
                sync_declaration_manifestations(ddm, loggerSynchro)
            loggerSynchro.info("------------------------------------------------")


        dico_dossier = {
            "dossier": dossier_normalize(id_demarche, doss, emplacement_dossier),
            "contacts_externes": contact_externe_normalize(doss, None),
            "dossier_interlocuteur": dossier_interlocuteur_normalize(doss),
            "dossier_champs": dossiers_champs_normalize(doss, emplacement_dossier, None)[0],
            "dossier_document": dossier_document_normalize(doss, emplacement_dossier),
            "messages": message_normalize(doss, emplacement_dossier),
            "demandes": demande_normalize(id_demarche, titre_demarche, doss)
        }

        # 3. Synchronisation en base
        if liaison:
            loggerSynchro.info(f"------ DOSSIER {doss_dm_norma[0]["nom_dossier"]} (Démarches Simplifiées) ------")
        else:
            loggerSynchro.info(f"------ DOSSIER {dico_dossier["dossier"]["nom_dossier"]} (Démarches Simplifiées) ------")

        sync_dossiers([dico_dossier], demarche.numero, True)
        
        return redirect(request.META.get("HTTP_REFERER", "/"))

    except Exception as e:
        logger.exception(f"[DOSSIER] Échec de l'actualisation complète du dossier {num_dossier} : {e}")
        return HttpResponse(f"Erreur : {e}", status=500)



@login_required
def sauvegarder_note_dossier(request):
    
    dossier_id = request.POST.get("dossierId")
    note_id = request.POST.get("noteId")
    contenu = request.POST.get("note")

    instructeur = Instructeur.objects.filter(email=request.user.email).first()
    dossier = get_object_or_404(Dossier, id_ds=dossier_id)

    if not instructeur:
        logger.error(f"[DOSSIER {dossier.numero}] Sauvegarde note échouée : instructeur non identifié ({request.user.email}).")
        return redirect(request.META.get("HTTP_REFERER", "/"))

    if note_id:  # Modification d'une note existante
        note = get_object_or_404(DossierNote, id=note_id, id_instructeur=instructeur)
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

    return redirect(request.META.get("HTTP_REFERER", "/"))




@require_POST
@login_required
def mettre_a_jour_relecture_juridique(request):
    dossier_id = request.POST.get("dossier_id")
    relecture = request.POST.get("relecture_juridique") == "true"

    dossier = get_object_or_404(Dossier, id=dossier_id)
    dossier.relecture_juridique = relecture
    dossier.save()

    logger.info(f"[DOSSIER {dossier.numero}] Relecture mise à jour : {relecture} par {request.user.email}")
    return JsonResponse({"status": "ok", "relecture_juridique": relecture})


@require_POST
@login_required
def ajouter_relecteur_juridique_dossier(request):
    dossier_id = request.POST.get("dossier_id")
    relecteur_id = request.POST.get("relecteur_id")

    dossier = get_object_or_404(Dossier, id=dossier_id)
    relecteur = get_object_or_404(Instructeur, id=relecteur_id)

    # Évite les doublons
    existant = DossierRelecteurJuridique.objects.filter(id_dossier=dossier, id_instructeur=relecteur).exists()
    if not existant:
        DossierRelecteurJuridique.objects.create(id_dossier=dossier, id_instructeur=relecteur)
    else:
        dossRJ = DossierRelecteurJuridique.objects.filter(id_dossier=dossier, id_instructeur=relecteur).first()
        if dossRJ.relu :
             request.session["relecteur_juridique_message"] = (
                "Cet.te relecteur.rice a déjà réalisé.e une relecture sur le dossier."
            )
        else:
            request.session["relecteur_juridique_message"] = (
                "Cet.te relecteur.rice a déjà une relecture en cours sur le dossier."
            )
    return redirect(reverse("instruction_dossier", kwargs={"num_dossier": dossier.numero}))



@require_POST
@login_required
def relecture_juridique_faite(request):
    dossier_id = request.POST.get("dossier_id")
    relecteur_entry_id = request.POST.get("relecteur_id")

    dossier = get_object_or_404(Dossier, id=dossier_id)
    entry = get_object_or_404(DossierRelecteurJuridique, id=relecteur_entry_id)

    if request.user.email == entry.id_instructeur.email:
        entry.relu = True
        entry.save()

        # Dossier Action
        instructeur = Instructeur.objects.filter(email=request.user.email).first()
        nom_prenom = '(' + instructeur.id_agent_autorisations.nom + " " + instructeur.id_agent_autorisations.prenom + ')'
        enregistrer_action(dossier, instructeur, "Relecture", nom_prenom)

    else:
        request.session["relecteur_juridique_message"] = ("Vous n’êtes pas autorisé.e à valider cette relecture.")

    return redirect(reverse("instruction_dossier", kwargs={"num_dossier": dossier.numero}))


@require_POST
@login_required
def retirer_relecteur_juridique(request):

    drj_id = request.POST.get("dossier_relecture_juridique_id")
    drj = get_object_or_404(DossierRelecteurJuridique, id=drj_id)
    dossier = drj.id_dossier

    try :
        drj.delete()
    except :
        request.session["relecteur_juridique_message"] = ("Relecteur.rice juridique n'as pas pu être retiré.e du dossier.")
    
    return redirect(reverse("instruction_dossier", kwargs={"num_dossier": dossier.numero}))



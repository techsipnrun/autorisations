from datetime import date
import json
import logging
import os
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib.auth.decorators import login_required
from autorisations.models.models_instruction import Demarche, Dossier, EtapeDossier, EtatDossier
from autorisations.models.models_utilisateurs import DossierBeneficiaire, DossierInstructeur, DossierInterlocuteur, Groupeinstructeur, Instructeur
from autorisations import settings
from DS.graphql_client import GraphQLClient
from autorisations.models.models_documents import DossierDocument
from synchronisation.src.normalisation.norma_contacts_externes import contact_externe_normalize
from synchronisation.src.normalisation.norma_demandes import demande_normalize
from synchronisation.src.normalisation.norma_dossier_champs import dossiers_champs_normalize
from synchronisation.src.normalisation.norma_dossier_document import dossier_document_normalize
from synchronisation.src.normalisation.norma_dossier_interlocuteur import dossier_interlocuteur_normalize
from synchronisation.src.normalisation.norma_messages import message_normalize
from synchronisation.src.synchro.sync_dossiers import sync_dossiers
from synchronisation.src.utils.fichiers import construire_emplacement_dossier
from synchronisation.src.normalisation.norma_dossier import dossier_normalize
from synchronisation.src.normalisation.norma_dossiers import dossiers_normalize_process
from instruction.utils import format_etat_dossier
from synchronisation.src.main import lancer_normalisation_et_synchronisation_pour_une_demarche

logger = logging.getLogger('ORM_DJANGO')

def get_dossier_counts(demarche, etape_a_affecter, etat_instruction, etats_termines, current_year, groupes_user=None):
    ids_etats_termines = list(etats_termines.values_list("id", flat=True))

    query_suivis = Dossier.objects.filter(id_demarche=demarche).exclude(id_etape_dossier=etape_a_affecter).exclude(id_etat_dossier__in=ids_etats_termines)

    nb_suivis_user = 0
    if groupes_user:
        nb_suivis_user = query_suivis.filter(id_groupeinstructeur_id__in=groupes_user).count()

    return {
        "demarche": demarche,
        "nb_reception": Dossier.objects.filter(id_demarche=demarche, id_etape_dossier=etape_a_affecter).count(),
        "nb_suivis": query_suivis.count(),
        "nb_traites": Dossier.objects.filter(id_demarche=demarche, id_etat_dossier__in=ids_etats_termines, date_fin_instruction__year=current_year).count(),
        "nb_suivis_user": nb_suivis_user
    }


@login_required
def accueil(request):
    etat_construction = EtatDossier.objects.filter(nom__iexact="en_construction").first()
    etat_instruction = EtatDossier.objects.filter(nom__iexact="en_instruction").first()
    etats_termines = EtatDossier.objects.filter(nom__in=["accepte", "refuse", "sans_suite"])
    etape_a_affecter = EtapeDossier.objects.filter(etape="À affecter").first()

    current_year = date.today().year
    demarches = Demarche.objects.all().order_by("titre")

    # ✅ Sécurisation
    groupes_user = []
    instructeur = Instructeur.objects.filter(id_agent_autorisations__mail_1=request.user.email).first()
    if instructeur:
        groupes_user = list(
            instructeur.groupeinstructeurinstructeur_set.values_list("id_groupeinstructeur_id", flat=True)
        )

    dossier_infos = [
        get_dossier_counts(d, etape_a_affecter, etat_instruction, etats_termines, current_year, groupes_user)
        for d in demarches
    ]

    return render(request, 'instruction/instruction.html', {"dossier_infos": dossier_infos})



@login_required
def instruction_demarche(request, num_demarche):

    demarche = get_object_or_404(Demarche, numero=num_demarche)

    etapes = EtapeDossier.objects.exclude(etape="À affecter")

    etats_termines = EtatDossier.objects.filter(nom__in=["accepte", "refuse", "sans_suite"])
    ids_etats_termines = list(etats_termines.values_list("id", flat=True))

    instructeur = Instructeur.objects.filter(id_agent_autorisations__mail_1=request.user.email).first()
    groupes_user = []
    if instructeur:
        groupes_user = instructeur.groupeinstructeurinstructeur_set.values_list("id_groupeinstructeur_id", flat=True)


    # Filtrage conditionnel si la case est cochée
    dossiers_query = Dossier.objects.filter(
        id_etape_dossier__in=etapes,
        id_demarche=demarche.id
    ).exclude(
        id_etat_dossier__in=ids_etats_termines
    )

    if request.GET.get("mes_dossiers") == "1" :
        dossiers_query = dossiers_query.filter(id_groupeinstructeur_id__in=groupes_user)

    dossiers = dossiers_query.select_related("id_dossier_type", "id_groupeinstructeur").order_by("date_depot")

    dossier_infos = []
    for dossier in dossiers:
        interlocuteur = DossierInterlocuteur.objects.filter(id_dossier=dossier).select_related("id_demandeur_intermediaire").first()

        beneficiaire = None
        if interlocuteur:
            dossier_beneficiaire = DossierBeneficiaire.objects.filter(id_dossier_interlocuteur=interlocuteur).select_related("id_beneficiaire").first()
            if dossier_beneficiaire:
                beneficiaire = dossier_beneficiaire.id_beneficiaire

        dossier_infos.append({
            "nom_dossier": dossier.nom_dossier,
            "type": dossier.id_dossier_type.type if dossier.id_dossier_type else "N/A",
            "numero": dossier.numero,
            "beneficiaire": f"{beneficiaire.prenom} {beneficiaire.nom}" if beneficiaire else "N/A",
            "date_depot": dossier.date_depot,
            "groupe": dossier.id_groupeinstructeur.nom if dossier.id_groupeinstructeur else "N/A",
            "etape": dossier.id_etape_dossier.etape if dossier.id_etape_dossier.etape else "Non défini"
        })


    return render(request, "instruction/instruction_demarche.html", {
    "demarche": demarche,
    "dossiers": dossier_infos,
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

    nb_cartes = 0
    champs_prepares = []
    for champ in dossier.dossierchamp_set.select_related("id_champ__id_champ_type").order_by("id"):

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

        # Si aucun instructeur du groupe n'est affecté au dossier,
        # et que l'utilisateur connecté fait partie du groupe : il peut se déclarer
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
        "À valider avant signature": ["Repasser en instruction", "Envoyer pour relecture qualité"],
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



    return render(request, 'instruction/instruction_dossier.html', {
        "dossier": dossier,
        "etat_dossier": format_etat_dossier(dossier.id_etat_dossier.nom),
        "champs": champs_prepares,
        "coeurData": fond_coeur_de_parc,
        "adhesionData": fond_aire_adhesion,
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
        # "geometrie_modif": json.dumps(dossier.geometrie_modif) if dossier.geometrie_modif else None,
        "ROOT_FOLDER": os.getenv('ROOT_FOLDER'),
        "emplacements_documents": emplacements_documents,
        "annexes_instructeur": annexes_instructeur,
        "demarche": demarche,
        "beneficiaire": beneficiaire,
        "demandeur_intermediaire": demandeur_intermediaire,
        "etapes_custom": etapes_custom,
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

        contact_beneficiaire = doss["demandeur"]  # ou selon ta structure réelle

        demarche = dossier.id_demarche  # objet Django déjà lié au dossier
        id_demarche = demarche.id
        titre_demarche = demarche.titre

        #Mettre à un autre endroit car si le nom du doss change on créer une deuxieme dossier ici (au lieu de le renommer)
        emplacement_dossier = construire_emplacement_dossier(doss, contact_beneficiaire, titre_demarche)

        dico_dossier = {
            "dossier": dossier_normalize(id_demarche, doss, emplacement_dossier),
            "contacts_externes": contact_externe_normalize(doss),
            "dossier_interlocuteur": dossier_interlocuteur_normalize(doss),
            "dossier_champs": dossiers_champs_normalize(doss, emplacement_dossier),
            "dossier_document": dossier_document_normalize(doss, emplacement_dossier),
            "messages": message_normalize(doss, emplacement_dossier),
            "demandes": demande_normalize(id_demarche, titre_demarche, doss)
        }

        # 3. Synchronisation en base
        sync_dossiers([dico_dossier])

        logger.info(f"[DOSSIER] Actualisation complète du dossier {num_dossier} réussie.")
        # return redirect('instruction_dossier', num_dossier=num_dossier)
        return redirect(request.META.get("HTTP_REFERER", "/"))

    except Exception as e:
        logger.exception(f"[DOSSIER] Échec de l'actualisation complète du dossier {num_dossier} : {e}")
        return HttpResponse(f"Erreur : {e}", status=500)




@login_required
def instruction_dossier_consultation(request, num_dossier):
    dossier = get_object_or_404(Dossier, numero=num_dossier)
    return render(request, "instruction/instruction_dossier_consultation.html", {
        "dossier": dossier,
        "is_formulaire_active": False,
        "is_messagerie_active": False,
        "is_consultation_active": True,
    })




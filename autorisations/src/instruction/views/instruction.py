from datetime import date
import json
import logging
import os
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib.auth.decorators import login_required
from autorisations.models.models_instruction import Demarche, Dossier, EtapeDossier, EtatDossier
from autorisations.models.models_utilisateurs import DossierBeneficiaire, DossierInstructeur, DossierInterlocuteur, Groupeinstructeur
from autorisations import settings
from DS.graphql_client import GraphQLClient
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

logger = logging.getLogger('ORM_DJANGO')

def get_dossier_counts(demarche, etape_a_affecter, etat_instruction, etats_termines, current_year):
    ids_etats_termines = list(etats_termines.values_list("id", flat=True))

    return {
        "demarche": demarche,
        "nb_reception": Dossier.objects.filter(id_demarche=demarche, id_etape_dossier=etape_a_affecter).count(),
        "nb_suivis": Dossier.objects.filter(id_demarche=demarche).exclude(id_etape_dossier=etape_a_affecter).exclude(id_etat_dossier__in=ids_etats_termines).count(),
        "nb_traites": Dossier.objects.filter(id_demarche=demarche, id_etat_dossier__in=etats_termines, date_fin_instruction__year=current_year).count(),
    }

@login_required
def accueil(request):
    etat_construction = EtatDossier.objects.filter(nom__iexact="en_construction").first()
    etat_instruction = EtatDossier.objects.filter(nom__iexact="en_instruction").first()
    etats_termines = EtatDossier.objects.filter(nom__in=["accepte", "refuse", "sans_suite"])
    

    etape_a_affecter = EtapeDossier.objects.filter(etape="À affecter").first()

    current_year = date.today().year
    demarches = Demarche.objects.all().order_by("titre")
    dossier_infos = [get_dossier_counts(d, etape_a_affecter, etat_instruction, etats_termines, current_year) for d in demarches]

    return render(request, 'instruction/instruction.html', {"dossier_infos": dossier_infos})


@login_required
def instruction_demarche(request, num_demarche):

    demarche = get_object_or_404(Demarche, numero=num_demarche)

    etapes = EtapeDossier.objects.exclude(etape="À affecter")

    etats_termines = EtatDossier.objects.filter(nom__in=["accepte", "refuse", "sans_suite"])
    ids_etats_termines = list(etats_termines.values_list("id", flat=True))


    dossiers = Dossier.objects.filter(
                id_etape_dossier__in=etapes,
                id_demarche=demarche.id
            ).exclude(
                id_etat_dossier__in=ids_etats_termines
            ).select_related(
                "id_dossier_type",
                "id_groupeinstructeur"
            ).order_by("date_depot")

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

    # Charger le fond de carte GeoJSON (une seule fois)
    fond_path = os.path.join(settings.BASE_DIR, "instruction/static/instruction/carto/fond_coeur_de_parc.geojson")

    with open(fond_path, encoding="utf-8") as f:
        fond_geojson = json.load(f)

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
            champs_prepares.append({"type": "carte", "nom": nom, "geojson": json.dumps(champ.geometrie)})

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


    return render(request, 'instruction/instruction_dossier.html', {
        "dossier": dossier,
        "etat_dossier": format_etat_dossier(dossier.id_etat_dossier.nom),
        "champs": champs_prepares,
        "fond_de_carte_data": fond_geojson,
        "is_formulaire_active": True,
        "is_messagerie_active": False,
        "groupes_instructeurs": groupes_instructeurs,
        "membres_groupe": membres_groupe,
        "etapes_possibles": etapes_possibles,
        "etape_actuelle": etape_actuelle,
        "instructeurs_dossier_ids": instructeurs_dossier,
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
        return redirect('instruction_dossier', num_dossier=num_dossier)

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

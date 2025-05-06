import json, os
from django.shortcuts import get_object_or_404, render, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
from autorisations.models.models_instruction import Dossier, EtatDossier
from autorisations.models.models_utilisateurs import Groupeinstructeur, GroupeinstructeurDemarche, DossierInterlocuteur, DossierBeneficiaire
from autorisations import settings
from instruction.utils import format_etat_dossier
from DS.call_DS import change_groupe_instructeur_ds
import logging
logger = logging.getLogger("ORM_DJANGO")

@login_required
def preinstruction(request):

    # Récupérer l'ID de l'état "en_construction"
    etat = EtatDossier.objects.filter(nom__iexact="en_construction").first()

    dossiers = Dossier.objects.filter(id_etat_dossier=etat).select_related("id_demarche").order_by("date_depot")
    dossier_infos = []

    for dossier in dossiers:

        # Chercher le demandeur via DossierInterlocuteur
        interlocuteur = DossierInterlocuteur.objects.filter(id_dossier=dossier).select_related("id_demandeur_intermediaire").first()
        demandeur = interlocuteur.id_demandeur_intermediaire if interlocuteur else None

        if not demandeur:
            benef = DossierBeneficiaire.objects.filter(id_dossier_interlocuteur=interlocuteur).select_related("id_beneficiaire").first()
            demandeur = benef.id_beneficiaire if benef else None

        dossier_infos.append({
            "demarche": dossier.id_demarche.type,
            "date_depot": dossier.date_depot,
            "demandeur": f"{demandeur.prenom} {demandeur.nom}" if demandeur else "N/A",
            "nom_projet": dossier.nom_dossier,
            "numero": dossier.numero,
        })
    return render(request, 'instruction/preinstruction.html', {"dossier_infos": dossier_infos})



@login_required
def preinstruction_dossier(request, numero):

    dossier = get_object_or_404(Dossier, numero=numero)

    # Charger le fond de carte GeoJSON (une seule fois)
    fond_path = os.path.join(settings.BASE_DIR, "instruction/static/instruction/carto/fond_coeur_de_parc.geojson")

    with open(fond_path, encoding="utf-8") as f:
        fond_geojson = json.load(f)

    champs_prepares = []
    for champ in dossier.dossierchamp_set.select_related("id_champ__id_champ_type").order_by("id"):

        ct = champ.id_champ.id_champ_type.type
        nom = champ.id_champ.nom

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

    return render(request, 'instruction/preinstruction_dossier.html', {
        "dossier": dossier,
        "etat_dossier": format_etat_dossier(dossier.id_etat_dossier.nom),
        "champs": champs_prepares,
        "fond_de_carte_data": fond_geojson,
        "is_formulaire_active": True,
        "is_messagerie_active": False,
        "groupes_instructeurs": groupes_instructeurs,
    })



@require_POST
def changer_groupe_instructeur(request):

    dossier_id = request.POST.get("dossierId")
    groupe_id = request.POST.get("groupeInstructeurId")

    nom_groupe = Groupeinstructeur.objects.filter(id=groupe_id).values_list("nom", flat=True).first()
    groupe_id_ds = GroupeinstructeurDemarche.objects.filter(id_groupeinstructeur=groupe_id).values_list("id_groupeinstructeur_ds", flat=True).first()
    dossier_num = Dossier.objects.filter(id_ds=dossier_id).values_list("numero", flat=True).first()

    if not dossier_id or not groupe_id_ds:
        messages.error(request, "Champs manquants.")
        return redirect(request.META.get('HTTP_REFERER', '/'))
    
    result = change_groupe_instructeur_ds(dossier_id, groupe_id_ds)

    if result["success"]:
        logger.info(f"[UPDATE] Groupe Instructeur changé avec succès (Dossier {dossier_num} --> {nom_groupe})")

    else:
        logger.error(f"Echec du changement de Groupe Instructeur (Dossier {dossier_num} --> {nom_groupe})")

    return redirect(request.META.get('HTTP_REFERER', '/'))

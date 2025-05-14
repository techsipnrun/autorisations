from django.http import HttpResponseBadRequest
from django.urls import reverse
from django.utils import timezone
import json, os
from django.shortcuts import get_object_or_404, render, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
from autorisations.models.models_instruction import Dossier, EtapeDossier, EtatDossier
from autorisations.models.models_utilisateurs import Groupeinstructeur, GroupeinstructeurDemarche, DossierInterlocuteur, DossierBeneficiaire, Instructeur
from autorisations import settings
from instruction.utils import format_etat_dossier
from DS.call_DS import change_groupe_instructeur_ds, passer_en_instruction_ds
import logging

logger = logging.getLogger("ORM_DJANGO")

@login_required
def preinstruction(request):

    # Récupérer l'ID de l'état "en_construction"  ICI
    # etat = EtatDossier.objects.filter(nom__iexact="en_construction").first()
    # dossiers = Dossier.objects.filter(id_etat_dossier=etat).select_related("id_demarche").order_by("date_depot")


    etape = EtapeDossier.objects.filter(etape="À affecter").first()
    dossiers = Dossier.objects.filter(id_etape_dossier=etape).select_related("id_demarche").order_by("date_depot")

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

    membres_groupe = []
    if dossier.id_groupeinstructeur:
        membres_groupe = dossier.id_groupeinstructeur.groupeinstructeurinstructeur_set.select_related("id_instructeur__id_agent_autorisations").values_list("id_instructeur", flat=False)
        membres_groupe = [m.id_instructeur for m in dossier.id_groupeinstructeur.groupeinstructeurinstructeur_set.select_related("id_instructeur__id_agent_autorisations")]


    return render(request, 'instruction/preinstruction_dossier.html', {
        "dossier": dossier,
        "etat_dossier": format_etat_dossier(dossier.id_etat_dossier.nom),
        "etape_dossier": dossier.id_etape_dossier.etape,
        "champs": champs_prepares,
        "fond_de_carte_data": fond_geojson,
        "is_formulaire_active": True,
        "is_messagerie_active": False,
        "groupes_instructeurs": groupes_instructeurs,
        "membres_groupe": membres_groupe,
    })



@require_POST
def changer_groupe_instructeur(request):

    dossier_id = request.POST.get("dossierId")
    groupe_id = request.POST.get("groupeInstructeurId")

    nom_groupe = Groupeinstructeur.objects.filter(id=groupe_id).values_list("nom", flat=True).first()
    groupe_id_ds = GroupeinstructeurDemarche.objects.filter(id_groupeinstructeur=groupe_id).values_list("id_groupeinstructeur_ds", flat=True).first()
    dossier = Dossier.objects.filter(id_ds=dossier_id).first()
    dossier_num = dossier.numero

    if not dossier_id or not groupe_id_ds:
        logger.error(f"[FORM] Changement groupe instructeur : paramètres manquants (dossier_id={dossier_id}, groupe_id_ds={groupe_id_ds})")
        return redirect(request.META.get('HTTP_REFERER', '/'))
    
    result = change_groupe_instructeur_ds(dossier_id, groupe_id_ds)

    if result["success"]:
        logger.info(f"[UPDATE] Groupe Instructeur changé avec succès (Dossier {dossier_num} --> {nom_groupe})")

        # mettre à jour le groupe instructeur en base
        try:
            dossier.id_groupeinstructeur_id = groupe_id
            dossier.save()
            logger.info(f"[PG] Groupe Instructeur mis à jour dans Postgres (Dossier {dossier_num} --> {nom_groupe})")

        except Exception as e:
            logger.error(f"[PG] Erreur de mise à jour du groupe instructeur (groupe mis à jour sur DS) : {e}")


    else:
        logger.error(f"Echec du changement de Groupe Instructeur (Dossier {dossier_num} --> {nom_groupe})")

    return redirect(request.META.get('HTTP_REFERER', '/'))


@require_POST
def passer_en_instruction(request):
    dossier_id = request.POST.get("dossierId")
    instructeur_email = request.user.email

    instructeur_id_ds = Instructeur.objects.filter(email=instructeur_email).values_list("id_ds", flat=True).first()
    dossier = get_object_or_404(Dossier, id_ds=dossier_id)

    # Vérifie qu'un groupe instructeur est affecté
    if not dossier.id_groupeinstructeur:
        logger.warning(f"[FORM] Tentative de passage en instruction sans groupe instructeur affecté (Dossier {dossier_id})")
        return redirect(request.META.get("HTTP_REFERER", "/"))

    if not instructeur_id_ds:
        logger.error(f"Passage Dossier en instruction : Instructeur non reconnu pour l'email : {instructeur_email}")
        return redirect(request.META.get("HTTP_REFERER", "/"))

    result = passer_en_instruction_ds(dossier_id, instructeur_id_ds)

    if result["success"]:
        logger.info(f"[DS] Passage en instruction réussi pour le dossier {dossier_id}")

        try:
            etat_instruction = EtatDossier.objects.get(nom__iexact="en_instruction")
            dossier.id_etat_dossier = etat_instruction
            dossier.date_debut_instruction = timezone.now()
            dossier.save()
            logger.info(f"[PG] État du dossier {dossier.nom_dossier} mis à jour en 'en_instruction'.")
            
            return redirect(reverse("instruction_dossier", kwargs={"num_dossier": dossier.numero}))

        except Exception as e:
            logger.error(f"[PG] Erreur lors de la mise à jour de l'état du dossier : {e}")

    else:
        logger.error(f"[DS] Échec du passage en instruction pour le dossier {dossier_id} : {result['message']}")

    return redirect(request.META.get("HTTP_REFERER", "/"))





@require_POST
def passer_etape_en_preinstruction(request):

    dossier_id = request.POST.get("dossierId")

    if not dossier_id:
        return HttpResponseBadRequest("Tentative de passage en préinstruction : Paramètre 'dossierId' manquant.")

    dossier = get_object_or_404(Dossier, id_ds=dossier_id)

    try:
        etape = EtapeDossier.objects.get(etape="En pré-instruction")
    except EtapeDossier.DoesNotExist:
        logger.error("Étape 'En pré-instruction' introuvable en base.")
        return HttpResponseBadRequest("Étape 'En pré-instruction' non définie.")

    dossier.id_etape_dossier = etape
    dossier.save()

    logger.info(f"Etape du dossier {dossier.numero} mise à jour en 'En pré-instruction'.")
  
    return redirect(reverse("instruction_dossier", kwargs={"num_dossier": dossier.numero}))


@require_POST
@login_required
def sauvegarder_note_dossier(request):
    dossier_id = request.POST.get("dossierId")
    nouvelle_note = request.POST.get("note")

    dossier = get_object_or_404(Dossier, id_ds=dossier_id)
    dossier.note = nouvelle_note
    dossier.save()

    instructeur = Instructeur.objects.filter(email=request.user.email).select_related("id_agent_autorisations").first()

    if instructeur and instructeur.id_agent_autorisations:
        nom = instructeur.id_agent_autorisations.nom
        prenom = instructeur.id_agent_autorisations.prenom
        logger.info(f"Dossier {dossier.numero} : note modifiée par {prenom} {nom} ({instructeur.email})")
    else:
        logger.info(f"Dossier {dossier.numero} : note modifiée par {request.user.email} (utilisateur non identifié comme instructeur)")

    return redirect(request.META.get("HTTP_REFERER", "/"))

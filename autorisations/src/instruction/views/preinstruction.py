from django.http import HttpResponseBadRequest
from django.urls import reverse
from django.utils import timezone
import json, os
from django.shortcuts import get_object_or_404, render, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
from autorisations.models.models_instruction import Demarche, Dossier, DossierAction, DossierChamp, DossierManifSportive, DossierManifestationLiaison, DossierNote, EtapeDossier, EtatDossier, Message
from autorisations.models.models_utilisateurs import DossierInstructeur, Groupeinstructeur, GroupeinstructeurDemarche, DossierInterlocuteur, DossierBeneficiaire, Instructeur
from autorisations import settings
from autorisations.models.models_documents import DossierDocument
from instruction.utils import dossiers_reception_action_a_faire, enregistrer_action, format_etat_dossier
from DS.call_DS import change_groupe_instructeur_ds, passer_en_instruction_ds
import logging
import ast
from collections import defaultdict


logger = logging.getLogger("ORM_DJANGO")

@login_required
def preinstruction(request):

    # Récupérer l'ID de l'état "en_construction"  ICI
    # etat = EtatDossier.objects.filter(nom__iexact="en_construction").first()
    # dossiers = Dossier.objects.filter(id_etat_dossier=etat).select_related("id_demarche").order_by("date_depot")


    etape = EtapeDossier.objects.filter(etape="À affecter").first()
    dossiers = Dossier.objects.filter(id_etape_dossier=etape).select_related("id_demarche").order_by("date_depot")

    dossiers_actions = dossiers_reception_action_a_faire(dossiers, request.user)

    dossier_infos = []

    instructeur = Instructeur.objects.filter(email=request.user.email).first()
    if not instructeur:
        messages.warning(request, f"⚠️ Attention, vous n'avez pas de profil 'Instructeur.rice' : Contactez l'administrateur.rice si besoin.")

    for dossier in dossiers:
        if dossier.id_demarche.type != "Manifestations sportives" :

            # Chercher le demandeur via DossierInterlocuteur
            interlocuteur = DossierInterlocuteur.objects.filter(id_dossier=dossier).select_related("id_demandeur_intermediaire").first()
            demandeur = interlocuteur.id_demandeur_intermediaire if interlocuteur else None
            
            # On affiche le nom et prenom du beneficiaire si jamais le demandeur intermédiaire ne les a pas de renseignés 
            if not demandeur or not(demandeur.prenom and demandeur.nom):
                benef = DossierBeneficiaire.objects.filter(id_dossier_interlocuteur=interlocuteur).select_related("id_beneficiaire").first()
                demandeur = benef.id_beneficiaire if benef else None

            dossier_infos.append({
                "demarche": dossier.id_demarche.type,
                "date_depot": dossier.date_depot,
                "demandeur": f"{demandeur.prenom} {demandeur.nom}" if demandeur else "N/A",
                "nom_projet": dossier.nom_dossier,
                "numero": dossier.numero,
                "action_a_faire": True if dossier in dossiers_actions else False
            })

    num_demarche_manif_sportive = Demarche.objects.get(type="Manifestations sportives").numero

    # -----------------------------------------
    # DossierManifSportive non liés à un Dossier
    # -----------------------------------------
    dossiers_manif_sportive_DM = DossierManifSportive.objects.exclude(
        id__in=DossierManifestationLiaison.objects.values_list("id_dossier_manif", flat=True)
    ).exclude(
        archive=True
    )
    # Trier par date décroissante
    dossiers_manif_sportive_DM = dossiers_manif_sportive_DM.order_by("-date_debut_evenement")


    # -----------------------------------------
    # Dossiers (de type "Manifestations sportives") non liés à un DossierManifSportive
    # -----------------------------------------
    dossiers_manif_sportive_DS = Dossier.objects.filter(
        id_demarche__type="Manifestations sportives"
    ).exclude(
        id__in=DossierManifestationLiaison.objects.values_list("id_dossier", flat=True)
    )

    # Trier par date décroissante
    dossiers_manif_sportive_DS = dossiers_manif_sportive_DS.order_by("-date_depot")

    dossiers_manif_sportive_DS_infos = []
    for dossier in dossiers_manif_sportive_DS:
        # --- 1. Demandeur (bénéficiaire) ---
        interlocuteur = DossierInterlocuteur.objects.filter(id_dossier=dossier).first()
        beneficiaire = None
        if interlocuteur:
            dossier_benef = DossierBeneficiaire.objects.filter(id_dossier_interlocuteur=interlocuteur).select_related("id_beneficiaire").first()
            if dossier_benef:
                beneficiaire = dossier_benef.id_beneficiaire

        nom_demandeur = f"{beneficiaire.nom} {beneficiaire.prenom}" if beneficiaire else "N/A"

        # --- 2. Numéro de dossier sur déclaration-manifestations ---
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
    # Dossiers (de type "Manifestations sportives") liés à au moins un DossierManifSportive
    # -----------------------------------------
    dossiers_manif_sportive_complet = Dossier.objects.filter(
        id_demarche__type="Manifestations sportives",
        id__in=DossierManifestationLiaison.objects.values_list("id_dossier", flat=True),
        id_etape_dossier__etape="À affecter"
    )

    # Récupération des liaisons
    liaisons = DossierManifestationLiaison.objects.filter(
        id_dossier__in=dossiers_manif_sportive_complet
    ).select_related("id_dossier_manif")

    # Création d’un dictionnaire : dossier → dossier_manif
    dossiers_manif_sportive_complet_map = {
        liaison.id_dossier: liaison.id_dossier_manif
        for liaison in liaisons
    }

    # Conversion en liste de tuples pour itération dans le template
    dossiers_manif_sportive_complet_list = list(dossiers_manif_sportive_complet_map.items())
    # Trier par date de début de la course décroissante
    dossiers_manif_sportive_complet_list = sorted(
    dossiers_manif_sportive_complet_list,
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
        })



@login_required
def preinstruction_dossier(request, numero):

    dossier = get_object_or_404(Dossier, numero=numero)

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
    for champ in dossier.dossierchamp_set.select_related("id_champ__id_champ_type", "id_document").order_by("ordre"):

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
            nb_cartes += 1
            geojson_source = champ.geometrie_modif or champ.geometrie
            champs_prepares.append({"type": "carte", "nom": nom, "geojson": json.dumps(geojson_source), "id":champ.id})

        elif ct == "header_section":
            champs_prepares.append({"type": "header", "titre": nom})

        elif ct == "piece_justificative":

            if champ.id_document :
                emplacement_doc= champ.id_document.emplacement
                # emplacement_doc = os.path.join(os.environ.get("NAS_ROOT"), champ.id_document.emplacement, champ.id_document.titre)
                champs_prepares.append({"type": "piece_justificative", "nom": nom, "url": champ.id_document.url_ds, "titre_doc": champ.id_document.titre, "emplacement_doc": emplacement_doc})
            else :

                champs_prepares.append({"type": "piece_justificative", "nom": nom, "titre_doc": "ERROR PARSING URL DS"})

        elif ct == "drop_down_list":
            
            if nom == 'Choix de la méthode pour localiser le projet' and 'Remplir le module de cartographie' not in champ.valeur :
                geojson_source = champ.geometrie_modif or champ.geometrie

                if not (geojson_source) :

                    champs_prepares.append({"type": "drop_down_list", "nom": nom, "valeur": champ.valeur, "geometrie_a_saisir": 'oui', "geojson": json.dumps({}), "id":champ.id})
                else :

                    champs_prepares.append({"type": "drop_down_list", "nom": nom, "valeur": champ.valeur, "geometrie_a_saisir": 'non', "geojson": json.dumps(geojson_source), "id":champ.id})

            else :
                champs_prepares.append({"type": "drop_down_list", "nom": nom,"valeur": champ.valeur, "geometrie_a_saisir": 'non pas concerné'})
                
        elif ct == "repetition":
            repetitions = []

            try:
                valeur = ast.literal_eval(champ.valeur) if isinstance(champ.valeur, str) else champ.valeur or {}
            except Exception as e:
                # print("Erreur lors de l’évaluation de la chaîne :", e)
                valeur = {}

            for liste in (valeur or {}).values():
                bloc = []
                for item in liste:
                    bloc.append({"nom": item.get("nom"), "valeur": item.get("valeur")})
                repetitions.append(bloc)
            # print(repetitions)
            # [[ {"nom": "Nom du ravitaillement", "valeur": "ravito1"}, {"nom": "...", "valeur": "..."} ],...]
            champs_prepares.append({
                "type": "repetition",
                "nom": nom,
                "valeur": repetitions or "Non renseigné"
            })
           
        else:
            champs_prepares.append({"type": "champ", "nom": nom, "valeur": champ.valeur or "Non renseigné"})

    #Récupérer tous les noms de groupes instructeurs pour la démarche en question
    groupes_instructeurs = Groupeinstructeur.objects.filter(groupeinstructeurdemarche__id_demarche=dossier.id_demarche).order_by("nom")

    membres_groupe = []
    if dossier.id_groupeinstructeur:
        membres_groupe = dossier.id_groupeinstructeur.groupeinstructeurinstructeur_set.select_related("id_instructeur__id_agent_autorisations").values_list("id_instructeur", flat=False)
        membres_groupe = [m.id_instructeur for m in dossier.id_groupeinstructeur.groupeinstructeurinstructeur_set.select_related("id_instructeur__id_agent_autorisations")]


    # Instructeurs déjà affectés au dossier
    instructeurs_dossier_ids = set(
        DossierInstructeur.objects.filter(id_dossier=dossier)
        .values_list("id_instructeur_id", flat=True)
    )

    # Instructeur connecté (pour le bouton 'se déclarer instructeur')
    instructeur_connecte = (
        Instructeur.objects
        .filter(email=request.user.email)
        .select_related("id_agent_autorisations")
        .first()
    )

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
        "Prêt à la signature": "envoye.png",
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
            "instructeur": f"{n.id_instructeur.id_agent_autorisations.prenom} {n.id_instructeur.id_agent_autorisations.nom}" if n.id_instructeur.id_agent_autorisations else n.id_instructeur.email
        }
        for n in notes_queryset
    ]

    resume_pdf_titre = f"dossier-{dossier.numero}.pdf"

    doss_manif_sportive = None
    if dossier.id_demarche.type == "Manifestations sportives":
        liaison = DossierManifestationLiaison.objects.filter(id_dossier=dossier).select_related("id_dossier_manif").first()
        if liaison:
            doss_manif_sportive = liaison.id_dossier_manif

    # Messages non lus
    nb_messages_non_lus = Message.objects.filter(
        id_dossier=dossier,
        lu=False
    ).exclude(
        email_emetteur='contact@demarches-simplifiees.fr'
    ).exclude(
        email_emetteur__endswith='reunion-parcnational.fr'
    ).count()



    return render(request, 'instruction/preinstruction_dossier.html', {
        "dossier": dossier,
        "etat_dossier": format_etat_dossier(dossier.id_etat_dossier.nom),
        "etape_dossier": dossier.id_etape_dossier.etape,
        "champs": champs_prepares,
        "coeurData": fond_coeur_de_parc,
        "adhesionData": fond_aire_adhesion,
        "mafateData": fond_mafate,
        "nb_cartes": nb_cartes,
        "is_formulaire_active": True,
        "is_messagerie_active": False,
        "groupes_instructeurs": groupes_instructeurs,
        "membres_groupe": membres_groupe,
        "instructeurs_dossier_ids": instructeurs_dossier_ids,
        "instructeur_connecte": instructeur_connecte,
        "NAS_ROOT": os.getenv('NAS_ROOT'),
        "emplacements_documents": emplacements_documents,
        "annexes_instructeur": annexes_instructeur,
        "beneficiaire": beneficiaire,
        "demandeur_intermediaire": demandeur_intermediaire,
        "dossier_actions": dossier_actions,
        "notes": notes,
        "preinstruction_message": request.session.pop("preinstruction_message", None),
        "retirer_instructeur_message": request.session.pop("retirer_instructeur_message", None),
        "resume_pdf_titre": resume_pdf_titre,
        "doss_manif_sportive": doss_manif_sportive,
        "nb_messages_non_lus": nb_messages_non_lus,
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
        logger.error(f"[DOSSIER {dossier_num}] Changement groupe instructeur : paramètres manquants (dossier_id={dossier_id}, groupe_id_ds={groupe_id_ds})")
        return redirect(request.META.get('HTTP_REFERER', '/'))
    
    result = change_groupe_instructeur_ds(dossier_id, groupe_id_ds)

    if result["success"]:
        logger.info(f"[DOSSIER {dossier_num}] Groupe Instructeur changé avec succès sur DS par {request.user} --> Affecté au groupe {nom_groupe}.")

        # mettre à jour le groupe instructeur en base
        try:
            dossier.id_groupeinstructeur_id = groupe_id
            dossier.save()
            logger.info(f"[DOSSIER {dossier_num}] Groupe Instructeur mis à jour dans Postgres par {request.user} --> Affecté au groupe {nom_groupe}.")

            # Dossier Action
            instructeur = Instructeur.objects.filter(email=request.user.email).first()
            enregistrer_action(dossier, instructeur, "Affectation au groupe", nom_groupe)

        except Exception as e:
            logger.error(f"[DOSSIER {dossier_num}] Erreur de mise à jour du Groupe Instructeur en BDD par {request.user} (groupe mis à jour sur DS) : {e}")

    else:
        logger.error(f"[DOSSIER {dossier_num}] Echec du changement de Groupe Instructeur par {request.user} (Affectation souhaitée : {nom_groupe})")

    return redirect(request.META.get('HTTP_REFERER', '/'))


@require_POST
def passer_en_instruction(request):
    dossier_id = request.POST.get("dossierId")
    instructeur_email = request.user.email

    instructeur = Instructeur.objects.filter(email=instructeur_email).first()
    dossier = get_object_or_404(Dossier, id_ds=dossier_id)

    # Vérifie qu'un groupe instructeur est affecté
    if not dossier.id_groupeinstructeur:
        logger.warning(f"[DOSSIER {dossier.numero}] Échec de passage en instruction par {instructeur_email} : aucun groupe instructeur affecté.")
        return redirect(request.META.get("HTTP_REFERER", "/"))

    if not instructeur :
        logger.error(f"[DOSSIER {dossier.numero}] Échec de passage en instruction par {instructeur_email} : Mail de l'instructeur non reconnu en BDD.")
        return redirect(request.META.get("HTTP_REFERER", "/"))

    result = passer_en_instruction_ds(dossier_id, instructeur)

    if result["success"]:
        logger.info(f"[DOSSIER {dossier.numero}] Passage en instruction réussi sur DS par {instructeur_email}")

        try:
            etat_instruction = EtatDossier.objects.get(nom__iexact="en_instruction")
            dossier.id_etat_dossier = etat_instruction
            dossier.date_debut_instruction = timezone.now()
            dossier.save()
            logger.info(f"[DOSSIER {dossier.numero}] État du dossier mis à jour en 'en_instruction' par {instructeur_email}.")
            
            return redirect(reverse("instruction_dossier", kwargs={"num_dossier": dossier.numero}))

        except Exception as e:
            logger.error(f"[DOSSIER {dossier.numero}] Erreur lors de la mise à jour en 'en_instruction' par {instructeur_email}: {e}")

    else:
        logger.error(f"[DOSSIER {dossier.numero}] Échec du passage en instruction sur DS par {instructeur_email}: {result['message']}")

    return redirect(request.META.get("HTTP_REFERER", "/"))



# @require_POST
# @login_required
# def sauvegarder_note_dossier(request):
#     dossier_id = request.POST.get("dossierId")
#     nouvelle_note = request.POST.get("note")

#     dossier = get_object_or_404(Dossier, id_ds=dossier_id)
#     dossier.note = nouvelle_note
#     dossier.save()

#     instructeur = Instructeur.objects.filter(email=request.user.email).select_related("id_agent_autorisations").first()

#     if instructeur and instructeur.id_agent_autorisations:
#         nom = instructeur.id_agent_autorisations.nom
#         prenom = instructeur.id_agent_autorisations.prenom
#         logger.info(f"[DOSSIER {dossier.numero}] Note modifiée par {prenom} {nom} ({instructeur.email})")
#     else:
#         logger.warning(f"[DOSSIER {dossier.numero}] Note modifiée par {request.user.email} (utilisateur non identifié comme instructeur)")

#     return redirect(request.META.get("HTTP_REFERER", "/"))

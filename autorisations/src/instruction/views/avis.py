from datetime import date
import logging
import os
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.db.models import Exists, OuterRef

from autorisations.models.models_instruction import Demarche, Dossier, Message
from autorisations.models.models_avis import Avis, AvisDocument, AvisNature, AvisThematique, DossierAvis, Expert
from autorisations.models.models_utilisateurs import ContactExterne, DossierInstructeur, Instructeur
from autorisations.models.models_documents import Document, DocumentFormat, DocumentNature, MessageDocument
from instruction.utils import create_message_avis_bdd
from synchronisation.src.utils.model_helpers import update_fields
from pathlib import Path
from django.utils.timezone import localtime
from django.views.decorators.csrf import csrf_exempt
from django.core.files.uploadedfile import SimpleUploadedFile

from synchronisation.src.utils.fichiers import nettoyer_nom_fichier

logger = logging.getLogger('ORM_DJANGO')


@login_required
def instruction_dossier_consultation(request, num_dossier):

    dossier = get_object_or_404(Dossier, numero=num_dossier)
    dossiers_avis = (DossierAvis.objects.filter(id_dossier=dossier))
    liste_avis = []
    nb_avis_avec_nouveau_mess = 0

    for da in dossiers_avis:
        avis = da.id_avis

        # Déterminer l'expert
        expert = "N/A"
        if avis.id_avis_nature.nature == "Demande à une instance":
            if avis.id_expert and avis.id_expert.id_contact_externe:
                expert = str(avis.id_expert.id_contact_externe)
        elif avis.id_avis_nature.nature == "Consultation en interne":
            if avis.id_expert and avis.id_expert.id_instructeur:
                expert = f"{avis.id_expert.id_instructeur} (Interne)"

        reponse = ""
        if avis.favorable :
            reponse = "Favorable"
        elif avis.favorable == False :
            reponse = "Défavorable"
        elif avis.statut == "Envoyé" :
            reponse = "En attente"

        # Messages non lus envoyés par l'expert
        if avis.id_expert.est_interne :
            email_expert = avis.id_expert.id_instructeur.email
        else :
            email_expert = avis.id_expert.id_contact_externe.email

        nb_messages_non_lus_avis = Message.objects.filter(id_avis=avis, lu=False, email_emetteur=email_expert).count()

        # Compteur d'avis avec des nouveaux messages
        if nb_messages_non_lus_avis > 0:
            nb_avis_avec_nouveau_mess += 1

        # Construire le dictionnaire
        liste_avis.append({
            "statut": avis.statut,
            "expert": expert or "N/A",
            "numero": avis.id,
            "demandeur": f"{avis.id_instructeur.id_agent_autorisations.nom} {avis.id_instructeur.id_agent_autorisations.prenom}" if avis.id_instructeur else "N/A",
            "date_demande": avis.date_demande_avis,
            "date_reponse": avis.date_reponse_avis,
            "favorable": reponse,
            "avis_nb_messages_non_lus": nb_messages_non_lus_avis,
        })

    liste_avis = sorted(
        liste_avis,
        key=lambda x: (x["statut"] == "Envoyé",
                    x["date_demande"]),
        reverse=True  # Pour mettre la date en décroissant
    )

    # Nombre d'avis envoyés
    nb_avis_envoyes = DossierAvis.objects.filter(id_dossier=dossier, id_avis__statut="Envoyé").count()

    # Messages non lus
    nb_messages_non_lus = Message.objects.filter(
        id_dossier=dossier,
        lu=False
    ).exclude(
        email_emetteur='contact@demarches-simplifiees.fr'
    ).exclude(
        email_emetteur__endswith='reunion-parcnational.fr'
    ).count()

    return render(request, "instruction/instruction_dossier_consultation.html", {
        "ROOT_FOLDER": os.getenv('ROOT_FOLDER'),
        "dossier": dossier,
        "is_formulaire_active": False,
        "is_messagerie_active": False,
        "is_consultation_active": True,
        "avis": liste_avis,
        "nb_avis_envoyes": nb_avis_envoyes,
        "nb_messages_non_lus": nb_messages_non_lus,
        "nb_avis_avec_nouveau_mess": nb_avis_avec_nouveau_mess,
    })


@login_required
def instruction_dossier_ajouter_avis(request, num_dossier, avis_id=None):
    dossier = get_object_or_404(Dossier, numero=num_dossier)

    avis = None
    if avis_id:
        avis = get_object_or_404(Avis, id=avis_id, id_dossier=dossier)

    # Récupérer toutes les natures et thématiques
    natures = AvisNature.objects.all().order_by("nature")
    thematiques = AvisThematique.objects.all().order_by("thematique")

    # Instructeur courant (user connecté)
    instructeur_connecte = Instructeur.objects.filter(email=request.user.email).first()

    # Tous les avis déjà envoyés pour ce dossier
    avis_existants = Avis.objects.filter(id_dossier=dossier, statut="Envoyé")

    # Extraire les instructeurs et contacts déjà utilisés
    instructeurs_utilises = avis_existants.filter(id_expert__id_instructeur__isnull=False) \
                                          .values_list("id_expert__id_instructeur__email", flat=True)
    contacts_utilises = avis_existants.filter(id_expert__id_contact_externe__isnull=False) \
                                      .values_list("id_expert__id_contact_externe__email", flat=True)


    # Instructeurs candidats
    instructeurs_qs = (
        Instructeur.objects
        .filter(email__isnull=False)
        .exclude(email__exact="")
        .exclude(email=request.user.email)  # pas soi-même
        .exclude(email__in=instructeurs_utilises)  # pas déjà utilisé
        .order_by("email")
    )

    # Contacts externes candidats
    contacts_qs = (
        ContactExterne.objects
        .filter(email__isnull=False)
        .exclude(email__exact="")
        .exclude(email=request.user.email)  # pas soi-même
        .exclude(email__in=contacts_utilises)  # pas déjà utilisé
        .exclude(id_type__type__in=["Demandeur intermédiaire", "Bénéficiaire"])  # on ne veut pas les demandeurs, juste les potentiels experts
        .order_by("nom", "email")
    )

    # Supprimer les doublons d'email (si jamais)
    instructeurs = {i.email: i for i in instructeurs_qs}.values()
    contacts_externes = {c.email: c for c in contacts_qs}.values()

    # Nombre d'avis envoyés
    nb_avis_envoyes = DossierAvis.objects.filter(id_dossier=dossier, id_avis__statut="Envoyé").count()

    # Messages non lus
    nb_messages_non_lus = Message.objects.filter(
        id_dossier=dossier,
        lu=False
    ).exclude(
        email_emetteur='contact@demarches-simplifiees.fr'
    ).exclude(
        email_emetteur__endswith='reunion-parcnational.fr'
    ).count()

    # Nombre d'avis avec au moins un message non lu de l'expert
    nb_avis_avec_nouveau_mess = 0
    for da in DossierAvis.objects.filter(id_dossier=dossier).select_related("id_avis__id_expert"):
        avis_item = da.id_avis
        if not avis_item or not avis_item.id_expert:
            continue

        if avis_item.id_expert.est_interne:
            email_expert = avis_item.id_expert.id_instructeur.email
        else:
            email_expert = avis_item.id_expert.id_contact_externe.email

        nb_non_lus_avis = Message.objects.filter(
            id_avis=avis_item,
            lu=False,
            email_emetteur=email_expert
        ).count()

        if nb_non_lus_avis > 0:
            nb_avis_avec_nouveau_mess += 1


    return render(request, "instruction/instruction_dossier_ajouter_avis.html", {
        "dossier": dossier,
        "avis": avis,
        "natures": natures,
        "thematiques": thematiques,
        "instructeurs": instructeurs,
        "contacts_externes": contacts_externes,
        "is_formulaire_active": False,
        "is_messagerie_active": False,
        "is_consultation_active": True,
        "nb_avis_envoyes": nb_avis_envoyes,
        "nb_messages_non_lus": nb_messages_non_lus,
        "nb_avis_avec_nouveau_mess": nb_avis_avec_nouveau_mess,
        "ROOT_FOLDER": os.getenv('ROOT_FOLDER'),
    })


@login_required
def instruction_dossier_ajouter_avis_existant(request, num_dossier):
    dossier = get_object_or_404(Dossier, numero=num_dossier)

    # Récupérer toutes les natures et thématiques
    natures = AvisNature.objects.all().order_by("nature")
    thematiques = AvisThematique.objects.all().order_by("thematique")

    # Tous les instructeurs
    tous_les_instructeurs = Instructeur.objects.all()

    # Instructeur courant (user connecté)
    instructeur_connecte = Instructeur.objects.filter(email=request.user.email).first()

    # Tous les avis déjà envoyés pour ce dossier
    avis_existants = Avis.objects.filter(id_dossier=dossier, statut="Envoyé")

    # Extraire les instructeurs et contacts déjà utilisés
    instructeurs_utilises = avis_existants.filter(id_expert__id_instructeur__isnull=False) \
                                          .values_list("id_expert__id_instructeur__email", flat=True)
    # contacts_utilises = avis_existants.filter(id_expert__id_contact_externe__isnull=False) \
    #                                   .values_list("id_expert__id_contact_externe__email", flat=True)

    # Instructeurs candidats
    instructeurs_qs = (
        Instructeur.objects
        .filter(email__isnull=False)
        .exclude(email__exact="")
        .exclude(email=request.user.email)  # pas soi-même
        .exclude(email__in=instructeurs_utilises)  # pas déjà utilisé
        .order_by("email")
    )

    # Contacts externes candidats
    contacts_qs = (
        ContactExterne.objects
        .filter(email__isnull=False)
        .exclude(email__exact="")
        .exclude(email=request.user.email)  # pas soi-même
        # .exclude(email__in=contacts_utilises)  # pas déjà utilisé
        .exclude(id_type__type__in=["Demandeur intermédiaire", "Bénéficiaire"])
        .order_by("nom", "email")
    )

    # Supprimer les doublons d'email (si jamais)
    instructeurs = {i.email: i for i in instructeurs_qs}.values()
    contacts_externes = {c.email: c for c in contacts_qs}.values()

    # Nombre d'avis envoyés
    # nb_avis_envoyes = DossierAvis.objects.filter(id_dossier=dossier, id_avis__statut="Envoyé").count()

    # Messages non lus
    nb_messages_non_lus = Message.objects.filter(
        id_dossier=dossier,
        lu=False
    ).exclude(
        email_emetteur='contact@demarches-simplifiees.fr'
    ).exclude(
        email_emetteur__endswith='reunion-parcnational.fr'
    ).count()

    # Nombre d'avis avec au moins un message non lu de l'expert
    nb_avis_avec_nouveau_mess = 0
    for da in DossierAvis.objects.filter(id_dossier=dossier).select_related("id_avis__id_expert"):
        avis_item = da.id_avis
        if not avis_item or not avis_item.id_expert:
            continue

        if avis_item.id_expert.est_interne:
            email_expert = avis_item.id_expert.id_instructeur.email
        else:
            email_expert = avis_item.id_expert.id_contact_externe.email

        nb_non_lus_avis = Message.objects.filter(
            id_avis=avis_item,
            lu=False,
            email_emetteur=email_expert
        ).count()

        if nb_non_lus_avis > 0:
            nb_avis_avec_nouveau_mess += 1

    
    # ----------------------------
    # PARTIE RECHERCHE D’AVIS
    # ----------------------------
    avis_list = None
    if request.GET:  # seulement si une recherche est soumise
        avis_list = Avis.objects.all().select_related("id_avis_nature", "id_avis_thematique", "id_expert", "id_instructeur")

        numero = request.GET.get("numero")
        expert = request.GET.get("expert")
        demandeur = request.GET.get("demandeur")
        date_demande = request.GET.get("date_demande")
        date_reponse = request.GET.get("date_reponse")
        favorable = request.GET.get("favorable")
        thematique = request.GET.get("thematique")
        nature = request.GET.get("nature")
        deja_lie = request.GET.get("deja_lie")
        statut = request.GET.get("statut")

        if numero:
            avis_list = avis_list.filter(id=numero)
        if expert:
            avis_list = avis_list.filter(id_expert=expert)
        if demandeur:
            avis_list = avis_list.filter(id_instructeur=demandeur)
        if date_demande:
            avis_list = avis_list.filter(date_demande_avis__date=date_demande)
        if date_reponse:
            avis_list = avis_list.filter(date_reponse_avis__date=date_reponse)
        if favorable in ["true", "false"]:
            avis_list = avis_list.filter(favorable=(favorable == "true"))
        if thematique:
            avis_list = avis_list.filter(id_avis_thematique=thematique)
        if nature:
            avis_list = avis_list.filter(id_avis_nature=nature)
        if statut:
            avis_list = avis_list.filter(statut=statut)
        
        # Sous-requête : avis liés à CE dossier -> exclusion
        subquery_dossier = DossierAvis.objects.filter(id_avis=OuterRef("pk"), id_dossier=dossier)
        avis_list = avis_list.annotate(deja_lie_ce_dossier=Exists(subquery_dossier)).filter(deja_lie_ce_dossier=False)

        # Sous-requête pour vérifier l’existence d’un lien DossierAvis
        subquery = DossierAvis.objects.filter(id_avis=OuterRef("pk"))
        if deja_lie == "1":
            avis_list = avis_list.annotate(deja_lie=Exists(subquery)).filter(deja_lie=True)
        elif deja_lie == "0":
            avis_list = avis_list.annotate(deja_lie=Exists(subquery)).filter(deja_lie=False)

        # tri + limitation à 20 avis
        avis_list = avis_list.order_by("-date_demande_avis")[:20]

    return render(request, "instruction/instruction_dossier_ajouter_avis_existant.html", {
        "dossier": dossier,
        "natures": natures,
        "thematiques": thematiques,
        "instructeurs": instructeurs,
        "tous_les_instructeurs": tous_les_instructeurs,
        "contacts_externes": contacts_externes,
        "is_formulaire_active": False,
        "is_messagerie_active": False,
        "is_consultation_active": True,
        # "nb_avis_envoyes": nb_avis_envoyes,
        "nb_messages_non_lus": nb_messages_non_lus,
        "nb_avis_avec_nouveau_mess": nb_avis_avec_nouveau_mess,
        "ROOT_FOLDER": os.getenv('ROOT_FOLDER'),
        "avis_list": avis_list,
    })


@login_required
def lier_dossier_avis(request, num_dossier, avis_id):
    dossier = get_object_or_404(Dossier, numero=num_dossier)
    avis = get_object_or_404(Avis, id=avis_id)

    if request.method == "POST":
        try:
            # Vérifie si déjà lié
            existe = DossierAvis.objects.filter(id_dossier=dossier, id_avis=avis).exists()
            if not existe:
                DossierAvis.objects.create(id_dossier=dossier, id_avis=avis)
            else:
                messages.warning(request, f"L'avis {avis.id} est déjà lié à ce dossier.")

        except Exception as e:
            messages.error(request, f"Une erreur est survenue lors de l’association de l’avis : {str(e)}")
            return redirect(request.META.get("HTTP_REFERER", "/"))

        # Redirection vers la consultation
        return redirect("instruction_dossier_consultation", num_dossier=dossier.numero)

    return redirect("instruction_dossier_ajouter_avis_existant", num_dossier=dossier.numero)



@login_required
def ajouter_avis_hors_appli(request, num_dossier):
    dossier = get_object_or_404(Dossier, numero=num_dossier)
    # instructeur = Instructeur.objects.filter(email=request.user.email).first()

    if request.method == "POST":
        try:
            # 1. Récupérer les champs du formulaire
            nature_id = request.POST.get("nature")
            thematique_id = request.POST.get("thematique")
            mode_contact = request.POST.get("mode_contact")
            favorable = request.POST.get("favorable") == "true"
            note = request.POST.get("note_demandeur")
            date_demande_avis = parse_datetime(request.POST.get("date_demande_avis")) if request.POST.get("date_demande_avis") else None
            date_reponse_avis = parse_datetime(request.POST.get("date_reponse_avis")) if request.POST.get("date_reponse_avis") else None
            instructeur_demandeur_id = request.POST.get("demandeur_avis")
            expert_interne = request.POST.get("expert_interne")
            expert_externe = request.POST.get("expert_externe")
            

            # Normalisation nom_prenom expert + Recupération Expert
            expert = None
            if expert_externe:
                try:
                    contact = ContactExterne.objects.get(id=expert_externe)
                    if contact.nom and contact.prenom :
                        nom_prenom_expert = nettoyer_nom_fichier(f"{contact.nom}_{contact.prenom}")
                    elif contact.raison_sociale :
                        nom_prenom_expert = nettoyer_nom_fichier(f"{contact.raison_sociale}")
                    elif contact.organisation :
                        nom_prenom_expert = nettoyer_nom_fichier(f"{contact.organisation}")
                    else :
                        nom_prenom_expert = f""

                except Exception as e:
                    messages.error(request, f"Erreur lors de la récupération de l'expert externe : {e}")
                    return redirect(request.META.get("HTTP_REFERER", "/"))
                
                expert, created = Expert.objects.get_or_create(
                    id_contact_externe_id=expert_externe,
                    defaults={"est_interne": False}
                )

                if created:
                        logger.info(f"[EXPERT] Nouvel expert externe créé : {contact}")
                
            elif expert_interne:

                try:
                    instru = Instructeur.objects.get(id=expert_interne)
                    nom_prenom_expert = nettoyer_nom_fichier(f"{instru.id_agent_autorisations.nom}_{instru.id_agent_autorisations.prenom}")

                except Exception as e:
                    messages.error(request, f"Erreur lors de la récupération de l'expert interne : {e}")
                    return redirect(request.META.get("HTTP_REFERER", "/"))
                
                expert, created = Expert.objects.get_or_create(
                    id_instructeur=expert_interne,
                    defaults={"est_interne": True}
                )
                if created:
                    logger.info(f"[EXPERT] Nouvel expert interne créé : {instru}")

            
            instructeur_demandeur = None
            if instructeur_demandeur_id:
                instructeur_demandeur = Instructeur.objects.get(id=instructeur_demandeur_id)

            # Création emplacement
            emplacement = ""
            if nom_prenom_expert :  
                emplacement = f"{dossier.emplacement}Avis/{nom_prenom_expert}/"


            # 2. Créer l’avis
            # Construire la formulation
            formulation = f"Avis demandé par {instructeur_demandeur} à {expert}."
            if mode_contact and mode_contact.lower() != "autre":
                formulation += f" La demande d'avis a été faite en dehors de l'application par {mode_contact}."

            avis = Avis.objects.create(
                id_avis_nature_id=nature_id,
                id_avis_thematique_id=thematique_id,
                id_dossier=dossier,
                id_expert=expert,
                emplacement=emplacement,
                id_instructeur=instructeur_demandeur,
                mode_contact=mode_contact,
                statut="Envoyé",
                formulation=formulation,
                favorable=favorable,
                note=note,
                date_demande_avis=date_demande_avis,
                date_reponse_avis=date_reponse_avis,
            )
            
            # Pour le cas ou le contact (expert) externe n'a ni nom, ni prénom, ni raison sociale, ni organisation
            if not avis.emplacement:
                avis.emplacement = f"{dossier.emplacement}Avis/Avis_{avis.id}/"
                avis.save(update_fields=["emplacement"])


            # Formulation = Message par défaut
            if formulation :
                try:
                    msg = Message.objects.create(
                        body=avis.formulation,
                        date_envoi=timezone.now(),
                        piece_jointe=False,
                        email_emetteur=request.user.email,
                        id_avis=avis,
                        lu=False,
                    )
                except Exception as e:
                    logger.warning(f"[DOSSIER {dossier.numero}] Ajout Avis {avis.id} hors application : Le message automatique (qui est égal à avis.formulation) n'a pas pu être créé")

    

            # 3. Associer l’avis au dossier
            DossierAvis.objects.create(
                id_dossier=dossier,
                id_avis=avis
            )


            # 4. Gestion des pièces jointes
            fichiers = request.FILES.getlist("pj_lie_avis")
            if fichiers :
                chemin_complet = f"{os.getenv('ROOT_FOLDER')}{emplacement}Annexes/"
                os.makedirs(os.path.dirname(chemin_complet), exist_ok=True)
                
                # on parcourt les fichiers et on les écrit physiquement
                for pj in fichiers :
                    
                    doc_pj = enregistrer_document(
                        fichier=pj,
                        nature_str="Annexe avis",
                        description=f"Pièce jointe pour la demande d'avis {avis.id} effectuée en dehors de l'application",
                        request=request,
                        emplacement_avis = emplacement,
                    )

                    # Création AvisDocument
                    if doc_pj:
                        AvisDocument.objects.create(
                            id_avis=avis,
                            id_document=doc_pj
                        )

            return redirect("instruction_dossier_consultation", num_dossier=dossier.numero)

        except Exception as e:
            messages.error(request, f"Erreur lors de l'ajout de l'avis : {e}")
            
            return redirect(request.META.get("HTTP_REFERER", "/"))



@login_required
def ajouter_pj_avis(request, avis_id):
    # dossier = get_object_or_404(Dossier, numero=num_dossier)
    avis = get_object_or_404(Avis, id=avis_id)
    instructeur = Instructeur.objects.filter(email=request.user.email).first()

    if request.method == "POST":
        try:
            fichiers = request.FILES.getlist("pj_avis")
            if not fichiers:
                messages.warning(request, "⚠️ Aucun fichier sélectionné.")
                return redirect(request.META.get("HTTP_REFERER", "/"))

            for pj in fichiers:
                try:
                    doc_pj = enregistrer_document(
                        fichier=pj,
                        nature_str="Annexe avis",
                        description=f"Pièce jointe ajoutée à l'avis {avis.id} par {instructeur}",
                        request=request,
                        emplacement_avis=avis.emplacement,
                    )
                    if doc_pj:
                        AvisDocument.objects.get_or_create(id_avis=avis, id_document=doc_pj)
                    else:
                        messages.error(request, f"❌ Erreur lors de l’enregistrement du document {pj.name}.")
                except Exception as e:
                    messages.error(request, f"❌ Erreur sur le fichier {pj.name} : {e}")

        except Exception as e:
            messages.error(request, f"❌ Erreur inattendue lors de l'ajout des pièces jointes : {e}")

        return redirect(request.META.get("HTTP_REFERER", "/"))


@require_POST
@login_required
def supprimer_pj_avis(request, avis_id, document_id):
    avis_doc = get_object_or_404(AvisDocument, id_avis_id=avis_id, id_document_id=document_id)

    # Supprime le lien Avis ↔ Document
    doc = avis_doc.id_document
    avis_doc.delete()

    # Supprime physiquement le document (optionnel si tu veux garder une trace)
    doc.delete()

    logger.info(f"[AVIS {avis_id}] Pièce jointe {doc.titre} supprimée par {request.user}")

    return redirect(request.META.get("HTTP_REFERER", "/"))


@require_POST
@login_required
def instruction_dossier_confirmer_ajout_avis(request, num_dossier, avis_id=None):
    
    try:
        instructeur = Instructeur.objects.filter(email=request.user.email).first()
        if not instructeur:
            messages.error(request, f"Aucun instructeur.rice n'est associé.e à votre profil : {e}")
            return redirect(request.META.get("HTTP_REFERER", "/"))
    except Exception as e:
        messages.error(request, f"Erreur lors de la récupération de l'instructeur : {e}")
        return redirect(request.META.get("HTTP_REFERER", "/"))
    
    # Récupérer le dossier
    dossier = get_object_or_404(Dossier, numero=num_dossier)

    # Si on reçoit un brouillon d'avis existant
    brouillon_avis = None
    if avis_id:
        brouillon_avis = get_object_or_404(Avis, id=avis_id, id_dossier=dossier)

    if request.method == "POST":
        # Champs du formulaire
        nature_id = request.POST.get("nature")
        thematique_id = request.POST.get("thematique")
        note = request.POST.get("note_demandeur", "").strip()
        mode_contact = request.POST.get("mode_contact")
        formulation_avis = request.POST.get("formulation_avis")
        expert_interne_id = request.POST.get("expert_interne") # instructeur ici 
        expert_externe_id = request.POST.get("expert_externe") # contact externe ici
        pj_projet_avis = request.FILES.get("pj_demande_avis")
        pj_projet_acte = request.FILES.get("pj_projet_acte")
        pj_rapport_cs = request.FILES.get("pj_rapport_cs")

        try:
            nature = AvisNature.objects.get(id=nature_id)
        except Exception as e:
            messages.error(request, f"Erreur lors de la récupération de la nature d'avis : {e}")
            return redirect(request.META.get("HTTP_REFERER", "/"))

        try:
            thematique = AvisThematique.objects.get(id=thematique_id)
        except Exception as e:
            messages.error(request, f"Erreur lors de la récupération de la thématique de l'avis : {e}")
            return redirect(request.META.get("HTTP_REFERER", "/"))
    
        if expert_interne_id:
            try:
                instru = Instructeur.objects.get(id=expert_interne_id)
                expert, created = Expert.objects.get_or_create(
                    id_instructeur=instru,
                    defaults={"est_interne": True}
                )
                if created:
                    logger.info(f"[EXPERT] Nouvel expert interne créé : {instru}")
                
                nom_prenom_expert = nettoyer_nom_fichier(f"{instru.id_agent_autorisations.nom}_{instru.id_agent_autorisations.prenom}")

            except Exception as e:
                messages.error(request, f"Erreur lors de la récupération de l'expert interne : {e}")
                return redirect(request.META.get("HTTP_REFERER", "/"))
        
            
        elif expert_externe_id:
            try:
                contact = ContactExterne.objects.get(id=expert_externe_id)
                expert, created = Expert.objects.get_or_create(
                    id_contact_externe=contact,
                    defaults={"est_interne": False}
                )
                if created:
                    logger.info(f"[EXPERT] Nouvel expert externe créé : {contact}")

                if contact.nom and contact.prenom :
                    nom_prenom_expert = nettoyer_nom_fichier(f"{contact.nom}_{contact.prenom}")
                elif contact.raison_sociale :
                    nom_prenom_expert = nettoyer_nom_fichier(f"{contact.raison_sociale}")
                elif contact.organisation :
                    nom_prenom_expert = nettoyer_nom_fichier(f"{contact.organisation}")
                else :
                    nom_prenom_expert = f"Avis_{avis_id}"


            except Exception as e:
                messages.error(request, f"Erreur lors de la récupération de l'expert externe : {e}")
                return redirect(request.META.get("HTTP_REFERER", "/"))
        

        doc_projet_acte = doc_rapport_instance = doc_projet_avis = None

        # On récupère l'emplacement physique de l'avis
        if brouillon_avis :
            if not brouillon_avis.emplacement :
                emplacement = f"{dossier.emplacement}Avis/{nom_prenom_expert}/"
            else :
                emplacement = brouillon_avis.emplacement
        else :
            emplacement = f"{dossier.emplacement}Avis/{nom_prenom_expert}/"
        
        # Si 1 des 3 fichiers est non null (on va pas créer d'emplacements pour les consult' internes sans docs par exemple)
        if pj_projet_avis or pj_projet_acte or pj_rapport_cs :
            
            chemin_complet = f"{os.getenv('ROOT_FOLDER')}{emplacement}Annexes/"
            os.makedirs(os.path.dirname(chemin_complet), exist_ok=True)

            if pj_projet_avis :
                extension = Path(pj_projet_avis.name).suffix.lower()
                if extension not in {".doc", ".docx", ".odt"} :
                    messages.error(request, f"❌ Le projet de demande d'avis doit etre au format .doc ou .docx ou .odt --> Type de fichier non autorisé : {extension}")
                    return redirect(request.META.get("HTTP_REFERER", "/"))
                
                doc_projet_avis = enregistrer_document(
                    fichier=pj_projet_avis,
                    nature_str="Annexe avis",
                    description=f"Projet de demande pour l'avis {avis_id}",
                    request=request,
                    emplacement_avis = emplacement,
                )
            
            if pj_projet_acte :
                extension = Path(pj_projet_acte.name).suffix.lower()
                if extension != ".pdf" :
                    messages.error(request, f"❌ Le projet d'acte doit etre au format .pdf --> Type de fichier non autorisé : {extension}")
                    return redirect(request.META.get("HTTP_REFERER", "/"))
                
                doc_projet_acte = enregistrer_document(
                    fichier=pj_projet_acte,
                    nature_str="Annexe avis",
                    description=f"Projet d’acte pour l'avis {avis_id}",
                    request=request,
                    emplacement_avis = emplacement,
                )
            
            if pj_rapport_cs :
                extension = Path(pj_rapport_cs.name).suffix.lower()
                if extension != ".pdf" :
                    messages.error(request, f"❌ Le rapport de l'instance doit etre au format .pdf --> Type de fichier non autorisé : {extension}")
                    return redirect(request.META.get("HTTP_REFERER", "/"))
                
                doc_rapport_instance = enregistrer_document(
                    fichier=pj_rapport_cs,
                    nature_str="Annexe avis",
                    description=f"Rapport Instance pour l'avis {avis_id}",
                    request=request,
                    emplacement_avis = emplacement,
                )

        # Brouillon deja existant
        if brouillon_avis :

            fields_to_update = {
                "id_avis_nature": nature,
                "id_avis_thematique": thematique,
                "id_expert": expert,
                "statut": "Envoyé",
                "date_demande_avis": timezone.now(),
                "note": note,
                "formulation": formulation_avis,
                "mode_contact": mode_contact,
                "emplacement": emplacement,
            }

            # Ajouter uniquement les docs non-nuls
            if doc_projet_acte:
                fields_to_update["id_projet_acte"] = doc_projet_acte
            if doc_rapport_instance:
                fields_to_update["id_rapport_instance"] = doc_rapport_instance
            if doc_projet_avis:
                fields_to_update["id_projet_avis"] = doc_projet_avis

            try:

                updated_fields = update_fields(brouillon_avis, fields_to_update)

                if updated_fields:
                    brouillon_avis.save(update_fields=updated_fields)
                    logger.info(
                        f"[DOSSIER {dossier.numero}] Brouillon d'avis ({brouillon_avis}) mis à jour. "
                        f"Changements: {', '.join(updated_fields)}"
                    )
            except Exception as e:
                logger.error(f"[DOSSIER {dossier.numero}] Avis {brouillon_avis.id} : Message supprimé car il y a eu une erreur lors de l'envoi de l'avis")
                messages.error(request, f"[ENVOI AVIS DOSSIER {dossier.numero}] Erreur lors de la mise à jour de l'avis {brouillon_avis} : {e}")
                return redirect(request.META.get("HTTP_REFERER", "/"))
            
            # Create message (formulation) + projet demande d'avis en PJ si il existe
            try:
                msg = Message.objects.create(
                    body=brouillon_avis.formulation,
                    date_envoi=timezone.now(),
                    piece_jointe=True if doc_projet_avis else False,
                    email_emetteur=request.user.email,
                    id_avis=brouillon_avis,
                    lu=False,
                )

                # Joindre le projet de demande d'avis au message
                if doc_projet_avis :
                    MessageDocument.objects.create(
                        id_message=msg,
                        id_document=doc_projet_avis
                    )

                logger.info(f"[DOSSIER {dossier.numero}] Avis {brouillon_avis.id} : message envoyé à {brouillon_avis.id_expert}")

            except Exception as e:
                brouillon_avis.statut = "Brouillon"
                brouillon_avis.save()
                messages.error(request, f"Avis non transmis : Erreur lors de la création du message par défaut (formulation avis): {e}")
                return redirect(request.META.get("HTTP_REFERER", "/"))

            # NOTIF MAIL à l'expert
        
        # Pas de Brouillon existant
        else :
            try:

                avis = Avis.objects.create(
                        id_avis_nature=nature,
                        id_avis_thematique=thematique,
                        date_demande_avis=timezone.now(),
                        statut="Envoyé",
                        note=note,
                        formulation= formulation_avis,
                        mode_contact=mode_contact,
                        id_dossier=dossier,
                        id_expert=expert,
                        id_instructeur=instructeur,
                        id_projet_acte=doc_projet_acte,
                        id_rapport_instance=doc_rapport_instance,
                        id_projet_avis=doc_projet_avis,
                        emplacement = emplacement,
                )

                logger.info(f"[DOSSIER {dossier.numero}] Brouillon de demande d'avis créé : {avis}")
            except Exception as e:
                messages.error(request, f"Erreur lors de la création de l'avis : {e}")
                return redirect(request.META.get("HTTP_REFERER", "/"))
        
            try:
                avis_dossier = DossierAvis.objects.create(
                    id_avis=avis,
                    id_dossier=dossier,
                )
            except Exception as e:
                messages.error(request, f"Erreur lors de la création du lien entre le dossier {dossier.numero} et {avis} : {e}")
                return redirect(request.META.get("HTTP_REFERER", "/"))
            
            # Create message (formulation)
            if avis.formulation :
                try:
                    msg = Message.objects.create(
                        body=avis.formulation,
                        date_envoi=timezone.now(),
                        piece_jointe=True if doc_projet_avis else False,
                        email_emetteur=request.user.email,
                        id_avis=avis,
                        lu=False,
                    )

                    # Joindre le projet de demande d'avis au message
                    if doc_projet_avis :
                        MessageDocument.objects.create(
                            id_message=msg,
                            id_document=doc_projet_avis
                        )

                    logger.info(f"[DOSSIER {dossier.numero}] Avis {avis.id} : message envoyé à {avis.id_expert}")

                except Exception as e:
                    avis.statut = "Brouillon"
                    avis.save()
                    messages.error(request, f"Avis non transmis : Erreur lors de la création du message par défaut (formulation avis): {e}")
                    return redirect(request.META.get("HTTP_REFERER", "/"))

        # NOTIF par MAIL à l'expert

    else :
        messages.error(request, f"Erreur lors de la transmission du formulaire : POST method required")
        return redirect(request.META.get("HTTP_REFERER", "/"))
    
    return redirect('instruction_dossier_consultation', num_dossier=num_dossier)



@require_POST
@login_required
def instruction_dossier_enregistrer_brouillon_avis(request, num_dossier, avis_id=None):

    try:
        instructeur = Instructeur.objects.filter(email=request.user.email).first()
        if not instructeur:
            messages.error(request, f"Aucun instructeur.rice n'est associé.e à votre profil : {e}")
            return redirect(request.META.get("HTTP_REFERER", "/"))
    except Exception as e:
        messages.error(request, f"Erreur lors de la récupération de l'instructeur : {e}")
        return redirect(request.META.get("HTTP_REFERER", "/"))
    
    # Récupérer le dossier
    dossier = get_object_or_404(Dossier, numero=num_dossier)

    # Si on reçoit un brouillon d'avis existant
    brouillon_avis = None
    if avis_id:
        brouillon_avis = get_object_or_404(Avis, id=avis_id, id_dossier=dossier)

    if request.method == "POST":
        # Champs du formulaire
        nature_id = request.POST.get("nature")
        thematique_id = request.POST.get("thematique")
        note = request.POST.get("note_demandeur", "").strip()
        mode_contact = request.POST.get("mode_contact")
        formulation_avis = request.POST.get("formulation_avis")
        expert_interne_id = request.POST.get("expert_interne") # instructeur ici 
        expert_externe_id = request.POST.get("expert_externe") # contact externe ici
        pj_projet_avis = request.FILES.get("pj_demande_avis")
        pj_projet_acte = request.FILES.get("pj_projet_acte")
        pj_rapport_cs = request.FILES.get("pj_rapport_cs")  

        # fichiers a reprendre
        fichier = request.FILES.get("pj_avis")
        if fichier :
            extension = Path(fichier.name).suffix.lower()
            if extension not in {".pdf", ".doc", ".docx", ".odt"} :
                messages.error(request, f"❌ Le fichier joint doit etre .pdf ou .doc ou .docx ou .odt --> Type de fichier non autorisé : {extension}")
                return redirect(request.META.get("HTTP_REFERER", "/"))

        try:
            nature = AvisNature.objects.get(id=nature_id)
        except Exception as e:
            messages.error(request, f"Erreur lors de la récupération de la nature d'avis : {e}")
            return redirect(request.META.get("HTTP_REFERER", "/"))

        try:
            thematique = AvisThematique.objects.get(id=thematique_id)
        except Exception as e:
            messages.error(request, f"Erreur lors de la récupération de la thématique de l'avis : {e}")
            return redirect(request.META.get("HTTP_REFERER", "/"))
    
        if expert_interne_id:
            try:
                instru = Instructeur.objects.get(id=expert_interne_id)
                expert, created = Expert.objects.get_or_create(
                    id_instructeur=instru,
                    defaults={"est_interne": True}
                )
                if created:
                    logger.info(f"[EXPERT] Nouvel expert interne créé : {instru}")
                
                nom_prenom_expert = nettoyer_nom_fichier(f"{instru.id_agent_autorisations.nom}_{instru.id_agent_autorisations.prenom}")

            except Exception as e:
                messages.error(request, f"Erreur lors de la récupération de l'expert interne : {e}")
                return redirect(request.META.get("HTTP_REFERER", "/"))
        
            
        elif expert_externe_id:
            try:
                contact = ContactExterne.objects.get(id=expert_externe_id)
                expert, created = Expert.objects.get_or_create(
                    id_contact_externe=contact,
                    defaults={"est_interne": False}
                )
                if created:
                    logger.info(f"[EXPERT] Nouvel expert externe créé : {contact}")

                if contact.nom and contact.prenom :
                    nom_prenom_expert = nettoyer_nom_fichier(f"{contact.nom}_{contact.prenom}")
                elif contact.raison_sociale :
                    nom_prenom_expert = nettoyer_nom_fichier(f"{contact.raison_sociale}")
                elif contact.organisation :
                    nom_prenom_expert = nettoyer_nom_fichier(f"{contact.organisation}")
                else :
                    nom_prenom_expert = f"Avis_{avis_id}"

            except Exception as e:
                messages.error(request, f"Erreur lors de la récupération de l'expert externe : {e}")
                return redirect(request.META.get("HTTP_REFERER", "/"))
            

        emplacement = ""
        doc_projet_acte = doc_rapport_instance = doc_projet_avis = None
        # Si 1 des 3 fichiers est non null (on va pas créer d'emplacements pour les consult' internes sans docs par exemple)
        if pj_projet_avis or pj_projet_acte or pj_rapport_cs :
            
            # On récupère l'emplacement physique de l'avis
            if brouillon_avis :
                if not brouillon_avis.emplacement :
                    emplacement = f"{dossier.emplacement}Avis/{nom_prenom_expert}/"
                else :
                    emplacement = brouillon_avis.emplacement
            else :
                emplacement = f"{dossier.emplacement}Avis/{nom_prenom_expert}/"
            
            chemin_complet = f"{os.getenv('ROOT_FOLDER')}{emplacement}Annexes/"
            os.makedirs(os.path.dirname(chemin_complet), exist_ok=True)

            if pj_projet_avis :
                extension = Path(pj_projet_avis.name).suffix.lower()
                if extension not in {".doc", ".docx", ".odt"} :
                    messages.error(request, f"❌ Le projet de demande d'avis doit etre au format .doc ou .docx ou .odt --> Type de fichier non autorisé : {extension}")
                    return redirect(request.META.get("HTTP_REFERER", "/"))
                
                doc_projet_avis = enregistrer_document(
                    fichier=pj_projet_avis,
                    nature_str="Annexe avis",
                    description=f"Projet de demande pour l'avis {avis_id}",
                    request=request,
                    emplacement_avis = emplacement,
                )
            
            if pj_projet_acte :
                extension = Path(pj_projet_acte.name).suffix.lower()
                if extension != ".pdf" :
                    messages.error(request, f"❌ Le projet d'acte doit etre au format .pdf --> Type de fichier non autorisé : {extension}")
                    return redirect(request.META.get("HTTP_REFERER", "/"))
                
                doc_projet_acte = enregistrer_document(
                    fichier=pj_projet_acte,
                    nature_str="Annexe avis",
                    description=f"Projet d’acte pour l'avis {avis_id}",
                    request=request,
                    emplacement_avis = emplacement,
                )
            
            if pj_rapport_cs :
                extension = Path(pj_rapport_cs.name).suffix.lower()
                if extension != ".pdf" :
                    messages.error(request, f"❌ Le rapport de l'instance doit etre au format .pdf --> Type de fichier non autorisé : {extension}")
                    return redirect(request.META.get("HTTP_REFERER", "/"))
                
                doc_rapport_instance = enregistrer_document(
                    fichier=pj_rapport_cs,
                    nature_str="Annexe avis",
                    description=f"Rapport Instance pour l'avis {avis_id}",
                    request=request,
                    emplacement_avis = emplacement,
                )
                
        
        # Brouillon deja existant
        if brouillon_avis :
            fields_to_update = {
                "id_avis_nature": nature,
                "id_avis_thematique": thematique,
                "id_expert": expert,
                "note": note,
                "formulation": formulation_avis,
                "mode_contact": mode_contact,
                "emplacement": emplacement,
            }

            # Ajouter uniquement les docs non-nuls
            if doc_projet_acte:
                fields_to_update["id_projet_acte"] = doc_projet_acte
            if doc_rapport_instance:
                fields_to_update["id_rapport_instance"] = doc_rapport_instance
            if doc_projet_avis:
                fields_to_update["id_projet_avis"] = doc_projet_avis

            try:

                updated_fields = update_fields(brouillon_avis, fields_to_update)

                if updated_fields:
                    brouillon_avis.save(update_fields=updated_fields)
                    logger.info(
                        f"[DOSSIER {dossier.numero}] Brouillon d'avis ({brouillon_avis}) mis à jour. "
                        f"Changements: {', '.join(updated_fields)}"
                    )
            except Exception as e:
                messages.error(request, f"[ENVOI AVIS DOSSIER {dossier.numero}] Erreur lors de la mise à jour de l'avis {brouillon_avis} : {e}")
                return redirect(request.META.get("HTTP_REFERER", "/"))
        
        # Création du Brouillon
        else:
            try:
                avis = Avis.objects.create(
                        id_avis_nature=nature,
                        id_avis_thematique=thematique,
                        date_demande_avis=timezone.now(),
                        statut="Brouillon",
                        note=note,
                        formulation= formulation_avis,
                        mode_contact=mode_contact,
                        id_dossier=dossier,
                        id_expert=expert,
                        id_instructeur=instructeur,
                        id_projet_acte=doc_projet_acte,
                        id_rapport_instance=doc_rapport_instance,
                        id_projet_avis=doc_projet_avis,
                        emplacement = emplacement
                )

                logger.info(f"[DOSSIER {dossier.numero}] Brouillon de demande d'avis créé : {avis}")

                        
            except Exception as e:
                messages.error(request, f"Erreur lors de la création de l'avis : {e}")
                return redirect(request.META.get("HTTP_REFERER", "/"))
            
            try:
                DossierAvis.objects.create(id_avis=avis, id_dossier=dossier)

            except Exception as e:
                messages.error(request, f"Erreur lors de la création du lien entre le dossier {dossier.numero} et {avis} : {e}")
                return redirect(request.META.get("HTTP_REFERER", "/"))
            
            
    else :
        messages.error(request, f"Erreur lors de la transmission du formulaire : POST method required")
        return redirect(request.META.get("HTTP_REFERER", "/"))

    return redirect('instruction_dossier_consultation', num_dossier=num_dossier)



@require_POST
@login_required
def supprimer_avis(request):

    avis_id = request.POST.get("avis_id")
    avis = get_object_or_404(Avis, id=avis_id)

    try:
        avis.delete()
        logger.info(f"Suppression de l'avis ({avis_id}) : {avis}")
    except Exception as e:
        messages.error(request, f"Erreur lors de la suppression de l'avis {avis} : {e}")

    return redirect(request.META.get("HTTP_REFERER", "/"))



@login_required
def instruction_dossier_avis(request, num_dossier, avis_id):

    # Récupérer le dossier et l'avis
    dossier = get_object_or_404(Dossier, numero=num_dossier)
    avis = get_object_or_404(Avis, id=avis_id)
    instructeur = Instructeur.objects.filter(email=request.user.email).first()

    # Liste des emails des instructeurs du dossier
    # liste_email_instructeurs = [
    #     i.email for i in Instructeur.objects.filter(dossierinstructeur__id_dossier=dossier)
    # ]

    est_instructeur_du_dossier = DossierInstructeur.objects.filter(
        id_dossier=dossier,
        id_instructeur=instructeur
    ).exists()

    # Messages non lus envoyés par l'expert
    if avis.id_expert.est_interne :
        email_expert = avis.id_expert.id_instructeur.email
    else :
        email_expert = avis.id_expert.id_contact_externe.email

    messages_non_lus = (Message.objects.filter(id_avis=avis, lu=False, email_emetteur=email_expert))
    ids_non_lus = list(messages_non_lus.values_list("id", flat=True))

    # Affichage messages
    raw_messages = Message.objects.filter(id_avis=avis).order_by("date_envoi")
    messages_fmt = []

    # Mise à jour des mesages non lus --> lus
    if est_instructeur_du_dossier:
        nb = messages_non_lus.update(lu=True)
        if nb > 0:
            logger.info(f"[DOSSIER {dossier.numero}] {nb} message(s) non lus ont été marqués comme lus par {request.user}.")
    
    for msg in raw_messages:  
        nouv_mess = 'non'
        if ids_non_lus != []:
            if msg.id in ids_non_lus :
                nouv_mess = 'oui'

        emetteur = msg.email_emetteur.lower().strip()
        instru = Instructeur.objects.filter(email=emetteur).first()
        contact = ContactExterne.objects.filter(email=emetteur).first()


        # left = Message expert, right = Message émis par instructeur
        align = "right" if emetteur != email_expert.lower().strip() else "left"
        date_fmt = localtime(msg.date_envoi).strftime("%d/%m/%Y %H:%M") if msg.date_envoi else "Date inconnue"

        # Recherche de la pièce jointe liée au message
        pj_title = pj_emplacement = None
        if msg.piece_jointe:

            message_doc = MessageDocument.objects.filter(id_message=msg).select_related("id_document").first()
            if message_doc and message_doc.id_document:   
                pj_title, pj_emplacement = message_doc.id_document.titre, message_doc.id_document.emplacement

        messages_fmt.append({"id": msg.id, "body": msg.body, "date_envoi": date_fmt, "align": align, "pj_title": pj_title, "pj_emplacement": pj_emplacement, "nouv_mess": nouv_mess, "emetteur": instru if instru else contact})

    # Nombre d'avis envoyés
    nb_avis_envoyes = DossierAvis.objects.filter(id_dossier=dossier, id_avis__statut="Envoyé").count()

    # Messages non lus
    nb_messages_non_lus = Message.objects.filter(
        id_dossier=dossier,
        lu=False
    ).exclude(
        email_emetteur='contact@demarches-simplifiees.fr'
    ).exclude(
        email_emetteur__endswith='reunion-parcnational.fr'
    ).count()

    resume_pdf_titre = f"dossier-{dossier.numero}.pdf"

    # Nombre d'avis avec au moins un message non lu de l'expert
    nb_avis_avec_nouveau_mess = 0
    for da in DossierAvis.objects.filter(id_dossier=dossier).select_related("id_avis__id_expert"):
        avis_item = da.id_avis
        if not avis_item or not avis_item.id_expert:
            continue

        if avis_item.id_expert.est_interne:
            email_expert_item = avis_item.id_expert.id_instructeur.email
        else:
            email_expert_item = avis_item.id_expert.id_contact_externe.email

        nb_non_lus_avis = Message.objects.filter(
            id_avis=avis_item,
            lu=False,
            email_emetteur=email_expert_item
        ).count()

        if nb_non_lus_avis > 0:
            nb_avis_avec_nouveau_mess += 1

        # Avis Document
        avis_documents = (
            AvisDocument.objects.filter(id_avis=avis)
            .select_related("id_document", "id_document__id_nature")
            .exclude(id_document__id_nature__nature="Avis instance") #pour ne pas prendre l'avis signé
        )

        # Liste avis_documents
        liste_avis_documents = [
            {
                "titre": ad.id_document.titre,
                "emplacement": ad.id_document.emplacement,
                "format": ad.id_document.id_format.format,
                "nature": ad.id_document.id_nature.nature,
            }
            for ad in avis_documents
        ]
    
    # Avis signés
    avis_signes = (
        Document.objects.filter(
            id__in=AvisDocument.objects.filter(
                id_avis=avis,
                id_document__id_nature__nature="Avis instance"
            ).values_list("id_document", flat=True)
        )
    )



    return render(request, 'instruction/instruction_dossier_avis.html', {
        "ROOT_FOLDER": os.getenv('ROOT_FOLDER'),
        "dossier": dossier,
        "avis": avis,
        "avis_documents": avis_documents,
        "liste_avis_documents": liste_avis_documents,
        "avis_signes": avis_signes,
        "messages_avis": messages_fmt,
        "is_formulaire_active": False,
        "is_messagerie_active": False,
        "is_consultation_active": True,
        "nb_avis_envoyes": nb_avis_envoyes,
        "est_instructeur_du_dossier": est_instructeur_du_dossier,
        "nb_messages_non_lus": nb_messages_non_lus,
        "resume_pdf_titre": resume_pdf_titre,
        "nb_avis_avec_nouveau_mess": nb_avis_avec_nouveau_mess,
    })



@require_POST
@csrf_exempt
def envoyer_message_avis(request):

    # Récupération message et PJ de l'instructeur
    avis_id = request.POST.get("avis_id")
    dossier_numero = request.POST.get("dossier_numero")
    body = request.POST.get("body")
    fichier = request.FILES.get("piece_jointe")

    if not body:
        messages.error(request, "Message vide")
        return redirect(request.META.get("HTTP_REFERER", "/"))
    
    # Vérification taille fichier (20 Mo max)
    if fichier and fichier.size > 20 * 1024 * 1024:
        messages.error(request, "Fichier trop volumineux. Taille maximale : 20 Mo.")
        return redirect(request.META.get("HTTP_REFERER", "/"))
    
    # Récupérer le dossier
    avis = get_object_or_404(Avis, id=avis_id)
    dossier = get_object_or_404(Dossier, numero=dossier_numero)

    # Récupérer l'instructeur
    instructeur = Instructeur.objects.filter(email=request.user.email).first()

    if not instructeur :
        logger.error(f"[DOSSIER {dossier_numero} ] {avis} - Erreur lors de l'envoi du message : L'instructeur ({request.user}) n'existe pas")
        messages.error(request, f"Echec de l'envoi du message : Votre profil 'Instructeur' n'existe pas")
        return redirect(request.META.get("HTTP_REFERER", "/"))
    
 
    try: 
        if fichier:

            fichier.seek(0)
            fichier_bdd = SimpleUploadedFile(
                name=fichier.name,
                content=fichier.read(),
                content_type=fichier.content_type
            )
            create_message_avis_bdd(
                body=body,
                email_emetteur=request.user.email,
                avis_obj=avis,
                document_file=fichier_bdd,
                document_title=fichier.name,
                document_format_str=fichier.name.split('.')[-1].lower(),
                document_description=f"Pièce jointe instructeur dans la messagerie de l'avis {avis.id}",
            )

        else:
            create_message_avis_bdd(
                body=body,
                email_emetteur=request.user.email,
                avis_obj=avis
            )

        
    except Exception as e:

        logger.error(f"[DOSSIER {dossier_numero} ] {avis} - Erreur lors de l'envoi du message : {e}")
        messages.error(request, f"Erreur lors de l'envoi du message : {e}")
        return redirect(request.META.get("HTTP_REFERER", "/"))
    
    return redirect(request.META.get("HTTP_REFERER", "/"))



@require_POST
@csrf_exempt
def envoyer_message_avis_vision_expert(request):

    avis_id = request.POST.get("avis_id")
    avis = get_object_or_404(Avis, id=avis_id)

    # Récupération message et PJ de l'envoyeur
    body = request.POST.get("body")
    fichier = request.FILES.get("piece_jointe")

    if not body:
        messages.error(request, "Message vide")
        return redirect(request.META.get("HTTP_REFERER", "/"))
    
    # Vérification taille fichier (20 Mo max)
    if fichier and fichier.size > 20 * 1024 * 1024:
        messages.error(request, "Fichier trop volumineux. Taille maximale : 20 Mo.")
        return redirect(request.META.get("HTTP_REFERER", "/"))
 
    try: 
        if fichier:

            fichier.seek(0)
            fichier_bdd = SimpleUploadedFile(
                name=fichier.name,
                content=fichier.read(),
                content_type=fichier.content_type
            )
            create_message_avis_bdd(
                body=body,
                email_emetteur=request.user.email,
                avis_obj=avis,
                document_file=fichier_bdd,
                document_title=fichier.name,
                document_format_str=fichier.name.split('.')[-1].lower(),
                document_description=f"Pièce jointe instructeur dans la messagerie de l'avis {avis.id}",
            )

        else:
            create_message_avis_bdd(
                body=body,
                email_emetteur=request.user.email,
                avis_obj=avis
            )

    except Exception as e:

        logger.error(f"[AVIS {avis_id}] Erreur lors de l'envoi du message : {e}")
        messages.error(request, f"Erreur lors de l'envoi du message : {e}")
        return redirect(request.META.get("HTTP_REFERER", "/"))
    
    return redirect(request.META.get("HTTP_REFERER", "/"))



def enregistrer_document(fichier, nature_str, description, request, emplacement_avis, annexe=True):
    if not fichier:
        return None

    # Extension du fichier
    nom, extension = os.path.splitext(fichier.name)
    extension = extension.lstrip('.').lower()

    # Récupération du format
    format_obj = DocumentFormat.objects.filter(format__iexact=extension).first()
    if not format_obj:
        messages.error(request, f"Format {extension} non reconnu.")
        return None

    # Récupération de la nature
    nature_obj = DocumentNature.objects.filter(nature__iexact=nature_str).first()
    if not nature_obj:
        messages.error(request, f"Nature '{nature_str}' introuvable.")
        return None

    # Emplacement et chemin
    if annexe :
        emplacement_annexes = f"{emplacement_avis}Annexes/"
    else :
        emplacement_annexes = emplacement_avis

    chemin_complet = f"{os.getenv('ROOT_FOLDER')}{emplacement_annexes}"

    # Maj de l'ancien doc s’il existe
    doc = Document.objects.filter(emplacement=emplacement_annexes, titre=fichier.name).first()
    if doc:
        # Mise à jour plutôt que suppression
        doc.id_format = format_obj
        doc.id_nature = nature_obj
        doc.description = description
        doc.save(update_fields=["id_format", "id_nature", "description"])
    else:
        # Création
        doc = Document.objects.create(
            id_format=format_obj,
            id_nature=nature_obj,
            emplacement=emplacement_annexes,
            titre=fichier.name,
            description=description,
        )

    if not doc :
        messages.error(request, f"Erreur lors de la création du document {fichier.name} en base.")
        return None

    # Sauvegarde physique
    filepath = os.path.join(chemin_complet, fichier.name)
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
    with open(filepath, 'wb+') as destination:
        for chunk in fichier.chunks():
            destination.write(chunk)

    return doc



@require_POST
def supprimer_document_avis(request, avis_id, champ):

    avis = get_object_or_404(Avis, id=avis_id)

    if champ not in ["id_projet_acte", "id_rapport_instance", "id_projet_avis"]:
        messages.error(request, "Champ de document invalide")
        return redirect(request.META.get("HTTP_REFERER", "/"))

    setattr(avis, champ, None)
    avis.save(update_fields=[champ])

    return redirect(request.META.get("HTTP_REFERER", "/"))


@require_POST
@login_required
def mettre_a_jour_note_avis(request, avis_id):
    avis = get_object_or_404(Avis, id=avis_id)

    note = request.POST.get("note", "").strip()
    avis.note = note
    avis.save()

    return redirect(request.META.get("HTTP_REFERER", "/"))



@login_required
def nouvelle_demande_avis_generique(request):
    
    # Récupérer toutes les natures et thématiques
    natures = AvisNature.objects.all().order_by("nature")
    thematiques = AvisThematique.objects.all().order_by("thematique")
    demarches = Demarche.objects.all().order_by("type")

    # Instructeur courant (user connecté)
    instructeur_connecte = Instructeur.objects.filter(email=request.user.email).first()

    # Instructeurs candidats
    instructeurs_ = Instructeur.objects.filter(email__isnull=False).exclude(email__exact="").order_by("email")

    # Contacts externes candidats
    contacts_ = ContactExterne.objects.filter(email__isnull=False).exclude(email__exact="").exclude(id_type__type__in=["Demandeur intermédiaire", "Bénéficiaire"]).order_by("nom", "email")

    # Supprimer les doublons d'email (si jamais)
    instructeurs = {i.email: i for i in instructeurs_}.values()
    contacts_externes = {c.email: c for c in contacts_}.values()


    # return redirect(request.META.get("HTTP_REFERER", "/"))
    return render(request, "instruction/avis_nouvelle_demande_generique.html", {
        "natures": natures,
        "thematiques": thematiques,
        "instructeurs": instructeurs,
        "contacts_externes": contacts_externes,
        "demarches": demarches,
        # "ROOT_FOLDER": os.getenv('ROOT_FOLDER'),
    })


@require_POST
@login_required
def avis_confirmer_nouvelle_demande_generique(request):
    
    try:
        instructeur = Instructeur.objects.filter(email=request.user.email).first()
        if not instructeur:
            messages.error(request, f"Aucun instructeur.rice n'est associé.e à {request.user.email} : {e}")
            return redirect(request.META.get("HTTP_REFERER", "/"))
    except Exception as e:
        messages.error(request, f"Erreur lors de la récupération de l'instructeur {request.user} : {e}")
        return redirect(request.META.get("HTTP_REFERER", "/"))
    

    if request.method == "POST":
        # Champs du formulaire
        nature_id = request.POST.get("nature")
        demarche_id = request.POST.get("demarche")
        thematique_id = request.POST.get("thematique")
        note = request.POST.get("note_demandeur", "").strip()
        formulation_avis = request.POST.get("formulation_avis")
        expert_interne_id = request.POST.get("expert_interne") # instructeur ici 
        expert_externe_id = request.POST.get("expert_externe") # contact externe ici
        pj_projet_avis = request.FILES.get("pj_demande_avis")
        pj_projet_acte = request.FILES.get("pj_projet_acte")
        pj_rapport_cs = request.FILES.get("pj_rapport_cs")
        pjs_avis = request.FILES.getlist("pj_lie_avis")

        try:
            nature = AvisNature.objects.get(id=nature_id)
        except Exception as e:
            messages.error(request, f"Erreur lors de la récupération de la nature d'avis : {e}")
            return redirect(request.META.get("HTTP_REFERER", "/"))

        try:
            thematique = AvisThematique.objects.get(id=thematique_id)
        except Exception as e:
            messages.error(request, f"Erreur lors de la récupération de la thématique de l'avis : {e}")
            return redirect(request.META.get("HTTP_REFERER", "/"))
        
        try:
            demarche = Demarche.objects.get(id=demarche_id)
        except Exception as e:
            messages.error(request, f"Erreur lors de la récupération de la démarche {demarche_id} : {e}")
            return redirect(request.META.get("HTTP_REFERER", "/"))
    
        if expert_interne_id:
            try:
                instru = Instructeur.objects.get(id=expert_interne_id)
                expert, created = Expert.objects.get_or_create(
                    id_instructeur=instru,
                    defaults={"est_interne": True}
                )
                if created:
                    logger.info(f"[EXPERT] Nouvel expert interne créé : {instru}")
                
                nom_prenom_expert = nettoyer_nom_fichier(f"{instru.id_agent_autorisations.nom}_{instru.id_agent_autorisations.prenom}")

            except Exception as e:
                messages.error(request, f"Erreur lors de la récupération de l'expert interne : {e}")
                return redirect(request.META.get("HTTP_REFERER", "/"))
        
            
        elif expert_externe_id:
            try:
                contact = ContactExterne.objects.get(id=expert_externe_id)
                expert, created = Expert.objects.get_or_create(
                    id_contact_externe=contact,
                    defaults={"est_interne": False}
                )
                if created:
                    logger.info(f"[EXPERT] Nouvel expert externe créé : {contact}")

                if contact.nom and contact.prenom :
                    nom_prenom_expert = nettoyer_nom_fichier(f"{contact.nom}_{contact.prenom}")
                elif contact.raison_sociale :
                    nom_prenom_expert = nettoyer_nom_fichier(f"{contact.raison_sociale}")
                elif contact.organisation :
                    nom_prenom_expert = nettoyer_nom_fichier(f"{contact.organisation}")
                else :
                    nom_prenom_expert = f"Expert_Inconnu"


            except Exception as e:
                messages.error(request, f"Erreur lors de la récupération de l'expert externe : {e}")
                return redirect(request.META.get("HTTP_REFERER", "/"))
        

        doc_projet_acte = doc_rapport_instance = doc_projet_avis = None

        # On créé l'emplacement physique de l'avis
        emplacement_avis = f"Avis/{nettoyer_nom_fichier(demarche.type)}/{date.today().year}/{nom_prenom_expert}_{date.today().strftime("%d_%m")}/"
        
        # Si 1 des 3 fichiers est non null (on va pas créer d'emplacements pour les consult' internes sans docs par exemple)
        if pj_projet_avis or pj_projet_acte or pj_rapport_cs or pjs_avis :
            jour_mois_annee = date.today().strftime("%d/%m/%Y")
            
            chemin_complet = f"{os.getenv('ROOT_FOLDER')}{emplacement_avis}Annexes/"
            os.makedirs(os.path.dirname(chemin_complet), exist_ok=True)

            if pj_projet_avis :
                extension = Path(pj_projet_avis.name).suffix.lower()
                if extension not in {".doc", ".docx", ".odt"} :
                    messages.error(request, f"❌ Le projet de demande d'avis doit etre au format .doc ou .docx ou .odt --> Type de fichier non autorisé : {extension}")
                    return redirect(request.META.get("HTTP_REFERER", "/"))
                
                doc_projet_avis = enregistrer_document(
                    fichier=pj_projet_avis,
                    nature_str="Annexe avis",
                    description=f"Projet de demande pour la demande d'avis générique ({expert}) du {jour_mois_annee}",
                    request=request,
                    emplacement_avis = emplacement_avis,
                )
            
            if pj_projet_acte :
                extension = Path(pj_projet_acte.name).suffix.lower()
                if extension != ".pdf" :
                    messages.error(request, f"❌ Le projet d'acte doit etre au format .pdf --> Type de fichier non autorisé : {extension}")
                    return redirect(request.META.get("HTTP_REFERER", "/"))
                
                doc_projet_acte = enregistrer_document(
                    fichier=pj_projet_acte,
                    nature_str="Annexe avis",
                    description=f"Projet d’acte pour la demande d'avis générique ({expert}) du {jour_mois_annee}",
                    request=request,
                    emplacement_avis = emplacement_avis,
                )
            
            if pj_rapport_cs :
                extension = Path(pj_rapport_cs.name).suffix.lower()
                if extension != ".pdf" :
                    messages.error(request, f"❌ Le rapport de l'instance doit etre au format .pdf --> Type de fichier non autorisé : {extension}")
                    return redirect(request.META.get("HTTP_REFERER", "/"))
                
                doc_rapport_instance = enregistrer_document(
                    fichier=pj_rapport_cs,
                    nature_str="Annexe avis",
                    description=f"Rapport Instance pour la demande d'avis générique ({expert}) du {jour_mois_annee}",
                    request=request,
                    emplacement_avis = emplacement_avis,
                )


        # Création Avis
        try:

            avis = Avis.objects.create(
                    id_avis_nature=nature,
                    id_avis_thematique=thematique,
                    date_demande_avis=timezone.now(),
                    statut="Envoyé",
                    note=note,
                    formulation= formulation_avis,
                    mode_contact="Application",
                    id_demarche = demarche,
                    id_expert=expert,
                    id_instructeur=instructeur,
                    id_projet_acte=doc_projet_acte,
                    id_rapport_instance=doc_rapport_instance,
                    id_projet_avis=doc_projet_avis,
                    emplacement = emplacement_avis,
            )

            logger.info(f"[AVIS GENERIQUE {avis.id}] Avis créé")

            if pjs_avis :
                for pj in pjs_avis :
                    extension = Path(pj.name).suffix.lower()
                    
                    doc_pj_avis = enregistrer_document(
                        fichier=pj,
                        nature_str="Annexe avis",
                        description=f"Pièce jointe du demandeur pour la demande d'avis générique ({expert}) du {jour_mois_annee}",
                        request=request,
                        emplacement_avis = emplacement_avis,
                    )
                    
                    AvisDocument.objects.get_or_create(id_avis=avis, id_document=doc_pj_avis)

        except Exception as e:
            messages.error(request, f"Erreur lors de la création de l'avis : {e}")
            return redirect(request.META.get("HTTP_REFERER", "/"))
    
        # Create message (formulation)
        if avis.formulation :
            try:
                msg = Message.objects.create(
                    body=avis.formulation,
                    date_envoi=timezone.now(),
                    piece_jointe=True if doc_projet_avis else False,
                    email_emetteur=request.user.email,
                    id_avis=avis,
                    lu=False,
                )

                # Joindre le projet de demande d'avis au message
                if doc_projet_avis :
                    MessageDocument.objects.create(
                        id_message=msg,
                        id_document=doc_projet_avis
                    )

                logger.info(f"[AVIS GENERIQUE {avis.id}] : Message par défaut envoyé à {avis.id_expert}")

            except Exception as e:
                messages.error(request, f"Avis non transmis : Erreur lors de la création du message par défaut (formulation avis): {e}")
                return redirect(request.META.get("HTTP_REFERER", "/"))

        # NOTIF par MAIL à l'expert

    else :
        messages.error(request, f"Erreur lors de la transmission du formulaire : POST method required")
        return redirect(request.META.get("HTTP_REFERER", "/"))
    
    return redirect('avis_expert', avis_id=avis.id)

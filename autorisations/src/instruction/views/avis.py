import logging
import os
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.utils import timezone

from autorisations.models.models_instruction import Dossier
from autorisations.models.models_avis import Avis, AvisNature, AvisThematique, DossierAvis, Expert
from autorisations.models.models_utilisateurs import ContactExterne, Instructeur
from synchronisation.src.utils.model_helpers import update_fields


logger = logging.getLogger('ORM_DJANGO')


@login_required
def instruction_dossier_consultation(request, num_dossier):
    dossier = get_object_or_404(Dossier, numero=num_dossier)

    # dossiers_avis= Liste de tous les avis ou DossierAvis (id dossier=dossier)
    
    dossiers_avis = (DossierAvis.objects.filter(id_dossier=dossier))

    liste_avis = []
    for da in dossiers_avis:
        avis = da.id_avis

        # Déterminer l'expert
        expert = "N/A"
        if avis.id_avis_nature.nature == "Demande à une instance":
            if avis.id_expert and avis.id_expert.id_contact_externe:
                expert = avis.id_expert.id_contact_externe.get_display_name()
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

        # Construire le dictionnaire
        liste_avis.append({
            "statut": avis.statut,
            "expert": expert or "N/A",
            "numero": avis.id,
            "demandeur": f"{avis.id_instructeur.id_agent_autorisations.nom} {avis.id_instructeur.id_agent_autorisations.prenom}" if avis.id_instructeur else "N/A",
            "date_demande": avis.date_demande_avis,
            "date_reponse": avis.date_reponse_avis,
            "favorable": reponse,
        })

    liste_avis = sorted(
        liste_avis,
        key=lambda x: (x["statut"] == "Envoyé",
                    x["date_demande"]),
        reverse=True  # Pour mettre la date en décroissant
    )

    return render(request, "instruction/instruction_dossier_consultation.html", {
        "ROOT_FOLDER": os.getenv('ROOT_FOLDER'),
        "dossier": dossier,
        "is_formulaire_active": False,
        "is_messagerie_active": False,
        "is_consultation_active": True,
        "avis": liste_avis,
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

    # Contacts externes
    contacts_externes = list((
        ContactExterne.objects
        .filter(email__isnull=False)
        .exclude(email__exact='')
        .order_by('nom', 'email')
    ))

    # Instructeurs
    instructeurs = list(
        Instructeur.objects
        .filter(email__isnull=False)
        .exclude(email__exact='')
        .order_by('email')
    )


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
    })


@require_POST
@login_required
def instruction_dossier_confirmer_ajout_avis(request, num_dossier, avis_id=None):
    
    try:
        instructeur = Instructeur.objects.filter(id_agent_autorisations__mail_1=request.user.email).first()
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

    # Champs du formulaire
    nature_id = request.POST.get("nature")
    thematique_id = request.POST.get("thematique")
    note = request.POST.get("note_demandeur", "").strip()
    mode_contact = request.POST.get("mode_contact")
    formulation_avis = request.POST.get("formulation_avis")
    expert_interne_id = request.POST.get("expert_interne") # instructeur ici 
    expert_externe_id = request.POST.get("expert_externe") # contact externe ici
    fichier = request.FILES.get("pj_avis")

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

        except Exception as e:
            messages.error(request, f"Erreur lors de la récupération de l'expert externe : {e}")
            return redirect(request.META.get("HTTP_REFERER", "/"))

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
        }
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
        
        # NOTIF MAIL à l'expert
            
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
        
        # NOTIF MAIL à l'expert
        
    


    return redirect('instruction_dossier_consultation', num_dossier=num_dossier)



@require_POST
@login_required
def instruction_dossier_enregistrer_brouillon_avis(request, num_dossier, avis_id=None):

    try:
        instructeur = Instructeur.objects.filter(id_agent_autorisations__mail_1=request.user.email).first()
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

    # Champs du formulaire
    nature_id = request.POST.get("nature")
    thematique_id = request.POST.get("thematique")
    note = request.POST.get("note_demandeur", "").strip()
    mode_contact = request.POST.get("mode_contact")
    formulation_avis = request.POST.get("formulation_avis")
    expert_interne_id = request.POST.get("expert_interne") # instructeur ici 
    expert_externe_id = request.POST.get("expert_externe") # contact externe ici

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

        except Exception as e:
            messages.error(request, f"Erreur lors de la récupération de l'expert externe : {e}")
            return redirect(request.META.get("HTTP_REFERER", "/"))
        
    if brouillon_avis :

        fields_to_update = {
            "id_avis_nature": nature,
            "id_avis_thematique": thematique,
            "id_expert": expert,
            "note": note,
            "formulation": formulation_avis,
            "mode_contact": mode_contact,
        }
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
    
    else:
    
        try:
            avis = Avis.objects.create(
                statut="Brouillon",
                id_dossier=dossier,
                id_instructeur=instructeur,
                id_expert=expert,
                id_avis_nature=nature,
                id_avis_thematique=thematique,
                note=note,
                formulation=formulation_avis,
                mode_contact=mode_contact,
                date_demande_avis=timezone.now(),
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
        messages.error(request, f"Erreur lors de la suppressino de l'avis {avis} : {e}")

    return redirect(request.META.get("HTTP_REFERER", "/"))

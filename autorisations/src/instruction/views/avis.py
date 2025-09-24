import logging
import os
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.utils import timezone

from autorisations.models.models_instruction import Dossier, Message
from autorisations.models.models_avis import Avis, AvisNature, AvisThematique, DossierAvis, Expert
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

        # Messages non lus envoyés par l'expert
        if avis.id_expert.est_interne :
            email_expert = avis.id_expert.id_instructeur.email
        else :
            email_expert = avis.id_expert.id_contact_externe.email

        nb_messages_non_lus = Message.objects.filter(id_avis=avis, lu=False, email_emetteur=email_expert).count()

        # Construire le dictionnaire
        liste_avis.append({
            "statut": avis.statut,
            "expert": expert or "N/A",
            "numero": avis.id,
            "demandeur": f"{avis.id_instructeur.id_agent_autorisations.nom} {avis.id_instructeur.id_agent_autorisations.prenom}" if avis.id_instructeur else "N/A",
            "date_demande": avis.date_demande_avis,
            "date_reponse": avis.date_reponse_avis,
            "favorable": reponse,
            "nb_messages_non_lus": nb_messages_non_lus,
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
        .order_by("nom", "email")
    )

    # Supprimer les doublons d'email (si jamais)
    instructeurs = {i.email: i for i in instructeurs_qs}.values()
    contacts_externes = {c.email: c for c in contacts_qs}.values()


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
        "ROOT_FOLDER": os.getenv('ROOT_FOLDER'),
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
        


        # Si 1 des 3 fichiers est non null (on va pas créer d'emplacements pour les consult' internes sans docs par exemple)
        if pj_projet_avis or pj_projet_acte or pj_rapport_cs :
           
            emplacement = f"{dossier.emplacement}Avis/{nom_prenom_expert}/Annexes/"
            chemin_complet = f"{os.getenv('ROOT_FOLDER')}{emplacement}"
            os.makedirs(os.path.dirname(chemin_complet), exist_ok=True)

            if pj_projet_avis :
                extension = Path(pj_projet_avis.name).suffix.lower()
                if extension not in {".doc", ".docx", ".odt"} :
                    messages.error(request, f"❌ Le projet de demande d'avis doit etre au format .doc ou .docx ou .odt --> Type de fichier non autorisé : {extension}")
                    return redirect(request.META.get("HTTP_REFERER", "/"))
            
            if pj_projet_acte :
                extension = Path(pj_projet_acte.name).suffix.lower()
                if extension != ".pdf" :
                    messages.error(request, f"❌ Le projet d'acte doit etre au format .pdf --> Type de fichier non autorisé : {extension}")
                    return redirect(request.META.get("HTTP_REFERER", "/"))
            
            if pj_rapport_cs :
                extension = Path(pj_rapport_cs.name).suffix.lower()
                if extension != ".pdf" :
                    messages.error(request, f"❌ Le rapport de l'instance doit etre au format .pdf --> Type de fichier non autorisé : {extension}")
                    return redirect(request.META.get("HTTP_REFERER", "/"))
                
            
        doc_projet_avis = enregistrer_document(
            fichier=pj_projet_avis,
            dossier=dossier,
            nom_prenom_expert=nom_prenom_expert,
            nature_str="Annexe avis",
            description=f"Projet de demande pour l'avis {avis_id}",
            request=request,
        )

        doc_projet_acte = enregistrer_document(
            fichier=pj_projet_acte,
            dossier=dossier,
            nom_prenom_expert=nom_prenom_expert,
            nature_str="Annexe avis",
            description=f"Projet d’acte pour l'avis {avis_id}",
            request=request,
        )

        doc_rapport_instance = enregistrer_document(
            fichier=pj_rapport_cs,
            dossier=dossier,
            nom_prenom_expert=nom_prenom_expert,
            nature_str="Annexe avis",
            description=f"Rapport Instance pour l'avis {avis_id}",
            request=request,
        )


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
                # "id_projet_acte": doc_projet_acte,
                # "id_rapport_instance": doc_rapport_instance,
                # "id_projet_avis": doc_projet_avis,
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
            
            # Create message (formulation)
            try:
                msg = Message.objects.create(
                    body=brouillon_avis.formulation,
                    date_envoi=timezone.now(),
                    piece_jointe=False,
                    email_emetteur=request.user.email,
                    id_avis=brouillon_avis,
                    lu=False,
                )

                logger.info(f"[DOSSIER {dossier.numero}] Avis {brouillon_avis.id} : message envoyé à {brouillon_avis.id_expert}")

            except Exception as e:
                brouillon_avis.statut = "Brouillon"
                brouillon_avis.save()
                messages.error(request, f"Avis non transmis : Erreur lors de la création du message par défaut (formulation avis): {e}")
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
                        id_projet_acte=doc_projet_acte,
                        id_rapport_instance=doc_rapport_instance,
                        id_projet_avis=doc_projet_avis,
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
                        piece_jointe=False,
                        email_emetteur=request.user.email,
                        id_avis=avis,
                        lu=False,
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
            

         # Si 1 des 3 fichiers est non null (on va pas créer d'emplacements pour les consult' internes sans docs par exemple)
        if pj_projet_avis or pj_projet_acte or pj_rapport_cs :
           
            emplacement = f"{dossier.emplacement}Avis/{nom_prenom_expert}/Annexes/"
            chemin_complet = f"{os.getenv('ROOT_FOLDER')}{emplacement}"
            os.makedirs(os.path.dirname(chemin_complet), exist_ok=True)

            if pj_projet_avis :
                extension = Path(pj_projet_avis.name).suffix.lower()
                if extension not in {".doc", ".docx", ".odt"} :
                    messages.error(request, f"❌ Le projet de demande d'avis doit etre au format .doc ou .docx ou .odt --> Type de fichier non autorisé : {extension}")
                    return redirect(request.META.get("HTTP_REFERER", "/"))
            
            if pj_projet_acte :
                extension = Path(pj_projet_acte.name).suffix.lower()
                if extension != ".pdf" :
                    messages.error(request, f"❌ Le projet d'acte doit etre au format .pdf --> Type de fichier non autorisé : {extension}")
                    return redirect(request.META.get("HTTP_REFERER", "/"))
            
            if pj_rapport_cs :
                extension = Path(pj_rapport_cs.name).suffix.lower()
                if extension != ".pdf" :
                    messages.error(request, f"❌ Le rapport de l'instance doit etre au format .pdf --> Type de fichier non autorisé : {extension}")
                    return redirect(request.META.get("HTTP_REFERER", "/"))
                
            
        doc_projet_avis = enregistrer_document(
            fichier=pj_projet_avis,
            dossier=dossier,
            nom_prenom_expert=nom_prenom_expert,
            nature_str="Annexe avis",
            description=f"Projet de demande pour l'avis {avis_id}",
            request=request,
        )

        doc_projet_acte = enregistrer_document(
            fichier=pj_projet_acte,
            dossier=dossier,
            nom_prenom_expert=nom_prenom_expert,
            nature_str="Annexe avis",
            description=f"Projet d’acte pour l'avis {avis_id}",
            request=request,
        )

        doc_rapport_instance = enregistrer_document(
            fichier=pj_rapport_cs,
            dossier=dossier,
            nom_prenom_expert=nom_prenom_expert,
            nature_str="Annexe avis",
            description=f"Rapport Instance pour l'avis {avis_id}",
            request=request,
        )
            
        if brouillon_avis :
            # + enregistrer docs
            fields_to_update = {
                "id_avis_nature": nature,
                "id_avis_thematique": thematique,
                "id_expert": expert,
                "note": note,
                "formulation": formulation_avis,
                "mode_contact": mode_contact,
                # "id_projet_acte": doc_projet_acte,
                # "id_rapport_instance": doc_rapport_instance,
                # "id_projet_avis": doc_projet_avis,
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
        messages.error(request, f"Erreur lors de la suppressino de l'avis {avis} : {e}")

    return redirect(request.META.get("HTTP_REFERER", "/"))



@login_required
def instruction_dossier_avis(request, num_dossier, avis_id):

    # Récupérer le dossier et l'avis
    dossier = get_object_or_404(Dossier, numero=num_dossier)
    avis = get_object_or_404(Avis, id=avis_id, id_dossier=dossier)
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

        # left = Message expert, right = Message émis par instructeur
        align = "right" if emetteur != email_expert.lower().strip() else "left"
        date_fmt = localtime(msg.date_envoi).strftime("%d/%m/%Y %H:%M") if msg.date_envoi else "Date inconnue"

        # Recherche de la pièce jointe liée au message
        pj_title = pj_emplacement = None
        if msg.piece_jointe:

            message_doc = MessageDocument.objects.filter(id_message=msg).select_related("id_document").first()
            if message_doc and message_doc.id_document:   
                pj_title, pj_emplacement = message_doc.id_document.titre, message_doc.id_document.emplacement

        messages_fmt.append({"id": msg.id, "body": msg.body, "date_envoi": date_fmt, "align": align, "pj_title": pj_title, "pj_emplacement": pj_emplacement, "nouv_mess": nouv_mess})

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

    return render(request, 'instruction/instruction_dossier_avis.html', {
        "ROOT_FOLDER": os.getenv('ROOT_FOLDER'),
        "dossier": dossier,
        "avis": avis,
        "messages_avis": messages_fmt,
        "is_formulaire_active": False,
        "is_messagerie_active": False,
        "is_consultation_active": True,
        "nb_avis_envoyes": nb_avis_envoyes,
        "est_instructeur_du_dossier": est_instructeur_du_dossier,
        "nb_messages_non_lus": nb_messages_non_lus,
        "resume_pdf_titre": resume_pdf_titre,
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
                dossier_obj=dossier,
                avis_obj=avis,
                document_file=fichier_bdd,
                document_title=fichier.name,
                document_format_str=fichier.name.split('.')[-1].lower(),
                document_description=f"Pièce jointe instructeur dans la messagerie de l'avis {avis.id} du dossier {dossier_numero}",
            )

        else:
            create_message_avis_bdd(
                body=body,
                email_emetteur=request.user.email,
                dossier_obj=dossier,
                avis_obj=avis
            )

        
    except Exception as e:

        logger.error(f"[DOSSIER {dossier_numero} ] {avis} - Erreur lors de l'envoi du message : {e}")
        messages.error(request, f"Erreur lors de l'envoi du message : {e}")
        return redirect(request.META.get("HTTP_REFERER", "/"))
    
    return redirect(request.META.get("HTTP_REFERER", "/"))




def enregistrer_document(fichier, dossier, nom_prenom_expert, nature_str, description, request):
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
    emplacement = f"{dossier.emplacement}Avis/{nom_prenom_expert}/Annexes/"
    chemin_complet = f"{os.getenv('ROOT_FOLDER')}{emplacement}"

    # Maj de l'ancien doc s’il existe
    doc = Document.objects.filter(emplacement=emplacement, titre=fichier.name).first()
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
            emplacement=emplacement,
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

    # print(avis.id_projet_acte)
    # messages.success(request, f"Document {champ} supprimé avec succès ✅")
    return redirect(request.META.get("HTTP_REFERER", "/"))

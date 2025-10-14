from datetime import timedelta
from django.utils import timezone
import json
import os
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib.auth.decorators import login_required
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.http import FileResponse, Http404, JsonResponse
import urllib
from autorisations.models.models_instruction import Dossier, DossierChamp, DossierManifSportive, EtapeDossier, Message, SynchronisationEtat
from autorisations.models.models_utilisateurs import ContactExterne, DossierInstructeur, DossierRelecteurQualite, DossierValideur, GroupeinstructeurInstructeur, Instructeur, Groupeinstructeur
from autorisations.models.models_documents import Document, DocumentFormat, DocumentNature, DossierDocument
from autorisations.models.models_avis import Avis, Expert
from instruction.utils import dossiers_action_a_faire, enregistrer_action
from synchronisation.src.main import lancer_normalisation_et_synchronisation, lancer_normalisation_et_synchronisation_pour_une_demarche
from threading import Lock
import threading
import subprocess
import sys
from mimetypes import guess_type
from django.contrib import messages
import logging
from django.db.models import Q
from django.utils.timezone import now
from autorisations import settings
from django.db import close_old_connections
from django.contrib.auth.models import Group, User

logger = logging.getLogger("ORM_DJANGO")
loggerDS = logging.getLogger("API_DS")  


@login_required(login_url='/login/')
def requetes(request):
    return render(request, 'instruction/requetes.html')



def lancer_en_arriere_plan2():
    """
    Démarre la synchro si et seulement si le flag en BDD est à False.
    Retourne True si démarré, False si déjà en cours.
    """
    # S'assurer que la ligne existe
    SynchronisationEtat.objects.get_or_create(id=1, defaults={"en_cours": False})

    # Tentative atomique: on passe en True seulement si c'est actuellement False
    rows = (SynchronisationEtat.objects
            .filter(id=1, en_cours=False)
            .update(en_cours=True, date_maj=timezone.now()))
    if rows == 0:
        logger.warning("Synchro déjà en cours – nouvelle tentative ignorée (BDD).")
        return False

    def lancement_et_suivi():
        close_old_connections()
        try:

            with open("logs/synchronisation.log", "a", buffering=1) as f:
                process = subprocess.Popen(
                    [sys.executable, "synchronisation/src/lancer_synchronisation.py"],
                    stdout=f,
                    stderr=f,
                )
                process.wait()
        except Exception:
            logger.exception("Erreur lors du sous-processus de synchronisation.")
        finally:
            # Toujours remettre à False, même en cas d'erreur ou kill
            try:
                SynchronisationEtat.objects.filter(id=1).update(en_cours=False, date_maj=timezone.now())
            finally:
                close_old_connections()

    threading.Thread(target=lancement_et_suivi).start()
    return True


@login_required
def actualiser_donnees(request):
    if request.method == "POST":
        lancé = lancer_en_arriere_plan2()
        if not lancé:
            return JsonResponse({
                "status": "already_running",
                "message": "Une actualisation est déjà en cours."
            })
        return JsonResponse({"status": "ok", "message": "Synchronisation lancée."})
    return JsonResponse({"status": "error", "message": "Requête invalide"})


@login_required
def etat_actualisation(request):
    etat, _ = SynchronisationEtat.objects.get_or_create(id=1, defaults={"en_cours": False})

    # Timeout de sécurité : si ça dépasse 2 heures, on force en_cours=False
    if etat.en_cours and etat.date_maj and etat.date_maj < timezone.now() - timedelta(hours=2):
        logger.warning(f"Réinitialisation forcée du flag 'en_cours' (timeout dépassé) – dernière MAJ : {etat.date_maj}")
        etat.en_cours = False
        # etat.date_maj = timezone.now()
        etat.save(update_fields=["en_cours", "date_maj"])

    return JsonResponse({
    "en_cours": etat.en_cours,
    "date_maj": etat.date_maj.isoformat() if etat.date_maj else None
})


@require_POST
@login_required
def se_declarer_instructeur(request):
    
    dossier_id = request.POST.get("dossier_id")
    dossier = get_object_or_404(Dossier, id=dossier_id)

    instructeur_request = Instructeur.objects.filter(email=request.user.email).first()

    instructeur_id = request.POST.get("instructeur_id")

    instructeur = Instructeur.objects.filter(id=instructeur_id).first()

    if instructeur and dossier.id_groupeinstructeur:
        instructeurs_du_groupe = dossier.id_groupeinstructeur.groupeinstructeurinstructeur_set.values_list("id_instructeur_id", flat=True)
        if instructeur.id in instructeurs_du_groupe:
            DossierInstructeur.objects.get_or_create(id_dossier=dossier, id_instructeur=instructeur)
            logger.info(f"[DOSSIER {dossier.numero}] Affectation à l'instructeur {instructeur.email}")

            nom_prenom = '(' + instructeur.id_agent_autorisations.nom + " " + instructeur.id_agent_autorisations.prenom + ')'

            # Dossier Action
            enregistrer_action(dossier, instructeur_request, "Instructeur.e ajouté.e", nom_prenom)
        else :
            logger.error(f"[DOSSIER {dossier.numero}] Incohérence lors de l'affectation du dossier à l'instructeur {instructeur.email}. L'utilisateur n'est pas dans le groupe instructeur : {instructeurs_du_groupe}")
    else :
        logger.error(f"[DOSSIER {dossier.numero}] Problème lors de l'affectation du dossier à l'instructeur : {instructeur}.")


    return redirect(request.META.get("HTTP_REFERER", "/"))


@require_POST
@login_required
def retirer_instructeur(request):
    dossier_id = request.POST.get("dossier_id")
    instructeur_id = request.POST.get("instructeur_id")

    dossier = get_object_or_404(Dossier, id=dossier_id)
    instructeur = get_object_or_404(Instructeur, id=instructeur_id)

    # Tous les instructeurs affectés
    instructeurs_ids = list(
        DossierInstructeur.objects.filter(id_dossier=dossier).values_list("id_instructeur", flat=True)
    )

    if instructeur.id not in instructeurs_ids:
        request.session["retirer_instructeur_message"] = "Cet instructeur n'est pas affecté à ce dossier."
        return redirect(request.META.get("HTTP_REFERER", "/"))

    # Simuler le retrait
    instructeurs_restants_ids = [i for i in instructeurs_ids if i != instructeur.id]

    if not instructeurs_restants_ids:
        request.session["retirer_instructeur_message"] = "Impossible de retirer l'instructeur : il faut au moins un autre instructeur affecté au dossier."
        return redirect(request.META.get("HTTP_REFERER", "/"))

    groupe = dossier.id_groupeinstructeur
    if not groupe:
        request.session["retirer_instructeur_message"] = "Aucun groupe instructeur n’est défini pour ce dossier."
        return redirect(request.META.get("HTTP_REFERER", "/"))

    instructeurs_groupe_ids = set(
        GroupeinstructeurInstructeur.objects.filter(id_groupeinstructeur=groupe).values_list("id_instructeur", flat=True)
    )

    if not (set(instructeurs_restants_ids) & instructeurs_groupe_ids):
        request.session["retirer_instructeur_message"] = (
            "Impossible de retirer l'instructeur : aucun instructeur restant n'appartient au groupe instructeur."
        )
        return redirect(request.META.get("HTTP_REFERER", "/"))

    # ✅ Retrait autorisé
    DossierInstructeur.objects.filter(id_dossier=dossier, id_instructeur=instructeur).delete()
    logger.info(f"[DOSSIER {dossier.numero}] On retire l'instructeur {instructeur.email} du dossier.")

    nom_prenom = f"({instructeur.id_agent_autorisations.nom} {instructeur.id_agent_autorisations.prenom})"
    enregistrer_action(dossier, instructeur, "Instructeur.e retiré.e", nom_prenom)

    return redirect(request.META.get("HTTP_REFERER", "/"))


@require_POST
@login_required
def changer_valideur(request):
    dossier_id = request.POST.get("dossier_id")
    new_valideur_id = request.POST.get("new_valideur_id")

    if not dossier_id or not new_valideur_id:
        request.session["changer_valideur_message"] = ("Données manquantes pour le changement de validant·e.")
        return redirect(request.META.get("HTTP_REFERER", "/"))

    dossier = get_object_or_404(Dossier, id=dossier_id)
    new_valideur = get_object_or_404(Instructeur, id=new_valideur_id)

    if not dossier:
        request.session["changer_valideur_message"] = ("Dossier introuvable.")
        return redirect(request.META.get("HTTP_REFERER", "/"))

    if not new_valideur:
        request.session["changer_valideur_message"] = ("Validant·e sélectionné·e invalide.")
        return redirect(request.META.get("HTTP_REFERER", "/"))
    
    id_old_valideur = DossierValideur.objects.filter(id_dossier=dossier).values_list("id_instructeur", flat=True).first()
    old_valideur = Instructeur.objects.filter(id=id_old_valideur).first()


    # S'assurer que le nouveau valideur est différent
    if old_valideur and old_valideur.id == new_valideur.id:
        request.session["changer_valideur_message"] = ("Le/la validant·e sélectionné·e est déjà affecté·e à ce dossier.")
        return redirect(request.META.get("HTTP_REFERER", "/"))

    # Suppression de l'ancien valideur (s'il existe)
    if old_valideur:
        DossierValideur.objects.filter(id_dossier=dossier, id_instructeur=old_valideur).delete()
    # Ajout du nouveau valideur
    DossierValideur.objects.get_or_create(id_dossier=dossier, id_instructeur=new_valideur)
    
    # On enregistre l'action
    instructeur_request = Instructeur.objects.filter(email=request.user.email).first()
    enregistrer_action(dossier, instructeur_request, "Validant.e changé.e", f"({new_valideur})")

    logger.info(f"[DOSSIER {dossier.numero}] Changement de validant.e : {old_valideur} --> {new_valideur}")

    return redirect(request.META.get("HTTP_REFERER", "/"))


@require_POST
@login_required
def changer_relecteur(request):
    dossier_id = request.POST.get("dossier_id")
    new_relecteur_id = request.POST.get("new_relecteur_id")

    if not dossier_id or not new_relecteur_id:
        request.session["changer_relecteur_qualite_message"] = ("Données manquantes pour le changement de relecteur.rice")
        return redirect(request.META.get("HTTP_REFERER", "/"))

    dossier = get_object_or_404(Dossier, id=dossier_id)
    new_relecteur = get_object_or_404(Instructeur, id=new_relecteur_id)

    if not dossier:
        request.session["changer_relecteur_qualite_message"] = ("Dossier introuvable.")
        return redirect(request.META.get("HTTP_REFERER", "/"))

    if not new_relecteur:
        request.session["changer_relecteur_qualite_message"] = ("Relecteur.rice sélectionné·e invalide.")
        return redirect(request.META.get("HTTP_REFERER", "/"))
    
    id_old_relecteur = DossierRelecteurQualite.objects.filter(id_dossier=dossier).values_list("id_instructeur", flat=True).first()
    old_relecteur = Instructeur.objects.filter(id=id_old_relecteur).first()


    # S'assurer que le nouveau valideur est différent
    if old_relecteur and old_relecteur.id == new_relecteur.id:
        request.session["changer_relecteur_qualite_message"] = ("Le/la relecteur.rice sélectionné·e est déjà affecté·e à ce dossier.")
        return redirect(request.META.get("HTTP_REFERER", "/"))

    # Suppression de l'ancien valideur (s'il existe)
    if old_relecteur:
        DossierRelecteurQualite.objects.filter(id_dossier=dossier, id_instructeur=old_relecteur).delete()
    # Ajout du nouveau valideur
    DossierRelecteurQualite.objects.get_or_create(id_dossier=dossier, id_instructeur=new_relecteur)
    
    # On enregistre l'action
    instructeur_request = Instructeur.objects.filter(email=request.user.email).first()
    enregistrer_action(dossier, instructeur_request, "Relecteur.rice changé.e", f"({new_relecteur})")

    logger.info(f"[DOSSIER {dossier.numero}] Changement de relecteur.rice : {old_relecteur} --> {new_relecteur}")

    return redirect(request.META.get("HTTP_REFERER", "/"))


@require_POST
@login_required
def enregistrer_geom(request):
    try:
        dossier_numero = request.POST.get("dossier_numero")
        geojson_str = request.POST.get("geojson_geom")
        id_champ = request.POST.get("id_champ")
        nb_cartes = request.POST.get("nb_cartes")

        dossier = get_object_or_404(Dossier, numero=dossier_numero)
        champ = get_object_or_404(DossierChamp, id=id_champ, id_dossier=dossier, id_champ__id_champ_type__type__in=["carte", "drop_down_list"])

        if not geojson_str:
            msg = "Aucune géométrie reçue (champ geojson_geom vide)."
            logger.warning(f"[DOSSIER {dossier.numero}] Enregistrement géométrie par {request.user}: {msg}")

            return redirect(f"{reverse('edit_carto', kwargs={'numero_dossier': dossier_numero})}?status=error&msg={urllib.parse.quote(msg)}")

        geojson_data = json.loads(geojson_str)

        # MAJ champ
        if not champ:
            msg = "Champ carte non trouvé."
            logger.error(f"[DOSSIER {dossier.numero}] Erreur lors de l'nregistrement de la géométrie par {request.user} : {msg}")
            return redirect(f"{reverse('edit_carto', kwargs={'numero_dossier': dossier.numero, 'id_champ': request.POST.get('id_champ')})}?status=error&msg={urllib.parse.quote(msg)}")

        champ.geometrie_modif = geojson_data
        champ.save()

        # MAJ géométrie dossier seulement s'il n'existe qu'un champ de type carte
        if nb_cartes == 1:
            dossier.geometrie_modif = geojson_data
            dossier.save()

        # Il y a au moins 2 champs cartes
        else:
            # Récupération de tous les champs carte du dossier
            champs_cartes = DossierChamp.objects.filter(
                id_dossier=dossier,
                id_champ__id_champ_type__type="carte"
            )

            features = []

            # On fusionne les geojson recupérés pour n'en faire qu'un
            for c in champs_cartes:
                geo = c.geometrie_modif or c.geometrie
                if geo:
                    # S'assurer que c'est bien un Feature ou FeatureCollection
                    if geo.get("type") == "Feature":
                        features.append(geo)
                    elif geo.get("type") == "FeatureCollection":
                        features.extend(geo.get("features", []))
                    else:
                        logger.warning(f"[DOSSIER {dossier.numero}] Géométrie ignorée : type inattendu ({geo.get('type')}) dans champ {c.id}")

            if features:
                geojson_fusionne = {
                    "type": "FeatureCollection",
                    "features": features
                }
                # Mise à jour de dossier.geometrie_modif si valeur différente
                if dossier.geometrie_modif != geojson_fusionne:
                    dossier.geometrie_modif = geojson_fusionne
                    dossier.save()

        msg = "Géométrie mise à jour avec succès."
        logger.info(f"[DOSSIER {dossier.numero}] {msg} par {request.user}")
        return redirect(f"{reverse('edit_carto', kwargs={'numero_dossier': dossier.numero, 'id_champ': id_champ})}?status=ok&msg={urllib.parse.quote(msg)}")

    except Exception as e:
        logger.error(f"[DOSSIER {dossier.numero}] Erreur lors de l'nregistrement de la géométrie par {request.user} : {e}")
        return redirect(f"/instruction/{request.POST.get('dossier_numero')}/edit_carto/{request.POST.get('id_champ')}?status=error&msg={urllib.parse.quote(str(e))}")



@login_required
def edit_carto(request, numero_dossier, id_champ):
    dossier = get_object_or_404(Dossier, numero=numero_dossier)
    
    # Récupère tous les champs carte
    # nb_cartes = dossier.dossierchamp_set.filter(id_champ__id_champ_type__type="carte").count()
    
    nb_cartes = dossier.dossierchamp_set.filter(
        Q(id_champ__id_champ_type__type="carte") |
        Q(id_champ__id_champ_type__type="drop_down_list", geometrie_a_saisir=True)
    ).count()


    champ = get_object_or_404(
            DossierChamp,
            id=id_champ,
            id_dossier=dossier,
            id_champ__id_champ_type__type__in=["carte", "drop_down_list"]
        )
        
    geojson_source = champ.geometrie_modif or champ.geometrie
    if not geojson_source:
        geojson_source = {
            "type": "FeatureCollection",
            "features": []
        }
    

    geojson = json.dumps(geojson_source)


    return render(request, 'edit_carto.html', {
                                                "numero_dossier": numero_dossier, 
                                                "geojson": geojson, 
                                                "etape_dossier": dossier.id_etape_dossier.etape if dossier.id_etape_dossier else None,
                                                "nb_cartes": nb_cartes,
                                                'id_champ': id_champ,
                                                'now': now(),
                                               })



def mes_dossiers_a_traiter_count(request):
    if not request.user.is_authenticated:
        return {}

    instructeur = Instructeur.objects.filter(id_agent_autorisations__mail_1=request.user.email).first()
    if not instructeur:
        return {}

    # Dossiers (en cours d'instruction) où l’utilisateur intervient
    dossiers = (
        Dossier.objects.filter(
            Q(dossierinstructeur__id_instructeur=instructeur) |
            Q(dossierrelecteurqualite__id_instructeur=instructeur) |
            Q(dossiervalideur__id_instructeur=instructeur) |
            Q(dossierrelecteur__id_instructeur=instructeur) |
            Q(dossiersignataire__id_instructeur=instructeur)
        )
        .exclude(id_etape_dossier__etape__in=["À affecter", "Accepté", "Refusé", "Non soumis à autorisation"])
        .distinct()
    )

    dossiers_actions = dossiers_action_a_faire(dossiers, instructeur)

    return {"nb_dossiers_instruction": len(dossiers_actions)}


def mes_avis_action_a_faire(request):
    """
    Renvoie un dictionnaire contenant le nombre d'avis où l'utilisateur
    a une action à faire :
      - Avis où il est expert (interne ou externe) et favorable is null
      - Avis où il est expert (interne ou externe) et favorable not null
        mais avec des messages non lus dont il n'est pas l'émetteur
      - Avis où il est demandeur et a des messages non lus de l'expert
    """
    if not request.user.is_authenticated:
        return {}

    email_user = request.user.email
    nb_avis_action = 0

    # ----------------------------------------------------------
    # 1️⃣ Identifier l’utilisateur comme instructeur et/ou expert
    # ----------------------------------------------------------
    instructeur = Instructeur.objects.filter(id_agent_autorisations__mail_1=email_user).first()

    expert = (
        Expert.objects.filter(id_instructeur=instructeur).first()
        if instructeur
        else Expert.objects.filter(id_contact_externe__email=email_user).first()
    )

    # ----------------------------------------------------------
    # 2️⃣ Cas où l’utilisateur est EXPERT (interne ou externe)
    # ----------------------------------------------------------
    if expert:
        # (a) Avis à rendre → favorable is null
        nb_avis_a_rendre = Avis.objects.filter(
            id_expert=expert, favorable__isnull=True
        ).count()

        # (b) Avis rendus avec messages non lus dont il n’est pas l’émetteur
        avis_rendus = Avis.objects.filter(
            id_expert=expert, favorable__isnull=False
        )
        for avis in avis_rendus:
            nb_non_lus = Message.objects.filter(
                id_avis=avis, lu=False
            ).exclude(email_emetteur=email_user).count()
            if nb_non_lus > 0:
                nb_avis_action += 1

        nb_avis_action += nb_avis_a_rendre

    # ----------------------------------------------------------
    # 3️⃣ Cas où l’utilisateur est DEMANDEUR d’avis
    # ----------------------------------------------------------
    if instructeur:
        avis_demandes = Avis.objects.filter(id_instructeur=instructeur)
        for avis in avis_demandes:
            # récupérer l’adresse mail de l’expert associé
            if avis.id_expert.est_interne:
                email_expert = avis.id_expert.id_instructeur.email
            else:
                email_expert = avis.id_expert.id_contact_externe.email

            nb_non_lus = Message.objects.filter(
                id_avis=avis, lu=False, email_emetteur=email_expert
            ).count()

            if nb_non_lus > 0:
                nb_avis_action += 1

    return {"nb_avis_action_a_faire": nb_avis_action}



@login_required(login_url='/login/')
def ajouter_annexe_dossier(request, dossier_id):

    dossier = get_object_or_404(Dossier, id=dossier_id)

    if request.method == "POST" and request.FILES.get('annexe'):
        fichier = request.FILES['annexe']

        # Vérification de la taille (max 20 Mo)
        if fichier.size > 20 * 1024 * 1024:
            logger.warning(f"[DOSSIER {dossier.numero}] Annexe refusée ({request.user}) Taille > 50 Mo pour {fichier.name}")
            messages.error(request, f"Annexe refusée ({request.user}) Taille > 20 Mo pour {fichier.name}")
            return redirect(request.META.get("HTTP_REFERER", "/preinstruction/"))

        # Extension du fichier
        nom, extension = os.path.splitext(fichier.name)
        extension = extension.lstrip('.').lower()

        # Récupérer le format
        format_obj = DocumentFormat.objects.filter(format__iexact=extension).first()
        if not format_obj:
            logger.warning(f"[DOSSIER {dossier.numero}] Annexe refusée ({request.user}) car le format n'est pas reconnu : {fichier.name}.{extension}")
            return redirect(request.META.get("HTTP_REFERER", "/preinstruction/"))


        # Nature "Annexe instructeur"
        nature_obj = DocumentNature.objects.filter(nature__iexact="Annexe instructeur").first()
        if not nature_obj:
            logger.error(f"[DOSSIER {dossier.numero}] Annexe refusée ({request.user}) La nature 'Annexe instructeur' est introuvable en BDD.")
            return redirect(request.META.get("HTTP_REFERER", "/preinstruction/"))

        
        # Création du Document
        dossier = get_object_or_404(Dossier, pk=dossier_id)
        emplacement = f"{dossier.emplacement}Annexes/{fichier.name}"
        chemin_complet = f"{os.getenv('ROOT_FOLDER')}{emplacement}"

        # Vérification si un Document avec le même emplacement existe déjà en base, si on est ici c'est qu'on a confirmé l'écrasement dans le pop up JS
        if Document.objects.filter(emplacement=f"{dossier.emplacement}Annexes/", titre=fichier.name).exists():
            
            try:
                ancien_doc = Document.objects.get(emplacement=f"{dossier.emplacement}Annexes/", titre=fichier.name)
                # Supprimer le lien avec le dossier
                DossierDocument.objects.filter(id_document=ancien_doc).delete()
                # Supprimer le document lui-même
                ancien_doc.delete()
            except Document.DoesNotExist:
                pass  # Aucun doc à supprimer, donc on ignore

            logger.info(f"[DOSSIER {dossier.numero}] Annexe {fichier.name} écrasée par {request.user} — ancien document supprimé.")

        doc = Document.objects.create(
            id_format=format_obj,
            id_nature=nature_obj,
            titre=fichier.name,
            emplacement=f"{dossier.emplacement}Annexes/",
            description=f"Annexe ajouté par l'instructeur {request.user} sur le dossier {dossier.numero}"
        )


        # Lien avec le Dossier
        DossierDocument.objects.create(id_dossier=dossier, id_document=doc)

        # Enregistrement physique
        os.makedirs(os.path.dirname(chemin_complet), exist_ok=True)


        # Si un fichier du même nom existe déjà, on le supprime
        if os.path.exists(chemin_complet):
            os.remove(chemin_complet)

        try:
            with open(chemin_complet, 'wb+') as destination:
                for chunk in fichier.chunks():
                    destination.write(chunk)

            logger.info(f"[DOSSIER {dossier.numero}] Annexe {fichier.name} ajoutée avec succès par {request.user}")
            return redirect(request.META.get("HTTP_REFERER", "/preinstruction/"))

        except Exception as e:
            logger.error(f"[DOSSIER {dossier.numero}] Erreur lors de l'écriture de l'annexe instructeur (Note) : {e}")
            messages.error(request, "Une erreur est survenue lors de l’enregistrement du fichier. Veuillez réessayer.")
            return redirect(request.META.get("HTTP_REFERER", "/preinstruction/"))


    logger.warning(f"[DOSSIER {dossier.numero}] Annexe non ajoutée par {request.user} : Aucune pièce jointe reçue.")
    return redirect(request.META.get("HTTP_REFERER", "/preinstruction/"))



@login_required
def synchroniser_demarche(request, num_demarche):
    if request.method == "POST":
        try:
            lancer_normalisation_et_synchronisation_pour_une_demarche(num_demarche)
        except Exception as e:
            logger.error(f"Erreur de synchronisation pour la démarche {num_demarche} : {e}")
    return redirect("instruction_demarche", num_demarche=num_demarche)


@login_required
def synchroniser_demarche_depuis_reception(request, num_demarche):
    if request.method == "POST":
        try:
            lancer_normalisation_et_synchronisation_pour_une_demarche(num_demarche)
        except Exception as e:
            logger.error(f"Erreur de synchronisation pour la démarche {num_demarche} : {e}")
    return redirect(request.META.get("HTTP_REFERER", "/preinstruction/"))


@login_required
def afficher_annexe(request, chemin, titre=None):
    try:
        if titre :
            chemin_entier = os.path.join(os.environ.get("ROOT_FOLDER"), chemin, titre)
        else :
            chemin_entier = os.path.join(os.environ.get("ROOT_FOLDER"), chemin)

        if not os.path.exists(chemin_entier):
            raise Http404("Fichier introuvable")

        content_type, _ = guess_type(chemin_entier)
        if not content_type:
            content_type = 'application/octet-stream'  # type par défaut
        
        response = FileResponse(open(chemin_entier, 'rb'), content_type=content_type)
        return response


    except Exception as e:
        raise Http404("Erreur d'accès au fichier : " + str(e))


@require_POST
@login_required
def supprimer_annexe_instructeur(request):
    document_id = request.POST.get("document_id")
    dossier_id = request.POST.get("dossier_id")

    doc = get_object_or_404(Document, id=document_id, id_nature__nature__iexact="Annexe instructeur")
    dossier = get_object_or_404(Dossier, id=dossier_id)

    try:
        # Supprimer le lien
        DossierDocument.objects.filter(id_dossier=dossier, id_document=doc).delete()

        # Supprimer le fichier physique
        chemin_fichier = os.path.join(os.getenv("ROOT_FOLDER"), doc.emplacement, doc.titre)
        if os.path.exists(chemin_fichier):
            os.remove(chemin_fichier)

        # Supprimer le document
        doc.delete()

        logger.info(f"[DOSSIER {dossier.numero}] Annexe instructeur supprimée : {doc.titre} par {request.user}")
        return redirect(request.META.get("HTTP_REFERER", "/"))

    except Exception as e:
        logger.error(f"[DOSSIER {dossier.numero}] Erreur suppression annexe instructeur ({doc.titre}) par {request.user} : {e}")
        raise




@login_required
def dossier_manif_sportive_sans_ds(request, numero):


    doss_manif_sportive = get_object_or_404(DossierManifSportive, numero_dossier_declaration_manifestations=numero)

     # Charger le fond de carte GeoJSON (une seule fois)
    fond_coeur_de_parc = os.path.join(settings.BASE_DIR, "instruction/static/instruction/carto/fond_coeur_de_parc.geojson")
    with open(fond_coeur_de_parc, encoding="utf-8") as f:
        fond_coeur_de_parc = json.load(f)

    fond_aire_adhesion = os.path.join(settings.BASE_DIR, "instruction/static/instruction/carto/aire_adhesion.geojson")
    with open(fond_aire_adhesion, encoding="utf-8") as f:
        fond_aire_adhesion = json.load(f)

    return render(request, 'instruction/dossier_manif_sportive_sans_ds.html', {
        "doss_manif_sportive": doss_manif_sportive,
        "coeurData": fond_coeur_de_parc,
        "adhesionData": fond_aire_adhesion,
    })



@login_required
def gestion_groupes(request):
    if request.method == "POST":
        action = request.POST.get("action")
        type_objet = request.POST.get("type")  # "groupe" ou "groupe_instructeur"
        groupe_id = request.POST.get("groupe_id")
        user_id = request.POST.get("user_id")

        if type_objet == "groupe":  # Groupes Django classiques
            groupe = get_object_or_404(Group, id=groupe_id)
            if action == "add":
                user = get_object_or_404(User, id=user_id)
                groupe.user_set.add(user)
                messages.success(request, f"Utilisateur {user.username} ajouté au groupe {groupe.name}.")
            elif action == "remove":
                user = get_object_or_404(User, id=user_id)
                groupe.user_set.remove(user)
                messages.success(request, f"Utilisateur {user.username} retiré du groupe {groupe.name}.")

        elif type_objet == "groupe_instructeur":  # Groupes instructeurs
            groupe = get_object_or_404(Groupeinstructeur, id=groupe_id)
            instructeur = get_object_or_404(Instructeur, id=user_id)

            if action == "add":
                GroupeinstructeurInstructeur.objects.get_or_create(
                    id_groupeinstructeur=groupe, id_instructeur=instructeur
                )
                messages.success(request, f"Instructeur {instructeur} ajouté au groupe instructeur {groupe.nom}.")
            elif action == "remove":
                GroupeinstructeurInstructeur.objects.filter(
                    id_groupeinstructeur=groupe, id_instructeur=instructeur
                ).delete()
                messages.success(request, f"Instructeur {instructeur} retiré du groupe instructeur {groupe.nom}.")

        return redirect("gestion_groupes")
    
    user = request.user
    param = request.GET.get("mes_groupes")
    if param is None:
        # Aucun paramètre → on coche par défaut
        show_only_mine = True
    else:
        # Si présent → on suit la valeur ("1" = coché, tout le reste = décoché)
        show_only_mine = (param == "1")

    # Groupes Django
    groupes = Group.objects.all().prefetch_related("user_set")
    if show_only_mine:
        groupes = [g for g in groupes if user in g.user_set.all()]


    users = User.objects.all()

    # Séparation des groupes
    groupes_saadd = [g for g in groupes if "SAADD" in g.name.upper()]
    groupes_sppn = [g for g in groupes if "SPPN" in g.name.upper()]
    groupes_general = [g for g in groupes if "SAADD" not in g.name.upper() and "SPPN" not in g.name.upper()]

    # Groupes instructeurs
    groupes_instructeurs = Groupeinstructeur.objects.all().order_by("nom").prefetch_related(
        "groupeinstructeurinstructeur_set__id_instructeur__id_agent_autorisations"
    )

    if show_only_mine:
        groupes_instructeurs = [
            g for g in groupes_instructeurs
            if g.groupeinstructeurinstructeur_set.filter(id_instructeur__email=user.email).exists()
        ]

    # on construit un dict {groupe_id: [ids instructeurs déjà dedans]}
    instructeurs_groupes_map = {
        g.id: [lien.id_instructeur.id for lien in g.groupeinstructeurinstructeur_set.all()]
        for g in groupes_instructeurs
    }

    instructeurs = Instructeur.objects.select_related("id_agent_autorisations").all()


    return render(request, "instruction/gestion_groupes.html", {
        "groupes_saadd": groupes_saadd,
        "groupes_sppn": groupes_sppn,
        "groupes_general": groupes_general,
        "groupes_instructeurs": groupes_instructeurs,
        "instructeurs_groupes_map": instructeurs_groupes_map,
        "instructeurs": instructeurs,
        "users": users,  # pour liste déroulante d’ajout
        "show_only_mine": show_only_mine,
    })




@login_required
def gestion_contacts(request):
    """
    Affiche et permet de modifier les contacts externes et les instructeurs.
    """
    if request.method == "POST":
        type_objet = request.POST.get("type_objet")
        obj_id = request.POST.get("id")

        if type_objet == "contact":
            contact = get_object_or_404(ContactExterne, id=obj_id)
            contact.nom = request.POST.get("nom")
            contact.prenom = request.POST.get("prenom")
            contact.email = request.POST.get("email")
            contact.telephone = request.POST.get("telephone")
            contact.organisation = request.POST.get("organisation")
            contact.raison_sociale = request.POST.get("raison_sociale")
            contact.adresse = request.POST.get("adresse")
            contact.save()
            messages.success(request, f"✅ Contact {contact.get_display_name()} mis à jour.")

        elif type_objet == "instructeur":
            instructeur = get_object_or_404(Instructeur, id=obj_id)
            agent = instructeur.id_agent_autorisations
            agent.nom = request.POST.get("nom")
            agent.prenom = request.POST.get("prenom")
            agent.mail_1 = request.POST.get("email")
            agent.acronyme = request.POST.get("acronyme")
            agent.actif = "actif" in request.POST
            agent.save()
            messages.success(request, f"✅ Instructeur {agent.nom} {agent.prenom} mis à jour.")

        return redirect("gestion_contacts")

    instructeurs = Instructeur.objects.select_related("id_agent_autorisations").all().order_by("id_agent_autorisations__nom")
    contacts = ContactExterne.objects.select_related("id_type").all().order_by("nom", "prenom")

    return render(request, "instruction/gestion_contacts.html", {
        "instructeurs": instructeurs,
        "contacts": contacts,
    })
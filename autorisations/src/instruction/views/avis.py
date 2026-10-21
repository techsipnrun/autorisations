from datetime import date, timedelta
import logging
import os
import tempfile
import zipfile
from functools import wraps
from uuid import uuid4
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.urls import reverse
from django.http import FileResponse, HttpResponse, HttpResponseBadRequest, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST, require_http_methods
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.db import models, transaction
from django.db.models import Exists, OuterRef
import smbclient
from autorisations.settings import EMAIL_NOTIF_TEST, NOTIFS_PROD

from autorisations.models.models_instruction import Demarche, Dossier, Message
from autorisations.models.models_avis import Avis, AvisDocument, AvisNature, AvisThematique, DossierAvis, Expert
from autorisations.models.models_utilisateurs import ContactExterne, DossierInstructeur, EmailOutbox, Instructeur
from autorisations.models.models_documents import Document, DocumentFormat, DocumentNature, MessageDocument
from autorisations.utils.nas_fonctions import creer_dossier_sur_nas, ecrire_file_sur_nas, supprimer_file_sur_nas
from notifications.service import compute_dedupe_key, create_EmailOutbox, envoi_mail
from instruction.utils_instru import create_message_avis_bdd, enregistrer_document
from synchronisation.utils.model_helpers import update_fields
from pathlib import Path
from django.utils.timezone import localtime
from django.views.decorators.csrf import csrf_exempt
from django.core.files.uploadedfile import SimpleUploadedFile

from instruction.utils.avis_utils import (attach_pj_to_avis, avis_est_conseil_scientifique, expert_est_conseil_scientifique, get_documents_zip_avis, get_expert_label,get_email_expert,count_unread_messages_for_avis,get_demandeur_label, get_or_create_expert_from_form,get_pieces_jointes_demandeur,get_reponse_label,count_avis_with_unread_messages_for_dossier, thematiques_avis_liees_a_demarche, utilisateur_est_publicateur_raa_cs)
from instruction.utils.dossier_utils import count_unread_messages_for_dossier, get_chemin_complet_dossier, redirect_error
from instruction.views.errors import avis_introuvable
from instruction.utils.avis_utils import get_dossiers_lies_affiches_avis
from instruction.utils.avis_utils import emplacement_demande_avis_dossier
from instruction.utils.avis_reservations import creation_avis_reservee, modification_brouillon_verrouillee, reserver_numero, lire_reservation, utiliser_reservation

from synchronisation.utils.fichiers import nettoyer_nom_fichier
from instruction.forms_avis import DemandeAvisForm, ImportAvisCSForm
from instruction.utils.avis_formulaires import charger_configuration
from instruction.utils.avis_utils import contact_est_conseil_scientifique, filtre_numero_avis, repartition_thematiques_avis

logger = logging.getLogger('ORM_DJANGO')


def _configuration_formulaire(contexte, dossier=None, numero=None):
    thematiques = list(AvisThematique.objects.all().order_by("thematique"))
    demarches = [dossier.id_demarche] if dossier else list(Demarche.objects.all())
    return {"champs": charger_configuration(contexte),
        "thematiques_par_demarche": repartition_thematiques_avis(thematiques, demarches),
        "variables": {
        "numero_dossier": dossier.numero if dossier else "", "numero_avis": numero or "",
        "type_demarche": dossier.id_demarche.type if dossier else "",
        "demarche": str(getattr(dossier.id_demarche, "pk", "")) if dossier else "",
    }}


def _valider_formulaire_configure(request, dossier=None, avis=None, brouillon=False, contexte=None):
    contexte = contexte or ("dossier" if dossier else "generique")
    configuration = charger_configuration(contexte)
    donnees = request.POST.copy()
    for champ in configuration:
        if champ["code"] in {"nature", "demarche", "expert_interne", "expert_externe", "thematique", "demandeur_avis"} and not donnees.get(champ["code"]):
            donnees[champ["code"]] = champ["defaut"]
    try:
        nature = AvisNature.objects.get(id=donnees.get("nature"))
        type_nature = {"Consultation en interne": "interne", "Demande à une instance": "instance"}.get(nature.nature, "")
        contact = ContactExterne.objects.get(id=donnees["expert_externe"]) if type_nature == "instance" and donnees.get("expert_externe") else None
        demarche = dossier.id_demarche if dossier else Demarche.objects.get(id=donnees.get("demarche"))
        etat = {cle: donnees.get(cle, "") for cle in ("expert_interne", "expert_externe", "demarche")}
        if dossier:
            etat["demarche"] = str(getattr(demarche, "pk", ""))
        etat.update(nature_type=type_nature, expert_cs="true" if contact_est_conseil_scientifique(contact) else "false")
        numero = "" if contexte == "existant" else avis.id if avis else request.reservation_avis.numero
        formulaire = DemandeAvisForm(donnees, request.FILES, configuration=configuration, etat=etat, avis=avis, brouillon=brouillon,
            variables={"numero_dossier": dossier.numero if dossier else "", "numero_avis": numero, "type_demarche": demarche.type},
            thematiques_autorisees=[str(t.pk) for t in thematiques_avis_liees_a_demarche(demarche)])
        if formulaire.is_valid():
            if contexte == "existant":
                # Vérifier les références avant toute écriture (Expert, NAS, Avis).
                Instructeur.objects.get(id=formulaire.cleaned_data["demandeur_avis"])
                if type_nature == "interne":
                    Instructeur.objects.get(id=formulaire.cleaned_data["expert_interne"])
                AvisThematique.objects.get(id=formulaire.cleaned_data["thematique"])
                for code in ("date_demande_avis", "date_reponse_avis"):
                    valeur = formulaire.cleaned_data.get(code)
                    formulaire.donnees[code] = valeur.isoformat() if valeur else ""
            request.POST = formulaire.donnees
            request._files = formulaire.fichiers_actifs
            return None
        erreurs = [f"{formulaire.fields[cle].label} : {message}" if cle in formulaire.fields else str(message)
                   for cle, messages_champ in formulaire.errors.items() for message in messages_champ]
        return redirect_error(request, " ".join(erreurs))
    except (ObjectDoesNotExist, ValueError, TypeError):
        if contexte == "existant":
            return redirect_error(request, "Sélectionnez une nature, un instructeur, une thématique et un expert valides.")
        return redirect_error(request, "Sélectionnez une nature, une démarche et un expert valides.")


def _creation_avec_numero_reserve(vue):
    @wraps(vue)
    def executer(request, *args, **kwargs):
        avis_id = kwargs.get("avis_id", args[1] if len(args) > 1 else None)
        num_dossier = kwargs.get("num_dossier", args[0] if args else None)
        try:
            if avis_id:
                with modification_brouillon_verrouillee(request, num_dossier, avis_id) as avis:
                    if avis and avis.statut != "Brouillon":
                        return redirect("instruction_dossier_consultation", num_dossier=num_dossier)
                    request.brouillon_reservation = avis
                    if not avis or request.POST.get("generer_numero") == "1":
                        return vue(request, *args, **kwargs)
                    if str(request.POST.get("nature")) != str(avis.id_avis_nature_id):
                        return redirect_error(request, "La nature d'un avis au statut Brouillon ne peut pas être modifiée.")
                    erreur = _valider_formulaire_configure(request, avis.id_dossier if avis else None, avis,
                        brouillon=vue.__name__ == "instruction_dossier_enregistrer_brouillon_avis")
                    if erreur is not None:
                        return erreur
                    return vue(request, *args, **kwargs)
            with creation_avis_reservee(request, num_dossier) as reservation:
                request.reservation_avis = reservation
                if reservation.id_avis_id:
                    if num_dossier is not None:
                        if vue.__name__ == "instruction_dossier_enregistrer_brouillon_avis":
                            return redirect("instruction_dossier_ajouter_avis", num_dossier=num_dossier, avis_id=reservation.id_avis_id)
                        return redirect("instruction_dossier_consultation", num_dossier=num_dossier)
                    return redirect("avis_expert", avis_id=reservation.id_avis_id)
                dossier = getattr(request, "dossier_reservation", None) or (Dossier.objects.filter(numero=num_dossier).first() if num_dossier is not None else None)
                erreur = _valider_formulaire_configure(request, dossier,
                    brouillon=vue.__name__ == "instruction_dossier_enregistrer_brouillon_avis")
                if erreur is not None:
                    return erreur
                return vue(request, *args, **kwargs)
        except PermissionDenied as erreur:
            return HttpResponseForbidden(str(erreur))
        except ValidationError as erreur:
            return HttpResponseBadRequest(" ".join(erreur.messages))
    return executer


def _destinataire_cs_depuis_formulaire(request, expert, obligatoire=True):
    """Valide le code de destinataire ; l'obligation dépend de la configuration."""
    destinataire = (request.POST.get("destinataire") or "").strip().upper()
    valeurs_valides = {choix for choix, _ in Avis.Destinataire.choices}
    if destinataire in valeurs_valides:
        return destinataire
    if obligatoire:
        raise ValueError("Le destinataire CS ou BCS est obligatoire pour une demande d'avis au Conseil scientifique.")
    return None


def _notifier_demande_avis(request, avis, dossier=None):
    """Préparer l'outbox en transaction ; envoyer seulement après le commit."""
    destinataires = [get_email_expert(avis)] if NOTIFS_PROD else [EMAIL_NOTIF_TEST]
    generique = dossier is None
    sujet = f"{avis.id_instructeur} vous demande votre avis"
    if dossier:
        sujet += f" sur le dossier n° {dossier.numero} ({dossier.id_demarche.type})"
    elif avis.id_demarche.type:
        sujet += f" ({avis.id_demarche.type})"
    contexte = {
        "avis_numero": avis.id, "demarche_type": avis.id_demarche.type,
        "demandeur": str(avis.id_instructeur), "message": avis.formulation,
        "url": f"{os.getenv('URL_APPLI')}reception_avis/{avis.id}/",
    }
    if dossier:
        contexte["dossier_numero"] = dossier.numero
    template = "nouvelle_demande_avis_generique" if generique else "nouvelle_demande_avis_dossier"
    try:
        cle = compute_dedupe_key(destinataires, sujet, template, contexte)
        outbox = create_EmailOutbox(destinataires, sujet, template, cle, contexte, dossier, type_mail="Notification")
        if not outbox:
            raise ValueError("La notification n'a pas pu être préparée.")
    except Exception:
        logger.exception("[AVIS %s] Échec de préparation de la notification.", avis.id)
        messages.error(request, "La notification n'a pas pu être préparée. Contactez le support.")
        return

    def envoyer():
        try:
            ok, erreur = envoi_mail(outbox.id)
            if not ok:
                raise ValueError(erreur)
            logger.info("[AVIS %s] Notification %s envoyée.", avis.id, outbox.id)
        except Exception:
            logger.exception("[AVIS %s] Échec d'envoi de la notification %s.", avis.id, outbox.id)
            messages.error(request, "La demande a été enregistrée mais sa notification n'a pas pu être envoyée. Contactez le support.")
    transaction.on_commit(envoyer)


def _enregistrer_pj_complementaires(request, avis):
    """Conserver les PJ d'un brouillon et ne remplacer que celles de cet avis."""
    nouveaux = request.FILES.getlist("pj_lie_avis")
    remplacements = {cle for cle in request.FILES if cle.startswith("remplacer_pj_")}
    if not nouveaux and not remplacements:
        return
    liens = list(AvisDocument.objects.filter(id_avis=avis).select_related("id_document")) if remplacements else []
    cles_connues = {f"remplacer_pj_{lien.id_document_id}" for lien in liens}
    if remplacements - cles_connues:
        raise ValueError("La pièce jointe à remplacer n'appartient pas à cet avis.")
    fichiers = nouveaux + [request.FILES[cle] for cle in remplacements]
    for fichier in fichiers:
        if Path(fichier.name).suffix.lower() not in {".pdf", ".png", ".jpg", ".jpeg", ".doc", ".docx", ".odt"}:
            raise ValueError(f"Format non autorisé pour la pièce jointe {fichier.name}.")
    if not creer_dossier_sur_nas(f"{os.getenv('NAS_ROOT')}{avis.emplacement}Annexes/"):
        raise ValueError("Impossible de préparer le répertoire des pièces jointes sur le NAS.")

    def enregistrer(fichier):
        doc = enregistrer_document(
            fichier=fichier, nature_str="Annexe avis", request=request,
            description=f"Pièce jointe pour la demande d'avis {avis.id}", emplacement_avis=avis.emplacement,
        )
        if not doc:
            raise ValueError(f"La pièce jointe {fichier.name} n'a pas pu être enregistrée. Réessayez.")
        return doc

    for lien in liens:
        fichier = request.FILES.get(f"remplacer_pj_{lien.id_document_id}")
        if fichier:
            doc = enregistrer(fichier)
            if doc.pk != lien.id_document_id:
                AvisDocument.objects.get_or_create(id_avis=avis, id_document=doc)
                lien.delete()
    for fichier in nouveaux:
        AvisDocument.objects.get_or_create(id_avis=avis, id_document=enregistrer(fichier))


@login_required
def instruction_dossier_consultation(request, num_dossier) :

    # --- Récupération du dossier ---
    dossier = Dossier.objects.filter(numero=num_dossier).first()
    if not dossier:
        logger.error(f"[CONSULTATION] Dossier {num_dossier} introuvable en base — user={request.user}")
        return redirect_error(request, f"Le dossier {num_dossier} est introuvable. Contactez le support.")
        

    # --- Récupération de l'instructeur.rice ---
    instructeur = Instructeur.objects.filter(email=request.user.email).first()
    if not instructeur:
        logger.warning(f"[CONSULTATION DOSSIER] Utilisateur {request.user.email} sans profil instructeur")
        messages.warning(request,"Vous n'avez pas de profil 'Instructeur.trice'. Contactez le support.")

    dossiers_avis = DossierAvis.objects.filter(id_dossier=dossier).select_related(
        "id_avis",
        "id_avis__id_instructeur",
        "id_avis__id_expert",
        "id_avis__id_expert__id_instructeur",
        "id_avis__id_expert__id_contact_externe",
        "id_avis__id_avis_nature"
    )

    liste_avis = []
    nb_avis_avec_nouveau_mess = 0


    for da in dossiers_avis:
        avis = da.id_avis

        if not avis:
            logger.error(f"[CONSULTATION] Dossier {num_dossier} - DossierAvis {da.id} : Avis manquant")
            continue


        # EXPERT
        expert = get_expert_label(avis, num_dossier)
       
        # RÉPONSE AVIS
        reponse = get_reponse_label(avis)

        # EMAIL DE L’EXPERT
        email_expert = get_email_expert(avis, num_dossier)
       
        # MESSAGES (DE L'EXPERT) NON LUS
        nb_messages_non_lus_avis = count_unread_messages_for_avis(avis, email_expert, num_dossier)
        if nb_messages_non_lus_avis > 0:
            nb_avis_avec_nouveau_mess += 1

        # DEMANDEUR
        demandeur = get_demandeur_label(avis, num_dossier)
        

        # Construire le dictionnaire
        liste_avis.append({
            "statut": avis.statut,
            "expert": expert or "N/A",
            "numero": avis.id,
            "numero_affiche": avis.numero_affiche,
            "demandeur": demandeur,
            "date_demande": avis.date_demande_avis,
            "date_reponse": avis.date_reponse_avis,
            "reponse": reponse,
            "avis_nb_messages_non_lus": nb_messages_non_lus_avis,
        })


    # TRI DES AVIS
    try:
        liste_avis = sorted(
            liste_avis,
            key=lambda x: (x["statut"] == "Envoyé", x["date_demande"]),
            reverse=True
        )
    except Exception as e:
        logger.error(f"[CONSULTATION DOSSIER {dossier.numero}] Erreur lors du tri de la liste des avis : {e}")



    # Nombre d'avis envoyés
    nb_avis_envoyes = DossierAvis.objects.filter(id_dossier=dossier, id_avis__statut="Envoyé").count()

    # Messages non lus DOSSIER
    nb_messages_non_lus = count_unread_messages_for_dossier(dossier, num_dossier)



    return render(request, "instruction/instruction_dossier_consultation.html", {
        "NAS_ROOT": os.getenv('NAS_ROOT'),
        "dossier": dossier,
        "chemin_complet": get_chemin_complet_dossier(dossier),
        "est_instructeur": instructeur,
        "is_formulaire_active": False,
        "is_messagerie_active": False,
        "is_consultation_active": True,
        "avis": liste_avis,
        "nb_avis_envoyes": nb_avis_envoyes,
        "nb_messages_non_lus": nb_messages_non_lus,
        "nb_avis_avec_nouveau_mess": nb_avis_avec_nouveau_mess,
    })


@login_required
@require_http_methods(["GET", "POST"])
def instruction_dossier_ajouter_avis(request, num_dossier, avis_id=None):
    
    # --- Récupération du dossier ---
    dossier = Dossier.objects.filter(numero=num_dossier).first()
    if not dossier:
        logger.error(f"[AJOUTER AVIS] Dossier {num_dossier} introuvable en base — user={request.user}")
        return redirect_error(request, f"Le dossier {num_dossier} est introuvable. Contactez le support.")
        


    instructeur_connecte = Instructeur.objects.filter(email=request.user.email).first()
    if not instructeur_connecte:
        return HttpResponseForbidden("Vous devez disposer d'un profil instructeur pour créer une demande d'avis.")
    reservation = None
    if avis_id is None:
        try:
            if request.method == "POST":
                reservation = reserver_numero(instructeur_connecte, dossier, request.POST.get("reservation"))
                return redirect(reverse("instruction_dossier_ajouter_avis", kwargs={"num_dossier": num_dossier}) + "?reservation=" + str(reservation.pk))
            if not request.GET.get("reservation"):
                return render(request, "instruction/avis_reserver_numero.html", {
                    "reservation_cle": uuid4(), "dossier": dossier,
                })
            reservation = lire_reservation(request.GET["reservation"], instructeur_connecte, dossier)
            if reservation.id_avis_id:
                return redirect("instruction_dossier_ajouter_avis", num_dossier=num_dossier, avis_id=reservation.id_avis_id)
        except PermissionDenied as erreur:
            return HttpResponseForbidden(str(erreur))
        except ValidationError as erreur:
            return HttpResponseBadRequest(" ".join(erreur.messages))
        except Exception:
            logger.exception("[DOSSIER %s] Impossible de préparer la réservation d'avis.", num_dossier)
            return HttpResponse("Impossible de réserver le numéro d'avis. Réessayez ou contactez le support.", status=503)
    elif request.method != "GET":
        return HttpResponseBadRequest("Utilisez les boutons d'enregistrement ou d'envoi de l'avis.")

    # --- Récupération éventuelle de l'avis (édition) ---
    avis = None
    if avis_id is not None:
        avis = Avis.objects.filter(id=avis_id, id_dossier=dossier).select_related(
            "id_projet_avis", "id_projet_acte", "id_rapport_instance",
        ).first()
        if not avis:
            logger.error(f"[AJOUT AVIS] Dossier {num_dossier} — Avis {avis_id} introuvable ou non lié au dossier.")
            return avis_introuvable(request, avis_id, num_dossier)
            
        

    pieces_complementaires = []
    if avis:
        # AvisDocument matérialise l'ajout aux « Autres PJ », même si le même
        # Document est également référencé par un ou plusieurs champs principaux.
        pieces_complementaires = (
            AvisDocument.objects.filter(id_avis=avis)
            .exclude(id_document__id_nature__nature="Avis instance")
            .select_related("id_document").order_by("id")
        )

    # Récupérer toutes les natures et thématiques
    natures = AvisNature.objects.all().order_by("nature")

    # thematiques = AvisThematique.objects.all().order_by("thematique")
    thematiques = AvisThematique.objects.all().order_by("thematique")

    # Tous les avis déjà envoyés pour ce dossier
    avis_existants = Avis.objects.filter(id_dossier=dossier, statut="Envoyé")

    # La restriction existante concerne les experts internes, pas les instances.
    instructeurs_utilises = avis_existants.filter(id_expert__id_instructeur__isnull=False) \
                                          .values_list("id_expert__id_instructeur__email", flat=True)


    # Instructeurs candidats
    instructeurs_qs = (
        Instructeur.objects
        .filter(email__isnull=False)
        .exclude(email__exact="")
        .exclude(email__exact="autorisations@reunion-parcnational.fr")
        .exclude(email=request.user.email)  # pas soi-même
        .exclude(email__in=instructeurs_utilises)  # pas déjà utilisé
        .order_by("id_agent_autorisations__nom","id_agent_autorisations__prenom")
    )

    # Contacts externes candidats
    contacts_qs = (
        ContactExterne.objects
        .filter(email__isnull=False, id_type__type="Instance")
        .exclude(email__exact="")
        .exclude(email=request.user.email)  # pas soi-même
        .order_by("nom", "email")
    )

    # Supprimer les doublons d'email (si jamais)
    instructeurs = {i.email: i for i in instructeurs_qs}.values()
    contacts_externes = {c.email: c for c in contacts_qs}.values()

    # Nombre d'avis envoyés
    nb_avis_envoyes = DossierAvis.objects.filter(id_dossier=dossier, id_avis__statut="Envoyé").count()

    # Messages non lus
    nb_messages_non_lus = count_unread_messages_for_dossier(dossier, num_dossier)


    # --- Nombre d'avis avec au moins un message non lu de l'expert ---
    nb_avis_avec_nouveau_mess = count_avis_with_unread_messages_for_dossier(dossier, num_dossier)

    # nb_avis_avec_nouveau_mess = 0
    # for da in DossierAvis.objects.filter(id_dossier=dossier).select_related("id_avis__id_expert"):
    #     avis_item = da.id_avis
    #     if not avis_item or not avis_item.id_expert:
    #         continue

    #     if avis_item.id_expert.est_interne:
    #         email_expert = avis_item.id_expert.id_instructeur.email
    #     else:
    #         email_expert = avis_item.id_expert.id_contact_externe.email

    #     nb_non_lus_avis = Message.objects.filter(
    #         id_avis=avis_item,
    #         lu=False,
    #         email_emetteur=email_expert
    #     ).count()

    #     if nb_non_lus_avis > 0:
    #         nb_avis_avec_nouveau_mess += 1


    return render(request, "instruction/instruction_dossier_ajouter_avis.html", {
        "dossier": dossier,
        "chemin_complet": get_chemin_complet_dossier(dossier),
        "avis": avis,
        "natures": natures,
        "thematiques": thematiques, 
        "instructeurs": instructeurs,
        "contacts_externes": contacts_externes,
        "pieces_complementaires": pieces_complementaires,
        "reservation": reservation,
        "numero_avis": avis.numero_affiche if avis else reservation.numero,
        "avis_formulaire_configuration": _configuration_formulaire("dossier", dossier, avis.id if avis else reservation.numero),
        "is_formulaire_active": False,
        "is_messagerie_active": False,
        "is_consultation_active": True,
        "nb_avis_envoyes": nb_avis_envoyes,
        "nb_messages_non_lus": nb_messages_non_lus,
        "nb_avis_avec_nouveau_mess": nb_avis_avec_nouveau_mess,
        "NAS_ROOT": os.getenv('NAS_ROOT'),
    })


@login_required
def instruction_dossier_ajouter_avis_existant(request, num_dossier):
    
    # --- Récupération du dossier ---
    dossier = Dossier.objects.filter(numero=num_dossier).first()
    if not dossier:
        logger.error(f"[AJOUTER AVIS EXISTANT] Dossier {num_dossier} introuvable en base — user={request.user}")
        return redirect_error(request, f"Le dossier {num_dossier} est introuvable. Contactez le support.")
        

    # Récupérer toutes les natures et thématiques
    natures = AvisNature.objects.all().order_by("nature")
    thematiques = AvisThematique.objects.all().order_by("thematique")

    # Tous les instructeurs
    # tous_les_instructeurs = Instructeur.objects.all()
    tous_les_instructeurs = Instructeur.objects.select_related("id_agent_autorisations").order_by("id_agent_autorisations__nom","id_agent_autorisations__prenom")
    tous_les_experts = Expert.objects.all()


    # --- Instructeur courant (user connecté) ---
    instructeur_connecte = Instructeur.objects.filter(email=request.user.email).first()
    if not instructeur_connecte:
        logger.warning(f"[AJOUTER AVIS EXISTANT] Utilisateur {request.user.email} sans profil instructeur")
        messages.warning(request, "Vous n'avez pas de profil 'Instructeur.trice'. Contactez le support.")

    # Tous les avis déjà envoyés pour ce dossier
    avis_existants = Avis.objects.filter(id_dossier=dossier, statut="Envoyé")

    # Extraire les instructeurs et contacts déjà utilisés
    instructeurs_utilises = avis_existants.filter(id_expert__id_instructeur__isnull=False) \
                                          .values_list("id_expert__id_instructeur__email", flat=True)
    
    # Instructeurs candidats
    instructeurs_qs = (
        Instructeur.objects
        .filter(email__isnull=False)
        .exclude(email__exact="")
        .exclude(email__exact="autorisations@reunion-parcnational.fr")
        # .exclude(email=request.user.email)  # pas soi-même
        .exclude(email__in=instructeurs_utilises)  # pas déjà utilisé
        .order_by("id_agent_autorisations__nom","id_agent_autorisations__prenom")
    )

    # Contacts externes candidats
    contacts_qs = (
        ContactExterne.objects
        .filter(email__isnull=False, id_type__type="Instance")
        .exclude(email__exact="")
        .exclude(email=request.user.email)  # pas soi-même
        .exclude(id_type__type__in=["Demandeur intermédiaire", "Bénéficiaire"])
        .order_by("nom", "email")
    )

    # Supprimer les doublons d'email (si jamais)
    instructeurs = {i.email: i for i in instructeurs_qs}.values()
    contacts_externes = {c.email: c for c in contacts_qs}.values()

    # --- Messages non lus DOSSIER ---
    nb_messages_non_lus = count_unread_messages_for_dossier(dossier, num_dossier)

    # --- Avis avec au moins un message non lu ---
    nb_avis_avec_nouveau_mess = count_avis_with_unread_messages_for_dossier(dossier, num_dossier)


    # ----------------------------
    # PARTIE RECHERCHE D’AVIS
    # ----------------------------
    avis_list = None

    try :
        if request.GET:  # seulement si une recherche est soumise
            avis_list = Avis.objects.all().select_related("id_avis_nature", "id_avis_thematique", "id_expert", "id_instructeur")

            numero = request.GET.get("numero")
            expert = request.GET.get("expert")
            demandeur = request.GET.get("demandeur")
            date_demande = request.GET.get("date_demande")
            date_reponse = request.GET.get("date_reponse")
            reponse = request.GET.get("reponse")
            thematique = request.GET.get("thematique")
            nature = request.GET.get("nature")
            deja_lie = request.GET.get("deja_lie")
            statut = request.GET.get("statut")

            if numero:
                avis_list = avis_list.filter(filtre_numero_avis(numero))
            if expert:
                avis_list = avis_list.filter(id_expert=expert)
            if demandeur:
                avis_list = avis_list.filter(id_instructeur=demandeur)
            if date_demande:
                avis_list = avis_list.filter(date_demande_avis__date=date_demande)
            if date_reponse:
                avis_list = avis_list.filter(date_reponse_avis__date=date_reponse)
            if reponse in {valeur for valeur, _libelle in Avis.Reponse.choices}:
                avis_list = avis_list.filter(reponse=reponse)
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

    except Exception as e:
        logger.error(f"[AJOUTER AVIS EXISTANT] Dossier {num_dossier} Erreur lors de la recherche d'avis — user={request.user} : {e}")
        messages.error(request, f"Une erreur est survenue au cours de la recherche de la demande d'avis existante. Contactez le support.")
    

    return render(request, "instruction/instruction_dossier_ajouter_avis_existant.html", {
        "dossier": dossier,
        "chemin_complet": get_chemin_complet_dossier(dossier),
        "natures": natures,
        "thematiques": thematiques,
        "instructeurs": instructeurs,
        "tous_les_instructeurs": tous_les_instructeurs,
        "contacts_externes": contacts_externes,
        "is_formulaire_active": False,
        "is_messagerie_active": False,
        "is_consultation_active": True,
        "nb_messages_non_lus": nb_messages_non_lus,
        "nb_avis_avec_nouveau_mess": nb_avis_avec_nouveau_mess,
        "NAS_ROOT": os.getenv('NAS_ROOT'),
        "avis_list": avis_list,
        "tous_les_experts": tous_les_experts,
        "avis_formulaire_configuration": _configuration_formulaire("existant", dossier),
    })



@login_required
def lier_dossier_avis(request, num_dossier, avis_id):

    # --- Récupération dossier ---
    dossier = Dossier.objects.filter(numero=num_dossier).first()
    if not dossier:
        logger.error(f"[LIER AVIS À DOSSIER] Dossier {num_dossier} introuvable — user={request.user.email}")
        return redirect_error(request, f"Dossier {num_dossier} introuvable. Contactez le support.")
        
    
    # --- Récupération avis ---
    avis = Avis.objects.filter(id=avis_id).select_related(
        "id_expert",
        "id_expert__id_instructeur",
    ).first()
    if not avis:
        logger.error(f"[LIER AVIS À DOSSIER] Avis {avis_id} introuvable — dossier={num_dossier}")
        return redirect_error(request, f"L'avis {avis_id} est introuvable. Contactez le support.")
        
    


    if request.method == "POST":
        try:
            # Vérifie si déjà lié
            existe = DossierAvis.objects.filter(id_dossier=dossier, id_avis=avis).exists()
            if not existe:
                DossierAvis.objects.create(id_dossier=dossier, id_avis=avis)
            else:
                messages.warning(request, f"L'avis {avis.id} est déjà lié à ce dossier.")

        except Exception as e:
            logger.error(f"[LIER AVIS À DOSSIER] Erreur lors de l’association de l'Avis {avis_id} au Dossier {num_dossier} : {e}")
            return redirect_error(request, f"Une erreur est survenue lors de l’association de l’avis au dossier. Contactez le support.")
            

        # Redirection vers la consultation
        return redirect("instruction_dossier_consultation", num_dossier=dossier.numero)

    return redirect("instruction_dossier_ajouter_avis_existant", num_dossier=dossier.numero)



@login_required
def ajouter_avis_hors_appli(request, num_dossier):
    
    dossier = Dossier.objects.filter(numero=num_dossier).first()
    if not dossier:
        logger.error(f"[AJOUT AVIS HORS APPLI] Dossier {num_dossier} introuvable")
        return redirect_error(request, f"Dossier {num_dossier} introuvable. Contactez le support.")
        

    if request.method == "POST":
        try:
            erreur = _valider_formulaire_configure(request, dossier, contexte="existant")
            if erreur is not None:
                return erreur
            # 1. Récupérer les champs du formulaire
            nature_id = request.POST.get("nature")
            thematique_id = request.POST.get("thematique")
            mode_contact = request.POST.get("mode_contact")
            reponse = request.POST.get("reponse")
            if reponse and reponse not in {valeur for valeur, _libelle in Avis.Reponse.choices}:
                return redirect_error(request, "La réponse de l'avis n'est pas valide.")
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
                    logger.error(f"[DOSSIER {dossier.numero}] Ajout Avis hors application : Erreur lors de la récupération de l'expert externe : {e}")
                    return redirect_error(request, f"Erreur lors de la récupération de l'expert externe. Contactez le support.")
                    
                
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
                    logger.error(f"[DOSSIER {dossier.numero}] Ajout Avis hors application : Erreur lors de la récupération de l'expert interne : {e}")
                    return redirect_error(request, f"Erreur lors de la récupération de l'expert interne. Contactez le support.")
                    
                
                expert, created = Expert.objects.get_or_create(
                    id_instructeur=expert_interne,
                    defaults={"est_interne": True}
                )
                if created:
                    logger.info(f"[EXPERT] Nouvel expert interne créé : {instru}")

            
            instructeur_demandeur = None
            if instructeur_demandeur_id:
                instructeur_demandeur = Instructeur.objects.get(id=instructeur_demandeur_id)

            numero_avis_externe = None
            publie_au_raa = None
            if expert_est_conseil_scientifique(expert):
                donnees_cs = request.POST.copy()
                # Conserver le comportement historique si un ancien formulaire est soumis.
                if not donnees_cs.get("publication_raa"):
                    donnees_cs["publication_raa"] = "a_publier"
                formulaire_cs = ImportAvisCSForm(donnees_cs)
                if not formulaire_cs.is_valid():
                    return redirect_error(request, " ".join(
                        f"{formulaire_cs.fields[cle].label} : {message}"
                        for cle, erreurs in formulaire_cs.errors.items() for message in erreurs
                    ))
                numero_avis_externe = formulaire_cs.cleaned_data["numero_avis_externe"] or None
                # Choix métier : non requise et déjà publiée sont toutes deux traitées.
                publie_au_raa = None if formulaire_cs.cleaned_data["publication_raa"] == "a_publier" else True

            # Création emplacement
            emplacement = emplacement_demande_avis_dossier(dossier, nom_prenom_expert)


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
                numero_avis_externe=numero_avis_externe,
                publie_au_raa=publie_au_raa,
                formulation=formulation,
                reponse=reponse or None,
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

            attach_pj_to_avis(avis, fichiers, emplacement, request, dossier.numero)

            # if fichiers :
            #     chemin_complet = f"{os.getenv('NAS_ROOT')}{emplacement}Annexes/"
            #     creer_dossier_sur_nas(chemin_complet)
                
            #     # on parcourt les fichiers et on les écrit physiquement
            #     for pj in fichiers :
                    
            #         doc_pj = enregistrer_document(
            #             fichier=pj,
            #             nature_str="Annexe avis",
            #             description=f"Pièce jointe pour la demande d'avis {avis.id} effectuée en dehors de l'application",
            #             request=request,
            #             emplacement_avis = emplacement,
            #         )

            #         # Création AvisDocument
            #         if doc_pj:
            #             AvisDocument.objects.create(
            #                 id_avis=avis,
            #                 id_document=doc_pj
            #             )

            return redirect("instruction_dossier_consultation", num_dossier=dossier.numero)

        except Exception as e:
            logger.error(f"[AJOUT AVIS HORS APPLI] Dossier {num_dossier} : {e}")
            return redirect_error(request, f"Erreur lors de l'ajout de l'avis. Contactez le support.")
            



@login_required
def ajouter_pj_avis(request, avis_id):
    
    avis = Avis.objects.filter(id=avis_id).first()
    if not avis:
        logger.error(f"[AJOUT PJ AVIS] Avis {avis_id} introuvable")
        return redirect_error(request, "L'avis demandé est introuvable. Contactez le support.")
        


    if request.method == "POST":
        fichiers = request.FILES.getlist("pj_avis")
        if not fichiers:
            return redirect_error(request, "⚠️ Aucun fichier sélectionné.")
        
        try:  
           attach_pj_to_avis(
                avis=avis,
                fichiers=fichiers,
                emplacement_avis=avis.emplacement,
                request=request,
                dossier_numero=None,
            )


        except Exception as e:
            logger.error(f"[AJOUT PJ AVIS] Avis {avis_id} : {e}")
            messages.error(request, f"Une erreur est survenue lors de l'ajout des pièces jointes. Contacter le support.")

        return redirect(request.META.get("HTTP_REFERER", "/"))


@require_POST
@login_required
def supprimer_pj_avis(request, avis_id, document_id):
    
    avis = Avis.objects.filter(id=avis_id).first()
    if not avis:
        logger.error(f"[SUPPR PJ AVIS] Avis {avis_id} introuvable")
        return redirect_error(request, "L'avis est introuvable en base. Contactez le support.")
    
    avis_doc = AvisDocument.objects.filter(id_avis=avis, id_document_id=document_id).first()
    champs_principaux = ("id_projet_avis", "id_projet_acte", "id_rapport_instance")
    champs = [
        champ for champ in champs_principaux
        if getattr(avis, f"{champ}_id") == document_id
    ]
    source = request.POST.get("source")
    if source in champs_principaux:
        if source not in champs:
            return JsonResponse({"success": False, "error": "Cette pièce jointe n'appartient pas au champ indiqué."}, status=403)
        champs = [source]
        avis_doc = None
    elif source == "annexe" or (not source and avis_doc):
        # Une annexe et un champ principal peuvent référencer le même Document.
        champs = []
    elif source or len(champs) > 1:
        return JsonResponse({"success": False, "error": "Précisez le champ de la pièce jointe à retirer. Rechargez la page puis réessayez."}, status=400)
    if not avis_doc and not champs:
        logger.warning("[SUPPR PJ AVIS] Document %s non lié à l'avis %s.", document_id, avis_id)
        return JsonResponse({"success": False, "error": "Cette pièce jointe n'appartient pas à cet avis."}, status=403)

    try:
        for champ in champs:
            setattr(avis, champ, None)
        if champs:
            avis.save(update_fields=champs)
        if avis_doc:
            avis_doc.delete()
        # Conserver le Document et son fichier : d'autres messages peuvent le référencer.
    except Exception:
        logger.exception("[AVIS %s] Échec du retrait de la pièce jointe %s.", avis_id, document_id)
        return JsonResponse({"success": False, "error": "La pièce jointe n'a pas pu être retirée."}, status=500)

    logger.info("[AVIS %s] Pièce jointe %s retirée de %s par %s.", avis_id, document_id, source or "lien historique", request.user)
    if "application/json" in request.headers.get("Accept", ""):
        return JsonResponse({"success": True})
    return redirect(request.META.get("HTTP_REFERER", "/"))


@require_POST
@login_required
@_creation_avec_numero_reserve
def instruction_dossier_confirmer_ajout_avis(request, num_dossier, avis_id=None):
    

    instructeur = getattr(request, "instructeur_reservation", None) or Instructeur.objects.filter(email=request.user.email).first()
    if not instructeur:
        logger.warning(f"Erreur lors de la récupération de l'instructeur pour le user {request.user} : {e}")
        return redirect_error(request, f"Aucun instructeur.rice n'est associé.e à votre profil. Contactez le support.")

    
    # --- Récupération dossier ---
    dossier = getattr(request, "dossier_reservation", None) or Dossier.objects.filter(numero=num_dossier).first()
    if not dossier:
        logger.error(f"[CONFIRMER AJOUT AVIS] Dossier {num_dossier} introuvable en base.")
        return redirect_error(request, f"Dossier {num_dossier} introuvable. Contactez le support.")
    

    # --- Récupération brouillon éventuel ---
    brouillon_avis = None
    if avis_id:
        brouillon_avis = getattr(request, "brouillon_reservation", None) or Avis.objects.filter(id=avis_id, id_dossier=dossier).first()
        if not brouillon_avis:
            logger.error(f"[CONFIRMER AJOUT AVIS] Brouillon avis {avis_id} introuvable pour dossier {num_dossier}.")
            return redirect_error(request, "Le brouillon de l'avis est introuvable. Contactez le support.")
    

    # ---- Extraction expert interne/externe ---- #
    try :
        expert, nom_prenom_expert = get_or_create_expert_from_form(request)

    except Exception as e:
        logger.error(f"[CONFIRMER AJOUT AVIS] Dossier {num_dossier}, {avis_id} : Erreur lors de la récupération de l'expert (get_or_create_expert_from_form) : {e}")
        return redirect_error(request, f"Erreur lors de la récupération de l’expert. Contactez le support.")

    try:
        destinataire = _destinataire_cs_depuis_formulaire(request, expert, obligatoire=False)
    except ValueError as e:
        return redirect_error(request, str(e))


    if request.method == "POST":
        # Champs du formulaire
        nature_id = request.POST.get("nature")
        if brouillon_avis and brouillon_avis.statut == "Brouillon" and str(nature_id) != str(brouillon_avis.id_avis_nature_id):
            return redirect_error(request, "La nature d'un avis au statut Brouillon ne peut pas être modifiée.")
        thematique_id = request.POST.get("thematique")
        note = request.POST.get("note_demandeur", "").strip()
        mode_contact = "Application"
        formulation_avis = (request.POST.get("formulation_avis") or "").strip()
        pj_projet_avis = request.FILES.get("pj_demande_avis")
        pj_projet_acte = request.FILES.get("pj_projet_acte")
        pj_rapport_cs = request.FILES.get("pj_rapport_cs")
        liste_autres_pj = request.FILES.getlist("pj_lie_avis")


        # --- Récupération nature ---
        try:
            nature = AvisNature.objects.get(id=nature_id)
        except Exception as e:
            logger.error(f"Erreur lors de la récupération de la nature d'avis {nature_id} : {e}")
            return redirect_error(request, f"Erreur lors de la récupération de la nature d'avis. Contactez le support.")
            


        # --- Récupération thématique ---
        try:
            thematique = AvisThematique.objects.get(id=thematique_id)
        except Exception as e:
            logger.error(f"Erreur lors de la récupération de la thématique de l'avis {thematique_id} : {e}")
            return redirect_error(request, f"Erreur lors de la récupération de la thématique de l'avis. Contactez le support.")
            

        
        if nature.nature not in {"Consultation en interne", "Demande à une instance"}:
            return redirect_error(request, "La nature de l'avis n'est pas autorisée pour ce formulaire.")
        if (nature.nature == "Consultation en interne") != bool(expert.est_interne):
            return redirect_error(request, "L'expert sélectionné ne correspond pas à la nature de l'avis.")
        # ---- On récupère l'emplacement physique de l'avis ----
        try:
            emplacement = emplacement_demande_avis_dossier(dossier, nom_prenom_expert, brouillon_avis)
        except Exception:
            logger.exception("[DOSSIER %s] Impossible de préparer le répertoire de la demande d'avis.", dossier.numero)
            return redirect_error(request, "Impossible de préparer le répertoire de la demande d'avis sur le NAS. Réessayez ou contactez le support.")
        
        doc_projet_acte = doc_rapport_instance = doc_projet_avis = None


        # ---- Création des folders
        if pj_projet_avis or pj_projet_acte or pj_rapport_cs or liste_autres_pj :
            chemin_complet = f"{os.getenv('NAS_ROOT')}{emplacement}Annexes/"
            creer_dossier_sur_nas(chemin_complet)



        #############################
        # ---- ÉCRITURE DES PJ ---- #
        #############################
        # Projet d'avis
        if pj_projet_avis :
            extension = Path(pj_projet_avis.name).suffix.lower()
            if extension not in {".doc", ".docx", ".odt"} :
                logger.warning(f"[CONFIRMER AJOUT AVIS] Le projet de demande d'avis a tenté d'être déposé au format {extension} par {request.user}. Formats autorisés : .doc, .docx, .odt")
                return redirect_error(request, f"❌ Le projet de demande d'avis doit etre au format .doc ou .docx ou .odt --> Type de fichier non autorisé : {extension}")
                
            
            doc_projet_avis = enregistrer_document(
                fichier=pj_projet_avis,
                nature_str="Annexe avis",
                description=f"Projet de demande pour l'avis {avis_id}",
                request=request,
                emplacement_avis = emplacement,
            )
        
        # Projet d'acte
        if pj_projet_acte :
            extension = Path(pj_projet_acte.name).suffix.lower()
            if extension not in {".doc", ".docx", ".odt", ".pdf"} :
                logger.warning(f"[CONFIRMER AJOUT AVIS] Le projet d'acte a tenté d'être déposé au format {extension} par {request.user}. Format autorisé : .doc, .docx, .odt, .pdf")
                return redirect_error(request, f"❌ Le projet d'acte doit etre au format .doc, .docx, .odt ou .pdf --> Type de fichier non autorisé : {extension}")
                
            
            doc_projet_acte = enregistrer_document(
                fichier=pj_projet_acte,
                nature_str="Annexe avis",
                description=f"Projet d’acte pour l'avis {avis_id}",
                request=request,
                emplacement_avis = emplacement,
            )
        
        # Rapport CS
        if pj_rapport_cs :
            extension = Path(pj_rapport_cs.name).suffix.lower()
            if extension != ".pdf" :
                logger.warning(f"[CONFIRMER AJOUT AVIS] Le rapport au CS a tenté d'être déposé au format {extension} par {request.user}. Format autorisé : .pdf")
                return redirect_error(request, f"❌ Le rapport de l'instance doit etre au format .pdf --> Type de fichier non autorisé : {extension}")
                
            
            doc_rapport_instance = enregistrer_document(
                fichier=pj_rapport_cs,
                nature_str="Annexe avis",
                description=f"Rapport Instance pour l'avis {avis_id}",
                request=request,
                emplacement_avis = emplacement,
            )

        # # Autres PJ
        # if liste_autres_pj :
        #     try :
            
        #         # Ecriture physique
        #         for pj in liste_autres_pj :

        #             if avis_id:
        #                 description = f"Pièce jointe déposée par {request.user} pour la demande d'avis {avis_id}"
        #             else:
        #                 description = f"Pièce jointe déposée par {request.user}"
                    
        #             doc_pj = enregistrer_document(
        #                 fichier=pj,
        #                 nature_str="Annexe avis",
        #                 description=description,
        #                 request=request,
        #                 emplacement_avis = emplacement,
        #             )

        #             # Création AvisDocument
        #             if doc_pj:
        #                 AvisDocument.objects.create(id_avis=avis, id_document=doc_pj)

        #     except Exception as e:
        #         logger.error(f"[CONFIRMER AJOUT AVIS] Dossier {dossier.numero}, Avis {avis_id} : Echec du rattachement des autres pièces jointes à la demande d'avis par {request.user} : {e}")
        #         return redirect_error(request, f"Erreur lors du rattachement des pièces jointes annexes à la demande d'avis. Contactez le support.")
                       



        for fichier, document in (
            (pj_projet_avis, doc_projet_avis),
            (pj_projet_acte, doc_projet_acte),
            (pj_rapport_cs, doc_rapport_instance),
        ):
            if fichier and not document:
                logger.error("[DOSSIER %s] Échec de l'enregistrement de la pièce jointe %s.", num_dossier, fichier.name)
                return redirect_error(request, f"La pièce jointe {fichier.name} n'a pas pu être enregistrée. Réessayez.")

        ####################################################
        # ---- CAS 1 : BROUILLON D'AVIS DÉJÀ EXISTANT ---- #
        ####################################################
        if brouillon_avis :

            fields_to_update = {
                "id_avis_nature": nature,
                "id_avis_thematique": thematique,
                "id_expert": expert,
                "destinataire": destinataire,
                "id_demarche": dossier.id_demarche,
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
                    logger.info(f"[DOSSIER {dossier.numero}] Brouillon d'avis ({brouillon_avis}) mis à jour. Changements: {', '.join(updated_fields)}")
                avis = brouillon_avis

            except Exception as e:
                logger.error(f"[CONFIRMER AJOUT AVIS] Dossier {dossier.numero}, Avis {brouillon_avis.id} : Erreur lors de la mise à jour de l'avis : {e}")
                return redirect_error(request, f"Une erreur est survenue lors de la mise à jour de l'avis. Contactez le support.")
            

            # Create message (formulation) + projet demande d'avis en PJ si il existe
            try:
                projet_avis_message = brouillon_avis.id_projet_avis
                msg = Message.objects.create(
                    body=brouillon_avis.formulation,
                    date_envoi=timezone.now(),
                    piece_jointe=bool(projet_avis_message),
                    email_emetteur=request.user.email,
                    id_avis=brouillon_avis,
                    lu=False,
                )

                # Joindre le projet de demande d'avis au message
                if projet_avis_message:
                    MessageDocument.objects.create(id_message=msg, id_document=projet_avis_message)

                logger.info(f"[CONFIRMER AJOUT AVIS] Dossier {dossier.numero}, Avis {brouillon_avis.id} : message par défaut envoyé à {brouillon_avis.id_expert} par {request.user}")

            except Exception as e:
                brouillon_avis.statut = "Brouillon"
                brouillon_avis.save()
                logger.error(f"[CONFIRMER AJOUT AVIS] Dossier {dossier.numero}, Avis {brouillon_avis.id} : Demande d'avis de {request.user} non transmise à {brouillon_avis.id_expert} - Erreur lors de la création du message par défaut (formulation avis) : {e}")
                return redirect_error(request, f"Avis non transmis : Erreur lors de la création du message par défaut (formulation avis): {e}")

        
        
        #############################################################
        # ---- CAS 2 : NOUVEL AVIS (PAS DE BROUILLON EXISTANT) ---- #
        #############################################################
        else :
            try:

                avis = Avis.objects.create(
                        id=request.reservation_avis.numero,
                        id_avis_nature=nature,
                        id_avis_thematique=thematique,
                        date_demande_avis=timezone.now(),
                        statut="Envoyé",
                        note=note,
                        formulation= formulation_avis,
                        mode_contact=mode_contact,
                        id_dossier=dossier,
                        id_demarche=dossier.id_demarche,
                        id_expert=expert,
                        destinataire=destinataire,
                        id_instructeur=instructeur,
                        id_projet_acte=doc_projet_acte,
                        id_rapport_instance=doc_rapport_instance,
                        id_projet_avis=doc_projet_avis,
                        emplacement = emplacement,
                )

                utiliser_reservation(request, avis)
                logger.info(f"[CONFIRMER AJOUT AVIS] Dossier {dossier.numero} : Avis {avis.id} créé par {request.user}")

            except Exception as e:
                logger.error(f"[CONFIRMER AJOUT AVIS] Dossier {dossier.numero} : Erreur lors de la création de l'avis par {request.user} : {e} ")
                return redirect_error(request, f"Erreur lors de la création de l'avis. Contactez le support.")
        
            try:
                DossierAvis.objects.create(id_avis=avis,id_dossier=dossier)

            except Exception as e:
                logger.error(f"[CONFIRMER AJOUT AVIS] Dossier {dossier.numero}, Avis {avis.id} : Erreur lors de la création du DossierAvis par {request.user} : {e} ")
                return redirect_error(request, f"Erreur lors de la création du lien entre le dossier et l'avis. Contactez le support.")


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
                        MessageDocument.objects.create(id_message=msg, id_document=doc_projet_avis)

                    logger.info(f"[CONFIRMER AJOUT AVIS] Dossier {dossier.numero}, Avis {avis.id} : message par défaut envoyé à {avis.id_expert} par {request.user}")


                except Exception as e:
                    avis.statut = "Brouillon"
                    avis.save()
                    logger.error(f"[CONFIRMER AJOUT AVIS] Dossier {dossier.numero}, Avis {avis.id} : Demande d'avis de {request.user} non transmise à {avis.id_expert} - Erreur lors de la création du message par défaut (formulation avis) : {e}")
                    return redirect_error(request, f"Avis non transmis : Erreur lors de la création du message par défaut (formulation avis): {e}")

        try:
            _enregistrer_pj_complementaires(request, avis)
        except Exception as e:
            logger.exception("[AVIS %s] Échec de l'enregistrement des pièces jointes.", avis.id)
            return redirect_error(request, str(e))

        request.creation_avis_validee = True
        _notifier_demande_avis(request, avis, dossier)

    else :
        logger.error(f"[CONFIRMER AJOUT AVIS] Erreur lors de la transmission du formulaire par {request.user} : méthode POST requise.")
        return redirect_error(request, f"Erreur lors de la transmission du formulaire : méthode POST requise. Contactez le support.")
    
    return redirect('instruction_dossier_consultation', num_dossier=num_dossier)




@require_POST
@login_required
@_creation_avec_numero_reserve
def instruction_dossier_enregistrer_brouillon_avis(request, num_dossier, avis_id=None):

    generation_numero = request.POST.get("generer_numero") == "1"
    if generation_numero and avis_id:
        return redirect_error(request, "Cette demande possède déjà un numéro d'avis.")
    try:
        instructeur = getattr(request, "instructeur_reservation", None) or Instructeur.objects.filter(email=request.user.email).first()
        if not instructeur:
            return redirect_error(request, f"Aucun instructeur.rice n'est associé.e à votre profil. Contactez le support")
            
    except Exception as e:
        return redirect_error(request, f"Erreur lors de la récupération de l'instructeur : {e}")
        

    # --- Récupération dossier ---
    dossier = getattr(request, "dossier_reservation", None) or Dossier.objects.filter(numero=num_dossier).first()
    if not dossier:
        logger.error(f"[SAVE BROUILLON AVIS] Dossier {num_dossier} introuvable")
        return redirect_error(request, f"Dossier {num_dossier} introuvable. Contactez le support.")
        

    # Si on reçoit un brouillon d'avis existant
    brouillon_avis = None
    if avis_id:
        brouillon_avis = getattr(request, "brouillon_reservation", None) or Avis.objects.filter(id=avis_id, id_dossier=dossier).first()
        if not brouillon_avis:
            logger.error(f"[SAVE BROUILLON AVIS] Brouillon d'avis {avis_id} introuvable en base pour dossier {num_dossier}")
            return redirect_error(request, "Avis introuvable en base. Contactez le support.")
            
        

    if request.method == "POST":
        # Champs du formulaire
        nature_id = request.POST.get("nature")
        if brouillon_avis and brouillon_avis.statut == "Brouillon" and str(nature_id) != str(brouillon_avis.id_avis_nature_id):
            return redirect_error(request, "La nature d'un avis au statut Brouillon ne peut pas être modifiée.")
        thematique_id = request.POST.get("thematique")
        note = request.POST.get("note_demandeur", "").strip()
        mode_contact = "Application"
        formulation_avis = request.POST.get("formulation_avis") or ""
        expert_interne_id = request.POST.get("expert_interne") # instructeur ici 
        expert_externe_id = request.POST.get("expert_externe") # contact externe ici
        pj_projet_avis = request.FILES.get("pj_demande_avis")
        pj_projet_acte = request.FILES.get("pj_projet_acte")
        pj_rapport_cs = request.FILES.get("pj_rapport_cs")  
        liste_autres_pj = request.FILES.getlist("pj_lie_avis")
   

        try:
            nature = AvisNature.objects.get(id=nature_id)
        except Exception as e:
            logger.error(f"[SAVE BROUILLON AVIS] Nature {nature_id} introuvable : {e}")
            return redirect_error(request, f"Erreur lors de la récupération de la nature de l'avis. Contactez le suppport.")
            

        try:
            thematique = AvisThematique.objects.get(id=thematique_id)
        except Exception as e:
            logger.error(f"[SAVE BROUILLON AVIS] Thématique {thematique_id} introuvable : {e}")
            return redirect_error(request, f"Erreur lors de la récupération de la thématique de l'avis. Contactez le suppport.")

    
        if bool(expert_interne_id) == bool(expert_externe_id):
            return redirect_error(request, "Sélectionnez un seul expert pour la demande d'avis.")
        if generation_numero and (nature.nature != "Demande à une instance" or not expert_externe_id):
            return redirect_error(request, "La génération du numéro est réservée aux demandes à une instance.")

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
                logger.error(f"[SAVE BROUILLON AVIS] Expert interne {expert_interne_id} introuvable : {e}")
                return redirect_error(request, f"Erreur lors de la récupération de l'expert interne. Contactez le suppport.")
        
            
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
                logger.error(f"[SAVE BROUILLON AVIS] Expert externe {expert_externe_id} introuvable : {e}")
                return redirect_error(request, f"Erreur lors de la récupération de l'expert externe. Contactez le suppport.")

        try:
            destinataire = _destinataire_cs_depuis_formulaire(request, expert, obligatoire=generation_numero)
        except ValueError as e:
            return redirect_error(request, str(e))
                
                

        # ---- On récupère l'emplacement physique de l'avis ----
        try:
            emplacement = emplacement_demande_avis_dossier(dossier, nom_prenom_expert, brouillon_avis)
        except Exception:
            logger.exception("[DOSSIER %s] Impossible de préparer le répertoire du brouillon d'avis.", dossier.numero)
            return redirect_error(request, "Impossible de préparer le répertoire du brouillon d'avis sur le NAS. Réessayez ou contactez le support.")


        # ---- Création des folders
        if pj_projet_avis or pj_projet_acte or pj_rapport_cs or liste_autres_pj :
            chemin_complet = f"{os.getenv('NAS_ROOT')}{emplacement}Annexes/"
            creer_dossier_sur_nas(chemin_complet)

            
        

        #############################
        # ---- ÉCRITURE DES PJ ---- #
        #############################
        doc_projet_acte = doc_rapport_instance = doc_projet_avis = None

        # Projet d'avis
        if pj_projet_avis :
            extension = Path(pj_projet_avis.name).suffix.lower()
            if extension not in {".doc", ".docx", ".odt"} :
                logger.warning(f"[SAVE BROUILLON AVIS] Le projet de demande d'avis a tenté d'être déposé au format {extension} par {request.user}. Formats autorisés : .doc, .docx, .odt")
                return redirect_error(request, f"❌ Le projet de demande d'avis doit etre au format .doc ou .docx ou .odt --> Type de fichier non autorisé : {extension}")
                
            
            doc_projet_avis = enregistrer_document(
                fichier=pj_projet_avis,
                nature_str="Annexe avis",
                description=f"Projet de demande pour l'avis {avis_id}",
                request=request,
                emplacement_avis = emplacement,
            )
        
        # Projet d'acte
        if pj_projet_acte :
            extension = Path(pj_projet_acte.name).suffix.lower()
            if extension not in {".doc", ".docx", ".odt", ".pdf"} :
                logger.warning(f"[SAVE BROUILLON AVIS] Le projet d'acte a tenté d'être déposé au format {extension} par {request.user}. Format autorisé : .doc, .docx, .odt ou .pdf")
                return redirect_error(request, f"❌ Le projet d'acte doit etre au format .doc, .docx, .odt ou .pdf --> Type de fichier non autorisé : {extension}")
                
            
            doc_projet_acte = enregistrer_document(
                fichier=pj_projet_acte,
                nature_str="Annexe avis",
                description=f"Projet d’acte pour l'avis {avis_id}",
                request=request,
                emplacement_avis = emplacement,
            )
        
        # Rapport CS
        if pj_rapport_cs :
            extension = Path(pj_rapport_cs.name).suffix.lower()
            if extension != ".pdf" :
                logger.warning(f"[SAVE BROUILLON AVIS] Le projet d'acte a tenté d'être déposé au format {extension} par {request.user}. Format autorisé : .pdf")
                return redirect_error(request, f"❌ Le rapport de l'instance doit etre au format .pdf --> Type de fichier non autorisé : {extension}")
                
            
            doc_rapport_instance = enregistrer_document(
                fichier=pj_rapport_cs,
                nature_str="Annexe avis",
                description=f"Rapport Instance pour l'avis {avis_id}",
                request=request,
                emplacement_avis = emplacement,
            )
                
        
        for fichier, document in (
            (pj_projet_avis, doc_projet_avis),
            (pj_projet_acte, doc_projet_acte),
            (pj_rapport_cs, doc_rapport_instance),
        ):
            if fichier and not document:
                logger.error("[DOSSIER %s] Échec de l'enregistrement de la pièce jointe %s.", num_dossier, fichier.name)
                return redirect_error(request, f"La pièce jointe {fichier.name} n'a pas pu être enregistrée. Réessayez.")

        ####################################################
        # ---- CAS 1 : BROUILLON D'AVIS DÉJÀ EXISTANT ---- #
        ####################################################
        if brouillon_avis :
            fields_to_update = {
                "id_avis_nature": nature,
                "id_avis_thematique": thematique,
                "id_expert": expert,
                "destinataire": destinataire,
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
                avis = brouillon_avis
            except Exception as e:
                logger.error(f"[SAVE BROUILLON AVIS] Dossier {dossier.numero}, Avis {brouillon_avis.id} : Erreur lors de la mise à jour de l'avis : {e}")
                return redirect_error(request, f"Erreur lors de la sauvegarde de l'avis. Contactez le support.")
                
        


        ###################################################################
        # ---- CAS 2 : NOUVEAU BROUILLON (PAS DE BROUILLON EXISTANT) ---- #
        ###################################################################
        else:
            try:
                avis = Avis.objects.create(
                        id=request.reservation_avis.numero,
                        id_avis_nature=nature,
                        id_avis_thematique=thematique,
                        date_demande_avis=timezone.now(),
                        statut="Brouillon",
                        note=note,
                        formulation= formulation_avis,
                        mode_contact=mode_contact,
                        id_dossier=dossier,
                        id_demarche=dossier.id_demarche,
                        id_expert=expert,
                        destinataire=destinataire,
                        id_instructeur=instructeur,
                        id_projet_acte=doc_projet_acte,
                        id_rapport_instance=doc_rapport_instance,
                        id_projet_avis=doc_projet_avis,
                        emplacement = emplacement
                )
                utiliser_reservation(request, avis)

                logger.info(f"[DOSSIER {dossier.numero}] Brouillon de demande d'avis créé : {avis}")

                        
            except Exception as e:
                logger.error(f"[SAVE BROUILLON AVIS] Dossier {dossier.numero} : Erreur lors de la création de l'avis par {request.user} : {e} ")
                return redirect_error(request, f"Erreur lors de la création de l'avis. Contactez le support.")
                
            
            try:
                DossierAvis.objects.create(id_avis=avis, id_dossier=dossier)

            except Exception as e:
                logger.error(f"[SAVE BROUILLON AVIS] Dossier {dossier.numero}, Avis {avis.id} : Erreur lors de la création du DossierAvis par {request.user} : {e} ")
                return redirect_error(request, f"Erreur lors de la création du lien entre le dossier et l'avis. Contactez le support.")
                
              
        try:
            _enregistrer_pj_complementaires(request, avis)
        except Exception as e:
            logger.exception("[AVIS %s] Échec de sauvegarde des pièces jointes du brouillon.", avis.id)
            return redirect_error(request, str(e))
        if generation_numero:
            request.creation_avis_validee = True
            return redirect("instruction_dossier_ajouter_avis", num_dossier=num_dossier, avis_id=avis.id)

        request.creation_avis_validee = True

    else :
        logger.error(f"[SAVE BROUILLON AVIS] Erreur lors de la transmission du formulaire par {request.user} : méthode POST requise.")
        return redirect_error(request, f"Erreur lors de la transmission du formulaire : méthode POST requise. Contactez le support.")
        

    return redirect('instruction_dossier_consultation', num_dossier=num_dossier)



@require_POST
@login_required
def supprimer_avis(request):

    avis_id = request.POST.get("avis_id")

    # Récupération AVIS
    avis = Avis.objects.filter(id=avis_id).first()
    if not avis:
        logger.error(f"[SUPPRESSION AVIS] Avis {avis_id} introuvable en base (user : {request.user}).")
        return redirect_error(request, f"L'avis {avis_id} est introuvable en base. Contactez le support.")

    # L'utilisateur doit être instructeur
    instructeur = Instructeur.objects.filter(email=request.user.email).first()
    if not instructeur:
        logger.warning(f"[SUPPRESSION AVIS] User {request.user.email} sans profil instructeur a tenté de supprimer l'avis {avis_id}")
        return redirect_error(request, "Vous n'avez pas de profil 'Instructeur.trice'. Contactez le support.")
    
    try:
        avis.delete()
        logger.info(f"Suppression de l'avis ({avis_id}) par {instructeur}")

    except Exception as e:
        logger.error(f"[SUPPRESSION AVIS] Erreur lors de la suppression de l'avis {avis_id} par {instructeur} : {e}")
        messages.error(request, f"Erreur lors de la suppression de l'avis. Contactez le support.")

    return redirect(request.META.get("HTTP_REFERER", "/"))



@login_required
def instruction_dossier_avis(request, num_dossier, avis_id):
    """
    Affiche la page de l'avis lié au dossier (Vision instructeur)
    """

    # --- Récupération dossier ---
    dossier = Dossier.objects.filter(numero=num_dossier).first()
    if not dossier:
        logger.error(f"[INSTRUCTION AVIS] Dossier {num_dossier} introuvable par {request.user}")
        return redirect_error(request, f"Dossier {num_dossier} introuvable. Contactez le support.")


    # --- Récupération avis ---
    avis = Avis.objects.filter(id=avis_id, id_dossier=dossier).first()
    if not avis:
        logger.error(f"[INSTRUCTION AVIS] Avis {avis_id} introuvable par {request.user} pour le dossier {num_dossier}")
        return avis_introuvable(request, avis_id, num_dossier)


    request.avis_courant = avis
    instructeur = Instructeur.objects.filter(email=request.user.email).first()

    # --- Instructeur du dossier ? ---
    est_instructeur_du_dossier = False
    if instructeur:
        est_instructeur_du_dossier = DossierInstructeur.objects.filter(id_dossier=dossier, id_instructeur=instructeur).exists()

    est_demandeur = False
    if avis.id_instructeur == instructeur :
        est_demandeur = True

    # --- Email expert ---
    email_expert = None
    if avis.id_expert:
        if avis.id_expert.est_interne and avis.id_expert.id_instructeur:
            email_expert = avis.id_expert.id_instructeur.email
        elif avis.id_expert.id_contact_externe:
            email_expert = avis.id_expert.id_contact_externe.email

    if not email_expert:
        logger.error(f"[AVIS {avis.id}] Pas d'email expert trouvé")
        return redirect_error(request, f"Erreur lors de la récupération de l'email de l'expert. Contactez le support.")
    
    est_expert = False
    if email_expert == instructeur.email :
        est_expert = True

    # --- Messages non lus envoyés par l'expert ---
    messages_non_lus = (Message.objects.filter(id_avis=avis, lu=False, email_emetteur=email_expert))
    ids_non_lus = list(messages_non_lus.values_list("id", flat=True))
    
    # Mise à jour des mesages non lus --> lus
    if est_demandeur and messages_non_lus :
        nb = messages_non_lus.update(lu=True)
        if nb > 0:
            logger.info(f"[DOSSIER {dossier.numero}] {nb} message(s) non lus ont été marqués comme lus par {request.user}.")


    raw_messages = Message.objects.filter(id_avis=avis).order_by("date_envoi")
    messages_fmt = []

    for msg in raw_messages:  
        nouv_mess = 'non'
        if ids_non_lus != []:
            if msg.id in ids_non_lus :
                nouv_mess = 'oui'

        emetteur = msg.email_emetteur.lower().strip()
        instru = Instructeur.objects.filter(email=emetteur).first()
        contact = ContactExterne.objects.filter(email=emetteur).first()

        # left = Message expert, right = Message émis par instructeur
        if est_expert :
            align = "left" if emetteur != email_expert.lower().strip() else "right"
        else :
            align = "right" if emetteur != email_expert.lower().strip() else "left"
        date_fmt = localtime(msg.date_envoi).strftime("%d/%m/%Y %H:%M") if msg.date_envoi else "Date inconnue"

        # Recherche de la pièce jointe liée au message
        pj_title = pj_emplacement = None
        if msg.piece_jointe:

            message_doc = MessageDocument.objects.filter(id_message=msg).select_related("id_document").first()
            if message_doc and message_doc.id_document:   
                pj_title, pj_emplacement = message_doc.id_document.titre, message_doc.id_document.emplacement

        messages_fmt.append({"id": msg.id, "body": msg.body, "date_envoi": date_fmt, "align": align, "pj_title": pj_title, "pj_emplacement": pj_emplacement, "nouv_mess": nouv_mess, "emetteur": instru if instru else contact})


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

    resume_pdf_titre = f"dossier-{dossier.numero}.pdf"

    dossiers_lies = list(
        Dossier.objects.filter(dossieravis__id_avis=avis)
        .select_related("id_demarche")
        .distinct()
    )
    if not dossiers_lies:
        dossiers_lies = [dossier]

    for dossier_lie in dossiers_lies:
        dossier_lie.chemin_complet = get_chemin_complet_dossier(dossier_lie)

    pieces_jointes_demandeur = get_pieces_jointes_demandeur(dossiers_lies)
    documents_zip_avis = get_documents_zip_avis(avis, dossiers_lies)

    # Nombre d'avis envoyés
    nb_avis_envoyes = DossierAvis.objects.filter(id_dossier=dossier, id_avis__statut="Envoyé").count()
    # Messages du pétitionnaire non lus pour le dossier
    nb_messages_non_lus = count_unread_messages_for_dossier(dossier, num_dossier)
    # Nombre d'avis avec au moins un message non lu de l'expert
    nb_avis_avec_nouveau_mess = count_avis_with_unread_messages_for_dossier(dossier, num_dossier)


    return render(request, 'instruction/instruction_dossier_avis.html', {
        "NAS_ROOT": os.getenv('NAS_ROOT'),
        "dossier": dossier,
        "avis": avis,
        "avis_documents": avis_documents,
        "liste_avis_documents": liste_avis_documents,
        "avis_signes": avis_signes,
        "pieces_jointes_demandeur": pieces_jointes_demandeur,
        "documents_zip_avis": documents_zip_avis,
        "messages_avis": messages_fmt,
        "is_formulaire_active": False,
        "is_messagerie_active": False,
        "is_consultation_active": True,
        "nb_avis_envoyes": nb_avis_envoyes,
        "est_instructeur_du_dossier": est_instructeur_du_dossier,
        "nb_messages_non_lus": nb_messages_non_lus,
        "resume_pdf_titre": resume_pdf_titre,
        "dossiers_lies": dossiers_lies,
        "dossiers_lies_affiches": get_dossiers_lies_affiches_avis(dossiers_lies),
        "nb_avis_avec_nouveau_mess": nb_avis_avec_nouveau_mess,
        "est_demandeur": est_demandeur,
        "est_expert": est_expert,
        "expert_is_CS": avis_est_conseil_scientifique(avis),
        "peut_modifier_destinataire": bool(
            request.user.is_superuser
            or est_expert
            or est_demandeur
            or utilisateur_est_publicateur_raa_cs(request.user)
        ),
        "peut_modifier_date_transmission_cs": bool(
            request.user.is_superuser or est_expert
        ),
        "peut_voir_note_avis": bool(
            request.user.is_superuser
            or ((est_demandeur or est_instructeur_du_dossier) and not est_expert)
        ),
    })


@require_POST
@login_required
def telecharger_documents_avis_zip(request, avis_id):
    avis = Avis.objects.filter(id=avis_id).first()
    if not avis:
        return redirect_error(request, "La demande d'avis est introuvable.")

    dossiers_lies = list(
        Dossier.objects.filter(dossieravis__id_avis=avis).distinct()
    )
    if not dossiers_lies and avis.id_dossier_id:
        dossiers_lies = [avis.id_dossier]
    documents_autorises = {
        document["cle"]: document
        for document in get_documents_zip_avis(avis, dossiers_lies)
    }
    cles_selectionnees = list(dict.fromkeys(request.POST.getlist("documents")))
    selection = [
        documents_autorises[cle]
        for cle in cles_selectionnees
        if cle in documents_autorises
    ]
    fichiers_externes = request.FILES.getlist("external_files")
    taille_max_fichier = 20 * 1024 * 1024
    taille_max_totale = 100 * 1024 * 1024

    if any(fichier.size > taille_max_fichier for fichier in fichiers_externes):
        return redirect_error(request, "Chaque fichier externe doit peser au maximum 20 Mo.")
    if sum(fichier.size for fichier in fichiers_externes) > taille_max_totale:
        return redirect_error(request, "Les fichiers externes ne peuvent pas dépasser 100 Mo au total.")
    if not selection and not fichiers_externes:
        return redirect_error(request, "Sélectionnez au moins un document à compresser.")

    fichier_zip = tempfile.SpooledTemporaryFile(max_size=20 * 1024 * 1024)
    noms_utilises = set()
    nombre_fichiers = 0

    def obtenir_nom_archive(nom_fichier):
        nom_base = Path(nom_fichier.replace("\\", "/")).name or "document"
        nom_archive = nom_base
        index = 2
        while nom_archive.lower() in noms_utilises:
            chemin_nom = Path(nom_base)
            nom_archive = f"{chemin_nom.stem}_{index}{chemin_nom.suffix}"
            index += 1
        noms_utilises.add(nom_archive.lower())
        return nom_archive

    with zipfile.ZipFile(fichier_zip, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for document in selection:
            chemin = os.path.join(
                os.getenv("NAS_ROOT", ""),
                document["emplacement"],
                document["titre"],
            )
            nom_archive = obtenir_nom_archive(document["titre"])

            try:
                with smbclient.open_file(chemin, mode="rb") as source:
                    with archive.open(nom_archive, mode="w") as destination:
                        while bloc := source.read(1024 * 1024):
                            destination.write(bloc)
                nombre_fichiers += 1
            except Exception as exc:
                noms_utilises.discard(nom_archive.lower())
                logger.warning(
                    f"[AVIS {avis.id}] Document ignoré lors de la création du ZIP "
                    f"({document['titre']}) : {exc}"
                )

        for fichier in fichiers_externes:
            nom_archive = obtenir_nom_archive(fichier.name)
            with archive.open(nom_archive, mode="w") as destination:
                for bloc in fichier.chunks():
                    destination.write(bloc)
            nombre_fichiers += 1

    if not nombre_fichiers:
        fichier_zip.close()
        return redirect_error(request, "Aucun des documents sélectionnés n'est disponible.")

    fichier_zip.seek(0)
    return FileResponse(
        fichier_zip,
        as_attachment=True,
        filename=f"documents-avis-{avis.id}.zip",
        content_type="application/zip",
    )



@require_POST
@login_required
def envoyer_message_avis(request):
    """
    Envoi d’un message dans la messagerie d’un avis.
    Gère texte, PJ, log, notifications expert.
    """
    
    # Récupération message et PJ de l'instructeur
    avis_id = request.POST.get("avis_id")
    dossier_numero = request.POST.get("dossier_numero")
    body = request.POST.get("body")
    fichier = request.FILES.get("piece_jointe")

    if not body:
        return redirect_error(request, "Message vide")
    
    # Vérification taille fichier (20 Mo max)
    if fichier and fichier.size > 20 * 1024 * 1024:
        return redirect_error(request, "Fichier trop volumineux. Taille maximale : 20 Mo.")
    

    # --- Récupération Avis ---
    avis = Avis.objects.filter(id=avis_id).first()
    if not avis:
        logger.error(f"[ENVOI MSG AVIS] Avis {avis_id} introuvable par {request.user}")
        return redirect_error(request, "L'avis demandé est introuvable. Contactez le support.")

    # --- Récupération Dossier ---
    dossier = Dossier.objects.filter(numero=dossier_numero).first()
    if not dossier:
        logger.error(f"[ENVOI MSG AVIS] Avis {avis_id} : Dossier {dossier_numero} introuvable par {request.user}")
        return redirect_error(request, "Le dossier est introuvable. Contactez le support.")
    

    # Récupérer l'instructeur
    instructeur = Instructeur.objects.filter(email=request.user.email).first()

    if not instructeur :
        logger.warning(f"[ENVOI MSG AVIS] User {request.user.email} sans profil instructeur a tenté d'envoyer un message sur l'avis {avis.id} (Dossier {dossier_numero})")
        return redirect_error(request, f"Echec de l'envoi du message : Vous n'avez pas de profil 'Instructeur'. Contatez l'administration")

    # --- Création message ---
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
        logger.error(f"[ENVOI MSG AVIS] Dossier {dossier_numero}, Avis {avis.id} : Erreur lors de l'envoi du message : {e}")
        return redirect_error(request, f"Erreur lors de l'envoi du message. Contactez le support.")

    
    
    ####################################
    # NOTIFICATION PAR MAIL A L'EXPERT
    ####################################
    email_expert = get_email_expert(avis, dossier_numero)
    if not email_expert:
        logger.error(f"[ENVOI MSG AVIS] Dossier {dossier_numero}, Avis {avis.id} : L'expert {avis.id_expert} n'a pas été notifié car son adresse mail n'a pas été trouvée.")
        return redirect_error(request, "Message envoyé, mais l’expert n’a pas pu être notifié par mail. Contactez le support pouren savoir plus.")

    # On notifie les agents dans le cadre d'une vraie instruction
    if NOTIFS_PROD :
        emails_norm = [get_email_expert(avis)]
    # Test de notification par mail à EMAIL_NOTIF_TEST   
    else :
        emails_norm = [EMAIL_NOTIF_TEST]


    sujet = f"Avis n° {avis.id} - {avis.id_demarche.type} : Vous avez un nouveau message"

    context = {
        "avis_numero": avis.id,
        "demarche_type": avis.id_demarche.type,
        "demandeur": str(avis.id_instructeur),
        "message": body,
        "url": f"{os.getenv('URL_APPLI')}reception_avis/{avis.id}/"
    }
    template_name = "nouveau_message_demandeur" 

    try :
        dedupe = compute_dedupe_key(emails_norm, sujet, template_name, context)

    except Exception as e:
        logger.error(f"[ENVOI MSG AVIS] Dossier {dossier.numero}, Avis {avis.id} : Erreur lors de la création de la clé unique (compute_dedupe_key) : {e}")
        return redirect_error(request, f"L'email de notification à {avis.id_expert} n'a pas été envoyé. Contactez le support pour en savoir plus.")

    
    # Vérifie si un mail identique a déjà été créé dans les 2 dernières heures (pour éviter le spam)
    existe_deja = EmailOutbox.objects.filter(
        dedupe_key=dedupe,
        date_creation__gte= timezone.now() - timedelta(hours=2)
    ).exists()

    if not existe_deja:
        outbox = create_EmailOutbox(emails_norm, sujet, template_name, dedupe, context, dossier, type_mail = "Notification")

        if outbox :
            ok, err = envoi_mail(outbox.id)
        else :
            logger.error(f"[AVIS {avis.id}] Nouveau message demandeur : Erreur lors de la création de l'EmailOutbox, {avis.id_expert} n'a pas été notifié par mail.")
            messages.error(request, f"L'email de notification à {avis.id_expert} n'a pas été envoyé. Contactez le support pour en savoir plus.")

        if ok:
            logger.info(f"[AVIS {avis.id}] Notification Email {outbox.id} (Nouveau message demandeur) envoyée à {', '.join(outbox.to)} ")
        else:
            logger.error(f"[AVIS {avis.id}] Échec envoi notification email {outbox.id} (Nouveau message demandeur) à {', '.join(outbox.to)} : {err}")
            messages.error(request, f"L'email de notification à {avis.id_expert} n'a pas été envoyé. Contactez le support pour en savoir plus.")

    return redirect(request.META.get("HTTP_REFERER", "/"))



@require_POST
@csrf_exempt
@login_required
def envoyer_message_avis_vision_expert(request):
    #Cette vue peut etre appelée par l'expert ou le demandeur

    avis_id = request.POST.get("avis_id")
    body = request.POST.get("body")
    fichier = request.FILES.get("piece_jointe")

    # --- Avis ---
    avis = Avis.objects.filter(id=avis_id).first()
    if not avis:
        logger.error(f"[MSG AVIS VISION EXPERT] Avis {avis_id} introuvable par {request.user}")
        return redirect_error(request, "L'avis demandé est introuvable. Contactez le support.")

    instructeur = Instructeur.objects.filter(email__iexact=request.user.email).first()
    dossier_ids = DossierAvis.objects.filter(id_avis=avis).values_list(
        "id_dossier_id",
        flat=True,
    )
    est_instructeur_dossier = bool(
        instructeur
        and DossierInstructeur.objects.filter(
            id_dossier_id__in=dossier_ids,
            id_instructeur=instructeur,
        ).exists()
    )
    est_demandeur = bool(
        instructeur and avis.id_instructeur_id == instructeur.id
    )
    est_expert = (
        (get_email_expert(avis, None) or "").strip().casefold()
        == (request.user.email or "").strip().casefold()
    )
    est_publicateur_cs = (
        avis_est_conseil_scientifique(avis)
        and utilisateur_est_publicateur_raa_cs(request.user)
    )
    if not (
        request.user.is_superuser
        or est_demandeur
        or est_expert
        or est_instructeur_dossier
        or est_publicateur_cs
    ):
        logger.warning(
            f"[MSG AVIS VISION EXPERT] Avis {avis.id} : envoi refusé à "
            f"{request.user} (utilisateur non autorisé)."
        )
        return redirect_error(
            request,
            "Vous n'êtes pas autorisé à envoyer un message sur cet avis.",
        )
        

    if not body:
        messages.error(request, "Message vide.")
        
    
    # Vérification taille fichier (20 Mo max)
    if fichier and fichier.size > 20 * 1024 * 1024:
        return redirect_error(request, "Fichier trop volumineux. Taille maximale : 20 Mo.")
        
 
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
        logger.error(f"[MSG AVIS VISION EXPERT] Avis {avis_id} : Erreur lors de l'envoi du message : {e}")
        return redirect_error(request, f"Erreur lors de l'envoi du message. Contactez le support.")
        
    


    email_expert = get_email_expert(avis, None)
    email_demandeur = avis.id_instructeur.email if avis.id_instructeur else None


    if email_expert == request.user.email :
        ####################################
        # NOTIFICATION PAR MAIL AU DEMANDEUR
        ####################################

        # On notifie les agents dans le cadre d'une vraie instruction
        if NOTIFS_PROD :
            emails_norm = [email_demandeur]
        # Test de notification par mail à EMAIL_NOTIF_TEST   
        else :
            emails_norm = [EMAIL_NOTIF_TEST]


        sujet = f"Avis n° {avis.id} - {avis.id_demarche.type} : Nouveaux messages de l'expert.e"
        
        context = {
            "avis_numero": avis.id,
            "demarche_type": avis.id_demarche.type,
            "expert": str(avis.id_expert),
            "message": body,
            "url": f"{os.getenv('URL_APPLI')}reception_avis/{avis.id}/"
        }
        template_name = "nouveau_message_expert" 
        dedupe = compute_dedupe_key(emails_norm, sujet, template_name, context)

        try :
            dedupe = compute_dedupe_key(emails_norm, sujet, template_name, context)

        except Exception as e:
            logger.error(f"[MSG AVIS VISION EXPERT] Avis {avis.id} : Erreur lors de la création de la clé unique (compute_dedupe_key) : {e}")
            return redirect_error(request, f"L'email de notification à {avis.id_instructeur} n'a pas été envoyé. Contactez le support pour en savoir plus.")
            

        # Vérifie si un mail identique a déjà été créé dans les 2 dernières heures (pour éviter le spam)
        existe_deja = EmailOutbox.objects.filter(
            dedupe_key=dedupe,
            date_creation__gte= timezone.now() - timedelta(hours=2)
        ).exists()

        if not existe_deja:
            outbox = create_EmailOutbox(emails_norm, sujet, template_name, dedupe, context, None, type_mail = "Notification")

            if outbox :
                ok, err = envoi_mail(outbox.id)
            else :
                logger.error(f"[MSG AVIS VISION EXPERT] Avis {avis.id} : Erreur lors de la création de l'EmailOutbox, {avis.id_instructeur} (demandeur) n'a pas été notifié par mail.")
                messages.error(request, f"L'email de notification à {avis.id_instructeur} n'a pas été envoyé. Contactez le support pour en savoir plus.")

            if ok:
                logger.info(f"[MSG AVIS VISION EXPERT] Avis {avis.id} : Notification Email {outbox.id} (Nouveau message de l'expert) envoyée à {', '.join(outbox.to)} ")
            else:
                logger.error(f"[MSG AVIS VISION EXPERT] Avis {avis.id} : Échec envoi notification email {outbox.id} (Nouveau message de l'expert) à {', '.join(outbox.to)} : {err}")
                messages.error(request, f"L'email de notification à {avis.id_instructeur} n'a pas été envoyé. Contactez le support pour en savoir plus.")


    else :
        ####################################
        # NOTIFICATION PAR MAIL A L'EXPERT
        ####################################

        # On notifie les agents dans le cadre d'une vraie instruction
        if NOTIFS_PROD :
            emails_norm = [get_email_expert(avis)]
        # Test de notification par mail à EMAIL_NOTIF_TEST   
        else :
            emails_norm = [EMAIL_NOTIF_TEST]


        sujet = f"Avis n° {avis.id} - {avis.id_demarche.type} : Vous avez un nouveau message"

        context = {
            "avis_numero": avis.id,
            "demarche_type": avis.id_demarche.type,
            "demandeur": str(avis.id_instructeur),
            "message": body,
            "url": f"{os.getenv('URL_APPLI')}reception_avis/{avis.id}/"
        }
        template_name = "nouveau_message_demandeur" 

        try :
            dedupe = compute_dedupe_key(emails_norm, sujet, template_name, context)

        except Exception as e:
            logger.error(f"[MSG AVIS VISION EXPERT] Avis {avis.id} : Erreur lors de la création de la clé unique (compute_dedupe_key) : {e}")
            return redirect_error(request, f"L'email de notification à {avis.id_expert} n'a pas été envoyé. Contactez le support pour en savoir plus.")
            

        # Vérifie si un mail identique a déjà été créé dans les 2 dernières heures (pour éviter le spam)
        existe_deja = EmailOutbox.objects.filter(
            dedupe_key=dedupe,
            date_creation__gte= timezone.now() - timedelta(hours=2)
        ).exists()

        if not existe_deja:
            outbox = create_EmailOutbox(emails_norm, sujet, template_name, dedupe, context, None, type_mail = "Notification")

            if outbox :
                ok, err = envoi_mail(outbox.id)
            else :
                logger.error(f"[MSG AVIS VISION EXPERT] Avis {avis.id} : Erreur lors de la création de l'EmailOutbox, {avis.id_expert} n'a pas été notifié par mail.")
                messages.error(request, f"L'email de notification à {avis.id_expert} n'a pas été envoyé. Contactez le support pour en savoir plus.")

            if ok:
                logger.info(f"[MSG AVIS VISION EXPERT] Avis {avis.id} : Notification Email {outbox.id} (Nouveau message du demandeur) envoyée à {', '.join(outbox.to)} ")
            else:
                logger.error(f"[MSG AVIS VISION EXPERT] Avis {avis.id} : Échec envoi notification email {outbox.id} (Nouveau message du demandeur) à {', '.join(outbox.to)} : {err}")
                messages.error(request, f"L'email de notification à {avis.id_expert} n'a pas été envoyé. Contactez le support pour en savoir plus.")

    return redirect(request.META.get("HTTP_REFERER", "/"))




# @require_POST
# def supprimer_document_avis(request, avis_id, champ):
#     """
#     Supprime une pièce jointe d’un avis
#     """

#     # --- Récupération Avis ---
#     avis = Avis.objects.filter(id=avis_id).first()
#     if not avis:
#         logger.error(f"[SUPPRESSION DOC AVIS] Avis {avis_id} introuvable par {request.user}")
#         messages.error(request, "L'avis est introuvable. Contactez le support.")
#         return redirect(request.META.get("HTTP_REFERER", "/"))
    

#     if champ not in ["id_projet_acte", "id_rapport_instance", "id_projet_avis"]:
#         messages.error(request, "Champ de document invalide")
#         return redirect(request.META.get("HTTP_REFERER", "/"))

#     setattr(avis, champ, None)
#     avis.save(update_fields=[champ])

#     return redirect(request.META.get("HTTP_REFERER", "/"))


@require_POST
@login_required
def mettre_a_jour_note_avis(request, avis_id):

    # --- Récupération avis ---
    avis = Avis.objects.filter(id=avis_id).first()
    if not avis:
        logger.error(f"[MAJ NOTE AVIS] Avis {avis_id} introuvable par {request.user}")
        return redirect_error(request, "L'avis est introuvable. Contactez le support.")
    
    # --- Validation instructeur ---
    instructeur = Instructeur.objects.filter(email=request.user.email).first()
    if not instructeur and not request.user.is_superuser:
        logger.warning(f"[MAJ NOTE AVIS] User {request.user} sans profil instructeur a tenté de modifier la note de l'avis {avis_id}")
        return redirect_error(request, "Vous devez disposer d'un profil instructeur pour modifier cette note. Contactez le support.")

    est_expert_interne = bool(
        instructeur
        and
        avis.id_expert
        and avis.id_expert.est_interne
        and avis.id_expert.id_instructeur_id == instructeur.id
    )
    est_demandeur = bool(instructeur and avis.id_instructeur_id == instructeur.id)
    est_instructeur_dossier = bool(
        instructeur
        and DossierInstructeur.objects.filter(
            id_instructeur=instructeur,
            id_dossier__dossieravis__id_avis=avis,
        ).exists()
    )
    if (
        not request.user.is_superuser
        and (est_expert_interne or not (est_demandeur or est_instructeur_dossier))
    ):
        logger.warning(
            f"[MAJ NOTE AVIS] User {request.user} non autorisé a tenté de modifier "
            f"la note de l'avis {avis_id}."
        )
        return redirect_error(request, "Vous n'êtes pas autorisé à modifier cette note.")
    
    try :
        note = request.POST.get("note", "").strip()
        avis.note = note
        avis.save(update_fields=["note"])

    except Exception as e:
        logger.error(f"[MAJ NOTE AVIS] Erreur lors de la mise à jour de la note de l'avis {avis_id} par {request.user} : {e}")
        messages.error(request, "Erreur lors de la mise à jour de la note. Contactez le support.")

    return redirect(request.META.get("HTTP_REFERER", "/"))



@login_required
@require_http_methods(["GET", "POST"])
def nouvelle_demande_avis_generique(request):
    
    try :

        # Récupérer toutes les natures et thématiques
        natures = AvisNature.objects.all().order_by("nature")
        thematiques = AvisThematique.objects.all().order_by("thematique")
        demarches = Demarche.objects.all().order_by("type")

        # Instructeur courant (user connecté)
        instructeur_connecte = Instructeur.objects.filter(email=request.user.email).first()
        if not instructeur_connecte:
            logger.warning(f"[NOUVELLE DEMANDE AVIS GÉNÉRIQUE] User {request.user} a tenté une demande d'avis sans profil instructeur.")
            return redirect_error(request, "Vous devez disposer d'un profil instructeur pour créer une demande d’avis. Contactez le support.")

        if request.method == "POST":
            reservation = reserver_numero(instructeur_connecte, cle=request.POST.get("reservation"))
            return redirect(reverse("nouvelle_demande_avis_generique") + "?reservation=" + str(reservation.pk))
        if not request.GET.get("reservation"):
            return render(request, "instruction/avis_reserver_numero.html", {"reservation_cle": uuid4()})
        reservation = lire_reservation(request.GET["reservation"], instructeur_connecte)
        if reservation.id_avis_id:
            return redirect("avis_expert", avis_id=reservation.id_avis_id)

        # Instructeurs candidats
        instructeurs_ = Instructeur.objects.filter(email__isnull=False).exclude(email__exact="").exclude(email__exact="autorisations@reunion-parcnational.fr").order_by("id_agent_autorisations__nom","id_agent_autorisations__prenom")

        # Contacts externes candidats
        contacts_ = ContactExterne.objects.filter(email__isnull=False, id_type__type="Instance").exclude(email__exact="").order_by("nom", "email")

        # Supprimer les doublons d'email (si jamais)
        instructeurs = {i.email: i for i in instructeurs_}.values()
        contacts_externes = {c.email: c for c in contacts_}.values()

    except PermissionDenied as erreur:
        return HttpResponseForbidden(str(erreur))
    except ValidationError as erreur:
        return HttpResponseBadRequest(" ".join(erreur.messages))
    except Exception as e:
        logger.error(f"[NOUVELLE DEMANDE GENERIQUE] Erreur inattendue (user {request.user}) : {e}")
        return HttpResponse("Impossible de préparer la demande d'avis. Réessayez ou contactez le support.", status=503)
    

    return render(request, "instruction/avis_nouvelle_demande_generique.html", {
        "reservation": reservation,
        "natures": natures,
        "thematiques": thematiques,
        "instructeurs": instructeurs,
        "contacts_externes": contacts_externes,
        "demarches": demarches,
        "avis_formulaire_configuration": _configuration_formulaire("generique", numero=reservation.numero),
    })



@require_POST
@login_required
@_creation_avec_numero_reserve
def avis_confirmer_nouvelle_demande_generique(request):
    

    # --- Récupération instructeur ---
    instructeur = getattr(request, "instructeur_reservation", None) or Instructeur.objects.filter(email=request.user.email).first()
    if not instructeur:
        logger.warning(f"[CONFIRMER AVIS GENERIQUE] Le user {request.user} a tenté de confirmer une nouvelle demande d'avis générique sans profil Instructeur.")
        return redirect_error(request, "Vous devez disposer d'un profil instructeur pour créer une demande d’avis. Contactez le support.")
    
    
    # Champs du formulaire
    nature_id = request.POST.get("nature")
    demarche_id = request.POST.get("demarche")
    thematique_id = request.POST.get("thematique")
    note = request.POST.get("note_demandeur", "").strip()
    formulation_avis = (request.POST.get("formulation_avis") or "").strip()
    expert_interne_id = request.POST.get("expert_interne") # instructeur ici 
    expert_externe_id = request.POST.get("expert_externe") # contact externe ici
    pj_projet_avis = request.FILES.get("pj_demande_avis")
    pj_projet_acte = request.FILES.get("pj_projet_acte")
    pj_rapport_cs = request.FILES.get("pj_rapport_cs")
    pjs_avis = request.FILES.getlist("pj_lie_avis")

    
    # --- Récupération nature ---
    try:
        nature = AvisNature.objects.get(id=nature_id)
    except Exception as e:
        logger.error(f"[CONFIRMER AVIS GENERIQUE] Erreur lors de la récupération de la nature d'avis {nature_id} (User {request.user}) : {e}")
        return redirect_error(request, "Erreur lors de la récupération de la nature d'avis. Contactez le support.")
    

    # --- Récupération thématique ---
    try:
        thematique = AvisThematique.objects.get(id=thematique_id)
    except Exception as e:
        logger.error(f"[CONFIRMER AVIS GENERIQUE] Erreur lors de la récupération de la thématique {thematique_id} (User {request.user}) : {e}")
        return redirect_error(request, "Erreur lors de la récupération de la thématique. Contactez le support.")


    # --- Récupération démarche ---
    try:
        demarche = Demarche.objects.get(id=demarche_id)
    except Exception as e:
        logger.error(f"[CONFIRMER AVIS GENERIQUE] Erreur lors de la récupération de la démarche {demarche_id} (User {request.user}) : {e}")
        return redirect_error(request, "Erreur lors de la récupération de la démarche. Contactez le support.")

    consultation = nature.nature == "Consultation en interne"
    instance = nature.nature == "Demande à une instance"
    if not consultation and not instance:
        return redirect_error(request, "La nature de l'avis n'est pas autorisée pour ce formulaire.")
    if bool(expert_interne_id) == bool(expert_externe_id):
        return redirect_error(request, "Choisissez un seul expert.")
    if consultation != bool(expert_interne_id):
        return redirect_error(request, "L'expert sélectionné ne correspond pas à la nature de l'avis.")

    # --- EXPERT ---
    try:
        expert, nom_prenom_expert = get_or_create_expert_from_form(request)

    except Exception as e:
        logger.error(f"[CONFIRMER AVIS GENERIQUE] Erreur lors de la récupération de l'expert : {e}")
        return redirect_error(request, "Erreur lors de la récupération de l'expert. Contactez le support.")

    try:
        destinataire = _destinataire_cs_depuis_formulaire(request, expert, obligatoire=False)
    except ValueError as e:
        return redirect_error(request, str(e))
        
    
    # --- Emplacement ---
    emplacement_avis = f"Avis/{nettoyer_nom_fichier(demarche.type)}/{date.today().year}/{nom_prenom_expert}_{date.today().strftime('%d_%m')}_{request.reservation_avis.numero}/"
    doc_projet_acte = doc_rapport_instance = doc_projet_avis = None
    jour_mois_annee = date.today().strftime("%d/%m/%Y")
    
    if pj_projet_avis or pj_projet_acte or pj_rapport_cs or pjs_avis :
        chemin_complet = f"{os.getenv('NAS_ROOT')}{emplacement_avis}Annexes/"
        if not creer_dossier_sur_nas(chemin_complet):
            return redirect_error(request, "Impossible de préparer le répertoire des pièces jointes sur le NAS.")


    # --- Écriture fichiers ---
    if pj_projet_avis :
        extension = Path(pj_projet_avis.name).suffix.lower()
        if extension not in {".doc", ".docx", ".odt"} :
            return redirect_error(request, f"❌ Le projet de demande d'avis doit etre au format .doc ou .docx ou .odt --> Type de fichier non autorisé : {extension}")
        
        doc_projet_avis = enregistrer_document(
            fichier=pj_projet_avis,
            nature_str="Annexe avis",
            description=f"Projet de demande pour la demande d'avis générique ({expert}) du {jour_mois_annee}",
            request=request,
            emplacement_avis = emplacement_avis,
        )
    
    if pj_projet_acte :
        extension = Path(pj_projet_acte.name).suffix.lower()
        if extension not in {".doc", ".docx", ".odt", ".pdf"} :
            logger.error(f"[CONFIRMER AVIS GENERIQUE] Le projet d'acte a tenté d'être déposé au format {extension} par {request.user}. Format autorisé : .doc, .docx, .odt, .pdf")
            return redirect_error(request, f"❌ Le projet d'acte doit etre au format .doc, .docx, .odt ou .pdf --> Type de fichier non autorisé : {extension}")
        
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
            return redirect_error(request, f"❌ Le rapport de l'instance doit etre au format .pdf --> Type de fichier non autorisé : {extension}")
        
        doc_rapport_instance = enregistrer_document(
            fichier=pj_rapport_cs,
            nature_str="Annexe avis",
            description=f"Rapport Instance pour la demande d'avis générique ({expert}) du {jour_mois_annee}",
            request=request,
            emplacement_avis = emplacement_avis,
        )



    for fichier, document in ((pj_projet_avis, doc_projet_avis), (pj_projet_acte, doc_projet_acte), (pj_rapport_cs, doc_rapport_instance)):
        if fichier and not document:
            return redirect_error(request, f"La pièce jointe {fichier.name} n'a pas pu être enregistrée. Réessayez.")

    # --- Création Avis ---
    try:

        avis = Avis.objects.create(
                id=request.reservation_avis.numero,
                id_avis_nature=nature,
                id_avis_thematique=thematique,
                date_demande_avis=timezone.now(),
                statut="Envoyé",
                note=note,
                formulation= formulation_avis,
                mode_contact="Application",
                id_demarche = demarche,
                id_expert=expert,
                destinataire=destinataire,
                id_instructeur=instructeur,
                id_projet_acte=doc_projet_acte,
                id_rapport_instance=doc_rapport_instance,
                id_projet_avis=doc_projet_avis,
                emplacement = emplacement_avis,
        )

        utiliser_reservation(request, avis)
        logger.info(f"[AVIS GENERIQUE {avis.id}] Avis créé par {request.user}")
    
    except Exception as e:
        logger.error(f"[CONFIRMER AVIS GENERIQUE] Erreur lors de la création de l'avis : {e}")
        return redirect_error(request, "Erreur lors de la création de l'avis. Contactez le support.")
    

    # Pièces jointes annexes
    if pjs_avis :
        for pj in pjs_avis :
            # extension = Path(pj.name).suffix.lower()
            try :
                doc_pj_avis = enregistrer_document(
                    fichier=pj,
                    nature_str="Annexe avis",
                    description=f"Pièce jointe du demandeur pour la demande d'avis générique ({expert}) du {jour_mois_annee}",
                    request=request,
                    emplacement_avis = emplacement_avis,
                )
                
                if not doc_pj_avis:
                    raise ValueError(f"La pièce jointe {pj.name} n'a pas pu être enregistrée.")
                AvisDocument.objects.get_or_create(id_avis=avis, id_document=doc_pj_avis)
                
            except Exception as e:
                logger.error(f"[AVIS GENERIQUE {avis.id}] Erreur lors de l'enregistrement d'une pièce jointe : {e}")
                return redirect_error(request, "Erreur lors de l’enregistrement d’une pièce jointe. Réessayez.")


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
                MessageDocument.objects.create(id_message=msg, id_document=doc_projet_avis)

            logger.info(f"[AVIS GENERIQUE {avis.id}] : Message par défaut envoyé à {avis.id_expert}")

        except Exception as e:
            logger.error(f"[AVIS GENERIQUE {avis.id}] Erreur lors de la création du message initial : {e}")
            return redirect_error(request, "Erreur lors de la création du message initial. Réessayez.")

    
    request.creation_avis_validee = True
    _notifier_demande_avis(request, avis)

    return redirect('avis_expert', avis_id=avis.id)



@login_required
def remplacer_document_avis(request):
    """
    Remplacement sécurisé d'un document (Projet d'avis, Projet d'acte, Rapport du conseil) lié à un avis.
    - Si le document est partagé par plusieurs avis → création d’un nouveau Document.
    - Sinon → remplacement du fichier + mise à jour de l’objet Document.
    """

    avis_id = request.POST.get("avis_id")
    document_id = request.POST.get("document_id")
    fichier = request.FILES.get("fichier")

    if not avis_id or not document_id or not fichier:
        logger.warning(f"[REMPLACER DOC AVIS] Tentative de remplacement de document lié à un avis par {request.user}. Information manquante.")
        return redirect_error(request, "❌ Données manquantes.")

    # --- Récupération Avis ---
    avis = Avis.objects.filter(id=avis_id).first()
    if not avis:
        logger.error(f"[REMPLACER DOC] Avis {avis_id} introuvable.")
        return redirect_error(request, "Avis introuvable. Contactez le support.")

    # --- Récupération Document ---
    document = Document.objects.filter(id=document_id).first()
    if not document:
        logger.error(f"[REMPLACER DOC] Avis {avis_id} : Document {document_id} introuvable.")
        return redirect_error(request, "Document introuvable. Contactez le support.")

    # --- Vérification extension ---
    ext = Path(fichier.name).suffix.lower()
    if ext not in [".pdf", ".doc", ".docx", ".odt"]:
        return redirect_error(request, f"❌ Format non autorisé ({ext}). Formats acceptés : .pdf, .doc, .docx, .odt")

    # --- Récupération Format ---
    format_obj = DocumentFormat.objects.filter(format__iexact=ext.lstrip(".")).first()
    if not format_obj:
        return redirect_error(request, f"❌ Format '{ext}' introuvable en base. Contactez le support.")


    root = os.environ.get("NAS_ROOT", "")
    creer_dossier_sur_nas(os.path.join(root, document.emplacement))

    # --- DOCUMENT PARTAGÉ ?
    utilisations = Avis.objects.filter(
        models.Q(id_projet_avis=document) |
        models.Q(id_projet_acte=document) |
        models.Q(id_rapport_instance=document)
    ).distinct()

    est_partage = utilisations.count() > 1


    try:
        # =====================================================
        #  CAS 1 : DOCUMENT PARTAGÉ → création d’un nouveau doc
        # =====================================================

        if est_partage:
            nom_base, ext = os.path.splitext(fichier.name)
            titre_final = nom_base
            i = 1
            repertoire_absolu = os.path.join(root, document.emplacement)

            # Boucle pour éviter doublons (fichier + enregistrement)
            while True:
                chemin_candidat = os.path.join(repertoire_absolu, f"{titre_final}{ext}")
                existe_fichier = smbclient.path.exists(chemin_candidat)
                existe_enregistrement = Document.objects.filter(
                    emplacement=document.emplacement,
                    titre=f"{titre_final}{ext}"
                ).exists()

                if not existe_fichier and not existe_enregistrement:
                    break  # nom libre

                i += 1
                titre_final = f"{nom_base}_{i}"

            # Écriture du fichier sur le NAS
            if not ecrire_file_sur_nas(fichier, chemin_candidat): 
                # logger.error(f"[NAS] ❌ Échec de l’écriture du fichier {fichier.name} sur {chemin_candidat}")
                raise Exception(f"[NAS] ❌ Échec de l’écriture du fichier {fichier.name} sur {chemin_candidat}")

            logger.info(f"[AVIS {avis.id}] Nouveau fichier créé par {request.user} : {chemin_candidat}")

            # Création du nouvel enregistrement Document
            nouveau_doc = Document.objects.create(
                id_format=format_obj,
                id_nature=document.id_nature,
                id_statut=document.id_statut,
                url_ds=document.url_ds,
                emplacement=document.emplacement,
                description=f"Nouveau document pour l'avis {avis.id}",
                titre=f"{titre_final}{ext}",
                numero=document.numero,
                numero_reference=document.numero_reference,
                id_document_reference_id=document.id_document_reference_id,
            )

            # On détermine quel champ de l’avis doit être mis à jour
            if avis.id_projet_avis_id == document.id:
                avis.id_projet_avis = nouveau_doc
            elif avis.id_projet_acte_id == document.id:
                avis.id_projet_acte = nouveau_doc
            elif avis.id_rapport_instance_id == document.id:
                avis.id_rapport_instance = nouveau_doc

            avis.save()


        # =====================================================
        #  CAS 2 : DOCUMENT NON PARTAGÉ → on écrase l'ancien doc
        # ======================================================
        else:
            ancien_chemin = os.path.join(root, document.emplacement, document.titre)
            nouveau_chemin = os.path.join(root, document.emplacement, fichier.name)

            # Si doublon exact de nom → incrémentation aussi
            nom_base, ext = os.path.splitext(fichier.name)
            titre_final = nom_base
            i = 1

            while Document.objects.filter(emplacement=document.emplacement, titre=f"{titre_final}{ext}").exclude(id=document.id).exists():
                titre_final = f"{nom_base}_{i}"
                i += 1

            nouveau_chemin = os.path.join(root, document.emplacement, f"{titre_final}{ext}")

            # Étape 1 : Écriture du nouveau fichier
            if not ecrire_file_sur_nas(fichier, nouveau_chemin): 
                # logger.error(f"[NAS] ❌ Échec de l’écriture du fichier {fichier.name} sur {nouveau_chemin}")
                raise Exception(f"[NAS] ❌ Échec de l’écriture du fichier {fichier.name} sur {nouveau_chemin}")
            
            # Étape 2 : Supprimer l’ancien fichier
            if not supprimer_file_sur_nas(ancien_chemin):
                logger.error(f"[AVIS {avis.id}] ❌ Erreur lors de la suppression de l'ancien fichier {ancien_chemin} par {request.user}")

            # Mise à jour document
            document.titre = f"{titre_final}{ext}"
            document.id_format = format_obj
            document.description = f"Remplacement du {document.id_nature.nature} pour l'avis {avis.id}"
            document.save()

            logger.info(f"[AVIS {avis.id}] Document remplacé par {request.user} : {nouveau_chemin}")

    except Exception as e:
        logger.error(f"[AVIS {avis.id}] Erreur lors du remplacement du document : {e}")
        messages.error(request, f"❌ Erreur lors du remplacement du document. Contatez le support.")

    return redirect(request.META.get("HTTP_REFERER", "/"))

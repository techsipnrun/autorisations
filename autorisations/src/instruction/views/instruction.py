import ast
import re
from collections import Counter
from datetime import date, timedelta
import json
import logging
import os
from django.db.models import Q, Count
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib.auth.decorators import login_required
from django.urls import reverse
import smbclient
from autorisations.models.models_instruction import Demarche, DemarcheColonneVueEnsemble, DemarcheDateActiviteConfiguration, Dossier, DossierAction, DossierManifSportive, DossierManifestationLiaison, EtapeDossier, EtatDossier, Message, SynchronisationEtat
from autorisations.models.models_utilisateurs import AgentAutorisations, ContactExterne, DossierBeneficiaire, DossierEnvoiActe, DossierInstructeur, DossierInterlocuteur, DossierIntermediaireSignature, DossierManifSportiveInstructeur, DossierPublicationRAA, DossierRelecteur, DossierRelecteurQualite, DossierSignataire, DossierValideur, EmailOutbox, Groupeinstructeur, GroupeinstructeurInstructeur, Instructeur, TypeContactExterne
from autorisations.settings import EMAIL_NOTIF_TEST, NOTIFS_PROD
from DS.graphql_client import GraphQLClient
from autorisations.models.models_documents import Document, DocumentFormat, DocumentNature, DocumentStatut, DossierDocument, DossierRelecteurDocument
from autorisations.models.models_avis import AvisDocument, DossierAvis
from autorisations.utils.nas_fonctions import _normalize_unc_path, creer_dossier_sur_nas, ecrire_file_sur_nas
from instruction.utils.avis_utils import build_avis_for_dossier
from instruction.utils.avis_dm_utils import (
    get_avis_dm_le_plus_recent,
    get_dates_demande_avis_dm,
)
from instruction.utils.dm import documents_deposes_sur_DM
from instruction.utils.document_utils import build_documents_for_dossier
from instruction.utils.dossier_utils import actualisation_dossier_est_bloquee, ajouter_message_bloc, build_champs_prepares, build_timeline_for_dossier, clear_etat_actualisation_dossier, count_unread_messages_for_dossier, get_actions_possibles, get_beneficiaire_for_dossier, get_demandeur_for_dossier, get_etat_actualisation_dossier, get_motif_decision, redirect_error, redirect_warning, safe_enregistrer_action, set_etat_actualisation_dossier
from instruction.utils.files_utils import load_geojson
from instruction.utils.ensembles_dossiers import contexte_dossiers_lies
from instruction.utils.utilisateurs_utils import build_roles_for_dossier, get_choix_destinataires_notification
from instruction.templatetags.group_tags import est_autorise_a_changer_etape, peut_annuler_en_instruction_comme_receptionniste
from instruction.utils.colonnes_vue_ensemble import (
    TABLEAU_ARCHIVES,
    TABLEAU_EN_COURS,
    TABLEAU_MES_DOSSIERS,
    colonnes_visibles,
    configurations_colonnes_vue_ensemble,
    libelles_colonnes,
)
from notifications.service import compute_dedupe_key, create_EmailOutbox, envoi_mail
from synchronisation.normalisation.norma_declaration_manifestations import dossiers_declaration_manifestations_normalize
from synchronisation.synchro.sync_declaration_manifestations import sync_declaration_manifestations
from synchronisation.normalisation.norma_contacts_externes import contact_externe_normalize
from synchronisation.normalisation.norma_demandes import demande_normalize
from synchronisation.normalisation.norma_dossier_champs import dossiers_champs_normalize
from synchronisation.normalisation.norma_dossier_document import dossier_document_normalize
from synchronisation.normalisation.norma_dossier_interlocuteur import dossier_interlocuteur_normalize
from synchronisation.normalisation.norma_messages import message_normalize
from synchronisation.synchro.sync_dossiers import sync_dossiers
from synchronisation.utils.fichiers import construire_emplacement_dossier
from synchronisation.normalisation.norma_dossier import dossier_normalize
from instruction.utils_instru import dossiers_action_a_faire, enregistrer_action, format_etat_dossier
from autorisations.models.models_instruction import DossierNote
from django.utils import timezone
from datetime import datetime
from django.db.models import Min
from django.views.decorators.http import require_POST
from django.http import Http404
from instruction.views.errors import dossier_introuvable
from django.contrib import messages
from django.contrib.auth.models import Group, User
from django.contrib.auth import get_user_model
from threading import Thread
from django.http import JsonResponse


logger = logging.getLogger('ORM_DJANGO')
loggerSynchro = logging.getLogger('SYNCHRONISATION')
loggerDM = logging.getLogger("API_DM")


def get_dossiers_instructeur(instructeur):
    """Retourne un queryset de tous les dossiers où l’instructeur intervient (SAUF SI LE DOSSIER EST EN RECEPTION), tous rôles confondus."""

    if not instructeur:
        return Dossier.objects.none()
    
    User = get_user_model()
    user = User.objects.filter(email__iexact=instructeur.email).first()


    # Base : rôles instructeur
    filtre = (
        Q(dossierinstructeur__id_instructeur=instructeur) |
        Q(dossierrelecteurqualite__id_instructeur=instructeur) |
        Q(dossiervalideur__id_instructeur=instructeur) |
        Q(dossierrelecteur__id_instructeur=instructeur) |
        Q(dossiersignataire__id_instructeur=instructeur) |
        Q(dossierintermediairesignature__id_instructeur=instructeur) |
        Q(dossierpublicationraa__id_instructeur=instructeur) |
        Q(dossierenvoiacte__id_instructeur=instructeur)
    )

    # ➕ Ajout des 2 conditions supplémentaires (même échantillon)
    if user :
        if user.groups.filter(name="Réception SPPN").exists():
            filtre |= Q(id_demarche__type__icontains="Mission scientifique")

        if user.groups.filter(name="Réception SAADD").exists():
            filtre |= ~Q(id_demarche__type__icontains="Mission scientifique")

    dossiers_hors_reception = (
        Dossier.objects
        .filter(filtre)
        .exclude(id_etape_dossier__etape="À affecter")
    )
    dossiers_dn_manif_non_lies_affectes = Dossier.objects.filter(
        id_etape_dossier__etape="À affecter",
        id_demarche__type__iexact="Manifestations sportives",
        dossiermanifestationliaison__isnull=True,
        dossierinstructeur__id_instructeur=instructeur,
    )
    return (dossiers_hors_reception | dossiers_dn_manif_non_lies_affectes).distinct()



def get_dossier_counts(demarche, etape_a_affecter, etapes_instruction, etapes_termines, current_year, instructeur=None):
    """
    Retourne le résumé des compteurs pour une démarche.
    """

    # Requêtes de base
    dossiers = Dossier.objects.filter(id_demarche=demarche)

    # -------------------------------
    # Nombre de dossiers en Réception
    # -------------------------------
    dossiers_DM_manif_sportive_non_lie_en_reception = 0
    dossiers_DM_affectes_instructeur = 0
    if demarche.type.lower() == 'manifestations sportives':
        dossiers_deja_lies_ids = DossierManifestationLiaison.objects.values_list("id_dossier_manif_id", flat=True)
        dossiers_dm_non_lies = DossierManifSportive.objects.filter(
            archive=False,
            id_etape__etape="En réception",
        ).exclude(id__in=dossiers_deja_lies_ids)
        dossiers_DM_manif_sportive_non_lie_en_reception = dossiers_dm_non_lies.count()
        if instructeur:
            dossiers_DM_affectes_instructeur = dossiers_dm_non_lies.filter(
                dossiermanifsportiveinstructeur__id_instructeur=instructeur
            ).distinct().count()

    nb_reception = dossiers.filter(id_etape_dossier=etape_a_affecter).count() + dossiers_DM_manif_sportive_non_lie_en_reception


    # --------------------------------
    # Nombre de dossiers en Intruction
    # --------------------------------
    nb_suivis = dossiers.filter(id_etape_dossier__in=etapes_instruction).count()


    # ---------------------------
    # Nombre de dossiers Archivés
    # ---------------------------
    dossiers_DM_manif_sportive_non_lie_archive = 0
    if demarche.type.lower() == 'manifestations sportives':
        # Pour un dossier DM orphelin, la date qui matérialise son traitement
        # est la date de réponse de l'avis. Ne pas compter ici l'intégralité
        # des archives historiques : la colonne porte bien sur l'année en cours.
        dossiers_DM_manif_sportive_non_lie_archive = (
            DossierManifSportive.objects
            .filter(
                archive=True,
                avis__date_reponse__year=current_year,
            )
            .exclude(id__in=dossiers_deja_lies_ids)
            .distinct()
            .count()
        )

    nb_traites = dossiers.filter(id_etape_dossier__in=etapes_termines, date_fin_instruction__year=current_year).count() + dossiers_DM_manif_sportive_non_lie_archive


    # Dossiers où l'instructeur intervient
    dossiers_instructeur = get_dossiers_instructeur(instructeur).filter(id_demarche=demarche)

    nb_suivis_user = (
        dossiers_action_a_faire(dossiers_instructeur, instructeur).count()
        + dossiers_DM_affectes_instructeur
    )

    return {
        "demarche": demarche,
        "nb_reception": nb_reception,
        "nb_suivis": nb_suivis,
        "nb_traites": nb_traites,
        "nb_suivis_user": nb_suivis_user,
    }



def get_role_sur_dossier(dossier, instructeur, action_a_faire=False):
    """Retourne le rôle exact de l'instructeur sur un dossier."""

    etape = dossier.id_etape_dossier.etape if dossier.id_etape_dossier else ""

    # Cas où une action est à faire
    if action_a_faire:

        # Rôles directs liés à l'étape
        mapping_action = {
            "À valider avant signature": "Valideur.se",
            "À valider avant demande d'avis": "Valideur.se",
            "À publier au RAA": "Publieur.se au RAA",
            "Acte à envoyer": "Envoyeur.se de l'acte",
            "En attente de signature": "Intermédiaire signature",
            "À affecter": "Relecteur.rice qualité",
            "En relecture qualité": "Relecteur.rice qualité",
        }
        if etape in mapping_action:
            return mapping_action[etape]

        # Cas particulier : relecteur
        if DossierRelecteur.objects.filter(id_dossier=dossier, id_instructeur=instructeur, relu=False).exists():
            return "Relecteur.rice"

        return "Instructeur.rice"

    # Cas général : aucun action à faire
    mapping_roles = [
        (DossierInstructeur, "Instructeur.rice"),
        (DossierValideur, "Valideur.se"),
        (DossierSignataire, "Signataire"),
        (DossierRelecteurQualite, "Relecteur.rice qualité"),
        (DossierEnvoiActe, "Envoyeur.se de l'acte"),
        (DossierIntermediaireSignature, "Intermédiaire signature"),
        (DossierPublicationRAA, "Publieur.se au RAA"),
        (DossierRelecteur, "Relecteur.rice"),
    ]

    for model, role in mapping_roles:
        if model.objects.filter(id_dossier=dossier, id_instructeur=instructeur).exists():
            return role

    return "Inconnu"


def _roles_par_dossier(dossiers, instructeur, actions_ids):
    """Calcule les roles affiches sans requete SQL dossier par dossier."""
    dossier_ids = [dossier.id for dossier in dossiers]
    roles = {}
    mapping_action = {
        "À valider avant signature": "Valideur.se",
        "À valider avant demande d'avis": "Valideur.se",
        "À publier au RAA": "Publieur.se au RAA",
        "Acte à envoyer": "Envoyeur.se de l'acte",
        "En attente de signature": "Intermédiaire signature",
        "À affecter": "Relecteur.rice qualité",
        "En relecture qualité": "Relecteur.rice qualité",
    }
    relectures_non_faites = set(
        DossierRelecteur.objects.filter(
            id_dossier_id__in=dossier_ids,
            id_instructeur=instructeur,
            relu=False,
        ).values_list("id_dossier_id", flat=True)
    )
    for dossier in dossiers:
        if dossier.id not in actions_ids:
            continue
        etape = dossier.id_etape_dossier.etape if dossier.id_etape_dossier else ""
        roles[dossier.id] = mapping_action.get(
            etape,
            "Relecteur.rice" if dossier.id in relectures_non_faites else "Instructeur.rice",
        )

    mapping_roles = [
        (DossierInstructeur, "Instructeur.rice"),
        (DossierValideur, "Valideur.se"),
        (DossierSignataire, "Signataire"),
        (DossierRelecteurQualite, "Relecteur.rice qualité"),
        (DossierEnvoiActe, "Envoyeur.se de l'acte"),
        (DossierIntermediaireSignature, "Intermédiaire signature"),
        (DossierPublicationRAA, "Publieur.se au RAA"),
        (DossierRelecteur, "Relecteur.rice"),
    ]
    dossiers_sans_role = set(dossier_ids) - set(actions_ids)
    for model, role in mapping_roles:
        ids = model.objects.filter(
            id_dossier_id__in=dossiers_sans_role,
            id_instructeur=instructeur,
        ).values_list("id_dossier_id", flat=True)
        for dossier_id in ids:
            roles.setdefault(dossier_id, role)
    return roles


def get_dates_debut_manifestation(dossiers):
    """Retourne la date de début DM indexée par identifiant de dossier DN."""
    dossier_ids = [dossier.id for dossier in dossiers]
    return {
        liaison.id_dossier_id: liaison.id_dossier_manif.date_debut_evenement
        for liaison in DossierManifestationLiaison.objects.filter(
            id_dossier_id__in=dossier_ids
        ).select_related("id_dossier_manif")
    }


def get_date_debut_manifestation_vue(dossier, dates_debut_manifestation, dossiers_complets_ids):
    """Date affichée dans la colonne manifestation de la vue d'ensemble.

    Les dossiers complets gardent la date portée par Déclaration Manifestations.
    Pour un DN orphelin, cette colonne utilise la date d'activité configurée pour
    sa démarche, afin d'éviter une colonne vide alors que l'information existe.
    """
    date_dm = dates_debut_manifestation.get(dossier.id)
    if date_dm or dossier.id in dossiers_complets_ids:
        return date_dm
    return dossier.date_debut_activite


def get_dates_reception_manifestation(dossiers):
    """Retourne la date de réception à afficher pour chaque dossier DN.

    Pour un dossier complet, il s'agit de la plus récente date entre son dépôt
    DN et la dernière demande d'avis sur DM. Pour un DN orphelin, la date de
    dépôt DN reste la date de réception.
    """
    dossiers_par_id = {dossier.id: dossier for dossier in dossiers}
    if not dossiers_par_id:
        return {}

    liaisons = list(
        DossierManifestationLiaison.objects.filter(
            id_dossier_id__in=dossiers_par_id
        ).select_related("id_dossier_manif")
    )
    dates_demande_avis_dm = get_dates_demande_avis_dm(
        liaison.id_dossier_manif_id for liaison in liaisons
    )

    dates_reception = {
        dossier_id: dossier.date_depot
        for dossier_id, dossier in dossiers_par_id.items()
    }
    for liaison in liaisons:
        date_depot_dn = dossiers_par_id[liaison.id_dossier_id].date_depot
        date_demande_avis_dm = dates_demande_avis_dm.get(
            liaison.id_dossier_manif_id
        )
        dates_reception[liaison.id_dossier_id] = max(
            (date for date in (date_depot_dn, date_demande_avis_dm) if date),
            default=None,
        )

    return dates_reception


def get_indicateurs_date_manifestation(date_debut):
    """Indique si la manifestation est passée ou commence dans les 30 jours."""
    if not date_debut:
        return False, False

    today = timezone.localdate()
    date_evenement = date_debut.date()
    return (
        date_evenement < today,
        today <= date_evenement <= today + timedelta(days=30),
    )


CONFIGURATION_DATE_ACTIVITE_DEFAUT = {
    "delai_alerte_jours": 30,
    "couleur_alerte": "#d97706",
    "couleur_passee": "#b91c1c",
}


def configuration_date_activite(configuration=None):
    """Retourne une configuration sûre, y compris avant toute personnalisation."""
    resultat = CONFIGURATION_DATE_ACTIVITE_DEFAUT.copy()
    if isinstance(configuration, dict):
        resultat.update({cle: configuration[cle] for cle in resultat if cle in configuration})
        return resultat
    if configuration:
        resultat["delai_alerte_jours"] = configuration.delai_alerte_jours
        for cle in ("couleur_alerte", "couleur_passee"):
            couleur = getattr(configuration, cle, "")
            if re.fullmatch(r"#[0-9a-fA-F]{6}", couleur or ""):
                resultat[cle] = couleur
    return resultat


def get_indicateurs_date_activite(date_debut, configuration=None):
    """Indique si une activité est passée ou arrive dans le délai configuré."""
    if not date_debut:
        return False, False
    regles = configuration_date_activite(configuration)
    date_activite = date_debut.date()
    today = timezone.localdate()
    return (
        date_activite < today,
        today <= date_activite <= today + timedelta(days=regles["delai_alerte_jours"]),
    )


def _contacts_demandeurs_par_dossier(dossier_ids):
    """Charge les demandeurs de plusieurs dossiers en deux requêtes maximum."""
    interlocuteurs = list(
        DossierInterlocuteur.objects
        .filter(id_dossier_id__in=dossier_ids)
        .select_related("id_demandeur_intermediaire")
    )
    interlocuteurs_par_dossier = {
        interlocuteur.id_dossier_id: interlocuteur
        for interlocuteur in interlocuteurs
    }
    beneficiaires = {
        beneficiaire.id_dossier_interlocuteur_id: beneficiaire.id_beneficiaire
        for beneficiaire in (
            DossierBeneficiaire.objects
            .filter(id_dossier_interlocuteur_id__in=[item.id for item in interlocuteurs])
            .select_related("id_beneficiaire")
        )
    }

    return {
        dossier_id: (
            interlocuteur.id_demandeur_intermediaire
            or beneficiaires.get(interlocuteur.id)
        )
        for dossier_id, interlocuteur in interlocuteurs_par_dossier.items()
    }


def _messages_non_lus_par_dossier(dossier_ids):
    """Compte en une requête les messages externes non lus des dossiers."""
    return {
        ligne["id_dossier_id"]: ligne["total"]
        for ligne in (
            Message.objects
            .filter(id_dossier_id__in=dossier_ids, lu=False)
            .exclude(email_emetteur__in=[
                "contact@demarches-simplifiees.fr",
                "contact@demarche.numerique.gouv.fr",
            ])
            .exclude(email_emetteur__endswith="reunion-parcnational.fr")
            .values("id_dossier_id")
            .annotate(total=Count("id"))
        )
    }


def _actions_a_faire_ids(dossiers, instructeur):
    """Version groupée des règles de dossiers_action_a_faire pour une démarche."""
    if not instructeur:
        return set()

    infos = list(
        dossiers.values_list(
            "id",
            "id_etape_dossier__etape",
            "id_demarche__type",
        )
    )
    dossier_ids = [dossier_id for dossier_id, _, _ in infos]
    if not dossier_ids:
        return set()

    def ids_role(modele):
        return set(
            modele.objects.filter(
                id_dossier_id__in=dossier_ids,
                id_instructeur=instructeur,
            ).values_list("id_dossier_id", flat=True)
        )

    instructeur_ids = ids_role(DossierInstructeur)
    valideur_ids = ids_role(DossierValideur)
    relecteur_qualite_ids = ids_role(DossierRelecteurQualite)
    publieur_ids = ids_role(DossierPublicationRAA)
    envoyeur_ids = ids_role(DossierEnvoiActe)
    intermediaire_ids = ids_role(DossierIntermediaireSignature)
    relectures_non_faites_ids = set(
        DossierRelecteur.objects.filter(
            id_dossier_id__in=dossier_ids,
            id_instructeur=instructeur,
            relu=False,
        ).values_list("id_dossier_id", flat=True)
    )
    non_lus_ids = set(_messages_non_lus_par_dossier(dossier_ids))
    dossiers_manif_lies_ids = set(
        DossierManifestationLiaison.objects.filter(
            id_dossier_id__in=dossier_ids
        ).values_list("id_dossier_id", flat=True)
    )

    resultat = set()
    etapes_terminales_relecture = {
        "Non soumis à autorisation", "Refusé", "Accepté"
    }
    for dossier_id, etape, type_demarche in infos:
        if (
            dossier_id in relectures_non_faites_ids
            and etape not in etapes_terminales_relecture
        ):
            resultat.add(dossier_id)

        if etape in {"À valider avant signature", "À valider avant demande d'avis"}:
            if dossier_id in valideur_ids:
                resultat.add(dossier_id)
        elif etape in etapes_terminales_relecture:
            if dossier_id in instructeur_ids and dossier_id in non_lus_ids:
                resultat.add(dossier_id)
        elif etape in {
            "En instruction", "En pré-instruction", "En attente réponse d'avis",
            "En attente de compléments", "Avis à envoyer",
        }:
            if dossier_id in instructeur_ids:
                resultat.add(dossier_id)
        elif (
            etape == "À affecter"
            and (type_demarche or "").lower() == "manifestations sportives"
            and dossier_id not in dossiers_manif_lies_ids
        ):
            if dossier_id in instructeur_ids:
                resultat.add(dossier_id)
        elif etape == "En relecture qualité" and dossier_id in relecteur_qualite_ids:
            resultat.add(dossier_id)
        elif etape == "À publier au RAA" and dossier_id in publieur_ids:
            resultat.add(dossier_id)
        elif etape == "Acte à envoyer" and dossier_id in envoyeur_ids:
            resultat.add(dossier_id)
        elif etape == "En attente de signature" and dossier_id in intermediaire_ids:
            resultat.add(dossier_id)

    return resultat



@login_required
def accueil(request):
    # Instructeur
    instructeur = Instructeur.objects.filter(email=request.user.email).first()
    if not instructeur:
        messages.warning(request, f"Attention, vous n'avez pas de profil 'Instructeur.rice' : Contactez le support si besoin.")

    # POUR LE MOMENT ON EXCLU MANIFESTATIONS SPORTIVES
    demarches = list(Demarche.objects.all().order_by("titre"))
    # demarches = demarches.exclude(type__icontains="manifestations sportives")

    current_year = date.today().year

    etapes_terminees = ["Non soumis à autorisation", "Refusé", "Accepté", "Annulé"]
    compteurs_dossiers = {
        ligne["id_demarche_id"]: ligne
        for ligne in (
            Dossier.objects.values("id_demarche_id").annotate(
                nb_reception=Count(
                    "id", filter=Q(id_etape_dossier__etape="À affecter")
                ),
                nb_suivis=Count(
                    "id",
                    filter=~Q(id_etape_dossier__etape__in=[*etapes_terminees, "À affecter"]),
                ),
                nb_traites=Count(
                    "id",
                    filter=Q(
                        id_etape_dossier__etape__in=etapes_terminees,
                        date_fin_instruction__year=current_year,
                    ),
                ),
            )
        )
    }

    dossiers_dm_lies_ids = DossierManifestationLiaison.objects.values_list(
        "id_dossier_manif_id", flat=True
    )
    nb_dm_reception = (
        DossierManifSportive.objects
        .filter(archive=False, id_etape__etape="En réception")
        .exclude(id__in=dossiers_dm_lies_ids)
        .count()
    )
    nb_dm_traites = (
        DossierManifSportive.objects
        .filter(archive=True, avis__date_reponse__year=current_year)
        .exclude(id__in=dossiers_dm_lies_ids)
        .distinct()
        .count()
    )
    nb_dm_actions = 0
    if instructeur:
        nb_dm_actions = (
            DossierManifSportive.objects
            .filter(
                archive=False,
                id_etape__etape="En réception",
                dossiermanifsportiveinstructeur__id_instructeur=instructeur,
            )
            .exclude(id__in=dossiers_dm_lies_ids)
            .distinct()
            .count()
        )

    dossiers_instructeur = get_dossiers_instructeur(instructeur).select_related(
        "id_etape_dossier", "id_demarche"
    )
    actions_ids = _actions_a_faire_ids(dossiers_instructeur, instructeur)
    actions_par_demarche = Counter(
        Dossier.objects.filter(id__in=actions_ids).values_list(
            "id_demarche_id", flat=True
        )
    )

    dossier_infos = []
    for demarche in demarches:
        compteurs = compteurs_dossiers.get(demarche.id, {})
        est_manif = (demarche.type or "").lower() == "manifestations sportives"
        dossier_infos.append({
            "demarche": demarche,
            "nb_reception": compteurs.get("nb_reception", 0) + (nb_dm_reception if est_manif else 0),
            "nb_suivis": compteurs.get("nb_suivis", 0),
            "nb_traites": compteurs.get("nb_traites", 0) + (nb_dm_traites if est_manif else 0),
            "nb_suivis_user": actions_par_demarche[demarche.id] + (nb_dm_actions if est_manif else 0),
        })

    return render(request, 'instruction/instruction.html', {
                                                            "dossier_infos": dossier_infos,
                                                            "instructeur":instructeur,
                                                            })


@login_required
def mesdossiers(request):

    instructeur = Instructeur.objects.filter(email=request.user.email).first()

    if not instructeur:
        messages.error(request, f"❌ Aucun profil 'Instructeur.rice' existant pour l'utilisateur.rice {request.user} : Contactez le support si besoin.")
        return render(request, "instruction/mesdossiers.html", { "dossiers_par_demarche": [] })
    
    # Étapes exclues
    etapes_termines_et_a_affecter = EtapeDossier.objects.filter(etape__in=["Non soumis à autorisation", "Refusé", "Accepté", "Annulé", "À affecter"])

    # Tous les dossiers où l'instructeur intervient (Hors étape 'À affecter')
    base_query = get_dossiers_instructeur(instructeur)

    # Liste dossiers liés à instructeur. Exclusion étapes ["Non soumis à autorisation", "Refusé", "Accepté", "À affecter"]
    dossiers = base_query.exclude(id_etape_dossier__in=etapes_termines_et_a_affecter)


    # POUR LE MOMENT ON EXCLU MANIFESTATIONS SPORTIVES
    # dossiers = dossiers.exclude(id_demarche__type="Manifestations sportives")


    # Liste dossiers avec action à faire (Hors étape 'À affecter')
    actions_ids = _actions_a_faire_ids(base_query, instructeur)
    dossiers_ids = set(dossiers.values_list("id", flat=True)) | actions_ids
    dossiers = list(
        Dossier.objects.filter(id__in=dossiers_ids).select_related(
            "id_demarche", "id_etape_dossier", "id_groupeinstructeur"
        )
    )
    configurations_date_activite = {
        configuration.id_demarche_id: configuration
        for configuration in DemarcheDateActiviteConfiguration.objects.filter(
            id_demarche_id__in={dossier.id_demarche_id for dossier in dossiers}
        )
    }
    dates_debut_manifestation = get_dates_debut_manifestation(dossiers)
    demandeurs = _contacts_demandeurs_par_dossier(dossiers_ids)
    messages_non_lus = _messages_non_lus_par_dossier(dossiers_ids)
    roles = _roles_par_dossier(dossiers, instructeur, actions_ids)
    dossiers_complets_ids = set(
        DossierManifestationLiaison.objects.values_list("id_dossier_id", flat=True)
    )

    dossiers_par_demarche = {}
    for dossier in dossiers:
        regles_date_activite = configuration_date_activite(
            configurations_date_activite.get(dossier.id_demarche_id)
        )
        date_debut_manifestation = get_date_debut_manifestation_vue(
            dossier, dates_debut_manifestation, dossiers_complets_ids
        )
        date_evenement_passee, date_evenement_dans_moins_un_mois = (
            get_indicateurs_date_manifestation(date_debut_manifestation)
        )
        date_activite_passee, date_activite_proche = get_indicateurs_date_activite(
            dossier.date_debut_activite, regles_date_activite
        )

        # Bénéficiaire
        # beneficiaire = get_beneficiaire_for_dossier(dossier)

        # Demandeur
        demandeur = demandeurs.get(dossier.id)

        # Messages non lus DOSSIER
        nb_messages_non_lus = messages_non_lus.get(dossier.id, 0)

        # Déterminer rôle
        action = dossier.id in actions_ids
        role = roles.get(dossier.id, "Inconnu")

        # Structurer les infos
        dossiers_par_demarche.setdefault(dossier.id_demarche.type, []).append({
            "url_name": "instruction_dossier",
            "badge_manifestation": (
                "COMPLET" if dossier.id in dossiers_complets_ids else "DN"
            ) if dossier.id_demarche.type.lower() == "manifestations sportives" else "",
            "nom_dossier": dossier.nom_dossier,
            "nom_dossier_plus_parlant": dossier.nom_dossier_plus_parlant,
            "numero": dossier.numero,
            # "beneficiaire": f"{beneficiaire.prenom} {beneficiaire.nom}" if beneficiaire else "N/A",
            "demandeur": demandeur,
            "date_depot": dossier.date_depot,
            "date_debut_activite": dossier.date_debut_activite,
            "date_activite_passee": date_activite_passee,
            "date_activite_proche": date_activite_proche,
            **regles_date_activite,
            "date_debut_manifestation": date_debut_manifestation,
            "date_evenement_passee": date_evenement_passee,
            "date_evenement_dans_moins_un_mois": date_evenement_dans_moins_un_mois,
            "mon_role": role,
            "etape": dossier.id_etape_dossier.etape if dossier.id_etape_dossier else "Non défini",
            "nb_messages_non_lus": nb_messages_non_lus,
            "action_a_faire": action,
        })

    dossiers_dm_affectes = DossierManifSportive.objects.filter(
        archive=False,
        id_etape__etape="En réception",
        dossiermanifsportiveinstructeur__id_instructeur=instructeur,
    ).exclude(
        id__in=DossierManifestationLiaison.objects.values_list(
            "id_dossier_manif_id", flat=True
        )
    ).distinct().order_by("date_debut_evenement")
    demarche_manif = Demarche.objects.filter(
        type="Manifestations sportives"
    ).only("id").first()
    regles_date_activite_manif = configuration_date_activite(
        DemarcheDateActiviteConfiguration.objects.filter(
            id_demarche=demarche_manif
        ).first() if demarche_manif else None
    )

    for dossier_dm in dossiers_dm_affectes:
        date_evenement_passee, date_evenement_dans_moins_un_mois = (
            get_indicateurs_date_manifestation(dossier_dm.date_debut_evenement)
        )
        date_activite_passee, date_activite_proche = get_indicateurs_date_activite(
            dossier_dm.date_debut_evenement, regles_date_activite_manif
        )
        dossiers_par_demarche.setdefault("Manifestations sportives", []).append({
            "url_name": "dossier_manif_sportive_sans_ds",
            "badge_manifestation": "DM",
            "nom_dossier": dossier_dm.nom_dossier,
            "nom_dossier_plus_parlant": None,
            "numero": dossier_dm.numero_dossier_declaration_manifestations,
            "demandeur": " ".join(filter(None, [dossier_dm.prenom_organisateur, dossier_dm.nom_organisateur])) or dossier_dm.structure or "N/A",
            "date_depot": dossier_dm.date_depot,
            "date_debut_activite": dossier_dm.date_debut_evenement,
            "date_activite_passee": date_activite_passee,
            "date_activite_proche": date_activite_proche,
            **regles_date_activite_manif,
            "date_debut_manifestation": dossier_dm.date_debut_evenement,
            "date_evenement_passee": date_evenement_passee,
            "date_evenement_dans_moins_un_mois": date_evenement_dans_moins_un_mois,
            "mon_role": "Instructeur.rice",
            "etape": dossier_dm.id_etape.etape,
            "nb_messages_non_lus": 0,
            "action_a_faire": True,
        })
    demarches_affichees = {
        demarche.type: demarche
        for demarche in Demarche.objects.filter(
            type__in=list(dossiers_par_demarche)
        ).only("id", "type")
    }
    configurations_par_demarche = {}
    for configuration in DemarcheColonneVueEnsemble.objects.filter(
        id_demarche_id__in=[demarche.id for demarche in demarches_affichees.values()]
    ).only("id_demarche_id", "tableau", "colonne", "affiche", "libelle_personnalise"):
        configurations_par_demarche.setdefault(configuration.id_demarche_id, []).append(configuration)
    colonnes_mes_dossiers = {
        type_demarche: colonnes_visibles(
            type_demarche,
            configurations_par_demarche.get(demarche.id, []),
        )[TABLEAU_MES_DOSSIERS]
        for type_demarche, demarche in demarches_affichees.items()
    }
    colonnes_mes_dossiers_ordonnee = {
        type_demarche: configurations_colonnes_vue_ensemble(
            type_demarche,
            configurations_par_demarche.get(demarche.id, []),
        )[TABLEAU_MES_DOSSIERS]
        for type_demarche, demarche in demarches_affichees.items()
    }
    libelles_mes_dossiers = {
        type_demarche: libelles_colonnes(
            type_demarche,
            configurations_par_demarche.get(demarche.id, []),
        )[TABLEAU_MES_DOSSIERS]
        for type_demarche, demarche in demarches_affichees.items()
    }
    for type_demarche in dossiers_par_demarche:
        colonnes_mes_dossiers.setdefault(
            type_demarche,
            colonnes_visibles(type_demarche)[TABLEAU_MES_DOSSIERS],
        )
        libelles_mes_dossiers.setdefault(
            type_demarche,
            libelles_colonnes(type_demarche)[TABLEAU_MES_DOSSIERS],
        )
        colonnes_mes_dossiers_ordonnee.setdefault(
            type_demarche,
            configurations_colonnes_vue_ensemble(type_demarche)[TABLEAU_MES_DOSSIERS],
        )
    colonnes_mes_dossiers_colspan = {
        type_demarche: sum(colonnes.values())
        for type_demarche, colonnes in colonnes_mes_dossiers.items()
    }

    return render(request, "instruction/mesdossiers.html", {
        "dossiers_par_demarche": dossiers_par_demarche,
        "colonnes_mes_dossiers": colonnes_mes_dossiers,
        "libelles_mes_dossiers": libelles_mes_dossiers,
        "colonnes_mes_dossiers_ordonnee": colonnes_mes_dossiers_ordonnee,
        "colonnes_mes_dossiers_colspan": colonnes_mes_dossiers_colspan,
        "instructeur": instructeur,
    })



@login_required
def instruction_demarche(request, num_demarche):

    demarche = Demarche.objects.filter(numero=num_demarche).first()
    if not demarche:
        logger.error(f"[INSTRUCTION DEMARCHE] Erreur lors de l'affichage de la page par {request.user} : Démarche {num_demarche} introuvable.")
        return redirect_error(request, f"❌ La démarche {num_demarche} est introuvable en base. Contactez le support")

    configurations_tableaux = DemarcheColonneVueEnsemble.objects.filter(
        id_demarche=demarche,
    ).only("tableau", "colonne", "affiche", "libelle_personnalise")
    configurations_colonnes = configurations_colonnes_vue_ensemble(
        demarche.type, configurations_tableaux
    )
    visibilite_colonnes = colonnes_visibles(demarche.type, configurations_tableaux)
    libelles_tableaux = libelles_colonnes(demarche.type, configurations_tableaux)
    colonnes_en_cours = visibilite_colonnes[TABLEAU_EN_COURS]
    colonnes_archives = visibilite_colonnes[TABLEAU_ARCHIVES]
    libelles_en_cours = libelles_tableaux[TABLEAU_EN_COURS]
    libelles_archives = libelles_tableaux[TABLEAU_ARCHIVES]
    colonnes_en_cours_ordonnee = configurations_colonnes[TABLEAU_EN_COURS]
    colonnes_archives_ordonnee = configurations_colonnes[TABLEAU_ARCHIVES]
    regles_date_activite = configuration_date_activite(
        DemarcheDateActiviteConfiguration.objects.filter(id_demarche=demarche).first()
    )


    etapes_termines = EtapeDossier.objects.filter(etape__in=["Non soumis à autorisation", "Refusé", "Accepté", "Annulé"])

    instructeur = Instructeur.objects.filter(email=request.user.email).first()
    if not instructeur:
        messages.warning(request, f"⚠️ Attention, vous n'avez pas de profil 'Instructeur.rice' : Contactez le support si besoin.")


    # Tous les dossiers liés à l'instructeur (hors 'À affecter')
    dossiers_instructeur = (
        get_dossiers_instructeur(instructeur)
        .filter(id_demarche=demarche)
        .select_related("id_etape_dossier", "id_demarche")
    )

    # Calculs groupés : aucune vérification de rôle dossier par dossier.
    dossiers_actions_ids = _actions_a_faire_ids(dossiers_instructeur, instructeur)
    dossiers_concernes_ids = set(dossiers_instructeur.values_list("id", flat=True))
    if instructeur:
        groupes_instructeur_ids = GroupeinstructeurInstructeur.objects.filter(
            id_instructeur=instructeur
        ).values_list("id_groupeinstructeur_id", flat=True)
        dossiers_concernes_ids.update(
            Dossier.objects.filter(
                id_demarche=demarche,
                id_groupeinstructeur_id__in=groupes_instructeur_ids,
            ).values_list("id", flat=True)
        )


    # ============================
    #    DOSSIERS EN INSTRUCTION
    # ============================
    dossiers = (
        Dossier.objects
        .filter(id_demarche=demarche)
        .exclude(id_etape_dossier__etape__in=["Accepté", "Refusé", "Non soumis à autorisation", "Annulé", "À affecter"])
        .select_related("id_groupeinstructeur", "id_etape_dossier", "id_demarche")
        .order_by("date_depot")
    )
    dossiers = list(dossiers)

    dates_debut_manifestation = get_dates_debut_manifestation(dossiers)
    dates_reception_manifestation = (
        get_dates_reception_manifestation(dossiers)
        if demarche.type.lower() == "manifestations sportives"
        else {}
    )
    dossiers_ids = [dossier.id for dossier in dossiers]
    demandeurs = _contacts_demandeurs_par_dossier(dossiers_ids)
    messages_non_lus = _messages_non_lus_par_dossier(dossiers_ids)
    dossiers_complets_ids = set(
        DossierManifestationLiaison.objects.values_list("id_dossier_id", flat=True)
    ) if demarche.type.lower() == "manifestations sportives" else set()
    dossier_infos = []
    for dossier in dossiers:
        date_debut_manifestation = get_date_debut_manifestation_vue(
            dossier, dates_debut_manifestation, dossiers_complets_ids
        )
        date_evenement_passee, date_evenement_dans_moins_un_mois = (
            get_indicateurs_date_manifestation(date_debut_manifestation)
        )
        date_activite_passee, date_activite_proche = get_indicateurs_date_activite(
            dossier.date_debut_activite, regles_date_activite
        )

        # Bénéficiaire
        # beneficiaire = get_beneficiaire_for_dossier(dossier)
        #  Demandeur
        demandeur = demandeurs.get(dossier.id)

        # Messages non lus
        nb_messages_non_lus = messages_non_lus.get(dossier.id, 0)

        dossier_infos.append({
            "badge_manifestation": "COMPLET" if dossier.id in dossiers_complets_ids else "DN",
            "nom_dossier": dossier.nom_dossier,
            "nom_dossier_plus_parlant": dossier.nom_dossier_plus_parlant,
            "obj_doss": dossier,
            "numero": dossier.numero,
            # "beneficiaire": f"{beneficiaire.prenom} {beneficiaire.nom}" if beneficiaire else "N/A",
            "demandeur": demandeur,
            "date_depot": dossier.date_depot,
            "date_reception": dates_reception_manifestation.get(
                dossier.id, dossier.date_depot
            ),
            "date_debut_activite": dossier.date_debut_activite,
            "date_activite_passee": date_activite_passee,
            "date_activite_proche": date_activite_proche,
            **regles_date_activite,
            "date_debut_manifestation": date_debut_manifestation,
            "date_evenement_passee": date_evenement_passee,
            "date_evenement_dans_moins_un_mois": date_evenement_dans_moins_un_mois,
            "groupe": dossier.id_groupeinstructeur.nom if dossier.id_groupeinstructeur else "N/A",
            "etape": dossier.id_etape_dossier.etape if dossier.id_etape_dossier.etape else "Non défini",
            "nb_messages_non_lus": nb_messages_non_lus,
            "action_a_faire": dossier.id in dossiers_actions_ids,
            "est_concerne": request.user.is_superuser or dossier.id in dossiers_concernes_ids,
        })


    # ============================
    #         ARCHIVES
    # ============================
    annee_selectionnee = int(request.GET.get("annee", datetime.now().year))

    # Années disponibles
    min_depot_dossier = Dossier.objects.filter(id_demarche=demarche).aggregate(min_date=Min("date_depot")).get("min_date")

    min_depot_dm = None
    if demarche.type and demarche.type.lower() == "manifestations sportives":
        min_depot_dm = DossierManifSportive.objects.aggregate(min_date=Min("date_depot")).get("min_date")

    dates_min = [d for d in [min_depot_dossier, min_depot_dm] if d is not None]
    annee_min = min(dates_min).year if dates_min else annee_selectionnee

    # min_depot = Dossier.objects.filter(id_demarche=demarche).aggregate(min_date=Min("date_depot")).get("min_date")
    # annee_min = min_depot.year if min_depot else annee_selectionnee
    annees_disponibles = list(range(annee_min, datetime.now().year + 1))

    dossier_archives_infos = []


    # ---------------------------------
    # 1. Dossiers classiques archivés
    # ---------------------------------
    dossiers_archives = list(Dossier.objects.filter(
        id_etape_dossier__in=etapes_termines,
        id_demarche=demarche,
        date_depot__year=annee_selectionnee
    ).select_related(
        "id_groupeinstructeur", "id_etape_dossier", "id_demarche"
    ).order_by("-date_depot"))

    dates_debut_manifestation_archives = get_dates_debut_manifestation(dossiers_archives)
    dates_reception_manifestation_archives = (
        get_dates_reception_manifestation(dossiers_archives)
        if demarche.type.lower() == "manifestations sportives"
        else {}
    )
    dossiers_archives_ids = [dossier.id for dossier in dossiers_archives]
    demandeurs_archives = _contacts_demandeurs_par_dossier(dossiers_archives_ids)
    messages_non_lus_archives = _messages_non_lus_par_dossier(dossiers_archives_ids)
    for dossier in dossiers_archives:

        date_activite_passee, date_activite_proche = get_indicateurs_date_activite(
            dossier.date_debut_activite, regles_date_activite
        )

        # Bénéficiaire
        # beneficiaire = get_beneficiaire_for_dossier(dossier)

        #  Demandeur
        demandeur = demandeurs_archives.get(dossier.id)

        # Messages non lus
        nb_messages_non_lus = messages_non_lus_archives.get(dossier.id, 0)

        dossier_archives_infos.append({
            "source": "dossier",
            "badge_manifestation": "COMPLET" if dossier.id in dossiers_complets_ids else "DN",
            "nom_dossier": dossier.nom_dossier,
            "nom_dossier_plus_parlant": dossier.nom_dossier_plus_parlant,
            "obj_doss": dossier,
            "numero": dossier.numero,
            "demandeur": demandeur,
            "date_depot": dossier.date_depot,
            "date_reception": dates_reception_manifestation_archives.get(
                dossier.id, dossier.date_depot
            ),
            "date_debut_activite": dossier.date_debut_activite,
            "date_activite_passee": date_activite_passee,
            "date_activite_proche": date_activite_proche,
            **regles_date_activite,
            "date_debut_manifestation": get_date_debut_manifestation_vue(
                dossier, dates_debut_manifestation_archives, dossiers_complets_ids
            ),
            "groupe": dossier.id_groupeinstructeur.nom if dossier.id_groupeinstructeur else "N/A",
            "etape": dossier.id_etape_dossier.etape if dossier.id_etape_dossier else "Non défini",
            "nb_messages_non_lus": nb_messages_non_lus,
            "action_a_faire": dossier.id in dossiers_actions_ids,
            "est_concerne": request.user.is_superuser or dossier.id in dossiers_concernes_ids,
            "url_detail": reverse("instruction_dossier", kwargs={"num_dossier": dossier.numero}),
        })


    # --------------------------------------------------------
    # 2. Dossiers DossierManifSportive archivés et non liés
    # --------------------------------------------------------
    if demarche.type and demarche.type.lower() == "manifestations sportives":
        dossiers_deja_lies_ids = DossierManifestationLiaison.objects.values_list("id_dossier_manif_id", flat=True)

        groupe_manif = Groupeinstructeur.objects.filter(nom__iexact="Manifestations sportives").first()

        dossiers_dm_archives_non_lies = list(
            DossierManifSportive.objects
            .filter(
                archive=True,
                date_depot__year=annee_selectionnee,
            )
            .exclude(id__in=dossiers_deja_lies_ids)
            .select_related("id_etape")
            .order_by("-date_depot")
        )
        dates_demande_avis_dm = get_dates_demande_avis_dm(
            dossier_dm.id for dossier_dm in dossiers_dm_archives_non_lies
        )

        for dossier_dm in dossiers_dm_archives_non_lies:
            demandeur = " ".join(
                part for part in [dossier_dm.prenom_organisateur, dossier_dm.nom_organisateur] if part
            ) or dossier_dm.structure or "N/A"

            dossier_archives_infos.append({
                "source": "dossier_manif_sportive",
                "badge_manifestation": "DM",
                "nom_dossier": dossier_dm.nom_dossier,
                "nom_dossier_plus_parlant": dossier_dm.nom_dossier,
                "obj_doss": dossier_dm,
                "numero": dossier_dm.numero_dossier_declaration_manifestations,
                "demandeur": demandeur,
                "date_depot": dossier_dm.date_depot,
                "date_reception": dates_demande_avis_dm.get(dossier_dm.id),
                "date_debut_activite": dossier_dm.date_debut_evenement,
                "date_debut_manifestation": dossier_dm.date_debut_evenement,
                "groupe": groupe_manif.nom if groupe_manif else "Manifestations sportives",
                "etape": dossier_dm.id_etape.etape if dossier_dm.id_etape else "Non défini",
                "nb_messages_non_lus": 0,
                "action_a_faire": False,
                "est_concerne": False,
                "url_detail": reverse("dossier_manif_sportive_sans_ds_archive", kwargs={"numero": dossier_dm.numero_dossier_declaration_manifestations}),
            })


    # Tri : dossiers avec action en premier, puis par nb de messages non lus
    dossier_archives_infos.sort(
        key=lambda d: (
            not d["action_a_faire"],
            -d["nb_messages_non_lus"],
            -(d["date_reception"].timestamp() if d["date_reception"] else 0),
        )
    )

    ###############################
    # Infos sur la synchro
    ###############################
    etat_global = SynchronisationEtat.objects.filter(id=1).values("en_cours").first()
    

    return render(request, "instruction/instruction_demarche.html", {
    "demarche": demarche,
    "dossiers": dossier_infos,
    "annees_disponibles": annees_disponibles,
    "annee_selectionnee": annee_selectionnee,
    "dossiers_archives": dossier_archives_infos,
    "colonnes_en_cours": colonnes_en_cours,
    "colonnes_archives": colonnes_archives,
    "libelles_en_cours": libelles_en_cours,
    "libelles_archives": libelles_archives,
    "colonnes_en_cours_ordonnee": colonnes_en_cours_ordonnee,
    "colonnes_archives_ordonnee": colonnes_archives_ordonnee,
    "table_demarche_colspan": sum(colonnes_en_cours.values()),
    "table_archives_colspan": sum(colonnes_archives.values()),
    "instructeur": instructeur,
    "synchro_globale_en_cours": etat_global["en_cours"] if etat_global else False,
    "synchro_demarche_en_cours": demarche.actualisation_statut == "running",
})





def _numero_acte_affiche(document):
    prefixes = {
        "Arrêté directeur": "DIR-I-",
        "Déliberation CA": "CA/",
    }
    return f"{prefixes.get(document.id_nature.nature, '')}{document.numero}"


def _cle_identite_demandeur(demandeur):
    if not demandeur:
        return None
    if demandeur.email:
        return ("email", demandeur.email.strip().lower())
    if demandeur.siret:
        return ("siret", demandeur.siret.strip())
    return (
        "identite",
        (demandeur.nom or "").strip().lower(),
        (demandeur.prenom or "").strip().lower(),
        (demandeur.raison_sociale or demandeur.organisation or "").strip().lower(),
    )


def _affichage_demandeur(demandeur):
    if not demandeur:
        return "Non renseigné"
    if demandeur.nom and demandeur.prenom and demandeur.email:
        return f"{demandeur.nom} {demandeur.prenom} ({demandeur.email})"
    return demandeur.get_display_name()


@login_required
def rechercher_projets_acte(request, num_dossier):
    dossier_courant = get_object_or_404(Dossier, numero=num_dossier)
    numero = (request.GET.get("numero") or "").strip()
    demarche_type = (request.GET.get("demarche_type") or "").strip()
    etape_dossier = (request.GET.get("etape") or "").strip()
    demandeur_id = (request.GET.get("demandeur") or "").strip()
    nature = (request.GET.get("nature") or "").strip()
    date_fin_instruction_minimale = timezone.now() - timedelta(days=365)

    liaisons = (
        DossierDocument.objects
        .select_related(
            "id_dossier__id_demarche",
            "id_dossier__id_etape_dossier",
            "id_document__id_nature",
            "id_document__id_statut",
        )
        .filter(
            Q(id_dossier__date_fin_instruction__isnull=True)
            | Q(id_dossier__date_fin_instruction__gte=date_fin_instruction_minimale),
            id_document__numero__isnull=False,
            id_document__id_nature__nature__in=[
                "Arrêté directeur",
                "Déliberation CA",
                "Avis simple",
                "Avis conforme",
            ],
            id_document__id_statut__statut__in=[
                "À valider",
                "À relire",
                "À signer",
                "À envoyer",
                "Envoyé",
            ],
        )
        .exclude(id_document__numero="")
        .exclude(id_dossier=dossier_courant)
        .order_by("-id_document__date")
    )
    if numero:
        liaisons = liaisons.filter(id_dossier__numero__icontains=numero)
    if demarche_type:
        liaisons = liaisons.filter(id_dossier__id_demarche__type=demarche_type)
    if etape_dossier:
        liaisons = liaisons.filter(
            id_dossier__id_etape_dossier__etape=etape_dossier
        )
    if nature:
        liaisons = liaisons.filter(id_document__id_nature__nature=nature)
    demandeur_filtre = (
        ContactExterne.objects.filter(id=demandeur_id).first()
        if demandeur_id
        else None
    )
    cle_demandeur_filtre = _cle_identite_demandeur(demandeur_filtre)
    actes_deja_presents = set(
        DossierDocument.objects
        .filter(
            id_dossier=dossier_courant,
            id_document__numero__isnull=False,
        )
        .exclude(id_document__numero="")
        .values_list(
            "id_document__id_nature_id",
            "id_document__numero",
        )
    )

    resultats = []
    demandeurs = {}
    documents_vus = set()
    projets_exclus = {}
    for liaison in liaisons:
        demandeur = get_demandeur_for_dossier(liaison.id_dossier)
        if (
            cle_demandeur_filtre
            and _cle_identite_demandeur(demandeur) != cle_demandeur_filtre
        ):
            continue
        cle_acte = (
            liaison.id_document.id_nature_id,
            liaison.id_document.numero,
        )
        if cle_acte in actes_deja_presents:
            projets_exclus[cle_acte] = (
                f"{liaison.id_document.id_nature.nature} "
                f"{_numero_acte_affiche(liaison.id_document)}"
            )
            continue
        if demandeur:
            demandeurs[demandeur.id] = _affichage_demandeur(demandeur)
        if liaison.id_document_id in documents_vus:
            continue
        documents_vus.add(liaison.id_document_id)
        resultats.append(
            {
                "document_id": liaison.id_document_id,
                "dossier_numero": liaison.id_dossier.numero,
                "dossier_etape": liaison.id_dossier.id_etape_dossier.etape,
                "demarche_type": liaison.id_dossier.id_demarche.type,
                "demandeur": (
                    _affichage_demandeur(demandeur)
                ),
                "nature": liaison.id_document.id_nature.nature,
                "numero": liaison.id_document.numero,
                "numero_affiche": _numero_acte_affiche(liaison.id_document),
            }
        )
        if len(resultats) == 50:
            break

    return JsonResponse(
        {
            "resultats": resultats,
            "projets_exclus": sorted(projets_exclus.values()),
            "demandeurs": [
                {"id": identifiant, "nom": nom}
                for identifiant, nom in sorted(
                    demandeurs.items(), key=lambda item: item[1].lower()
                )
            ],
        }
    )


@login_required
def instruction_dossier(request, num_dossier):

    dossier = Dossier.objects.filter(numero=num_dossier).first()
    if not dossier:
        logger.error(f"[INSTRUCTION DOSSIER] Erreur lors de l'affichage de la page par {request.user} : Dossier {num_dossier} introuvable.")
        return dossier_introuvable(request, num_dossier, "DN")
    
    demarche = dossier.id_demarche

    # Normalisation du path complet
    chemin_complet = dossier.emplacement
    if not chemin_complet.startswith(os.getenv('NAS_ROOT')):
        chemin_complet = os.path.join(os.getenv('NAS_ROOT'), chemin_complet)
    chemin_complet = _normalize_unc_path(chemin_complet)


    ####################################
    # Charger les fonds de carte GeoJSON
    ####################################
    fond_coeur_de_parc = load_geojson("instruction/static/instruction/carto/fond_coeur_de_parc.geojson")
    fond_aire_adhesion = load_geojson("instruction/static/instruction/carto/aire_adhesion.geojson")
    fond_mafate = load_geojson("instruction/static/instruction/carto/COT_MAFATE.geojson")
    perimetre_secteurs = load_geojson("instruction/static/instruction/carto/perimetre_secteur.geojson")
    pois_json = load_geojson("instruction/static/instruction/carto/pois.json")


    ####################################
    # Champs du formulaire DS
    ####################################
    champs_prepares, nb_cartes = build_champs_prepares(dossier)


    ####################################
    # Groupe Instructeurs
    ####################################
    # Groupes Instructeurs de la Démarche
    groupes_instructeurs = Groupeinstructeur.objects.filter(groupeinstructeurdemarche__id_demarche=dossier.id_demarche).order_by("nom")

    # Instructeurs du Dossier
    instructeurs_dossier = set(DossierInstructeur.objects.filter(id_dossier=dossier).values_list("id_instructeur_id", flat=True))

    # Instructeur connecté
    instructeur_connecte = (Instructeur.objects.filter(email=request.user.email).select_related("id_agent_autorisations").first())
    
    # Membres du groupe instructeur associé au Dossier
    membres_groupe = []
    if dossier.id_groupeinstructeur:
        membres_groupe = [
            m.id_instructeur
            for m in dossier.id_groupeinstructeur
                .groupeinstructeurinstructeur_set
                .select_related("id_instructeur__id_agent_autorisations")
        ]

    membres_groupe_ids = {instructeur.id for instructeur in membres_groupe}
    autres_instructeurs_du_dossier = list(
        Instructeur.objects
        .filter(id__in=instructeurs_dossier - membres_groupe_ids)
        .select_related("id_agent_autorisations")
        .order_by("id_agent_autorisations__nom", "id_agent_autorisations__prenom", "email")
    )


    ####################################
    # Bouton 'Se déclarer Instructeur'
    ####################################
    peut_se_declarer = False
               
    if dossier.id_groupeinstructeur and instructeur_connecte:
        instructeurs_du_groupe = set(
            dossier.id_groupeinstructeur
            .groupeinstructeurinstructeur_set
            .values_list("id_instructeur_id", flat=True)
        )

        # Si aucun instructeur du groupe n'est affecté au dossier, et que l'utilisateur connecté fait partie du groupe : il peut se déclarer
        if not instructeurs_dossier & instructeurs_du_groupe and instructeur_connecte.id in instructeurs_du_groupe:
            peut_se_declarer = True


    ###################################################
    # Infos sur le bénéficiaire/demandeur intermediaire
    ###################################################
    beneficiaire = get_beneficiaire_for_dossier(dossier)
    demandeur = get_demandeur_for_dossier(dossier)
    demandeur_intermediaire = None
    interlocuteur = DossierInterlocuteur.objects.filter(id_dossier=dossier).first()
    if interlocuteur and interlocuteur.id_demandeur_intermediaire:
        demandeur_intermediaire = interlocuteur.id_demandeur_intermediaire



    ########################################
    # Menu déroulant avec les choix d'étapes
    ########################################
    etapes_possibles = EtapeDossier.objects.all().order_by("etape")
    etape_actuelle = dossier.id_etape_dossier if hasattr(dossier, "id_etape_dossier") else None

    dossier_sppn = dossier.id_demarche.service == 'SPPN'
    # etapes_custom = get_etapes_custom(
    #     present_sur_ds=dossier.present_sur_ds,
    #     dossier_sppn=dossier_sppn,
    #     etape_actuelle=etape_actuelle.etape if etape_actuelle else "",
    #     demarche_type=demarche.type
    # )
    
    
    #####################################################
    # TIMELINE : Mapping entre les actions et leurs logos
    #####################################################
    dossier_actions = build_timeline_for_dossier(dossier)


    ################################
    #  Notes & Annexes Instructeur
    ################################
    liaison_notes = DossierManifestationLiaison.objects.filter(id_dossier=dossier).first()
    filtre_notes = Q(id_dossier=dossier)
    if liaison_notes:
        filtre_notes |= Q(id_dossier_manif_sportive=liaison_notes.id_dossier_manif)
    notes_queryset = DossierNote.objects.filter(filtre_notes).select_related(
        "id_instructeur__id_agent_autorisations"
    ).order_by("-date")
    notes = [
        {
            "id": n.id,
            "note": n.note,
            "date": n.date,
            "instructeur_id": n.id_instructeur.id,
            "origine_dm": n.id_dossier_manif_sportive_id is not None,
            "instructeur": f"{n.id_instructeur.id_agent_autorisations.prenom} {n.id_instructeur.id_agent_autorisations.nom}" 
                            if n.id_instructeur.id_agent_autorisations 
                            else n.id_instructeur.email,
        }
        for n in notes_queryset
    ]


    #############################
    # Documents
    #############################
    documents_data = build_documents_for_dossier(dossier)
    documents_numerotes = {
        liaison.id_document_id: liaison.id_document
        for liaison in (
            DossierDocument.objects
            .filter(
                id_dossier=dossier,
                id_document__numero__isnull=False,
            )
            .exclude(id_document__numero="")
            .select_related("id_document__id_nature")
        )
    }
    statuts_projet_acte_actif = [
        "À valider",
        "À relire",
        "À signer",
        "À envoyer",
        "Envoyé",
    ]
    dossiers_meme_acte_par_document = {}
    for document in documents_numerotes.values():
        dossiers_meme_acte_par_document[document.id] = list(
            DossierDocument.objects
            .filter(
                id_document__id_nature=document.id_nature,
                id_document__numero=document.numero,
                id_document__id_statut__statut__in=statuts_projet_acte_actif,
            )
            .exclude(id_dossier=dossier)
            .select_related(
                "id_dossier__id_demarche",
                "id_dossier__id_etape_dossier",
                "id_document__id_nature",
                "id_document__id_statut",
            )
            .order_by("id_dossier__numero")
        )
    for valeur in documents_data.values():
        if not isinstance(valeur, (list, tuple)):
            continue
        for document in valeur:
            if isinstance(document, Document):
                document.dossiers_meme_acte = (
                    dossiers_meme_acte_par_document.get(document.id, [])
                )
    taille_acte_mail_octets = None
    doc_a_envoyer = (documents_data.get("doc_a_envoyer") or [None])[0]
    if doc_a_envoyer:
        try:
            chemin_acte = os.path.join(
                os.getenv("NAS_ROOT", ""),
                dossier.emplacement,
                "Actes",
                doc_a_envoyer.titre,
            )
            taille_acte_mail_octets = smbclient.path.getsize(chemin_acte)
        except Exception as exc:
            logger.warning(
                f"[DOSSIER {dossier.numero}] Taille de l'acte à envoyer indisponible "
                f"pour le contrôle du formulaire : {exc}"
            )
    peut_remplacer_acte_signe = bool(
        etape_actuelle
        and etape_actuelle.etape == "Acte à envoyer"
        and (
            request.user.is_superuser
            or (
                instructeur_connecte
                and DossierIntermediaireSignature.objects.filter(
                    id_dossier=dossier,
                    id_instructeur=instructeur_connecte,
                ).exists()
            )
        )
    )

   
    ###############################
    # Liste d'instructeurs par rôle
    ###############################

    # Relecteur du dossier 
    relecteurs_du_dossier = DossierRelecteur.objects.filter(id_dossier=dossier)
    instructeurs = Instructeur.objects.select_related("id_agent_autorisations").order_by("id_agent_autorisations__nom","id_agent_autorisations__prenom")

    roles = build_roles_for_dossier(dossier)

    # Type contacts externes
    types_contacts = TypeContactExterne.objects.all()

    # Instructeur.rices du dossier
    instructeurs_du_dossier = Instructeur.objects.filter(
        dossierinstructeur__id_dossier=dossier
    ).select_related("id_agent_autorisations")


    ###############################
    # Messages non lus
    ###############################
    nb_messages_non_lus = count_unread_messages_for_dossier(dossier, dossier.numero)

    
    ####################################
    # Dossier Déclaration Manifestations
    ####################################
    doss_manif_sportive = None
    avis_manif_sportive = None
    docs_DM = {}
    liaison = None
    date_evenement_passee = False
    date_evenement_dans_moins_un_mois = False
    
    if dossier.id_demarche.type == "Manifestations sportives":
        liaison = DossierManifestationLiaison.objects.filter(id_dossier=dossier).select_related("id_dossier_manif").first()
        if liaison:
            doss_manif_sportive = liaison.id_dossier_manif
            date_evenement_passee, date_evenement_dans_moins_un_mois = (
                get_indicateurs_date_manifestation(doss_manif_sportive.date_debut_evenement)
            )

            avis_manif_sportive = get_avis_dm_le_plus_recent(doss_manif_sportive)

            # Récupération des PJ sur DM + emplacement NAS
            docs_DM = documents_deposes_sur_DM(doss_manif_sportive)
    
    dossiers_deja_lies_dm_ids = DossierManifestationLiaison.objects.values_list("id_dossier_manif_id", flat=True)
    limite_deux_mois = timezone.now() - timedelta(days=60)
    dossiers_DM_manif_sportive_non_lie_archive = (
        DossierManifSportive.objects
        .filter(archive=True,)
        .filter(
            Q(date_fin_evenement__gte=limite_deux_mois) |
            Q(date_fin_evenement__isnull=True)
        )
        .exclude(id__in=dossiers_deja_lies_dm_ids)
        .order_by("-date_debut_evenement")
    )



    ################
    #    Emails
    ################
    emails_contacts = ContactExterne.objects.filter(
        email__isnull=False
    ).exclude(email__exact="").values_list("email", flat=True).distinct()

    emails_instructeurs = Instructeur.objects.filter(
        email__isnull=False
    ).exclude(email__exact="").values_list("email", flat=True).distinct()

    # Fusionner et dédoublonner
    emails_uniques = sorted(set(emails_contacts) | set(emails_instructeurs))

    # Liste les envois d'acte et uniquement les notifications créées via la
    # cloche (les autres e-mails de type « Notification » sont automatiques).
    emails_dossiers = EmailOutbox.objects.filter(
        id_dossier=dossier.id,
    ).filter(
        Q(type_mail="Envoi de l'acte")
        | Q(template="notification_agents_dossier")
    ).order_by("-date_creation")

    # On ajoute les mails de Relance du dossier DM (s'il y en a)
    if liaison :
        emails_relance_dm = EmailOutbox.objects.filter(id_dossier_dm=doss_manif_sportive, type_mail="Relance", statut="Envoyé")
        emails_dossiers = (emails_dossiers | emails_relance_dm).order_by("-date_creation")
    else :
        
        emails_dossiers = emails_dossiers.order_by("-date_creation")

    # Les anciennes notifications manuelles stockaient l'e-mail de l'auteur.
    # On le résout au rendu si l'agent correspondant est connu.
    emails_dossiers = list(emails_dossiers)
    emails_auteurs = {
        email.context.get("auteur", "").strip().casefold()
        for email in emails_dossiers
        if email.template == "notification_agents_dossier"
        and email.context.get("auteur")
    }
    agents_auteurs = AgentAutorisations.objects.filter(
        Q(mail_1__in=emails_auteurs) | Q(mail_2__in=emails_auteurs)
    )
    noms_auteurs = {}
    for agent in agents_auteurs:
        nom_complet = " ".join(part for part in (agent.prenom, agent.nom) if part)
        for adresse in (agent.mail_1, agent.mail_2):
            if adresse and nom_complet:
                noms_auteurs[adresse.casefold()] = nom_complet
    for email in emails_dossiers:
        auteur = email.context.get("auteur", "")
        email.auteur_notification_affiche = noms_auteurs.get(auteur.casefold(), auteur)

    ##################
    #  AVIS 
    ##################
    avis_data = build_avis_for_dossier(dossier)


    ###############################
    # Infos sur la synchro
    ###############################
    etat_global = SynchronisationEtat.objects.filter(id=1).values("en_cours").first()


    # Actions possibles
    actions_possibles = get_actions_possibles(dossier)
    peut_changer_etape = request.user.is_superuser or est_autorise_a_changer_etape(request.user, dossier)
    peut_annuler_en_instruction = (
        "Classer comme annulé" in actions_possibles
        and peut_annuler_en_instruction_comme_receptionniste(request.user, dossier)
    )
    if not peut_changer_etape:
        actions_possibles = ["Classer comme annulé"] if peut_annuler_en_instruction else []

    DM_API_URL = os.getenv('DM_API_URL')

    agents_notification = get_choix_destinataires_notification()
    auteur_notification = (
        request.user.get_full_name().strip()
        or (str(instructeur_connecte) if instructeur_connecte else "")
        or request.user.email
    )

    return render(request, 'instruction/instruction_dossier.html', {
        **contexte_dossiers_lies(request, dossier),
        # Dossier
        "demarche": demarche,
        "dossier": dossier,
        "etat_dossier": format_etat_dossier(dossier.id_etat_dossier.nom),
        "chemin_complet": chemin_complet,
        "champs": champs_prepares,
        "etapes_possibles": etapes_possibles,
        "etapes_recherche_projet_acte": (
            EtapeDossier.objects
            .exclude(etape__in=["À affecter", "En pré-instruction"])
            .order_by("etape")
        ),
        "etape_actuelle": etape_actuelle,
        # "etapes_custom": etapes_custom,
        "dossier_actions": dossier_actions,
        "notes": notes,
        "emails_uniques": emails_uniques,
        "emails_dossiers": emails_dossiers,
        "nb_messages_non_lus": nb_messages_non_lus,
        "synchro_globale_en_cours": etat_global["en_cours"] if etat_global else False,
        "actions_possibles": actions_possibles,
        "motif_decision": get_motif_decision(dossier),
        "peut_changer_etape": peut_changer_etape,
        "peut_annuler_en_instruction": peut_annuler_en_instruction,

        # Manif Sportive
        "dossier_lie_manif_sportive": liaison is not None,
        "doss_manif_sportive": doss_manif_sportive,
        "date_evenement_passee": date_evenement_passee,
        "date_evenement_dans_moins_un_mois": date_evenement_dans_moins_un_mois,
        "avis_manif_sportive": avis_manif_sportive,
        **docs_DM,
        "dossiers_DM_manif_sportive_non_lie_archive": dossiers_DM_manif_sportive_non_lie_archive,

        # Carto
        "coeurData": fond_coeur_de_parc,
        "adhesionData": fond_aire_adhesion,
        "mafateData": fond_mafate,
        "secteursData": perimetre_secteurs,
        "nb_cartes": nb_cartes,
        "pois_json": pois_json,

        # Instructeurs
        "groupes_instructeurs": groupes_instructeurs,
        "instructeurs": instructeurs,
        "membres_groupe": membres_groupe,
        "autres_instructeurs_du_dossier": autres_instructeurs_du_dossier,
        "instructeurs_dossier_ids": instructeurs_dossier,
        "instructeurs_du_dossier": instructeurs_du_dossier,
        "peut_se_declarer": peut_se_declarer,
        "instructeur_connecte": instructeur_connecte,
        "agents_notification": agents_notification,
        "auteur_notification": auteur_notification,
        "peut_remplacer_acte_signe": peut_remplacer_acte_signe,
        "relecteurs_du_dossier": relecteurs_du_dossier,

        # Contacts
        "beneficiaire": beneficiaire,
        "demandeur_intermediaire": demandeur_intermediaire,
        "demandeur": demandeur,
        "demandeur_affichage": _affichage_demandeur(demandeur),
        "types_demarches": (
            Demarche.objects
            .exclude(type__isnull=True)
            .exclude(type="")
            .values_list("type", flat=True)
            .distinct()
            .order_by("type")
        ),
        "types_contacts": types_contacts,
        
        # Settings
        "NAS_ROOT": os.getenv('NAS_ROOT'),
        "is_formulaire_active": True,
        "is_messagerie_active": False,
        "messages_groupe_instructeur": request.session.pop("messages_bloc_groupe_instructeur", []),
        "messages_intermediaire_signature": request.session.pop("messages_bloc_intermediaire_signature", []),
        "messages_envoyeur_acte": request.session.pop("messages_bloc_envoyeur_acte", []),
        "messages_publieur_raa": request.session.pop("messages_bloc_publieur_raa", []),
        "messages_valideur": request.session.pop("messages_bloc_valideur", []),
        "messages_relecteur_qualite": request.session.pop("messages_bloc_relecteur_qualite", []),
        "messages_notes": request.session.pop("messages_bloc_notes", []),
        "changer_valideur_message": request.session.pop("changer_valideur_message", None),
        "changer_relecteur_qualite_message": request.session.pop("changer_relecteur_qualite_message", None),
        "relecteur_message": request.session.pop("relecteur_message", None),
        "now": timezone.now(),
        "DM_API_URL": DM_API_URL,
        "taille_acte_mail_octets": taille_acte_mail_octets,
        "taille_max_mail_mo": int(os.getenv("EMAIL_MAX_MESSAGE_SIZE_MB", "10")),

        **roles,
        **avis_data,
        **documents_data,
    })



@login_required
def sauvegarder_note_dossier(request):
    
    dossier_id = request.POST.get("dossierId")
    dossier_dm_id = request.POST.get("dossierManifSportiveId")
    note_id = request.POST.get("noteId")
    contenu = request.POST.get("note")

    dossier = Dossier.objects.filter(id_ds=dossier_id).first() if dossier_id else None
    dossier_dm = DossierManifSportive.objects.filter(id=dossier_dm_id).first() if dossier_dm_id else None
    if dossier_dm and not dossier:
        liaison_dm = DossierManifestationLiaison.objects.filter(
            id_dossier_manif=dossier_dm
        ).select_related("id_dossier").first()
        if liaison_dm:
            dossier = liaison_dm.id_dossier
    if not dossier and not dossier_dm:
        logger.error(f"[SAUVEGARDE NOTE DOSSIER] Dossier introuvable — User : {request.user}")
        return redirect_error(request, f"❌ Le dossier est introuvable. Contactez le support.")
    dossier_libelle = (
        f"DN {dossier.numero}"
        if dossier
        else f"DM {dossier_dm.numero_dossier_declaration_manifestations}"
    )
    
    instructeur = Instructeur.objects.filter(email=request.user.email).first()
    if not instructeur:
        logger.warning(f"[DOSSIER {dossier_libelle}] Le user {request.user} a tenté de sauvegarder la note sans profil instructeur.")
        return redirect_error(request, "❌ Vous n’avez pas de profil 'Instructeur'. Contactez le support.")
    
    if not contenu:
        logger.warning(f"[DOSSIER {dossier_libelle}] Le user {request.user} a tenté de sauvegarder une note vide.")
        return redirect_error(request, "La note est vide.")

    try :
        if note_id:  # Modification d'une note existante
            notes_autorisees = Q(id_dossier=dossier) if dossier else Q(id_dossier_manif_sportive=dossier_dm)
            if dossier:
                liaison = DossierManifestationLiaison.objects.filter(id_dossier=dossier).first()
                if liaison:
                    notes_autorisees |= Q(id_dossier_manif_sportive=liaison.id_dossier_manif)
            note = DossierNote.objects.filter(
                notes_autorisees, id=note_id, id_instructeur=instructeur
            ).first()
            if not note:
                logger.error(f"[DOSSIER {dossier_libelle}] Échec de la modification d'une note existante par {request.user} : Note {note_id} (instructeur={instructeur}) introuvable.")
                return redirect_error(request, "Erreur : Vous n'êtes pas autorisé à modifier la note. Contactez le support si besoin.")

            note.note = contenu
            note.save(update_fields=["note"])
            logger.info(f"[DOSSIER {dossier_libelle}] Note modifiée par {instructeur}")

        else:  # Création d'une nouvelle note
            DossierNote.objects.create(
                id_dossier=dossier,
                id_dossier_manif_sportive=dossier_dm if not dossier else None,
                id_instructeur=instructeur,
                note=contenu,
                date=timezone.now()
            )
            logger.info(f"[DOSSIER {dossier_libelle}] Nouvelle note ajoutée par {instructeur}")

    except Exception as e:
        logger.exception(f"[DOSSIER {dossier_libelle}] Erreur lors de la sauvegarde de la note {note_id} par {request.user} : {e}")
        return redirect_error(request, "❌ Une erreur est survenue lors de l’enregistrement de la note. Contactez le support.")

    ajouter_message_bloc(request, "notes", "Note enregistrée.", "success")
    return redirect(request.META.get("HTTP_REFERER", "/"))



@login_required
def supprimer_note_dossier(request):
    dossier_id = request.POST.get("dossierId")
    dossier_dm_id = request.POST.get("dossierManifSportiveId")
    note_id = request.POST.get("noteId")

    dossier = Dossier.objects.filter(id_ds=dossier_id).first() if dossier_id else None
    dossier_dm = DossierManifSportive.objects.filter(id=dossier_dm_id).first() if dossier_dm_id else None
    if dossier_dm and not dossier:
        liaison_dm = DossierManifestationLiaison.objects.filter(
            id_dossier_manif=dossier_dm
        ).select_related("id_dossier").first()
        if liaison_dm:
            dossier = liaison_dm.id_dossier
    if not dossier and not dossier_dm:
        logger.error(f"[SUPPRIMER NOTE] Dossier introuvable — User : {request.user}")
        return redirect_error(request, "❌ Le dossier est introuvable. Contactez le support.")
    dossier_libelle = (
        f"DN {dossier.numero}"
        if dossier
        else f"DM {dossier_dm.numero_dossier_declaration_manifestations}"
    )

    instructeur = Instructeur.objects.filter(email=request.user.email).first()
    if not instructeur:
        logger.warning(f"[DOSSIER {dossier_libelle}] Le user {request.user} a tenté de supprimer une note sans profil instructeur.")
        return redirect_error(request, "❌ Vous n’avez pas de profil 'Instructeur'. Contactez le support.")
    

    notes_autorisees = Q(id_dossier=dossier) if dossier else Q(id_dossier_manif_sportive=dossier_dm)
    if dossier:
        liaison = DossierManifestationLiaison.objects.filter(id_dossier=dossier).first()
        if liaison:
            notes_autorisees |= Q(id_dossier_manif_sportive=liaison.id_dossier_manif)
    note = DossierNote.objects.filter(
        notes_autorisees, id=note_id, id_instructeur=instructeur
    ).first()
    if not note:
        logger.error(f"[DOSSIER {dossier_libelle}] Suppression échouée : note {note_id} introuvable ou non autorisée pour {instructeur}.")
        return redirect_error(request, "Vous n'êtes pas autorisé à supprimer cette note. Contactez le support si besoin.")
  
    # Suppression si tout est OK
    try:
        note.delete()
        logger.info(f"[DOSSIER {dossier_libelle}] Note {note_id} supprimée par {instructeur}")

    except Exception as e:
        logger.error(f"[DOSSIER {dossier_libelle}] Erreur lors de la suppression de la note {note_id} par {request.user} : {e}")
        return redirect_error(request, "❌ Une erreur est survenue lors de la suppression de la note. Contactez le support.")


    ajouter_message_bloc(request, "notes", "Note supprimée.", "success")
    return redirect(request.META.get("HTTP_REFERER", "/"))




@require_POST
@login_required
def ajouter_relecteur_dossier(request):
    dossier_id = request.POST.get("dossier_id")
    relecteur_id = request.POST.get("relecteur_id")
    objet_demande = request.POST.get("objet_demande")
    files = request.FILES.getlist("pj_relecture")


    dossier = Dossier.objects.filter(id=dossier_id).first()
    if not dossier:
        logger.error(f"[NOUVELLE DEMANDE RELECTURE] Dossier (id={dossier_id}) introuvable — User= : {request.user}")
        return redirect_error(request, "❌ Le dossier est introuvable. Contactez le support.")

    relecteur = Instructeur.objects.filter(id=relecteur_id).first()
    if not relecteur:
        logger.error(f"[DOSSIER {dossier.numero}] Nouvelle demande de relecture. Relecteur {relecteur_id} introuvable — User : {request.user}")
        return redirect_error(request, "❌ Le relecteur indiqué est introuvable. Contactez le support.")

    demandeur_relecture = Instructeur.objects.filter(email=request.user.email).first()
    if not demandeur_relecture:
        logger.error(f"[DOSSIER {dossier.numero}] Nouvelle demande de relecture impossible : aucun profil Instructeur pour {request.user}.")
        return redirect_error(request, "❌ Vous n’avez pas de profil 'Instructeur'. Contactez le support.")


    for f in files:
        if f.size > 20 * 1024 * 1024:  # 20 Mo
            msg = f"Le fichier {f.name} dépasse la limite de 20 Mo."
            logger.warning(f"[DOSSIER {dossier.numero}] Nouvelle demande de relecture faite par {request.user} : {msg}")
            request.session["relecteur_message"] = msg
            return redirect(request.META.get("HTTP_REFERER", "/"))


    # Évite les doublons
    existant = DossierRelecteur.objects.filter(
        id_dossier=dossier,
        id_instructeur=relecteur,
    ).first()

    if existant:
        request.session["relecteur_message"] = (
            "Ce.tte relecteur.rice a déjà une relecture "
            + ("réalisée." if existant.relu else "en cours.")
        )
        return redirect(request.META.get("HTTP_REFERER", "/"))


    try : 
        dossier_relecteur = DossierRelecteur.objects.create(
            id_dossier=dossier,
            id_instructeur=relecteur,
            id_demandeur_relecture=demandeur_relecture,
            demande_relecture=objet_demande,
        )

    except Exception as e:
        logger.exception(f"[DOSSIER {dossier.numero}] Nouvelle demande de relecture faite par {request.user} - Erreur création DossierRelecteur : {e}")
        request.session["relecteur_message"] = "La demande de relecture a échoué. Contactez le support."
        return redirect(request.META.get("HTTP_REFERER", "/"))

 
    for f in files :

        # Extension du fichier
        nom, extension = os.path.splitext(f.name)
        extension = extension.lstrip('.').lower()

        # Récupérer le format
        format_obj = DocumentFormat.objects.filter(format__iexact=extension).first()
        if not format_obj:
            request.session["relecteur_message"] = (f"PJ refusée car le format n'est pas reconnu : {f.name}.{extension}.")
            logger.warning(f"[DOSSIER {dossier.numero}] Nouvelle demande de relecture faite par {request.user} : PJ refusée car le format n'est pas reconnu : {f.name}.{extension}")
            return redirect(request.META.get("HTTP_REFERER", "/"))
        


        # Ecriture du fichier
        emplacement = f"{dossier.emplacement}Annexes/Relecture/{f.name}"
        chemin_complet = f"{os.getenv('NAS_ROOT')}{emplacement}"
        creer_dossier_sur_nas(chemin_complet)

        # Évite les doublons → incrémente _2, _3...
        base_nom, ext = os.path.splitext(f.name)
        compteur = 1
        while smbclient.path.exists(chemin_complet):
            compteur += 1
            nouveau_nom = f"{base_nom}_{compteur}{ext}"
            emplacement = emplacement = f"{dossier.emplacement}Annexes/Relecture/{nouveau_nom}"
            f.name = nouveau_nom
            chemin_complet = os.path.join(os.getenv("NAS_ROOT"), emplacement)

        try:

            if not ecrire_file_sur_nas(f, chemin_complet): 
                logger.error(f"[NAS] ❌ Échec de l’écriture du fichier {nouveau_nom} sur {chemin_complet}")
                raise Exception(f"Échec de l’écriture du fichier {nouveau_nom} sur {chemin_complet}")
            

            logger.info(f"[DOSSIER {dossier.numero}] Demande de relecture : PJ {f.name} ajoutée avec succès par {request.user}")

        except Exception as e:
            logger.error(f"[DOSSIER {dossier.numero}] Demande de relecture : Erreur lors de l'écriture de la PJ {f.name} : {e}")
            request.session["relecteur_message"] = (f"Une erreur est survenue lors de l’enregistrement du fichier : {f.name}.{extension}")
            return redirect(request.META.get("HTTP_REFERER", "/"))


        # Création du Document
        try:
            document = Document.objects.create(
                id_format=format_obj,  
                id_nature=DocumentNature.objects.get(nature="Pièce jointe à relire"),
                id_statut=None,
                emplacement=f"{dossier.emplacement}Annexes/Relecture/",
                titre=f.name,
                description="Document joint à une demande de relecture"
            )

            # Liaison avec la demande de relecture
            DossierRelecteurDocument.objects.create(
                id_dossier_relecteur=dossier_relecteur,
                id_document=document
            )

        except Exception as e:
            logger.error(f"[DOSSIER {dossier.numero}] Nouvelle demande de relecture faite par {request.user} - Échec création Document pour {f.name} : {e}")
            request.session["relecteur_message"] = "❌ Erreur lors de la création du document en base. Contactez le support."
            return redirect(request.META.get("HTTP_REFERER", "/"))
        

    ####################################
    # NOTIFICATION PAR MAIL AU RELECTEUR 
    ####################################

    if request.user.email != relecteur.email :

        # On notifie les agents dans le cadre d'une vraie instruction
        if NOTIFS_PROD :
            emails_norm = [relecteur.email]
        # Test de notification par mail à EMAIL_NOTIF_TEST   
        else :
            emails_norm = [EMAIL_NOTIF_TEST]

        emails_txt = ", ".join(emails_norm)

        sujet = f"Dossier {dossier.numero} - Relecture demandée"

        context = {
                    "dossier_numero": dossier.numero,
                    "demarche_type": dossier.id_demarche.type,
                    "url": f"{os.getenv('URL_APPLI')}instruction/{dossier.numero}/"
                }
        template_name = "demande_relecture"

        try :
            dedupe = compute_dedupe_key(emails_norm, sujet, template_name, context)

        except Exception as e:
            logger.error(f"[DOSSIER {dossier.numero}] Nouvelle demande de relecture faite par {request.user} - Erreur lors de la création de la clé unique (compute_dedupe_key) : {e}")
            return redirect_error(request, f"L'email de notification à {emails_txt} n'a pas été envoyé. Contactez le support pour en savoir plus.")


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
                logger.error(f"[DOSSIER {dossier.numero}] Demande de relecture faite par {request.user} : Erreur lors de la création de l'EmailOutbox, {emails_txt} n'a pas été notifié de la demande de relecture par mail.")
                request.session["relecteur_message"] = (f"L'email de notification à {emails_txt} n'a pas été envoyé. Contactez le support pour en savoir plus.")
                return redirect(reverse("instruction_dossier", kwargs={"num_dossier": dossier.numero}))

            if ok:
                logger.info(f"[DOSSIER {dossier.numero}] Notification Email {outbox.id} (Demande de relecture faite par {request.user}) envoyée à {', '.join(outbox.to)} ")
            else:
                logger.error(f"[DOSSIER {dossier.numero}] Échec envoi notification email {outbox.id} (Demande de relecture faite par {request.user}) à {', '.join(outbox.to)} : {err}")
                request.session["relecteur_message"] = (f"L'email de notification à {emails_txt} n'a pas été envoyé. Contactez le support pour en savoir plus.")
                return redirect(reverse("instruction_dossier", kwargs={"num_dossier": dossier.numero}))

    
    return redirect(reverse("instruction_dossier", kwargs={"num_dossier": dossier.numero}))



@require_POST
@login_required
def relecture_faite(request):
    dossier_id = request.POST.get("dossier_id")
    relecteur_entry_id = request.POST.get("relecteur_id")
    reponse_demande = request.POST.get("reponse_demande")

    dossier = Dossier.objects.filter(id=dossier_id).first()
    if not dossier:
        logger.error(f"[RELECTURE FAITE] Dossier {dossier_id} introuvable — User : {request.user}")
        return redirect_error(request, "❌ Le dossier est introuvable. Contactez le support.")
    
    entry = (
        DossierRelecteur.objects
        .select_related("id_instructeur", "id_demandeur_relecture")
        .filter(id=relecteur_entry_id, id_dossier=dossier)
        .first()
    )
    if not entry:
        logger.error(f"[DOSSIER {dossier.numero}] Relecture faite par {request.user} - Entrée DossierRelecteur id={relecteur_entry_id} introuvable — User={request.user}")
        return redirect_error(request, "❌ La demande de relecture est introuvable. Contactez le support.")
    
    instructeur = Instructeur.objects.filter(email=request.user.email).first()
    if not instructeur:
        logger.warning(f"[DOSSIER {dossier.numero}] User={request.user} a tenté de valider une relecture sans profil instructeur.")
        return redirect_error(request, "❌ Vous n’avez pas de profil 'Instructeur'. Contactez le support.")
    
    if request.user.email == entry.id_instructeur.email:
        if entry.relu:
            request.session["relecteur_message"] = "Cette relecture a déjà été validée."
            return redirect(reverse("instruction_dossier", kwargs={"num_dossier": dossier.numero}))

        try:
            entry.relu = True
            entry.reponse_relecture = reponse_demande
            entry.save()

            # Dossier Action
            nom_prenom = str(instructeur)
            safe_enregistrer_action(dossier, instructeur, "Relecture", request, description = nom_prenom)

        except Exception as e:
            logger.exception(f"[DOSSIER {dossier.numero}] Erreur lors de la validation de la relecture (entry={entry.id}) par {request.user} : {e}")
            request.session["relecteur_message"] = ("Une erreur est survenue lors de la validation de la relecture. Contactez le support.")
            return redirect(reverse("instruction_dossier", kwargs={"num_dossier": dossier.numero}))


        # NOTIFICATION PAR MAIL AU DEMANDEUR DE LA RELECTURE
        demandeur_relecture = entry.id_demandeur_relecture
        if demandeur_relecture and demandeur_relecture.email:
            if NOTIFS_PROD:
                emails_norm = [demandeur_relecture.email]
            else:
                emails_norm = [EMAIL_NOTIF_TEST]

            sujet = f"Dossier {dossier.numero} - Relecture effectuée"
            template_name = "relecture_faite"
            context = {
                "dossier_numero": dossier.numero,
                "demarche_type": dossier.id_demarche.type,
                "relecteur": nom_prenom,
                "reponse_relecture": reponse_demande,
                "url": f"{os.getenv('URL_APPLI')}instruction/{dossier.numero}/",
            }

            try:
                dedupe = compute_dedupe_key(emails_norm, sujet, template_name, context)
                outbox = create_EmailOutbox(
                    emails_norm,
                    sujet,
                    template_name,
                    dedupe,
                    context,
                    dossier,
                    type_mail="Notification",
                )
                if not outbox:
                    raise RuntimeError("La création de l'EmailOutbox a échoué.")

                ok, err = envoi_mail(outbox.id)
                if ok:
                    logger.info(
                        f"[DOSSIER {dossier.numero}] Notification Email {outbox.id} "
                        f"(Relecture faite) envoyée à {', '.join(outbox.to)}"
                    )
                else:
                    raise RuntimeError(err)
            except Exception as e:
                logger.exception(
                    f"[DOSSIER {dossier.numero}] La personne à l'origine de la demande de relecture "
                    f"({demandeur_relecture}) n'a pas pu être notifiée : {e}"
                )
                request.session["relecteur_message"] = (
                    "La relecture est enregistrée, mais son demandeur n’a pas pu être notifié par email. "
                    "Contactez le support."
                )
        else:
            logger.warning(
                f"[DOSSIER {dossier.numero}] Relecture faite sans notification : "
                f"aucun demandeur enregistré pour la demande de relecture {entry.id}."
            )
    else:
        request.session["relecteur_message"] = ("Vous n’êtes pas autorisé.e à valider cette relecture.")

    return redirect(reverse("instruction_dossier", kwargs={"num_dossier": dossier.numero}))



@require_POST
@login_required
def retirer_relecteur(request):

    drj_id = request.POST.get("dossier_relecture_id")

    drj = DossierRelecteur.objects.filter(id=drj_id).select_related("id_dossier", "id_instructeur").first()
    if not drj:
        logger.error(f"[RETIRER RELECTEUR] DossierRelecteur id={drj_id} introuvable — User : {request.user}")
        return redirect_error(request, "❌ La demande de relecture est introuvable en base. Contactez le support.")

    dossier = drj.id_dossier

    # Vérification Instructeur
    instructeur = Instructeur.objects.filter(email=request.user.email).first()
    if not instructeur:
        logger.warning(f"[DOSSIER {dossier.numero}] Le user {request.user} tente de retirer un relecteur sans profil instructeur.")
        return redirect_error(request, "❌ Vous n’avez pas de profil 'Instructeur'. Contactez le support.")
    
    # Vérification autorisation à supprimer
    instructeurs_du_dossier = DossierInstructeur.objects.filter(
        id_dossier=dossier
    ).values_list("id_instructeur_id", flat=True)

    # Relecteur lui meme ou bien un des instructeurs du dossier
    if instructeur.id != drj.id_instructeur.id and instructeur.id not in instructeurs_du_dossier and not request.user.is_superuser :
        logger.warning(f"[DOSSIER {dossier.numero}] Retrait refusé : {request.user} n'est pas autorisé à retirer le relecteur {drj.id_instructeur.id}.")
        request.session["relecteur_message"] = "Vous n’êtes pas autorisé.e à retirer ce.ette relecteur.rice."
        return redirect(reverse("instruction_dossier", kwargs={"num_dossier": dossier.numero}))
    
    # Suppression
    try :
        drj.delete()
    except :
        request.session["relecteur_message"] = ("Le relecteur n'as pas pu être retiré du dossier. Contactez le support.")
    
    return redirect(reverse("instruction_dossier", kwargs={"num_dossier": dossier.numero}))

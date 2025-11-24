import logging

from django.contrib.auth.models import Group
from django.shortcuts import redirect
from autorisations.models.models_documents import DossierDocument
from autorisations.models.models_instruction import Dossier
from django.contrib import messages

from autorisations.models.models_utilisateurs import Instructeur

logger = logging.getLogger("ORM_DJANGO")



def get_instructeur_or_redirect(request, numero_dossier, action):
    instructeur = Instructeur.objects.filter(email=request.user.email).first()
    if not instructeur:
        logger.warning(f"[DOSSIER {numero_dossier}] Tentative d'action ({action}) du User {request.user} sans profil Instructeur.")
        messages.error(request, "Vous devez disposer d’un profil Instructeur. Contactez le support.")
        return None, redirect(request.META.get("HTTP_REFERER", "/"))
    return instructeur, None


def _get_group_instructeurs(group_name: str):
    group = Group.objects.filter(name=group_name).first()
    if not group:
        return Instructeur.objects.none()

    emails = [u.email for u in group.user_set.all() if u.email]
    return Instructeur.objects.filter(email__in=emails).select_related("id_agent_autorisations")


def _merge_without_duplicates(primary, extra):
    """Fusionne deux listes/Querysets d'instructeurs sans doublon."""
    primary_ids = {i.id for i in primary}
    return list(primary) + [i for i in extra if i.id not in primary_ids]


def _add_intermediaire_CA_if_needed(documents_du_dossier, base_list, intermediaires_CA):
    """Ajoute les intermédiaires CA si une délibération CA est présente dans les documents."""
    
    # Parcourir les DossierDocument
    for dd in documents_du_dossier:
        doc = dd.id_document
        if doc.id_nature.nature.lower() == "déliberation ca":
            for inter in intermediaires_CA:
                if inter not in base_list:
                    base_list.append(inter)
    return base_list




def build_roles_for_dossier(dossier):
    """Construit tous les rôles (intermédiaires, envoyeurs, publieurs, validants...)"""

    # Instructeurs du dossier
    instructeurs_du_dossier = Instructeur.objects.filter(dossierinstructeur__id_dossier=dossier).select_related("id_agent_autorisations")

    # DossierDocument du Dossier
    documents_du_dossier = DossierDocument.objects.filter(
        id_dossier=dossier
    ).select_related("id_document__id_nature", "id_document__id_statut")


    # --- INTERMEDIAIRE CA ---
    intermediaires_CA = _get_group_instructeurs("Intermédiaire CA")

    # --- POUR SIGNATURE SAADD / SPPN ---
    inter_saadd = _get_group_instructeurs("Envoi pour signature SAADD")
    inter_sppn = _get_group_instructeurs("Envoi pour signature SPPN")

    inter_saadd_fusion = _merge_without_duplicates(inter_saadd, instructeurs_du_dossier)
    inter_sppn_fusion = _merge_without_duplicates(inter_sppn, instructeurs_du_dossier)

    # Ajouter intermédiaire CA si délibération CA
    inter_saadd_fusion = _add_intermediaire_CA_if_needed(documents_du_dossier, inter_saadd_fusion, intermediaires_CA)
    inter_sppn_fusion = _add_intermediaire_CA_if_needed(documents_du_dossier, inter_sppn_fusion, intermediaires_CA)

    # --- INTERMEDIAIRES DU DOSSIER ---
    intermediaires_signature_du_dossier = Instructeur.objects.filter(dossierintermediairesignature__id_dossier=dossier).select_related("id_agent_autorisations")

    # --- ENVOYEURS D'ACTE ---
    envoyeurs_dossier = Instructeur.objects.filter(dossierenvoiacte__id_dossier=dossier).select_related("id_agent_autorisations")

    env_saadd = _get_group_instructeurs("Envoi de l'acte SAADD")
    env_sppn = _get_group_instructeurs("Envoi de l'acte SPPN")

    env_saadd_fusion = _merge_without_duplicates(env_saadd, instructeurs_du_dossier)
    env_sppn_fusion = _merge_without_duplicates(env_sppn, instructeurs_du_dossier)

    env_saadd_fusion = _add_intermediaire_CA_if_needed(documents_du_dossier, env_saadd_fusion, intermediaires_CA)
    env_sppn_fusion = _add_intermediaire_CA_if_needed(documents_du_dossier, env_sppn_fusion, intermediaires_CA)

    # --- PUBLIEURS RAA ---
    publieurs_dossier = Instructeur.objects.filter(dossierpublicationraa__id_dossier=dossier).select_related("id_agent_autorisations")

    publieur_saadd = _get_group_instructeurs("Publication RAA SAADD")
    publieur_sppn = _get_group_instructeurs("Publication RAA SPPN")

    publ_saadd_fusion = _merge_without_duplicates(publieur_saadd, instructeurs_du_dossier)
    publ_sppn_fusion = _merge_without_duplicates(publieur_sppn, instructeurs_du_dossier)

    publ_saadd_fusion = _add_intermediaire_CA_if_needed(documents_du_dossier, publ_saadd_fusion, intermediaires_CA)
    publ_sppn_fusion = _add_intermediaire_CA_if_needed(documents_du_dossier, publ_sppn_fusion, intermediaires_CA)

    # --- VALIDANTS ---
    val_saadd = _get_group_instructeurs("Validant-e SAADD")
    val_sppn = _get_group_instructeurs("Validant-e SPPN")

    validants_dossier = Instructeur.objects.filter(dossiervalideur__id_dossier=dossier).select_related("id_agent_autorisations")

    # --- RELECTEURS ---
    if "mission scientifique" in dossier.id_demarche.type.lower():
        relecteurs_group = _get_group_instructeurs("Relecteur-rice qualité SPPN")
    else:
        relecteurs_group = _get_group_instructeurs("Relecteur-rice qualité SAADD")

    relecteurs_dossier = Instructeur.objects.filter(dossierrelecteurqualite__id_dossier=dossier).select_related("id_agent_autorisations")

    # Fusion dossier + instructeurs du groupe
    relecteurs_fusion = _merge_without_duplicates(relecteurs_group, instructeurs_du_dossier)

    # --- Signataires ---
    signataires_group = _get_group_instructeurs("Signataire")

    return {
        "intermediaires_CA": intermediaires_CA,
        "intermediaires_dir_saadd": inter_saadd,
        "intermediaires_dir_sppn": inter_sppn,
        "intermediaires_dir_saadd_et_instructeurs": inter_saadd_fusion,
        "intermediaires_dir_sppn_et_instructeurs": inter_sppn_fusion,
        "intermediaires_signature_du_dossier": intermediaires_signature_du_dossier,

        "envoyeurs_actes_du_dossier": envoyeurs_dossier,
        "envoyeurs_acte_saadd": env_saadd,
        "envoyeurs_acte_sppn": env_sppn,
        "envoyeurs_saadd_et_instructeurs": env_saadd_fusion,
        "envoyeurs_sppn_et_instructeurs": env_sppn_fusion,

        "publieurs_RAA_du_dossier": publieurs_dossier,
        "publieurs_RAA_saadd": publieur_saadd,
        "publieurs_RAA_sppn": publieur_sppn,
        "publieurs_RAA_saadd_et_instructeurs": publ_saadd_fusion,
        "publieurs_RAA_sppn_et_instructeurs": publ_sppn_fusion,

        "validants_SAADD": val_saadd,
        "validants_SPPN": val_sppn,
        "validants": validants_dossier,

        "relecteurs_qualite": relecteurs_group,
        "relecteurs_qualite_du_dossier": relecteurs_dossier,
        "relecteurs_qualite_et_instructeurs": relecteurs_fusion,

        "signataires": signataires_group,
    }
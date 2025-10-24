from django import template

from autorisations.models.models_avis import DossierAvis

from autorisations.models.models_utilisateurs import DossierInstructeur, DossierRelecteur, DossierRelecteurQualite, DossierSignataire, DossierValideur, GroupeinstructeurDemarche, GroupeinstructeurInstructeur, Instructeur
from django.db.models import Q


register = template.Library()

@register.filter(name='has_group')
def has_group(user, group_name):
    """ Vérifie si un utilisateur appartient à un groupe spécifique """
    return user.groups.filter(name=group_name).exists()


@register.filter(name='has_any_group')
def has_any_group(user, group_names):
    """Vérifie si l'utilisateur appartient à l'un des groupes fournis (séparés par des virgules)."""
    group_list = [name.strip() for name in group_names.split(',')]
    return user.groups.filter(name__in=group_list).exists()



@register.filter(name="est_concerné_par_le_dossier")
def est_concerne_par_le_dossier(user, dossier):
    """
    Retourne True si l'utilisateur est concerné par le dossier :
    - superuser
    - instructeur du dossier
    - membre d’un groupe instructeur de la démarche
    - valideur
    - relecteur (juridique ou qualité)
    - signataire
    """

    # 1️⃣ utilisateur non connecté → non concerné
    if not user.is_authenticated:
        return False

    # 2️⃣ superuser → toujours concerné
    if user.is_superuser:
        return True

    # 3️⃣ recherche d’un Instructeur par email exact (champ email du modèle Instructeur)
    instructeur = Instructeur.objects.filter(email__iexact=user.email).first()
    if not instructeur:
        return False  # aucun instructeur lié à cet utilisateur

    # 4️⃣ Vérifie tous les liens directs avec le dossier
    if (
        DossierInstructeur.objects.filter(id_dossier=dossier, id_instructeur=instructeur).exists()
        or DossierValideur.objects.filter(id_dossier=dossier, id_instructeur=instructeur).exists()
        or DossierRelecteur.objects.filter(id_dossier=dossier, id_instructeur=instructeur).exists()
        or DossierRelecteurQualite.objects.filter(id_dossier=dossier, id_instructeur=instructeur).exists()
        or DossierSignataire.objects.filter(id_dossier=dossier, id_instructeur=instructeur).exists()
    ):
        return True

    # 5️⃣ Vérifie si l’instructeur appartient à un groupe lié à la démarche du dossier
    if getattr(dossier, "id_demarche", None):
        groupes_ids = GroupeinstructeurDemarche.objects.filter(
            id_demarche=dossier.id_demarche
        ).values_list("id_groupeinstructeur_id", flat=True)

        if GroupeinstructeurInstructeur.objects.filter(
            id_instructeur=instructeur,
            id_groupeinstructeur_id__in=groupes_ids,
        ).exists():
            return True

    # 6️⃣ sinon → non concerné
    return False

@register.filter(name="est_concerné_par_le_dossier_sans_les_admins")
def est_concerne_par_le_dossier_sans_les_admins(user, dossier):
    """
    Retourne True si l'utilisateur est concerné par le dossier :
    - instructeur du dossier
    - membre d’un groupe instructeur de la démarche
    - valideur
    - relecteur (juridique ou qualité)
    - signataire
    """

    # utilisateur non connecté → non concerné
    if not user.is_authenticated:
        return False

    # recherche d’un Instructeur par email exact (champ email du modèle Instructeur)
    instructeur = Instructeur.objects.filter(email__iexact=user.email).first()
    if not instructeur:
        return False  # aucun instructeur lié à cet utilisateur

    # Vérifie tous les liens directs avec le dossier
    if (
        DossierInstructeur.objects.filter(id_dossier=dossier, id_instructeur=instructeur).exists()
        or DossierValideur.objects.filter(id_dossier=dossier, id_instructeur=instructeur).exists()
        # or DossierRelecteur.objects.filter(id_dossier=dossier, id_instructeur=instructeur).exists()
        or DossierRelecteurQualite.objects.filter(id_dossier=dossier, id_instructeur=instructeur).exists()
        # or DossierSignataire.objects.filter(id_dossier=dossier, id_instructeur=instructeur).exists()
    ):
        return True

    # Vérifie si l’instructeur appartient à un groupe lié à la démarche du dossier
    if getattr(dossier, "id_demarche", None):
        groupes_ids = GroupeinstructeurDemarche.objects.filter(
            id_demarche=dossier.id_demarche
        ).values_list("id_groupeinstructeur_id", flat=True)

        if GroupeinstructeurInstructeur.objects.filter(
            id_instructeur=instructeur,
            id_groupeinstructeur_id__in=groupes_ids,
        ).exists():
            return True

    # sinon → non concerné
    return False


@register.filter(name="est_concerne_par_avis")
def est_concerne_par_demande_avis(user, avis):
    """
    Retourne True si l'utilisateur est concerné par un avis :
    - superuser
    - instructeur de l'avis (avis.id_instructeur)
    - instructeur, valideur ou relecteur qualité sur les dossiers liés à l'avis
    """

    # 1️⃣ utilisateur non connecté → non concerné
    if not user.is_authenticated:
        return False

    # 2️⃣ superuser → toujours concerné
    if user.is_superuser:
        return True

    # 3️⃣ recherche d’un Instructeur correspondant à l’utilisateur
    instructeur = Instructeur.objects.filter(email__iexact=user.email).first()
    if not instructeur:
        return False

    # 4️⃣ instructeur de l'avis → concerné
    if avis.id_instructeur_id == instructeur.id:
        return True

    # 5️⃣ récupère tous les dossiers liés à cet avis via DossierAvis
    dossier_ids = (
        DossierAvis.objects
        .filter(id_avis=avis)
        .values_list("id_demande__id_dossier_id", flat=True)
    )

    if not dossier_ids:
        return False

    # 6️⃣ instructeur, valideur ou relecteur qualité d’un dossier lié → concerné
    if (
        DossierInstructeur.objects.filter(id_dossier_id__in=dossier_ids, id_instructeur=instructeur).exists()
        or DossierValideur.objects.filter(id_dossier_id__in=dossier_ids, id_instructeur=instructeur).exists()
        or DossierRelecteurQualite.objects.filter(id_dossier_id__in=dossier_ids, id_instructeur=instructeur).exists()
    ):
        return True

    # 7️⃣ sinon → non concerné
    return False

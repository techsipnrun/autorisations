from django import template

from autorisations.models.models_avis import DossierAvis

from autorisations.models.models_utilisateurs import ContactExterne, DossierEnvoiActe, DossierInstructeur, DossierIntermediaireSignature, DossierPublicationRAA, DossierRelecteur, DossierRelecteurQualite, DossierSignataire, DossierValideur, GroupeinstructeurDemarche, GroupeinstructeurInstructeur, Instructeur
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
    - membre du groupe instructeur du dossier
    - valideur
    - intermédiaire signature
    - publieur RAA
    - envoyeur acte
    - relecteur
    - relecteur qualité
    - signataire
    """

    # 1 utilisateur non connecté → non concerné
    if not user.is_authenticated:
        return False

    # 2 superuser → toujours concerné
    if user.is_superuser:
        return True

    # 3 recherche d’un Instructeur par email exact (champ email du modèle Instructeur)
    instructeur = Instructeur.objects.filter(email__iexact=user.email).first()
    if not instructeur:
        return False  # aucun instructeur lié à cet utilisateur

    # 4 Vérifie tous les liens directs avec le dossier
    if (
        DossierInstructeur.objects.filter(id_dossier=dossier, id_instructeur=instructeur).exists()
        or DossierValideur.objects.filter(id_dossier=dossier, id_instructeur=instructeur).exists()
        or DossierRelecteur.objects.filter(id_dossier=dossier, id_instructeur=instructeur).exists()
        or DossierRelecteurQualite.objects.filter(id_dossier=dossier, id_instructeur=instructeur).exists()
        or DossierSignataire.objects.filter(id_dossier=dossier, id_instructeur=instructeur).exists()
        or DossierPublicationRAA.objects.filter(id_dossier=dossier, id_instructeur=instructeur).exists()
        or DossierEnvoiActe.objects.filter(id_dossier=dossier, id_instructeur=instructeur).exists()
        or DossierIntermediaireSignature.objects.filter(id_dossier=dossier, id_instructeur=instructeur).exists()
    ):
        return True
    

    # 5 Vérifie si l’instructeur appartient au groupe instructeur du dossier
    if ( dossier.id_groupeinstructeur and GroupeinstructeurInstructeur.objects
        .filter(id_instructeur=instructeur,id_groupeinstructeur=dossier.id_groupeinstructeur).exists()):
         return True
    
    # 6 Ajoute les receptionneurs selon le service SAADD ou SPPN
    if "Mission scientifique" in dossier.id_demarche.type :
        if user.groups.filter(name="Réception SPPN").exists():
            return True
    else :
        if user.groups.filter(name="Réception SAADD").exists():
            return True


    # 7 sinon → non concerné

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
    
    # 2️⃣bis membre du groupe Publication RAA Avis CS → concerné
    if user.groups.filter(name="Publication RAA Avis CS").exists():
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


@register.filter(name="afficher_user")
def user_display(user):
    """
    Retourne la représentation textuelle la plus pertinente pour un user :
    - Instructeur associé → str(Instructeur)
    - ContactExterne associé → str(ContactExterne)
    - Sinon → user.email
    """

    if not user or not user.email:
        return ""

    email = user.email.strip().lower()

    # 1. Essayer de trouver un instructeur
    instructeur = Instructeur.objects.filter(email__iexact=email).first()
    if instructeur:
        return str(instructeur)

    # 2. Essayer de trouver un contact externe
    contact = ContactExterne.objects.filter(email__iexact=email).first()
    if contact:
        return str(contact)

    # 3. Default → user.email
    return user.email
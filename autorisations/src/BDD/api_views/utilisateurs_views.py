from rest_framework import viewsets
from autorisations.models.models_utilisateurs import (
    AgentAutorisations, AgentAutorisationsUpdateLog, TypeContactExterne, ContactExterne,
    DossierInterlocuteur, DossierBeneficiaire, Instructeur, Groupeinstructeur,
    GroupeinstructeurDemarche, GroupeinstructeurInstructeur, DossierInstructeur
)
from ..api_serializers.utilisateurs_serializers import (
    AgentAutorisationsSerializer, TypeContactExterneSerializer,
    ContactExterneSerializer, DossierInterlocuteurSerializer, DossierBeneficiaireSerializer,
    InstructeurSerializer, GroupeinstructeurSerializer, GroupeinstructeurDemarcheSerializer,
    GroupeinstructeurInstructeurSerializer, DossierInstructeurSerializer
)
from drf_yasg.utils import swagger_auto_schema
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import DjangoModelPermissions


@swagger_auto_schema(tags=["Utilisateurs"])
class AgentAutorisationsViewSet(viewsets.ModelViewSet):
    """
    retrieve:
    Retourne un agent d'autorisations via son ID.

    list:
    Retourne la liste de tous les agents d'autorisations.

    create:
    Crée un nouvel agent d'autorisations.

    update:
    Met à jour un agent d'autorisations existant (remplacement total).

    partial_update:
    Met à jour partiellement un agent d'autorisations.

    delete:
    Supprime un agent d'autorisations.
    """
    queryset = AgentAutorisations.objects.all()
    serializer_class = AgentAutorisationsSerializer
    permission_classes = [DjangoModelPermissions]
    authentication_classes = [TokenAuthentication]



@swagger_auto_schema(tags=["Utilisateurs"])
class TypeContactExterneViewSet(viewsets.ModelViewSet):
    """
    retrieve:
    Retourne un type de contact externe via son ID.

    list:
    Retourne la liste de tous les types de contacts externes.

    create:
    Crée un nouveau type de contact externe.

    update:
    Met à jour un type de contact externe existant (remplacement total).

    partial_update:
    Met à jour partiellement un type de contact externe.

    delete:
    Supprime un type de contact externe.
    """
    queryset = TypeContactExterne.objects.all()
    serializer_class = TypeContactExterneSerializer
    permission_classes = [DjangoModelPermissions]
    authentication_classes = [TokenAuthentication]


@swagger_auto_schema(tags=["Utilisateurs"])
class ContactExterneViewSet(viewsets.ModelViewSet):
    """
    retrieve:
    Retourne un contact externe via son ID.

    list:
    Retourne la liste de tous les contacts externes.

    create:
    Crée un nouveau contact externe.

    update:
    Met à jour un contact externe existant (remplacement total).

    partial_update:
    Met à jour partiellement un contact externe.

    delete:
    Supprime un contact externe.
    """
    queryset = ContactExterne.objects.all()
    serializer_class = ContactExterneSerializer
    permission_classes = [DjangoModelPermissions]
    authentication_classes = [TokenAuthentication]


@swagger_auto_schema(tags=["Utilisateurs"])
class DossierInterlocuteurViewSet(viewsets.ModelViewSet):
    """
    retrieve:
    Retourne un interlocuteur de dossier via son ID.

    list:
    Retourne la liste de tous les interlocuteurs des demandes.

    create:
    Crée un nouvel interlocuteur de dossier.

    update:
    Met à jour un interlocuteur de dossier existant (remplacement total).

    partial_update:
    Met à jour partiellement un interlocuteur de dossier.

    delete:
    Supprime un interlocuteur de demande.
    """
    queryset = DossierInterlocuteur.objects.all()
    serializer_class = DossierInterlocuteurSerializer
    permission_classes = [DjangoModelPermissions]
    authentication_classes = [TokenAuthentication]


@swagger_auto_schema(tags=["Utilisateurs"])
class DossierBeneficiaireViewSet(viewsets.ModelViewSet):
    """
    retrieve:
    Retourne un bénéficiaire de demande via son ID.

    list:
    Retourne la liste de tous les bénéficiaires des demandes.

    create:
    Crée un nouveau bénéficiaire de demande.

    update:
    Met à jour un bénéficiaire de demande existant (remplacement total).

    partial_update:
    Met à jour partiellement un bénéficiaire de demande.

    delete:
    Supprime un bénéficiaire de demande.
    """
    queryset = DossierBeneficiaire.objects.all()
    serializer_class = DossierBeneficiaireSerializer
    permission_classes = [DjangoModelPermissions]
    authentication_classes = [TokenAuthentication]


@swagger_auto_schema(tags=["Utilisateurs"])
class InstructeurViewSet(viewsets.ModelViewSet):
    """
    retrieve:
    Retourne un instructeur via son ID.

    list:
    Retourne la liste de tous les instructeurs.

    create:
    Crée un nouvel instructeur.

    update:
    Met à jour un instructeur existant (remplacement total).

    partial_update:
    Met à jour partiellement un instructeur.

    delete:
    Supprime un instructeur.
    """
    queryset = Instructeur.objects.all()
    serializer_class = InstructeurSerializer
    permission_classes = [DjangoModelPermissions]
    authentication_classes = [TokenAuthentication]


@swagger_auto_schema(tags=["Utilisateurs"])
class GroupeinstructeurViewSet(viewsets.ModelViewSet):
    """
    retrieve:
    Retourne un groupe d'instructeurs via son ID.

    list:
    Retourne la liste de tous les groupes d'instructeurs.

    create:
    Crée un nouveau groupe d'instructeurs.

    update:
    Met à jour un groupe d'instructeurs existant (remplacement total).

    partial_update:
    Met à jour partiellement un groupe d'instructeurs.

    delete:
    Supprime un groupe d'instructeurs.
    """
    queryset = Groupeinstructeur.objects.all()
    serializer_class = GroupeinstructeurSerializer
    permission_classes = [DjangoModelPermissions]
    authentication_classes = [TokenAuthentication]


@swagger_auto_schema(tags=["Utilisateurs"])
class GroupeinstructeurDemarcheViewSet(viewsets.ModelViewSet):
    """
    retrieve:
    Retourne l'association entre un groupe d'instructeurs et une démarche via son ID.

    list:
    Retourne la liste de toutes les associations entre groupes d'instructeurs et démarches.

    create:
    Associe un groupe d'instructeurs à une démarche.

    update:
    Met à jour une association existante (remplacement total).

    partial_update:
    Met à jour partiellement une association.

    delete:
    Supprime une association entre un groupe et une démarche.
    """
    queryset = GroupeinstructeurDemarche.objects.all()
    serializer_class = GroupeinstructeurDemarcheSerializer
    permission_classes = [DjangoModelPermissions]
    authentication_classes = [TokenAuthentication]


@swagger_auto_schema(tags=["Utilisateurs"])
class GroupeinstructeurInstructeurViewSet(viewsets.ModelViewSet):
    """
    retrieve:
    Retourne l'association entre un groupe d'instructeurs et un instructeur via son ID.

    list:
    Retourne la liste de toutes les associations entre groupes d'instructeurs et instructeurs.

    create:
    Associe un instructeur à un groupe d'instructeurs.

    update:
    Met à jour une association existante (remplacement total).

    partial_update:
    Met à jour partiellement une association.

    delete:
    Supprime une association entre un groupe d'instructeurs et un instructeur.
    """
    queryset = GroupeinstructeurInstructeur.objects.all()
    serializer_class = GroupeinstructeurInstructeurSerializer
    permission_classes = [DjangoModelPermissions]
    authentication_classes = [TokenAuthentication]


@swagger_auto_schema(tags=["Utilisateurs"])
class DossierInstructeurViewSet(viewsets.ModelViewSet):
    """
    retrieve:
    Retourne l'association entre un dossier et un instructeur via son ID.

    list:
    Retourne la liste de toutes les associations entre dossiers et instructeurs.

    create:
    Associe un instructeur à un dossier.

    update:
    Met à jour une association existante (remplacement total).

    partial_update:
    Met à jour partiellement une association.

    delete:
    Supprime une association entre un dossier et un instructeur.
    """
    queryset = DossierInstructeur.objects.all()
    serializer_class = DossierInstructeurSerializer
    permission_classes = [DjangoModelPermissions]
    authentication_classes = [TokenAuthentication]

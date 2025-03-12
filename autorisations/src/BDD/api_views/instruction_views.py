from rest_framework import viewsets
from autorisations.models.models_instruction import (
    ChampType, EtatDemande, EtatDemarche, EtatDossier, Priorite, DemandeType, Groupe,
    Demarche, DossierType, Dossier, Demande, Champ, DemandeChamp, Message, DossierGroupe
)
from ..api_serializers.instruction_serializers import (
    ChampTypeSerializer, EtatDemandeSerializer, EtatDemarcheSerializer, EtatDossierSerializer,
    PrioriteSerializer, DemandeTypeSerializer, GroupeSerializer, DemarcheSerializer,
    DossierTypeSerializer, DossierSerializer, DemandeSerializer, ChampSerializer,
    DemandeChampSerializer, MessageSerializer, DossierGroupeSerializer
)
from drf_yasg.utils import swagger_auto_schema


@swagger_auto_schema(tags=["Instruction"])
class ChampTypeViewSet(viewsets.ModelViewSet):
    """
    retrieve:
    Retourne un type de champ via son ID.

    list:
    Retourne la liste de tous les types de champs.

    create:
    Crée un nouveau type de champ.

    update:
    Met à jour un type de champ existant.

    partial_update:
    Met à jour partiellement un type de champ.

    delete:
    Supprime un type de champ.
    """
    queryset = ChampType.objects.all()
    serializer_class = ChampTypeSerializer


@swagger_auto_schema(tags=["Instruction"])
class EtatDemandeViewSet(viewsets.ModelViewSet):
    """
    retrieve:
    Retourne un état de demande via son ID.

    list:
    Retourne la liste de tous les états de demande.

    create:
    Crée un nouvel état de demande.

    update:
    Met à jour un état de demande existant.

    partial_update:
    Met à jour partiellement un état de demande.

    delete:
    Supprime un état de demande.
    """
    queryset = EtatDemande.objects.all()
    serializer_class = EtatDemandeSerializer


@swagger_auto_schema(tags=["Instruction"])
class DemandeViewSet(viewsets.ModelViewSet):
    """
    retrieve:
    Retourne une demande via son ID.

    list:
    Retourne la liste de toutes les demandes.

    create:
    Crée une nouvelle demande.

    update:
    Met à jour une demande existante.

    partial_update:
    Met à jour partiellement une demande.

    delete:
    Supprime une demande.
    """
    queryset = Demande.objects.all()
    serializer_class = DemandeSerializer


@swagger_auto_schema(tags=["Instruction"])
class MessageViewSet(viewsets.ModelViewSet):
    """
    retrieve:
    Retourne un message via son ID.

    list:
    Retourne la liste de tous les messages.

    create:
    Crée un nouveau message.

    update:
    Met à jour un message existant.

    partial_update:
    Met à jour partiellement un message.

    delete:
    Supprime un message.
    """
    queryset = Message.objects.all()
    serializer_class = MessageSerializer


@swagger_auto_schema(tags=["Instruction"])
class EtatDemarcheViewSet(viewsets.ModelViewSet):
    """
    retrieve:
    Retourne un état de démarche via son ID.

    list:
    Retourne la liste de tous les états de démarche.

    create:
    Crée un nouvel état de démarche.

    update:
    Met à jour un état de démarche existant.

    partial_update:
    Met à jour partiellement un état de démarche.

    delete:
    Supprime un état de démarche.
    """
    queryset = EtatDemarche.objects.all()
    serializer_class = EtatDemarcheSerializer


@swagger_auto_schema(tags=["Instruction"])
class EtatDossierViewSet(viewsets.ModelViewSet):
    """
    retrieve:
    Retourne un état de dossier via son ID.

    list:
    Retourne la liste de tous les états de dossier.

    create:
    Crée un nouvel état de dossier.

    update:
    Met à jour un état de dossier existant.

    partial_update:
    Met à jour partiellement un état de dossier.

    delete:
    Supprime un état de dossier.
    """
    queryset = EtatDossier.objects.all()
    serializer_class = EtatDossierSerializer


@swagger_auto_schema(tags=["Instruction"])
class PrioriteViewSet(viewsets.ModelViewSet):
    """
    retrieve:
    Retourne une priorité via son ID.

    list:
    Retourne la liste de toutes les priorités.

    create:
    Crée une nouvelle priorité.

    update:
    Met à jour une priorité existante.

    partial_update:
    Met à jour partiellement une priorité.

    delete:
    Supprime une priorité.
    """
    queryset = Priorite.objects.all()
    serializer_class = PrioriteSerializer


@swagger_auto_schema(tags=["Instruction"])
class DemandeTypeViewSet(viewsets.ModelViewSet):
    """
    retrieve:
    Retourne un type de demande via son ID.

    list:
    Retourne la liste de tous les types de demande.

    create:
    Crée un nouveau type de demande.

    update:
    Met à jour un type de demande existant.

    partial_update:
    Met à jour partiellement un type de demande.

    delete:
    Supprime un type de demande.
    """
    queryset = DemandeType.objects.all()
    serializer_class = DemandeTypeSerializer


@swagger_auto_schema(tags=["Instruction"])
class GroupeViewSet(viewsets.ModelViewSet):
    """
    retrieve:
    Retourne un groupe (de plusieurs dossiers) via son ID.

    list:
    Retourne la liste de tous les groupes de dossiers.

    create:
    Crée un nouveau groupe (de plusieurs dossiers).

    update:
    Met à jour un groupe (de plusieurs dossiers) existant.

    partial_update:
    Met à jour partiellement un groupe (de plusieurs dossiers).

    delete:
    Supprime un groupe de dossiers.
    """
    queryset = Groupe.objects.all()
    serializer_class = GroupeSerializer


@swagger_auto_schema(tags=["Instruction"])
class DemarcheViewSet(viewsets.ModelViewSet):
    """
    retrieve:
    Retourne une démarche via son ID.

    list:
    Retourne la liste de toutes les démarches.

    create:
    Crée une nouvelle démarche.

    update:
    Met à jour une démarche existante.

    partial_update:
    Met à jour partiellement une démarche.

    delete:
    Supprime une démarche.
    """
    queryset = Demarche.objects.all()
    serializer_class = DemarcheSerializer


@swagger_auto_schema(tags=["Instruction"])
class DossierTypeViewSet(viewsets.ModelViewSet):
    """
    retrieve:
    Retourne un type de dossier via son ID.

    list:
    Retourne la liste de tous les types de dossier.

    create:
    Crée un nouveau type de dossier.

    update:
    Met à jour un type de dossier existant.

    partial_update:
    Met à jour partiellement un type de dossier.

    delete:
    Supprime un type de dossier.
    """
    queryset = DossierType.objects.all()
    serializer_class = DossierTypeSerializer


@swagger_auto_schema(tags=["Instruction"])
class DossierViewSet(viewsets.ModelViewSet):
    """
    retrieve:
    Retourne un dossier via son ID.

    list:
    Retourne la liste de tous les dossiers.

    create:
    Crée un nouveau dossier.

    update:
    Met à jour un dossier existant.

    partial_update:
    Met à jour partiellement un dossier.

    delete:
    Supprime un dossier.
    """
    queryset = Dossier.objects.all()
    serializer_class = DossierSerializer


@swagger_auto_schema(tags=["Instruction"])
class ChampViewSet(viewsets.ModelViewSet):
    """
    retrieve:
    Retourne un champ via son ID.

    list:
    Retourne la liste de tous les champs.

    create:
    Crée un nouveau champ.

    update:
    Met à jour un champ existant.

    partial_update:
    Met à jour partiellement un champ.

    delete:
    Supprime un champ.
    """
    queryset = Champ.objects.all()
    serializer_class = ChampSerializer


@swagger_auto_schema(tags=["Instruction"])
class DemandeChampViewSet(viewsets.ModelViewSet):
    """
    retrieve:
    Retourne une association entre une demande et un champ via son ID.

    list:
    Retourne la liste de toutes les associations entre demandes et champs.

    create:
    Associe une demande à un champ.

    update:
    Met à jour une association existante.

    partial_update:
    Met à jour partiellement une association.

    delete:
    Supprime une association entre une demande et un champ.
    """
    queryset = DemandeChamp.objects.all()
    serializer_class = DemandeChampSerializer


@swagger_auto_schema(tags=["Instruction"])
class DossierGroupeViewSet(viewsets.ModelViewSet):
    """
    retrieve:
    Retourne une association entre un dossier et un groupe via son ID.

    list:
    Retourne la liste de toutes les associations entre dossiers et groupes.

    create:
    Associe un dossier à un groupe.

    update:
    Met à jour une association existante.

    partial_update:
    Met à jour partiellement une association.

    delete:
    Supprime une association entre un dossier et un groupe.
    """
    queryset = DossierGroupe.objects.all()
    serializer_class = DossierGroupeSerializer

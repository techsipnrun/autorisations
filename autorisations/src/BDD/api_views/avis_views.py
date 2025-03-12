from rest_framework import viewsets, permissions
from autorisations.models.models_avis import (
    AvisNature, AvisThematique, Expert, Avis, AvisDocument, DemandeAvis
)
from BDD.permissions import PeutUtiliserMethodeAvis
from ..filters import AvisFilter
from ..api_serializers.avis_serializers import (
    AvisNatureSerializer, AvisThematiqueSerializer, ExpertSerializer,
    AvisSerializer, AvisDocumentSerializer, DemandeAvisSerializer
)
from django_filters.rest_framework import DjangoFilterBackend
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi

@swagger_auto_schema(tags=["Avis"])
class AvisNatureViewSet(viewsets.ModelViewSet):
    """
    retrieve:
    Retourne une nature d'avis via son ID.

    list:
    Retourne la liste de toutes les natures d'avis.

    create:
    Crée une nouvelle nature d'avis.

    update:
    Met à jour une nature d'avis existante (remplacement total).

    partial_update:
    Met à jour partiellement une nature d'avis.

    delete:
    Supprime une nature d'avis.
    """
    queryset = AvisNature.objects.all()
    serializer_class = AvisNatureSerializer
    permission_classes = [PeutUtiliserMethodeAvis]


@swagger_auto_schema(tags=["Avis"])
class AvisThematiqueViewSet(viewsets.ModelViewSet):
    """
    retrieve:
    Retourne une thématique d'avis via son ID.

    list:
    Retourne la liste de toutes les thématiques des avis.

    create:
    Crée une nouvelle thématique d'avis.

    update:
    Met à jour une thématique d'avis existante (remplacement total).

    partial_update:
    Met à jour partiellement une thématique d'avis.

    delete:
    Supprime une thématique d'avis.
    """
    queryset = AvisThematique.objects.all()
    serializer_class = AvisThematiqueSerializer
    permission_classes = [PeutUtiliserMethodeAvis]


@swagger_auto_schema(tags=["Avis"])
class ExpertViewSet(viewsets.ModelViewSet):
    """
    retrieve:
    Retourne un expert via son ID.

    list:
    Retourne la liste de tous les experts.

    create:
    Crée un nouvel expert.

    update:
    Met à jour un expert existant (remplacement total).

    partial_update:
    Met à jour partiellement un expert.

    delete:
    Supprime un expert.
    """
    queryset = Expert.objects.all()
    serializer_class = ExpertSerializer
    permission_classes = [PeutUtiliserMethodeAvis]


@swagger_auto_schema(tags=["Avis"])
class AvisViewSet(viewsets.ModelViewSet):
    """
    retrieve:
    Retourne un avis via son ID.

    list:
    Retourne la liste de tous les avis avec des options de filtrage.

    create:
    Crée un nouvel avis.

    update:
    Met à jour un avis existant (remplacement total).

    partial_update:
    Met à jour partiellement un avis.

    delete:
    Supprime un avis.
    """
    queryset = Avis.objects.all()
    serializer_class = AvisSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = AvisFilter  # Ajout du filtre personnalisé
    permission_classes = [PeutUtiliserMethodeAvis]

    @swagger_auto_schema(
        manual_parameters=[
            openapi.Parameter(
                'favorable', openapi.IN_QUERY, 
                description="Filtrer les avis selon qu'ils sont favorables (`true`) ou défavorables (`false`).", 
                type=openapi.TYPE_BOOLEAN
            ),
            openapi.Parameter(
                "date minimale de réponse à l'avis", openapi.IN_QUERY, 
                description="Filtrer les avis dont la date de réponse est postérieure à cette date (format `YYYY-MM-DD`).", 
                type=openapi.TYPE_STRING, format=openapi.FORMAT_DATE
            ),
            openapi.Parameter(
                "date limite de réponse à l'avis", openapi.IN_QUERY, 
                description="Filtrer les avis dont la date de réponse est antérieure à cette date (format `YYYY-MM-DD`).", 
                type=openapi.TYPE_STRING, format=openapi.FORMAT_DATE
            ),
            openapi.Parameter(
                "id de l'expert", openapi.IN_QUERY, 
                description="Filtrer les avis par l'expert ayant donné l'avis (`ID`).", 
                type=openapi.TYPE_INTEGER
            ),
        ],
        
    )
    def list(self, request, *args, **kwargs):
        """
        Retourne une liste d'avis filtrés.
        """
        return super().list(request, *args, **kwargs)
    
  
    

@swagger_auto_schema(tags=["Avis"])
class AvisDocumentViewSet(viewsets.ModelViewSet):
    """
    retrieve:
    Retourne un document d'avis via son ID.

    list:
    Retourne la liste de tous les documents liés aux avis.

    create:
    Associe un document à un avis.

    update:
    Met à jour l'association entre un document et un avis (remplacement total).

    partial_update:
    Met à jour partiellement l'association entre un document et un avis.

    delete:
    Dissocie un document d'un avis.
    """
    queryset = AvisDocument.objects.all()
    serializer_class = AvisDocumentSerializer
    permission_classes = [PeutUtiliserMethodeAvis]


@swagger_auto_schema(tags=["Avis"])
class DemandeAvisViewSet(viewsets.ModelViewSet):
    """
    retrieve:
    Retourne une association entre une demande et un avis via son ID.

    list:
    Retourne la liste des associations entre les demandes et les avis.

    create:
    Associe une demande à un avis.

    update:
    Met à jour une association entre une demande et un avis (remplacement total).

    partial_update:
    Met à jour partiellement une association entre une demande et un avis.

    delete:
    Dissocie une demande d'un avis.
    """
    queryset = DemandeAvis.objects.all()
    serializer_class = DemandeAvisSerializer
    permission_classes = [PeutUtiliserMethodeAvis]



# Ajouter la recherche textuelle (SearchFilter).


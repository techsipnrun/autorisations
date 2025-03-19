from rest_framework import viewsets
from autorisations.models.models_documents import (
    DocumentFormat, DocumentNature, Document, DossierDocument, MessageDocument
)
from ..api_serializers.documents_serializers import (
    DocumentFormatSerializer, DocumentNatureSerializer, DocumentSerializer,
    DossierDocumentSerializer, MessageDocumentSerializer
)
from drf_yasg.utils import swagger_auto_schema
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import DjangoModelPermissions


@swagger_auto_schema(tags=["Documents"])
class DocumentFormatViewSet(viewsets.ModelViewSet):
    """
    retrieve:
    Retourne un format de document via son ID.

    list:
    Retourne la liste de tous les formats de documents.

    create:
    Crée un nouveau format de document.

    update:
    Met à jour un format de document existant (remplacement total).

    partial_update:
    Met à jour partiellement un format de document.

    delete:
    Supprime un format de document.
    """
    queryset = DocumentFormat.objects.all()
    serializer_class = DocumentFormatSerializer
    permission_classes = [DjangoModelPermissions]
    authentication_classes = [TokenAuthentication]


@swagger_auto_schema(tags=["Documents"])
class DocumentNatureViewSet(viewsets.ModelViewSet):
    """
    retrieve:
    Retourne une nature de document via son ID.

    list:
    Retourne la liste de toutes les natures de documents.

    create:
    Crée une nouvelle nature de document.

    update:
    Met à jour une nature de document existante (remplacement total).

    partial_update:
    Met à jour partiellement une nature de document.

    delete:
    Supprime une nature de document.
    """
    queryset = DocumentNature.objects.all()
    serializer_class = DocumentNatureSerializer
    permission_classes = [DjangoModelPermissions]
    authentication_classes = [TokenAuthentication]


@swagger_auto_schema(tags=["Documents"])
class DocumentViewSet(viewsets.ModelViewSet):
    """
    retrieve:
    Retourne un document via son ID.

    list:
    Retourne la liste de tous les documents.

    create:
    Crée un nouveau document.

    update:
    Met à jour un document existant (remplacement total).

    partial_update:
    Met à jour partiellement un document.

    delete:
    Supprime un document.
    """
    queryset = Document.objects.all()
    serializer_class = DocumentSerializer
    permission_classes = [DjangoModelPermissions]
    authentication_classes = [TokenAuthentication]


@swagger_auto_schema(tags=["Documents"])
class DossierDocumentViewSet(viewsets.ModelViewSet):
    """
    retrieve:
    Retourne l'association entre un dossier et un document via son ID.

    list:
    Retourne la liste de toutes les associations entre dossiers et documents.

    create:
    Associe un document à un dossier.

    update:
    Met à jour l'association entre un dossier et un document.

    partial_update:
    Met à jour partiellement l'association entre un dossier et un document.

    delete:
    Dissocie un document d'un dossier.
    """
    queryset = DossierDocument.objects.all()
    serializer_class = DossierDocumentSerializer
    permission_classes = [DjangoModelPermissions]
    authentication_classes = [TokenAuthentication]


@swagger_auto_schema(tags=["Documents"])
class MessageDocumentViewSet(viewsets.ModelViewSet):
    """
    retrieve:
    Retourne l'association entre un message et un document via son ID.

    list:
    Retourne la liste de toutes les associations entre messages et documents.

    create:
    Associe un document à un message.

    update:
    Met à jour l'association entre un message et un document.

    partial_update:
    Met à jour partiellement l'association entre un message et un document.

    delete:
    Dissocie un document d'un message.
    """
    queryset = MessageDocument.objects.all()
    serializer_class = MessageDocumentSerializer
    permission_classes = [DjangoModelPermissions]
    authentication_classes = [TokenAuthentication]

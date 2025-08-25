from rest_framework import viewsets
from autorisations.models.models_documents import (
    DocumentFormat, DocumentNature, Document, DocumentStatut, DossierDocument, MessageDocument
)
from ..api_serializers.documents_serializers import (
    DocumentFormatSerializer, DocumentNatureSerializer, DocumentSerializer, DocumentStatutSerializer,
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
    Met à jour un format existant.

    partial_update:
    Met à jour partiellement un format.

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
    CRUD pour gérer les natures de documents.
    """
    queryset = DocumentNature.objects.all()
    serializer_class = DocumentNatureSerializer
    permission_classes = [DjangoModelPermissions]
    authentication_classes = [TokenAuthentication]


@swagger_auto_schema(tags=["Documents"])
class DocumentViewSet(viewsets.ModelViewSet):
    """
    CRUD pour gérer les documents.
    """
    queryset = Document.objects.all()
    serializer_class = DocumentSerializer
    permission_classes = [DjangoModelPermissions]
    authentication_classes = [TokenAuthentication]


@swagger_auto_schema(tags=["Documents"])
class DossierDocumentViewSet(viewsets.ModelViewSet):
    """
    CRUD pour gérer l’association entre dossiers et documents.
    """
    queryset = DossierDocument.objects.all()
    serializer_class = DossierDocumentSerializer
    permission_classes = [DjangoModelPermissions]
    authentication_classes = [TokenAuthentication]


@swagger_auto_schema(tags=["Documents"])
class MessageDocumentViewSet(viewsets.ModelViewSet):
    """
    CRUD pour gérer les messages liés aux documents.
    """
    queryset = MessageDocument.objects.all()
    serializer_class = MessageDocumentSerializer
    permission_classes = [DjangoModelPermissions]
    authentication_classes = [TokenAuthentication]


@swagger_auto_schema(tags=["Documents"])
class DocumentStatutViewSet(viewsets.ModelViewSet):
    """
    retrieve:
    Retourne un statut de document via son ID.

    list:
    Retourne la liste de tous les statuts de document.

    create:
    Crée un nouveau statut de document.

    update:
    Met à jour un statut de document existant (remplacement total).

    partial_update:
    Met à jour partiellement un statut de document.

    delete:
    Supprime un statut de document.
    """
    queryset = DocumentStatut.objects.all()
    serializer_class = DocumentStatutSerializer
    permission_classes = [DjangoModelPermissions]
    authentication_classes = [TokenAuthentication]

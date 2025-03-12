from rest_framework import serializers
from autorisations.models.models_documents import (
    DocumentFormat, DocumentNature, Document, DossierDocument, MessageDocument
)
from autorisations.models.models_instruction import Dossier, Message


class DocumentFormatSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentFormat
        fields = '__all__'


class DocumentNatureSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentNature
        fields = '__all__'


class DocumentSerializer(serializers.ModelSerializer):
    id_format = serializers.PrimaryKeyRelatedField(
        queryset=DocumentFormat.objects.all(),
        help_text="ID du format de document."
    )
    id_nature = serializers.PrimaryKeyRelatedField(
        queryset=DocumentNature.objects.all(),
        help_text="ID de la nature du document."
    )

    class Meta:
        model = Document
        fields = '__all__'


class DossierDocumentSerializer(serializers.ModelSerializer):
    id_dossier = serializers.PrimaryKeyRelatedField(
        queryset=Dossier.objects.all(),
        help_text="ID du dossier."
    )
    id_document = serializers.PrimaryKeyRelatedField(
        queryset=Document.objects.all(),
        help_text="ID du document."
    )

    class Meta:
        model = DossierDocument
        fields = '__all__'


class MessageDocumentSerializer(serializers.ModelSerializer):
    id_message = serializers.PrimaryKeyRelatedField(
        queryset=Message.objects.all(),
        help_text="ID du message."
    )
    id_document = serializers.PrimaryKeyRelatedField(
        queryset=Document.objects.all(),
        help_text="ID du document."
    )

    class Meta:
        model = MessageDocument
        fields = '__all__'

from rest_framework import serializers
from autorisations.models.models_avis import (
    AvisNature, AvisThematique, Expert, Avis, AvisDocument, DemandeAvis
)
from autorisations.models.models_instruction import Dossier
from autorisations.models.models_utilisateurs import Instructeur
from autorisations.models.models_documents import Document


class AvisNatureSerializer(serializers.ModelSerializer):
    class Meta:
        model = AvisNature
        fields = '__all__'


class AvisThematiqueSerializer(serializers.ModelSerializer):
    class Meta:
        model = AvisThematique
        fields = '__all__'


class ExpertSerializer(serializers.ModelSerializer):
    class Meta:
        model = Expert
        fields = '__all__'


class AvisSerializer(serializers.ModelSerializer):
    """
    Sérialiseur pour les avis.

    - `id_avis_nature`: ID de la nature de l'avis.
    - `id_avis_thematique`: ID de la thématique de l'avis.
    - `id_expert`: ID de l'expert ayant donné l'avis.
    """
    
    id_avis_nature = serializers.PrimaryKeyRelatedField(
        queryset=AvisNature.objects.all(),
        help_text="ID de la nature de l'avis."
    )
    id_avis_thematique = serializers.PrimaryKeyRelatedField(
        queryset=AvisThematique.objects.all(),
        help_text="ID de la thématique de l'avis."
    )
    id_expert = serializers.PrimaryKeyRelatedField(
        queryset=Expert.objects.all(),
        help_text="ID de l'expert ayant donné l'avis.",
    )
    id_dossier = serializers.PrimaryKeyRelatedField(
        queryset=Dossier.objects.all(),
        allow_null=True,
        help_text="ID du dossier lié à l'avis (peut être `null`).",
        required=False
    )
    id_instructeur = serializers.PrimaryKeyRelatedField(
        queryset=Instructeur.objects.all(),
        help_text="ID de l'instructeur lié à l'avis."
    )

    class Meta:
        model = Avis
        fields = '__all__'



class AvisDocumentSerializer(serializers.ModelSerializer):

    id_avis = serializers.PrimaryKeyRelatedField(
        queryset=Avis.objects.all(),
        help_text="ID de l'avis lié à ce document."
    )
    id_document = serializers.PrimaryKeyRelatedField(
        queryset=Document.objects.all(),
        help_text="ID du document associé à cet avis."
    )

    class Meta:
        model = AvisDocument
        fields = '__all__'


class DemandeAvisSerializer(serializers.ModelSerializer):
    class Meta:
        model = DemandeAvis
        fields = '__all__'

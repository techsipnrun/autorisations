from rest_framework import serializers
from autorisations.models.models_instruction import (
    ChampType, DossierChamp, EtatDemande, EtatDemarche, EtatDossier, Priorite, DemandeType, Groupe,
    Demarche, DossierType, Dossier, Demande, Champ, DemandeChamp, Message, DossierGroupe
)


class ChampTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChampType
        fields = '__all__'


class EtatDemandeSerializer(serializers.ModelSerializer):
    class Meta:
        model = EtatDemande
        fields = '__all__'


class EtatDemarcheSerializer(serializers.ModelSerializer):
    class Meta:
        model = EtatDemarche
        fields = '__all__'


class EtatDossierSerializer(serializers.ModelSerializer):
    class Meta:
        model = EtatDossier
        fields = '__all__'


class PrioriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Priorite
        fields = '__all__'


class DemandeTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = DemandeType
        fields = '__all__'


class GroupeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Groupe
        fields = '__all__'


class DemarcheSerializer(serializers.ModelSerializer):
    class Meta:
        model = Demarche
        fields = '__all__'


class DossierTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = DossierType
        fields = '__all__'


class DossierSerializer(serializers.ModelSerializer):
    id_demarche = serializers.PrimaryKeyRelatedField(
            queryset=Demarche.objects.all(),
            help_text="ID de la demarche.",
            required=True
        )
    
    class Meta:
        model = Dossier
        fields = '__all__'


class DemandeSerializer(serializers.ModelSerializer):
    id_dossier = serializers.PrimaryKeyRelatedField(
            queryset=Dossier.objects.all(),
            help_text="ID du dossier.",
            required=True
        )
    class Meta:
        model = Demande
        fields = '__all__'


class ChampSerializer(serializers.ModelSerializer):
    id_demarche = serializers.PrimaryKeyRelatedField(
            queryset=Demarche.objects.all(),
            help_text="ID de la demarche.",
            required=True
        )

    class Meta:
        model = Champ
        fields = '__all__'


class DemandeChampSerializer(serializers.ModelSerializer):
    id_demande = serializers.PrimaryKeyRelatedField(
            queryset=Demande.objects.all(),
            help_text="ID de la demande.",
            required=True
        )
    id_champ = serializers.PrimaryKeyRelatedField(
            queryset=Champ.objects.all(),
            help_text="ID du champ.",
            required=True
        )
    class Meta:
        model = DemandeChamp
        fields = '__all__'


class DossierChampSerializer(serializers.ModelSerializer):
    id_dossier = serializers.PrimaryKeyRelatedField(
            queryset=Dossier.objects.all(),
            help_text="ID du dossier.",
            required=True
        )
    id_champ = serializers.PrimaryKeyRelatedField(
            queryset=Champ.objects.all(),
            help_text="ID du champ.",
            required=True
        )
    class Meta:
        model = DossierChamp
        fields = '__all__'



class MessageSerializer(serializers.ModelSerializer):
    id_dossier = serializers.PrimaryKeyRelatedField(
            queryset=Dossier.objects.all(),
            help_text="ID du dossier.",
            required=True
        )
    
    class Meta:
        model = Message
        fields = '__all__'


class DossierGroupeSerializer(serializers.ModelSerializer):
    class Meta:
        model = DossierGroupe
        fields = '__all__'

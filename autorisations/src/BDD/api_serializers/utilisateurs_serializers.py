from rest_framework import serializers
from autorisations.models.models_utilisateurs import (
    AgentAutorisations, TypeContactExterne, ContactExterne,
    DemandeInterlocuteur, DemandeBeneficiaire, Instructeur, Groupeinstructeur,
    GroupeinstructeurDemarche, GroupeinstructeurInstructeur, DossierInstructeur
)
from autorisations.models.models_instruction import Demande


class AgentAutorisationsSerializer(serializers.ModelSerializer):  # rendre seulement le GET accesible, Interdit de modifier
    class Meta:
        model = AgentAutorisations
        fields = '__all__'


class TypeContactExterneSerializer(serializers.ModelSerializer):
    class Meta:
        model = TypeContactExterne
        fields = '__all__'


class ContactExterneSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContactExterne
        fields = '__all__'


class DemandeInterlocuteurSerializer(serializers.ModelSerializer):
    id_demande = serializers.PrimaryKeyRelatedField(
        queryset=Demande.objects.all(),
        help_text="ID de la demande."
    )

    class Meta:
        model = DemandeInterlocuteur
        fields = '__all__'


class DemandeBeneficiaireSerializer(serializers.ModelSerializer):
    id_beneficiaire = serializers.PrimaryKeyRelatedField(
        queryset=DemandeBeneficiaire.objects.all(),
        help_text="ID du bénéficiaire (table contact externe)."
    )

    class Meta:
        model = DemandeBeneficiaire
        fields = ['id','id_demande_interlocuteur','id_beneficiaire']


class InstructeurSerializer(serializers.ModelSerializer):
    id_agent_autorisations = serializers.PrimaryKeyRelatedField(
            queryset=AgentAutorisations.objects.all(),
            help_text="ID de l'agent (table agent_autorisations)."
        )

    class Meta:
        model = Instructeur
        fields = '__all__'


class GroupeinstructeurSerializer(serializers.ModelSerializer):
    class Meta:
        model = Groupeinstructeur
        fields = '__all__'


class GroupeinstructeurDemarcheSerializer(serializers.ModelSerializer):
    class Meta:
        model = GroupeinstructeurDemarche
        fields = '__all__'


class GroupeinstructeurInstructeurSerializer(serializers.ModelSerializer):
    class Meta:
        model = GroupeinstructeurInstructeur
        fields = '__all__'


class DossierInstructeurSerializer(serializers.ModelSerializer):
    class Meta:
        model = DossierInstructeur
        fields = '__all__'

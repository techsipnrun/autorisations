from rest_framework import serializers
from autorisations.models.models_utilisateurs import (
    AgentAutorisations, AgentAutorisationsUpdateLog, TypeContactExterne, ContactExterne,
    DossierInterlocuteur, DossierBeneficiaire, Instructeur, Groupeinstructeur,
    GroupeinstructeurDemarche, GroupeinstructeurInstructeur, DossierInstructeur,
    DossierValideur, DossierRelecteur, DossierRelecteurQualite, DossierSignataire,
    EmailOutbox
)


class AgentAutorisationsSerializer(serializers.ModelSerializer):
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


class DossierInterlocuteurSerializer(serializers.ModelSerializer):
    class Meta:
        model = DossierInterlocuteur
        fields = '__all__'


class DossierBeneficiaireSerializer(serializers.ModelSerializer):
    class Meta:
        model = DossierBeneficiaire
        fields = '__all__'


class InstructeurSerializer(serializers.ModelSerializer):
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


class DossierValideurSerializer(serializers.ModelSerializer):
    class Meta:
        model = DossierValideur
        fields = '__all__'


class DossierRelecteurSerializer(serializers.ModelSerializer):
    class Meta:
        model = DossierRelecteur
        fields = '__all__'


class DossierRelecteurQualiteSerializer(serializers.ModelSerializer):
    class Meta:
        model = DossierRelecteurQualite
        fields = '__all__'


class DossierSignataireSerializer(serializers.ModelSerializer):
    class Meta:
        model = DossierSignataire
        fields = '__all__'


class EmailOutboxSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmailOutbox
        fields = '__all__'

from django.contrib import admin
from .models.models_avis import Avis, AvisNature, AvisThematique, Expert, AvisDocument, DemandeAvis
from .models.models_documents import Document, DocumentFormat, DocumentNature, DossierDocument, MessageDocument
from .models.models_instruction import Champ, DossierChamp, DossierGroupe, Groupe, Message, ChampType, DemandeChamp, DemandeType, Dossier, Demande, Demarche, DossierType, EtatDemande, EtatDossier, EtatDemarche, Priorite
from .models.models_utilisateurs import ContactExterne, DossierBeneficiaire, DossierInterlocuteur, DossierInstructeur, GroupeinstructeurDemarche, GroupeinstructeurInstructeur, Instructeur, AgentAutorisations, Groupeinstructeur, TypeContactExterne


# Personnalisation globale de l'admin
admin.site.site_header = "Administration des Autorisations"
admin.site.index_title = "Portail d'administration"


"""
#######################
# AVIS
#######################
"""

admin.site.register(Avis)
admin.site.register(AvisNature)
admin.site.register(AvisThematique)
admin.site.register(Expert)
admin.site.register(AvisDocument)
admin.site.register(DemandeAvis)

"""
#######################
# DOCUMENT
#######################
"""
@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ('id', 'titre', 'id_nature', 'id_format', 'numero', 'emplacement')
    list_filter = ('id_nature', 'id_format')
    search_fields = ('titre', 'numero', 'emplacement')
    list_per_page = 30

admin.site.register(DocumentFormat)

admin.site.register(DocumentNature)

@admin.register(DossierDocument)
class DossierDocumentAdmin(admin.ModelAdmin):
    list_display = ('numero_dossier', 'nom_dossier', 'titre_document', 'nature_document')
    search_fields = (
        'id_dossier__numero',
        'id_dossier__nom_dossier',
        'id_document__titre',
        'id_document__id_nature__nature',
    )
    list_filter = ('id_document__id_nature', 'id_dossier__numero')
    list_per_page = 25

    def numero_dossier(self, obj):
        return obj.id_dossier.numero
    numero_dossier.short_description = "N° Dossier"

    def nom_dossier(self, obj):
        return obj.id_dossier.nom_dossier
    nom_dossier.short_description = "Nom du dossier"

    def titre_document(self, obj):
        return obj.id_document.titre
    titre_document.short_description = "Titre document"

    def nature_document(self, obj):
        return obj.id_document.id_nature.nature
    nature_document.short_description = "Nature"

admin.site.register(MessageDocument)


"""
#######################
# INSTRUCTION
#######################
"""

@admin.register(Dossier)
class DossierAdmin(admin.ModelAdmin):
    list_filter=('id_demarche',)
    search_fields=['nom_dossier']
    list_per_page = 20
admin.site.register(DossierType)
admin.site.register(DemandeType)
admin.site.register(EtatDemande)
admin.site.register(EtatDossier)
admin.site.register(EtatDemarche)
admin.site.register(Priorite)


@admin.register(Demande)
class DemandeAdmin(admin.ModelAdmin):
    list_display = ('id', 'id_demande_type', 'id_dossier', 'id_etat_demande', 'soumis_controle')
    list_filter = (
        'id_dossier',
        'id_etat_demande',
        'id_demande_type',
        'soumis_controle',
    )
    list_per_page = 20


class DemandeAdmin(admin.ModelAdmin):
    list_filter=('id_dossier',)
    list_per_page = 20
admin.site.register(Demarche)
admin.site.register(ChampType)


@admin.register(Champ)
class ChampAdmin(admin.ModelAdmin):
    list_display = ('nom', 'id_champ_type', 'id_demarche', 'requis')
    list_filter = ('id_champ_type', 'id_demarche')
    search_fields = ['nom']
    list_per_page = 20
admin.site.register(DemandeChamp)


@admin.register(DossierChamp)
class DossierChampAdmin(admin.ModelAdmin):
    list_display = ('numero_dossier', 'type_champ', 'nom_champ_limite')
    search_fields = (
        'id_dossier__numero',
        'id_champ__nom',
        'id_champ__id_champ_type__type',
    )
    list_filter = (
        'id_champ__id_champ_type',
    )
    list_per_page = 25

    def numero_dossier(self, obj):
        return obj.id_dossier.numero
    numero_dossier.short_description = "N° Dossier"

    def type_champ(self, obj):
        return obj.id_champ.id_champ_type.type
    type_champ.short_description = "Type de champ"

    def nom_champ_limite(self, obj):
        nom = obj.id_champ.nom
        return nom if len(nom) <= 60 else nom[:57] + '...'
    nom_champ_limite.short_description = "Nom du champ"

admin.site.register(Message)
admin.site.register(DossierGroupe)
admin.site.register(Groupe)



"""
#######################
# UTILISATEURS
#######################
"""

@admin.register(ContactExterne)
class ContactExterneAdmin(admin.ModelAdmin):
    list_display = ('nom', 'prenom', 'email', 'id_type')
    list_filter = ('id_type',)
    search_fields = ('nom', 'prenom', 'email', 'organisation', 'raison_sociale')
    list_per_page = 25
admin.site.register(TypeContactExterne)
admin.site.register(Instructeur)

@admin.register(AgentAutorisations)
class AgentAutorisationsAdmin(admin.ModelAdmin):
    list_display = ('nom', 'prenom', 'mail_1')
    list_filter = ('actif',)


admin.site.register(Groupeinstructeur)

admin.site.register(GroupeinstructeurDemarche)

@admin.register(GroupeinstructeurInstructeur)
class GroupeinstructeurInstructeurAdmin(admin.ModelAdmin):
    list_display = ('id_groupeinstructeur', 'id_instructeur')
    list_filter = ('id_groupeinstructeur',)

admin.site.register(DossierInstructeur)

admin.site.register(DossierInterlocuteur)

@admin.register(DossierBeneficiaire)
class DossierBeneficiaireAdmin(admin.ModelAdmin):
    list_display = ('nom_beneficiaire', 'prenom_beneficiaire', 'numero_dossier')
    list_filter = ('id_beneficiaire__id_type',)
    search_fields = ('id_beneficiaire__nom', 'id_beneficiaire__prenom', 'id_dossier_interlocuteur__id_dossier__numero')
    list_per_page = 25

    def nom_beneficiaire(self, obj):
        return obj.id_beneficiaire.nom
    nom_beneficiaire.short_description = "Nom bénéficiaire"

    def prenom_beneficiaire(self, obj):
        return obj.id_beneficiaire.prenom
    prenom_beneficiaire.short_description = "Prénom bénéficiaire"

    def numero_dossier(self, obj):
        return obj.id_dossier_interlocuteur.id_dossier.numero
    numero_dossier.short_description = "N° dossier"


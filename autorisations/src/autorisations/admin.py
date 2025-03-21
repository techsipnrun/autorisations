from django.contrib import admin
from .models.models_avis import Avis, AvisNature, AvisThematique, Expert, AvisDocument, DemandeAvis
from .models.models_documents import Document, DocumentFormat, DocumentNature, DossierDocument, MessageDocument
from .models.models_instruction import Champ, DossierChamp, DossierGroupe, Groupe, Message, ChampType, DemandeChamp, DemandeType, Dossier, Demande, Demarche, DossierType, EtatDemande, EtatDossier, EtatDemarche, Priorite
from .models.models_utilisateurs import AgentAutorisationsUpdateLog, ContactExterne, DossierBeneficiaire, DossierInterlocuteur, DossierInstructeur, GroupeinstructeurDemarche, GroupeinstructeurInstructeur, Instructeur, AgentAutorisations, Groupeinstructeur, TypeContactExterne


# Personnalisation globale de l'admin
admin.site.site_header = "Administration des Autorisations"
admin.site.index_title = "Portail d'administration"


#Avis
admin.site.register(Avis)
admin.site.register(AvisNature)
admin.site.register(AvisThematique)
admin.site.register(Expert)
admin.site.register(AvisDocument)
admin.site.register(DemandeAvis)

#Document
admin.site.register(Document)
admin.site.register(DocumentFormat)
admin.site.register(DocumentNature)
admin.site.register(DossierDocument)
admin.site.register(MessageDocument)


#Instruction
# admin.site.register(Dossier)
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
    list_filter=('id_dossier',)
    list_per_page = 20
admin.site.register(Demarche)
admin.site.register(ChampType)
admin.site.register(Champ)
admin.site.register(DemandeChamp)
admin.site.register(DossierChamp)
admin.site.register(Message)
admin.site.register(DossierGroupe)
admin.site.register(Groupe)

#Utilisateurs
admin.site.register(ContactExterne)
admin.site.register(TypeContactExterne)
admin.site.register(Instructeur)

@admin.register(AgentAutorisations)
class AgentAutorisationsAdmin(admin.ModelAdmin):
    list_display = ('nom', 'prenom', 'mail_1')


# admin.site.register(AgentAutorisations, AgentAutorisationsAdmin)
admin.site.register(Groupeinstructeur)
admin.site.register(GroupeinstructeurDemarche)
admin.site.register(GroupeinstructeurInstructeur)
admin.site.register(DossierInstructeur)
admin.site.register(DossierInterlocuteur)
admin.site.register(DossierBeneficiaire)



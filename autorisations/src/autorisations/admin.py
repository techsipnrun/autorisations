from django.contrib import admin
from .models.models_avis import Avis, AvisNature, AvisThematique, Expert, AvisDocument, DemandeAvis
from .models.models_documents import Document, DocumentFormat, DocumentNature, DossierDocument, MessageDocument
from .models.models_instruction import Champ, DossierAction, DossierChamp, DossierGroupe, EtapeDossier, Groupe, Message, ChampType, DemandeChamp, DemandeType, Dossier, Demande, Demarche, DossierType, EtatDemande, EtatDossier, EtatDemarche, ModificationType, Priorite
from .models.models_utilisateurs import ContactExterne, DossierBeneficiaire, DossierInterlocuteur, DossierInstructeur, GroupeinstructeurDemarche, GroupeinstructeurInstructeur, Instructeur, AgentAutorisations, Groupeinstructeur, TypeContactExterne


# Personnalisation globale de l'admin
admin.site.site_header = "Administration des Autorisations"
admin.site.index_title = "Portail d'administration"


"""
#######################
# AVIS
#######################
"""

@admin.register(Avis)
class AvisAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'nature',
        'thematique',
        'nom_dossier',
        'avis_favorable',
        'expert_nom_prenom',
        'instructeur_nom_prenom',
    )
    list_filter = ('id_avis_nature', 'id_avis_thematique', 'favorable')
    search_fields = (
        'id_dossier__nom_dossier',
        'id_expert__id_instructeur__id_agent_autorisations__nom',
        'id_expert__id_contact_externe__nom',
        'id_instructeur__id_agent_autorisations__nom',
    )
    list_per_page = 25

    def nature(self, obj):
        return obj.id_avis_nature.nature
    nature.short_description = "Nature"

    def thematique(self, obj):
        return obj.id_avis_thematique.thematique
    thematique.short_description = "Thématique"

    def nom_dossier(self, obj):
        return obj.id_dossier.nom_dossier if obj.id_dossier else "-"
    nom_dossier.short_description = "Nom du dossier"

    def avis_favorable(self, obj):
        if obj.favorable is None:
            return "–"
        return "Oui" if obj.favorable else "Non"
    avis_favorable.short_description = "Favorable"

    def expert_nom_prenom(self, obj):
        if obj.id_expert.est_interne and obj.id_expert.id_instructeur:
            agent = obj.id_expert.id_instructeur.id_agent_autorisations
            return f"{agent.nom} {agent.prenom}" if agent else "-"
        elif obj.id_expert.id_contact_externe:
            contact = obj.id_expert.id_contact_externe
            return f"{contact.nom} {contact.prenom}"
        return "-"
    expert_nom_prenom.short_description = "Expert"

    def instructeur_nom_prenom(self, obj):
        agent = obj.id_instructeur.id_agent_autorisations if obj.id_instructeur else None
        return f"{agent.nom} {agent.prenom}" if agent else "-"
    instructeur_nom_prenom.short_description = "Instructeur"


admin.site.register(AvisNature)

admin.site.register(AvisThematique)


@admin.register(Expert)
class ExpertAdmin(admin.ModelAdmin):
    list_display = ('id', 'est_interne_affichage', 'nom_expert')
    list_filter = ('est_interne',)
    search_fields = (
        'id_instructeur__id_agent_autorisations__nom',
        'id_instructeur__id_agent_autorisations__prenom',
        'id_contact_externe__nom',
        'id_contact_externe__prenom',
    )
    list_per_page = 25

    def est_interne_affichage(self, obj):
        return "Oui" if obj.est_interne else "Non"
    est_interne_affichage.short_description = "Est interne ?"

    def nom_expert(self, obj):
        if obj.est_interne and obj.id_instructeur and obj.id_instructeur.id_agent_autorisations:
            agent = obj.id_instructeur.id_agent_autorisations
            return f"{agent.nom} {agent.prenom}"
        elif obj.id_contact_externe:
            return f"{obj.id_contact_externe.nom} {obj.id_contact_externe.prenom}"
        return "-"
    nom_expert.short_description = "Expert"



@admin.register(AvisDocument)
class AvisDocumentAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'numero_document',
        'nature_avis',
        'avis_favorable',
        'expert_nom_prenom',
        'instructeur_nom_prenom',
    )
    search_fields = (
        'id_document__numero',
        'id_avis__id_avis_nature__nature',
        'id_avis__id_expert__id_contact_externe__nom',
        'id_avis__id_expert__id_instructeur__id_agent_autorisations__nom',
    )
    list_filter = ('id_avis__favorable', 'id_avis__id_avis_nature')
    list_per_page = 25

    def numero_document(self, obj):
        return obj.id_document.numero or "-"
    numero_document.short_description = "N° document"

    def nature_avis(self, obj):
        return obj.id_avis.id_avis_nature.nature
    nature_avis.short_description = "Nature de l’avis"

    def avis_favorable(self, obj):
        if obj.id_avis.favorable is None:
            return "–"
        return "Oui" if obj.id_avis.favorable else "Non"
    avis_favorable.short_description = "Favorable"

    def expert_nom_prenom(self, obj):
        expert = obj.id_avis.id_expert
        if expert.est_interne and expert.id_instructeur and expert.id_instructeur.id_agent_autorisations:
            agent = expert.id_instructeur.id_agent_autorisations
            return f"{agent.nom} {agent.prenom}"
        elif expert.id_contact_externe:
            return f"{expert.id_contact_externe.nom} {expert.id_contact_externe.prenom}"
        return "-"
    expert_nom_prenom.short_description = "Expert"

    def instructeur_nom_prenom(self, obj):
        agent = obj.id_avis.id_instructeur.id_agent_autorisations if obj.id_avis.id_instructeur else None
        return f"{agent.nom} {agent.prenom}" if agent else "-"
    instructeur_nom_prenom.short_description = "Instructeur"


@admin.register(DemandeAvis)
class DemandeAvisAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'type_demande',
        'numero_dossier',
        'expert_nom_prenom',
        'instructeur_nom_prenom',
    )
    list_filter = (
        'id_demande__id_dossier',
        'id_avis__favorable',
        'id_avis__id_expert',
        'id_avis__id_instructeur',
    )
    search_fields = (
        'id_demande__id_dossier__numero',
        'id_avis__id_expert__id_contact_externe__nom',
        'id_avis__id_expert__id_instructeur__id_agent_autorisations__nom',
        'id_avis__id_instructeur__id_agent_autorisations__nom',
    )
    list_per_page = 25

    def type_demande(self, obj):
        return obj.id_demande.id_demande_type.type
    type_demande.short_description = "Type de demande"

    def numero_dossier(self, obj):
        return obj.id_demande.id_dossier.numero
    numero_dossier.short_description = "N° dossier"

    def expert_nom_prenom(self, obj):
        expert = obj.id_avis.id_expert
        if expert.est_interne and expert.id_instructeur and expert.id_instructeur.id_agent_autorisations:
            agent = expert.id_instructeur.id_agent_autorisations
            return f"{agent.nom} {agent.prenom}"
        elif expert.id_contact_externe:
            return f"{expert.id_contact_externe.nom} {expert.id_contact_externe.prenom}"
        return "-"
    expert_nom_prenom.short_description = "Expert"

    def instructeur_nom_prenom(self, obj):
        agent = obj.id_avis.id_instructeur.id_agent_autorisations if obj.id_avis.id_instructeur else None
        return f"{agent.nom} {agent.prenom}" if agent else "-"
    instructeur_nom_prenom.short_description = "Instructeur"




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


@admin.register(MessageDocument)
class MessageDocumentAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'numero_dossier',
        'numero_avis',
        'date_envoi',
        'titre_document',
        'format_document',
        'mail_emetteur',
    )
    list_filter = (
        'id_document__id_nature',
        'id_message__id_dossier',
        'id_message__email_emetteur',
    )
    search_fields = (
        'id_document__numero',
        'id_message__id_dossier__numero',
        'id_message__email_emetteur',
    )
    list_per_page = 25

    def numero_dossier(self, obj):
        return obj.id_message.id_dossier.numero if obj.id_message and obj.id_message.id_dossier else "-"
    numero_dossier.short_description = "N° dossier"

    def numero_avis(self, obj):
        return obj.id_message.id_avis.id if obj.id_message and obj.id_message.id_avis else "-"
    numero_avis.short_description = "N° avis"

    def date_envoi(self, obj):
        return obj.id_message.date_envoi
    date_envoi.short_description = "Date d'envoi"

    def titre_document(self, obj):
        return obj.id_document.titre
    titre_document.short_description = "Titre document"

    def mail_emetteur(self, obj):
        return obj.id_message.email_emetteur or "-"
    mail_emetteur.short_description = "Émetteur"

    def format_document(self, obj):
        return obj.id_document.id_format.format
    format_document.short_description = "Format doc"



"""
#######################
# INSTRUCTION
#######################
"""

@admin.register(Dossier)
class DossierAdmin(admin.ModelAdmin):
    list_display = ('numero', 'nom_dossier', 'etat','groupe_instructeur', 'date_depot')
    list_filter = ('id_etat_dossier', 'id_demarche', 'id_groupeinstructeur')
    search_fields = ('numero', 'nom_dossier', 'id_demarche__titre')
    list_per_page = 20

    def etat(self, obj):
        return obj.id_etat_dossier.nom if obj.id_etat_dossier else "-"
    etat.short_description = "État"

    def groupe_instructeur(self, obj):
        return obj.id_groupeinstructeur.nom if obj.id_groupeinstructeur else "-"
    groupe_instructeur.short_description = "Groupe d'instructeurs"

    
admin.site.register(DossierType)

admin.site.register(DemandeType)

admin.site.register(EtatDemande)

admin.site.register(EtatDossier)

admin.site.register(EtapeDossier)

admin.site.register(ModificationType)

admin.site.register(DossierAction)

admin.site.register(EtatDemarche)

admin.site.register(Priorite)


@admin.register(Demande)
class DemandeAdmin(admin.ModelAdmin):
    list_display = ('id', 'id_demande_type', 'id_dossier', 'num_dossier', 'id_etat_demande')
    list_filter = (
        'id_dossier',
        'id_etat_demande',
        'id_demande_type',
        'soumis_controle',
    )
    search_fields = ('id_dossier__nom_dossier', 'id_dossier__numero')
    list_per_page = 20

    def num_dossier(self, obj):
        return obj.id_dossier.numero if obj.id_dossier else "-"
    num_dossier.short_description = "N° dossier"


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


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'email_emetteur',
        'date_envoi',
        'numero_dossier',
        'numero_avis',
        'piece_jointe_bool',
    )
    list_filter = ('piece_jointe', 'email_emetteur', 'date_envoi')
    search_fields = (
        'email_emetteur',
        'body',
        'id_dossier__numero',
        'id_avis__id',
    )
    list_per_page = 25

    def numero_dossier(self, obj):
        return obj.id_dossier.numero if obj.id_dossier else "-"
    numero_dossier.short_description = "N° dossier"

    def numero_avis(self, obj):
        return obj.id_avis.id if obj.id_avis else "-"
    numero_avis.short_description = "N° avis"

    def piece_jointe_bool(self, obj):
        return obj.piece_jointe
    piece_jointe_bool.boolean = True
    piece_jointe_bool.short_description = "Contient pièce jointe"


@admin.register(DossierGroupe)
class DossierGroupeAdmin(admin.ModelAdmin):
    list_display = ('id', 'nom_groupe', 'nom_dossier')
    list_filter = ('id_groupe',)
    search_fields = ('id_groupe__nom', 'id_dossier__nom_dossier')
    list_per_page = 25

    def nom_groupe(self, obj):
        return obj.id_groupe.nom
    nom_groupe.short_description = "Nom du groupe"

    def nom_dossier(self, obj):
        return obj.id_dossier.nom_dossier
    nom_dossier.short_description = "Nom du dossier"


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


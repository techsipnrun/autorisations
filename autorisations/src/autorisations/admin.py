import logging
from django.contrib import admin
from .models.models_avis import Avis, AvisNature, AvisThematique, Expert, AvisDocument, DossierAvis
from .models.models_documents import Document, DocumentFormat, DocumentNature, DocumentStatut, DossierDocument, DossierManifSportiveDocument, DossierRelecteurDocument, MessageDocument
from .models.models_instruction import ActionsPossibles, AvisManifSportive, Champ, ChangementEtape, DossierAction, DossierChamp, DossierGroupe, DossierManifSportive, DossierManifestationLiaison, DossierNote, EtapeDossier, Groupe, Message, ChampType, DemandeChamp, DemandeType, Dossier, Demande, Demarche, DossierType, EtatDemande, EtatDossier, EtatDemarche, Action, Priorite, SynchronisationEtat
from .models.models_utilisateurs import ContactExterne, DossierBeneficiaire, DossierEnvoiActe, DossierInterlocuteur, DossierInstructeur, DossierIntermediaireSignature, DossierPublicationRAA, EmailOutbox, GroupeinstructeurDemarche, GroupeinstructeurInstructeur, Instructeur, AgentAutorisations, Groupeinstructeur, TypeContactExterne, DossierValideur, DossierRelecteur, DossierRelecteurQualite, DossierSignataire
from django.db.models import Exists, OuterRef

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
        'statut',
        'nature',
        'thematique',
        'nom_dossier',
        'avis_favorable',
        'publie_au_raa_affichage',
        'expert_nom_prenom',
        'instructeur_nom_prenom',
    )
    list_filter = ('id_avis_nature', 'id_avis_thematique', 'favorable', 'statut')
    search_fields = (
        'id',
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

    def publie_au_raa_affichage(self, obj):
        return "Oui" if obj.publie_au_raa else "Non"
    publie_au_raa_affichage.short_description = "Publié au RAA"
    publie_au_raa_affichage.admin_order_field = "publie_au_raa"


admin.site.register(AvisNature)

@admin.register(AvisThematique)
class AvisThematiqueAdmin(admin.ModelAdmin):
    list_display = ("thematique", "demarche")
    list_filter = ("demarche",)
    search_fields = ("thematique", "demarche")


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



class ExpertTypeFilter(admin.SimpleListFilter):
    title = "Type d'expert"
    parameter_name = "expert_type"

    def lookups(self, request, model_admin):
        return (
            ("interne", "Interne"),
            ("externe", "Externe"),
            ("none", "Aucun"),
        )

    def queryset(self, request, queryset):
        if self.value() == "interne":
            return queryset.filter(id_avis__id_expert__id_instructeur__isnull=False)
        if self.value() == "externe":
            return queryset.filter(id_avis__id_expert__id_contact_externe__isnull=False)
        if self.value() == "none":
            return queryset.filter(
                id_avis__id_expert__id_instructeur__isnull=True,
                id_avis__id_expert__id_contact_externe__isnull=True,
            )
        return queryset


@admin.register(DossierAvis)
class DossierAvisAdmin(admin.ModelAdmin):
    list_display = (
        "id_dossier_numero",
        "id_avis_numero",
        "expert_interne",
        "expert_externe",
    )

    search_fields = (
        "id_dossier__numero",
        "id_avis__id",
        "id_avis__id_expert__id_contact_externe__nom",
        "id_avis__id_expert__id_contact_externe__prenom",
        "id_avis__id_expert__id_contact_externe__raison_sociale",
        "id_avis__id_expert__id_instructeur__id_agent_autorisations__nom",
        "id_avis__id_expert__id_instructeur__id_agent_autorisations__prenom",
    )

    list_filter = (ExpertTypeFilter,)  # ✅ Un seul filtre

    # --------- Colonnes personnalisées ---------
    def id_dossier_numero(self, obj):
        return obj.id_dossier.numero
    id_dossier_numero.short_description = "Numéro dossier"

    def id_avis_numero(self, obj):
        return obj.id_avis.id
    id_avis_numero.short_description = "Numéro avis"

    def expert_interne(self, obj):
        expert = obj.id_avis.id_expert
        if expert and expert.id_instructeur:
            instr = expert.id_instructeur
            return f"{instr.id_agent_autorisations.nom} {instr.id_agent_autorisations.prenom}"
        return "-"
    expert_interne.short_description = "Expert interne"

    def expert_externe(self, obj):
        expert = obj.id_avis.id_expert
        if expert and expert.id_contact_externe:
            contact = expert.id_contact_externe
            if contact.nom and contact.prenom:
                return f"{contact.nom} {contact.prenom}"
            return contact.raison_sociale or "-"
        return "-"
    expert_externe.short_description = "Expert externe"




"""
#######################
# DOCUMENT
#######################
"""

@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ('id', 'titre', 'id_nature', 'id_format', 'description', 'numero', 'id_statut', 'emplacement')
    list_filter = ('id_nature', 'id_format')
    search_fields = ('titre', 'numero', 'emplacement')
    list_per_page = 30

admin.site.register(DocumentFormat)

admin.site.register(DocumentNature)

admin.site.register(DocumentStatut)

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

class DemarcheTypeFilter(admin.SimpleListFilter):
    title = "Type de démarche"
    parameter_name = "id_demarche"

    def lookups(self, request, model_admin):
        return [(d.id, d.type) for d in Demarche.objects.all()]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(id_demarche__id=self.value())
        return queryset
    

class DossierLiaisonFilter(admin.SimpleListFilter):
    title = "Lié"
    parameter_name = "liaison"

    def lookups(self, request, model_admin):
        return (
            ("oui", "Oui"),
            ("non", "Non"),
        )

    def queryset(self, request, queryset):
        liaison_qs = DossierManifestationLiaison.objects.filter(
            id_dossier=OuterRef("pk")
        )

        queryset = queryset.annotate(est_lie=Exists(liaison_qs))

        if self.value() == "oui":
            return queryset.filter(est_lie=True)
        if self.value() == "non":
            return queryset.filter(est_lie=False)

        return queryset
    

@admin.register(Dossier)
class DossierAdmin(admin.ModelAdmin):
    list_display = ('numero', 'id', 'nom_dossier', 'etat', 'etape', 'groupe_instructeur', 'date_depot')
    list_filter = ('id_etat_dossier', 'id_etape_dossier', DemarcheTypeFilter, 'id_groupeinstructeur', 'present_sur_ds', DossierLiaisonFilter,)
    search_fields = ('numero', 'nom_dossier', 'id_demarche__titre')
    list_per_page = 20

    def etat(self, obj):
        return obj.id_etat_dossier.nom if obj.id_etat_dossier else "-"
    etat.short_description = "État"

    def etape(self, obj):
        return obj.id_etape_dossier.etape if obj.id_etape_dossier else "-"
    etape.short_description = "Étape"

    def groupe_instructeur(self, obj):
        return obj.id_groupeinstructeur.nom if obj.id_groupeinstructeur else "-"
    groupe_instructeur.short_description = "Groupe d'instructeurs"

    
admin.site.register(DossierType)

admin.site.register(DemandeType)

admin.site.register(EtatDemande)

admin.site.register(EtatDossier)

admin.site.register(EtapeDossier)

admin.site.register(Action)


@admin.register(DossierAction)
class DossierActionAdmin(admin.ModelAdmin):
    # list_display = ('id', 'id_dossier', 'id_instructeur', 'id_action', 'date')
    list_filter = ('id_action', 'id_instructeur')
    search_fields = ('id_dossier__numero', 'id_instructeur__email', 'id_action__action')
    readonly_fields = ('date',)
    ordering = ('-date',)


admin.site.register(EtatDemarche)

admin.site.register(Priorite)

'''Cette version n'affichait pas toutes les demandes (seulement une partie --> bug d'affichage)'''
# @admin.register(Demande)
# class DemandeAdmin(admin.ModelAdmin):
#     list_display = ('id', 'id_demande_type', 'id_dossier', 'num_dossier', 'id_etat_demande')
#     list_filter = (
#         'id_dossier',
#         'id_etat_demande',
#         'id_demande_type',
#         'soumis_controle',
#     )
#     search_fields = ('id_dossier__nom_dossier', 'id_dossier__numero')
#     list_per_page = 20

#     def num_dossier(self, obj):
#         return obj.id_dossier.numero if obj.id_dossier else "-"
#     num_dossier.short_description = "N° dossier"

@admin.register(Demande)
class DemandeAdmin(admin.ModelAdmin):
    list_display = ('id', 'type_demande_affichage', 'numero_dossier_affichage', 'etat_demande_affichage')
    list_filter = (
        'id_etat_demande',
        'id_demande_type',
        'soumis_controle',
        'id_dossier',
    )

    search_fields = ('id_dossier__nom_dossier', 'id_dossier__numero', 'id')
    list_per_page = 20

    @admin.display(description="N° dossier")
    def numero_dossier_affichage(self, obj):
        try:
            return obj.id_dossier.numero
        except:
            return "(Dossier cassé)"
        
    @admin.display(description="Type de demande")
    def type_demande_affichage(self, obj):
        try:
            return obj.id_demande_type.type
        except:
            return "(Type de demande cassé)"
        
    @admin.display(description="État de la demande")
    def etat_demande_affichage(self, obj):
        try:
            return obj.id_etat_demande.nom
        except:
            return "(Type de demande cassé)"



# admin.site.register(Demarche)
@admin.register(Demarche)
class DemarcheAdmin(admin.ModelAdmin):
    list_display = ('type', 'numero', 'service', 'delais_jours_instruction')
    search_fields = ['type']
    list_per_page = 20


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
    list_display = ('id', 'numero_dossier', 'type_champ', 'nom_champ_limite')
    search_fields = (
        'id_dossier__numero',
        'id_champ__nom',
        'id_champ__id_champ_type__type',
    )
    list_filter = (
        'id_champ__id_champ_type',
    )
    list_per_page = 25

    ordering = ('-id',)

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


class SourceListFilter(admin.SimpleListFilter):
    title = "Source"
    parameter_name = "source"

    def lookups(self, request, model_admin):
        return [
            ("avis", "Avis"),
            ("petitionnaire", "Demande pétitionnaire"),
        ]

    def queryset(self, request, queryset):
        if self.value() == "avis":
            return queryset.filter(id_avis__isnull=False)
        if self.value() == "petitionnaire":
            return queryset.filter(id_dossier__isnull=False)
        return queryset

@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'email_emetteur',
        'date_envoi',
        'numero_dossier',
        'numero_avis',
        'piece_jointe_bool',
        "source",
    )
    list_filter = ('piece_jointe', 'email_emetteur', 'date_envoi', 'lu', SourceListFilter)
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

    def source(self, obj):
        if obj.id_avis:
            return "Avis"
        elif obj.id_dossier:
            return "Demande pétitionnaire"
        return "-"
    source.short_description = "Source"


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




@admin.register(ChangementEtape)
class ChangementEtapeAdmin(admin.ModelAdmin):
    list_display = ("id", "action", "code", "url_name")
    search_fields = ("action", "code")
    ordering = ("id",)

    @admin.display(description="Nom URL")
    def url_name(self, obj):
        return obj.get_url_name()


@admin.register(ActionsPossibles)
class ActionsPossiblesAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "etape",
        "action",
        "demarche",
        "groupe_instructeur",
        "present_sur_dn",
        "coeur_de_parc",
        "type_manif_sportive",
    )

    list_filter = (
        "id_etape",
        "id_changement_etape",
        "id_demarche",
        "id_groupe_instructeur",
        "present_sur_dn",
        "coeur_de_parc",
        "type_manif_sportive",
    )

    search_fields = (
        "id_etape__etape",
        "id_changement_etape__action",
        "id_changement_etape__code",
        "id_demarche__titre",
        "id_demarche__type",
        "id_groupe_instructeur__nom",
    )


    list_select_related = (
        "id_etape",
        "id_changement_etape",
        "id_demarche",
        "id_groupe_instructeur",
    )

    ordering = (
        "id_etape__etape",
        "id_demarche__titre",
        "id_groupe_instructeur__nom",
        "id_changement_etape__action",
    )

    @admin.display(ordering="id_etape__etape", description="Étape")
    def etape(self, obj):
        return obj.id_etape

    @admin.display(ordering="id_changement_etape__action", description="Changement étape")
    def action(self, obj):
        return obj.id_changement_etape

    @admin.display(ordering="id_demarche__titre", description="Démarche")
    def demarche(self, obj):
        return obj.id_demarche or "Toutes"

    @admin.display(ordering="id_groupe_instructeur__nom", description="Groupe instructeur")
    def groupe_instructeur(self, obj):
        return obj.id_groupe_instructeur or "Tous"




"""
#######################
# UTILISATEURS
#######################
"""

class PersonneMoraleFilter(admin.SimpleListFilter):
    title = 'Personne morale'
    parameter_name = 'personne_morale'

    def lookups(self, request, model_admin):
        return [
            ('oui', 'Oui'),
            ('non', 'Non')
        ]

    def queryset(self, request, queryset):
        if self.value() == 'oui':
            return queryset.exclude(siret__isnull=True).exclude(siret__exact='')
        if self.value() == 'non':
            return queryset.filter(siret__isnull=True) | queryset.filter(siret__exact='')
        return queryset


@admin.register(ContactExterne)
class ContactExterneAdmin(admin.ModelAdmin):
    list_display = ('nom', 'prenom', 'email', 'id_type', 'raison_sociale')
    list_filter = ('id_type', PersonneMoraleFilter)
    search_fields = ('nom', 'prenom', 'email', 'organisation', 'raison_sociale')
    list_per_page = 25

admin.site.register(TypeContactExterne)
admin.site.register(Instructeur)

@admin.register(AgentAutorisations)
class AgentAutorisationsAdmin(admin.ModelAdmin):
    list_display = ('nom', 'prenom', 'mail_1')
    list_filter = ('actif',)
    search_fields = ('nom', 'prenom', 'mail_1')


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


admin.site.register(DossierNote)


@admin.register(DossierValideur)
class DossierValideurAdmin(admin.ModelAdmin):
    list_filter = ('id_instructeur', 'id_dossier')
    # list_display = ('id_instructeur', 'id_dossier') # ne passe pas

# admin.site.register(DossierValideur)

@admin.register(DossierRelecteur)
class DossierRelecteurAdmin(admin.ModelAdmin):
    list_filter = ('id_instructeur', 'relu',)

@admin.register(DossierRelecteurDocument)
class DossierRelecteurDocumentAdmin(admin.ModelAdmin):
    list_filter = ('id_dossier_relecteur', 'id_document',)


@admin.register(DossierRelecteurQualite)
class DossierRelecteurQualiteAdmin(admin.ModelAdmin):
    list_filter = ('id_instructeur',)


@admin.register(DossierSignataire)
class DossierSignataireAdmin(admin.ModelAdmin):
    list_filter = ('id_instructeur',)


@admin.register(DossierIntermediaireSignature)
class DossierIntermediaireSignatureAdmin(admin.ModelAdmin):
    # list_display = ('id', 'id_dossier', 'id_instructeur')
    # search_fields = ('id_dossier__numero', )
    list_filter = ('id_instructeur',)


@admin.register(DossierEnvoiActe)
class DossierEnvoiActeAdmin(admin.ModelAdmin):
    # list_display = ('id', 'id_dossier', 'id_instructeur')
    # search_fields = ('id_dossier__numero',)
    list_filter = ('id_instructeur',)


@admin.register(DossierPublicationRAA)
class DossierPublicationRAAAdmin(admin.ModelAdmin):
    # list_display = ('id', 'id_dossier', 'id_instructeur')
    # search_fields = ('id_dossier__numero',)
    list_filter = ('id_instructeur',)


# class DossierDSRecuListFilter(admin.SimpleListFilter):
#     title = 'Dossier DS reçu'
#     parameter_name = 'ds_recu'

#     def lookups(self, request, model_admin):
#         return [
#             ('oui', 'Oui'),
#             ('non', 'Non'),
#         ]

#     def queryset(self, request, queryset):
#         if self.value() == 'oui':
#             return queryset.filter(id_dossier__isnull=False)
#         if self.value() == 'non':
#             return queryset.filter(id_dossier__isnull=True)
#         return queryset
    

class LiaisonDossierFilter(admin.SimpleListFilter):
    title = 'Dossier DS reçu'
    parameter_name = 'ds_recu'

    def lookups(self, request, model_admin):
        return [
            ('oui', 'Oui'),
            ('non', 'Non'),
        ]

    def queryset(self, request, queryset):
        if self.value() == 'oui':
            # On garde uniquement les DossierManifSportive liés à un dossier
            ids = DossierManifestationLiaison.objects.values_list('id_dossier_manif_id', flat=True)
            return queryset.filter(id__in=ids)
        if self.value() == 'non':
            ids = DossierManifestationLiaison.objects.values_list('id_dossier_manif_id', flat=True)
            return queryset.exclude(id__in=ids)
        return queryset



@admin.register(DossierManifSportive)
class DossierManifSportiveAdmin(admin.ModelAdmin):
    list_display = ('nom_dossier', 'etat_dossier', 'etape', 'avis_colonne', 'numero_affiche', 'est_lie',)
    list_filter = ('etat_dossier', LiaisonDossierFilter)
    search_fields = ('nom_dossier', 'numero_dossier_declaration_manifestations')

    def numero_affiche(self, obj):
        return obj.numero_dossier_declaration_manifestations
    numero_affiche.short_description = "Numéro"

    def etape(self, obj):
        return obj.id_etape.etape if obj.id_etape else "-"
    etape.short_description = "Étape"

    def avis_colonne(self, obj):
        return obj.avis.reponse_avis if hasattr(obj, "avis") and obj.avis and obj.avis.reponse_avis else "-"
    avis_colonne.short_description = "Avis"

    @admin.display(boolean=True, description="Lié")
    def est_lie(self, obj):
        return DossierManifestationLiaison.objects.filter(id_dossier_manif=obj).exists()

admin.site.register(DossierManifestationLiaison)

admin.site.register(DossierManifSportiveDocument)

admin.site.register(SynchronisationEtat)



class EnvoyeAFilter(admin.SimpleListFilter):
    title = "Envoyé à"  # Titre du filtre dans l’admin
    parameter_name = "to_email"

    def lookups(self, request, model_admin):
        """Retourne les choix proposés dans la colonne de filtre"""
        emails = (
            EmailOutbox.objects.exclude(to__isnull=True)
            .values_list("to", flat=True)
        )

        # ⚙️ `to` est une liste d’adresses (ArrayField), donc on doit aplatir :
        unique_emails = set()
        for email_list in emails:
            if isinstance(email_list, list):
                unique_emails.update(email_list)
        
        # Trie alphabétique pour lisibilité
        return [(email, email) for email in sorted(unique_emails, key=str.lower)]

    def queryset(self, request, queryset):
        """Filtre le queryset selon la valeur choisie"""
        if self.value():
            return queryset.filter(to__icontains=self.value())
        return queryset
    

@admin.register(EmailOutbox)
class EmailOutboxAdmin(admin.ModelAdmin):
    list_display = ("sujet", "statut", "type_mail", "to", "date_creation")
    list_filter = ("statut", "type_mail", EnvoyeAFilter)
    search_fields = ("sujet", "email_from", "to")
    ordering = ("-date_creation",)

@admin.register(AvisManifSportive)
class AvisManifSportiveAdmin(admin.ModelAdmin):
    list_display = ('id', 'id_avis_manif_sportive', 'id_dossier_manif_sportive', 'etat', 'date_demande', 'date_reponse', 'reponse_avis',)
    list_filter = ('etat',)
    # search_fields = (
    #     'id_dossier_manif_sportive__nom_dossier',
    #     'id_dossier_manif_sportive__numero',
    # )
    date_hierarchy = 'date_demande'
    ordering = ('-date_demande',)




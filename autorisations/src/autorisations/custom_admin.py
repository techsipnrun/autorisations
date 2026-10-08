from django.contrib import admin
from django.db.models import Case, When, Value, CharField
from .admin_site import SchemaGroupedAdminSite
from .models.models_avis import Avis, AvisDocument, Expert
from .models.models_documents import Document, DossierDocument
from .models.models_instruction import Dossier, Demande, DossierGroupe, Groupe
from .models.models_utilisateurs import ContactExterne, DestinataireNotification, DossierInstructeur, DossierInterlocuteur, DossierBeneficiaire, Instructeur


class CustomAdminSite(SchemaGroupedAdminSite):
    site_header = "Bancarisation des Autorisations"
    index_title = "Portail de bancarisation"
    index_template = "custom_admin_index.html"  # Ajout du template personnalisé

# Instancier le site admin personnalisé
custom_admin_site = CustomAdminSite(name="custom_admin")


class DossierAdmin(admin.ModelAdmin):
    exclude = ('id_ds','id_dossier_parent')
    list_filter = ('id_demarche',)
custom_admin_site.register(Dossier, DossierAdmin)

class DemandeAdmin(admin.ModelAdmin):
    exclude = ('soumis_controle', 'en_attente_avis', 'avis_a_faire', 'en_attente_demandeur', 'en_attente_validation', 'id_interlocuteur_ds')
    list_filter = ('id_dossier',)
    def get_changeform_initial_data(self, request):
        """
        Définit une valeur par défaut lors de la création d'une nouvelle instance.
        """
        return {'pre_instruction_faite': True}
    
custom_admin_site.register(Demande, DemandeAdmin)


class DocumentAdmin(admin.ModelAdmin):
    exclude = ('url_ds',)
    list_filter = ('id_nature',)
custom_admin_site.register(Document, DocumentAdmin)

class DossierDocumentAdmin(admin.ModelAdmin):
    list_filter = ('id_dossier',)
custom_admin_site.register(DossierDocument, DossierDocumentAdmin)

class InstructeurAdmin(admin.ModelAdmin):
    exclude = ('id_ds',)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "id_agent_autorisations":
            kwargs["queryset"] = db_field.related_model.objects.order_by("nom")  # Trier par nom
        return super().formfield_for_foreignkey(db_field, request, **kwargs)
    
    def get_queryset(self, request):
        """
        Trie les instructeurs par nom dans la liste de l'admin.
        """
        qs = super().get_queryset(request)
        return qs.order_by("id_agent_autorisations__nom")
    
custom_admin_site.register(Instructeur, InstructeurAdmin)


@admin.register(DestinataireNotification, site=custom_admin_site)
class DestinataireNotificationCustomAdmin(admin.ModelAdmin):
    list_display = ("libelle", "email", "actif")
    list_filter = ("actif",)
    search_fields = ("libelle", "email")
    ordering = ("libelle", "email")


class DossierInstructeurAdmin(admin.ModelAdmin):
    list_filter = ('id_dossier', 'id_instructeur',)
custom_admin_site.register(DossierInstructeur, DossierInstructeurAdmin)


class ContactExterneAdmin(admin.ModelAdmin):
    list_filter = ('id_type',)
    def get_queryset(self, request):
            """
            Trie les contacts par nom dans la liste de l'admin.
            """
            qs = super().get_queryset(request)
            return qs.order_by('nom')
custom_admin_site.register(ContactExterne, ContactExterneAdmin)


class ExpertAdmin(admin.ModelAdmin):
    exclude = ('id_expert_ds','est_interne')
    def get_queryset(self, request):
        """
        Trie les Experts par id_agent_autorisations__nom ou id_contact_externe.
        """
        qs = super().get_queryset(request).annotate(
            nom_affichage=Case(
                When(id_instructeur__isnull=False, then="id_instructeur__id_agent_autorisations__nom"),
                When(id_contact_externe__isnull=False, then="id_contact_externe__nom"),
                default=Value("Inconnu"),  # Si les deux sont NULL
                output_field=CharField(),
            )
        ).order_by("nom_affichage")  # Trie sur le champ calculé

        return qs
custom_admin_site.register(Expert, ExpertAdmin)

class AvisAdmin(admin.ModelAdmin):
    list_filter = ('id_avis_nature', 'id_avis_thematique', 'id_expert', 'id_dossier',)
    exclude = ('id_ds', 'id_expert_ds', )
custom_admin_site.register(Avis, AvisAdmin)

class AvisDocumentAdmin(admin.ModelAdmin):
    list_filter = ('id_avis',)
custom_admin_site.register(AvisDocument, AvisDocumentAdmin)

class DossierInterlocuteurAdmin(admin.ModelAdmin):
    exclude = ('id_interlocuteur_ds', 'id_expert_ds', )
    list_filter = ('id_dossier',)
custom_admin_site.register(DossierInterlocuteur, DossierInterlocuteurAdmin)

class DossierBeneficiaireAdmin(admin.ModelAdmin):
    list_filter = ('id_beneficiaire',)
custom_admin_site.register(DossierBeneficiaire, DossierBeneficiaireAdmin)

custom_admin_site.register(Groupe)

class DossierGroupeAdmin(admin.ModelAdmin):
    list_filter = ('id_groupe',)
custom_admin_site.register(DossierGroupe, DossierGroupeAdmin)

from django.contrib import admin, messages
from django.core.exceptions import ValidationError

from autorisations.models.models_generation import (
    Balise, BaliseSourceChamp, DocumentTemplate, DocumentTemplateDemarche, TemplateBalise, DocumentGeneration, DocumentNumberReservation,
)
from .forms import BaliseConfigurationForm


class BaliseSourceChampInline(admin.TabularInline):
    model = BaliseSourceChamp
    extra = 0
    fields = ('id_demarche', 'id_champ')
    autocomplete_fields = ('id_demarche', 'id_champ')


@admin.register(Balise)
class BaliseAdmin(admin.ModelAdmin):
    form = BaliseConfigurationForm
    list_display = ("code", "libelle", "source", "type", "required", "actif")
    list_filter = ("source", "type", "required", "actif")
    search_fields = ("code", "libelle", "source_propriete")
    readonly_fields = ('mode',)
    inlines = (BaliseSourceChampInline,)


class DocumentTemplateDemarcheInline(admin.TabularInline):
    model = DocumentTemplateDemarche
    extra = 0
    autocomplete_fields = ("id_demarche",)


@admin.register(DocumentTemplate)
class DocumentTemplateAdmin(admin.ModelAdmin):
    list_display = ("nom", "id_nature", "chemin_relatif", "destination_relative", "nom_fichier", "actif", "date_verification")
    list_filter = ("actif", "id_nature")
    search_fields = ("nom", "chemin_relatif")
    list_select_related = ("id_nature",)
    inlines = (DocumentTemplateDemarcheInline,)
    actions = ("verifier_modele",)
    readonly_fields = ("rapport_validation", "date_verification")

    @admin.action(description="Vérifier le modèle et synchroniser ses balises")
    def verifier_modele(self, request, queryset):
        from .services.verification import TemplateVerificationService

        for template in queryset:
            try:
                verified = TemplateVerificationService().verify(template.pk)
                report = verified.rapport_validation
            except (ValueError, ValidationError) as exc:
                self.message_user(request, f"{template.nom} : {exc}", messages.ERROR)
                continue
            details = "; ".join(f"{b['code']} : {b['statut']}" for b in report['balises'])
            errors = "; ".join(report['erreurs'])
            self.message_user(
                request,
                f"{template.nom} — {'Valide' if report['valide'] else 'Invalide'}. {details} {errors}",
                messages.SUCCESS if report['valide'] else messages.ERROR,
            )


@admin.register(DocumentTemplateDemarche)
class DocumentTemplateDemarcheAdmin(admin.ModelAdmin):
    list_display = ('id_template', 'id_demarche')
    list_select_related = ('id_template', 'id_demarche')
    search_fields = ('id_template__nom', 'id_demarche__type')
    autocomplete_fields = ('id_template', 'id_demarche')


@admin.register(BaliseSourceChamp)
class BaliseSourceChampAdmin(admin.ModelAdmin):
    list_display = ('id_balise', 'id_demarche', 'id_champ')
    list_select_related = ('id_balise', 'id_demarche', 'id_champ')
    list_filter = ('id_demarche',)
    search_fields = ('id_balise__code', 'id_balise__libelle', 'id_champ__nom')


@admin.register(TemplateBalise)
class TemplateBaliseAdmin(admin.ModelAdmin):
    list_display = ('id_template', 'code', 'id_balise')
    list_select_related = ('id_template', 'id_balise')
    list_filter = ('id_template',)
    search_fields = ('code', 'id_template__nom')


@admin.register(DocumentGeneration)
class DocumentGenerationAdmin(admin.ModelAdmin):
    list_display = ('id', 'date', 'id_dossier', 'id_template', 'id_document', 'user')
    list_select_related = ('id_dossier', 'id_template', 'id_document', 'user')
    list_filter = ('date', 'id_template', 'user')
    search_fields = ('id_dossier__numero', 'id_document__titre', 'id_template__nom', 'user__username')
    date_hierarchy = 'date'
    readonly_fields = ('id',)
    fields = ('id', 'date', 'id_dossier', 'id_template', 'id_document', 'user',
              'context_snapshot', 'template_snapshot', 'file_corrections', 'circuit_events', 'id_numero')
    autocomplete_fields = ('id_dossier', 'id_template', 'id_document', 'user')


@admin.register(DocumentNumberReservation)
class DocumentNumberReservationAdmin(admin.ModelAdmin):
    list_display = ('numero','id_nature','id_dossier','id_template','origine','user','date')
    list_filter = ('id_nature','origine')
    search_fields = ('numero','id_dossier__numero','user__username')
    list_select_related = ('id_nature','id_dossier','id_template','user')
    readonly_fields = ('id',)

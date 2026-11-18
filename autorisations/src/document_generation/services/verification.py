"""Orchestration de la vérification et de sa synchronisation automatique."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from autorisations.models.models_generation import Balise, DocumentTemplate, TemplateBalise
from .analyzer import AnalysisReport, TemplateAnalyzer


class TemplateVerificationService:
    def verify(self, template_id):
        if settings.ENVIRONMENT != "dev":
            raise ValueError("La vérification est réservée au développement.")
        with transaction.atomic():
            # Sérialise deux vérifications et les modifications de cette fiche.
            template = DocumentTemplate.objects.select_for_update().get(pk=template_id)
            try:
                report = TemplateAnalyzer().analyze(template)
            except (ValidationError, ValueError) as exc:
                report = AnalysisReport(erreurs=[str(exc)])
            if report.analyse_complete:
                codes = [entry["code"] for entry in report.balises]
                catalogue = dict(Balise.objects.filter(Balise.perimetre(template), code__in=codes).values_list("code", "pk"))
                TemplateBalise.objects.filter(id_template=template).exclude(code__in=codes).delete()
                for code in codes:
                    defaults = {'id_balise_id': catalogue.get(code)}
                    if code == 'document.numero':
                        defaults['required'] = True
                    TemplateBalise.objects.update_or_create(id_template=template, code=code, defaults=defaults)
            # En cas de syntaxe illisible ou analyse partielle, conserver la
            # dernière liste complète et signaler qu'elle n'a pas été actualisée.
            template.rapport_validation = report.as_dict()
            template.date_verification = timezone.now()
            template.save(update_fields=("rapport_validation", "date_verification"))
            return template

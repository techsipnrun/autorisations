from django.core.management.base import BaseCommand, CommandError
from document_generation.services.pdf_preview import clean_previews, PdfPreviewError


class Command(BaseCommand):
    help = "Supprime les aperçus locaux dev inactifs depuis plus de deux heures."

    def add_arguments(self, parser):
        parser.add_argument("--max-age-hours", type=float, default=2)

    def handle(self, *args, **options):
        hours = options["max_age_hours"]
        if not 0 < hours < float("inf"):
            raise CommandError("Le délai doit être un nombre strictement positif et fini.")
        try:
            removed = clean_previews(hours * 3600)
        except (PdfPreviewError, OSError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f"{removed} répertoire(s) d'aperçu supprimé(s).")

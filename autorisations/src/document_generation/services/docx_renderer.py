"""Rendu DOCX entièrement en mémoire, sans accès au stockage final."""

from datetime import date, datetime
from io import BytesIO
from pathlib import Path

from docxtpl import DocxTemplate
from jinja2 import StrictUndefined
from jinja2.sandbox import SandboxedEnvironment
from django.utils.text import slugify
import smbclient


class DocxRenderError(Exception):
    pass


def format_word_value(value):
    # Les types restent natifs pour les conditions et les boucles Jinja.
    # Seul leur affichage dans le Word reçoit le format métier.
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        return value.strftime("%d/%m/%Y")
    if isinstance(value, bool):
        return "Oui" if value else "Non"
    return value


def build_preview_filename(template, dossier):
    name = slugify(template.nom)[:80] or "document"
    return f"Projet_{name}_{int(dossier.numero)}.docx"


class DocxRenderer:
    def render_to_memory(self, template_source, context):
        """Accepte le snapshot binaire validé, ou un fichier local pour les tests.

        Les vues utilisent exclusivement les octets lus et analysés dans le POST
        courant : aucune relecture susceptible de rendre un autre Word.
        """
        try:
            if isinstance(template_source, (str, Path)):
                if str(template_source).startswith(("\\\\", "//")):
                    with smbclient.open_file(str(template_source), mode="rb", share_access="rwd") as source:
                        template_source = source.read()
                else:
                    template_source = Path(template_source).read_bytes()
            if isinstance(template_source, bytes):
                template_source = BytesIO(template_source)
            tpl = DocxTemplate(template_source)
            tpl.init_docx()
        except Exception as exc:
            raise DocxRenderError("Le modèle Word est introuvable ou illisible.") from exc
        try:
            env = SandboxedEnvironment(undefined=StrictUndefined, autoescape=True, finalize=format_word_value)
            tpl.render(context, jinja_env=env, autoescape=True)
        except Exception as exc:
            raise DocxRenderError("Le modèle contient une erreur de rendu. Contactez l'administrateur.") from exc
        buffer = BytesIO()
        try:
            tpl.save(buffer)
            buffer.seek(0)
            return buffer
        except Exception as exc:
            buffer.close()
            raise DocxRenderError("Impossible de préparer le fichier Word à télécharger.") from exc

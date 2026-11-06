"""Source Word du NAS dev : résolution centralisée et lecture seule."""

import ntpath
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from dotenv import dotenv_values
import smbclient
from smbprotocol.exceptions import SMBException

from autorisations.models.models_generation import valider_chemin_template


class TemplatePathError(Exception):
    pass


def get_template_absolute_path(document_template):
    if settings.ENVIRONMENT != "dev":
        raise ValueError("L'accès aux templates est réservé à l'environnement dev.")
    try:
        valider_chemin_template(document_template.chemin_relatif)
    except ValidationError as exc:
        raise TemplatePathError("Le chemin du modèle Word est invalide.") from exc
    nas_root = dotenv_values(Path(settings.BASE_DIR) / ".env.dev").get("NAS_ROOT")
    if not nas_root or not nas_root.startswith("\\\\"):
        raise TemplatePathError("La racine NAS de développement est mal configurée.")
    nas_root = "\\\\" + "\\".join(part for part in nas_root.strip().split("\\") if part)
    base = ntpath.normpath(ntpath.join(nas_root, "Templates"))
    path = ntpath.normpath(ntpath.join(base, *document_template.chemin_relatif.split("/")))
    if ntpath.commonpath([base, path]).casefold() != base.casefold():
        raise TemplatePathError("Le modèle doit rester dans le dossier Templates/.")
    try:
        if not smbclient.path.isfile(path):
            raise TemplatePathError("Template introuvable : vérifiez son chemin dans Templates/.")
    except (OSError, SMBException, ValueError) as exc:
        raise TemplatePathError("Impossible de lire le template sur le NAS dev (chemin ou droits à vérifier).") from exc
    return path


def read_template_bytes(document_template):
    path = get_template_absolute_path(document_template)
    try:
        with smbclient.open_file(path, mode="rb", share_access="rwd") as source:
            return source.read()
    except (OSError, SMBException, ValueError) as exc:
        raise TemplatePathError("Impossible de lire le template sur le NAS dev (chemin ou droits à vérifier).") from exc

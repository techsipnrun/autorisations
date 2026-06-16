# instruction/templatetags/custom_filters.py
from django import template
import unicodedata
import re
from datetime import timedelta
from django.utils.timezone import localtime

register = template.Library()

@register.filter
def get_item(dictionary, key):
    return dictionary.get(key)


@register.filter
def url_name_from_label(label):
    """
    Transforme un label d'étape en nom d'URL Django, ex :
    "Passer en pré-instruction" -> "passer_en_pre_instruction_url"
    """
    label = unicodedata.normalize('NFD', label).encode('ascii', 'ignore').decode("utf-8")
    label = re.sub(r"[^a-zA-Z0-9]+", "_", label.strip().lower())

    return f"{label}_url"

@register.filter
def contains(value, substring):
    """Retourne True si substring est dans value"""
    if value is None:
        return False
    return str(substring) in value

@register.filter
def is_int(value):
    try:
        int(value)
        return True
    except (ValueError, TypeError):
        return False
    
@register.filter
def to_int(value):
    try:
        return int(value)
    except:
        return 0




@register.simple_tag
def format_periode_evenement(date_debut, date_fin):
    if not date_debut and not date_fin:
        return "à une date non renseignée"

    if date_debut:
        date_debut = localtime(date_debut)

    if date_fin:
        date_fin = localtime(date_fin)

    if date_debut and not date_fin:
        return f"le {date_debut.strftime('%d/%m/%Y')}"

    if date_fin and not date_debut:
        return f"le {date_fin.strftime('%d/%m/%Y')}"

    d1 = date_debut.date()
    d2 = date_fin.date()

    if d1 == d2:
        return f"le {d1.strftime('%d/%m/%Y')}"

    return f"du {d1.strftime('%d/%m/%Y')} au {d2.strftime('%d/%m/%Y')}"




DOCUMENTS = (
    ".doc", ".docx",
    ".odt", ".ott",
    ".rtf",
)

TABLEURS = (
    ".xls", ".xlsx",
    ".ods", ".ots",
    ".csv",
)

PRESENTATIONS = (
    ".ppt", ".pptx",
    ".odp", ".otp",
)

IMAGES = (
    ".png", ".jpg", ".jpeg",
    ".gif", ".bmp", ".tif", ".tiff",
    ".svg", ".webp",
)

CARTO = (
    ".kml", ".kmz",
    ".gpx",
    ".shp",
    ".geojson",
)

CODE = (
    ".xml",
    ".json",
    ".yaml", ".yml",
)

ARCHIVES = (
    ".zip", ".rar", ".7z",
    ".tar", ".gz",
)


@register.filter
def file_icon(filename):
    filename = filename.lower()

    if filename.endswith(".pdf"):
        return "logo_pdf.png"

    elif filename.endswith(DOCUMENTS):
        return "logo_word.png"

    elif filename.endswith(TABLEURS):
        return "excel.png"

    elif filename.endswith(PRESENTATIONS):
        return "powerpoint.png"

    elif filename.endswith(IMAGES):
        return "image.png"

    elif filename.endswith(CARTO):
        return "map.png"

    elif filename.endswith(CODE):
        return "code.png"

    elif filename.endswith(ARCHIVES):
        return "archive.png"

    elif filename.endswith(".txt"):
        return "text.png"

    return "file.png"


# @register.filter
# def filesize_fr(value):
#     if not value:
#         return ""

#     value = int(value)

#     for unit in ["o", "Ko", "Mo", "Go"]:
#         if value < 1024:
#             return f"{value:.1f} {unit}" if unit != "o" else f"{value} {unit}"
#         value /= 1024

#     return f"{value:.1f} To"
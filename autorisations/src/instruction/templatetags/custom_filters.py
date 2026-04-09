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
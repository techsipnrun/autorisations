# instruction/templatetags/custom_filters.py
from django import template
import unicodedata
import re

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
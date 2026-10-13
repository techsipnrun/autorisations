from django import template
from instruction.utils.cartographie import charger_configurations

register = template.Library()


@register.simple_tag
def configurations_cartographiques():
    return charger_configurations()

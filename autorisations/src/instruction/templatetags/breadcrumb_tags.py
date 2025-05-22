from django import template

register = template.Library()

@register.inclusion_tag("breadcrumb.html", takes_context=True)
def breadcrumb(context, items):
    """
    items = liste de dictionnaires : [{label: ..., url: ...}, ...]
    """
    return {'items': items}

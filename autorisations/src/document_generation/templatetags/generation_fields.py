from django import template
from autorisations.models.models_generation import Balise

register = template.Library()


@register.simple_tag
def information_groups(form, known_form, rows):
    groups = [dict(key='agida', title='Informations déjà connues', editor='known-editor', display='known-display',
                   fields=[], known_fields=[], rows=[]),
              dict(key='formulaire', title='Informations issues du formulaire', editor='form-source-editor',
                   display='form-source-display', fields=[], known_fields=[], rows=[])]
    sources = {}
    for current, target in [(form, 'fields'), (known_form, 'known_fields')]:
        if not hasattr(current, 'balise_map'):
            continue
        for name, balise in current.balise_map.items():
            index = 1 if balise.source == Balise.Source.FORMULAIRE else 0
            sources[balise.code] = index
            if current is known_form or balise.mode == Balise.Mode.CONNUE:
                groups[index][target].append(current[name])
    for row in rows or []:
        index = sources.get(row['code'], 1 if row.get('source') == Balise.Source.FORMULAIRE else 0)
        groups[index]['rows'].append(row)
    for group in groups:
        group['editing'] = group['key'] in getattr(known_form, 'edit_groups', set())
    return groups


@register.simple_tag
def manual_information_fields(form):
    return [form[name] for name, balise in form.balise_map.items()
            if balise.mode == Balise.Mode.A_RENSEIGNER] if hasattr(form, 'balise_map') else []

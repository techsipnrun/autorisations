"""Contexte incomplet réservé à l’aperçu, sans modifier les règles de génération."""
from .context_utils import set_nested_value
from .validation import lire_contexte, valeur_vide


def partial_preview_context(prepared, form, known_form, *, known_edited=False,
                            number=None, numbering_kind=None):
    form.is_valid()  # cleaned_data conserve uniquement les champs correctement typés.
    labels = {balise.code: current.fields[name].label
              for current in (form, known_form) if current is not None
              for name, balise in current.balise_map.items()}
    labels['document.numero'] = 'Numéro du document'
    fields = {balise.code: (form, name) for name, balise in form.balise_map.items()}
    if known_edited:
        known_form.is_valid()
        fields.update({balise.code: (known_form, name) for name, balise in known_form.balise_map.items()})
    context, missing = {}, []
    for balise in prepared['balises']:
        invalid = False
        raw = None
        if balise.code == 'document.numero':
            value = number
        elif balise.code in fields:
            current, name = fields[balise.code]
            invalid = name in current.errors
            value = current.cleaned_data.get(name)
            raw = current.data.get(current.add_prefix(name))
        else:
            value = lire_contexte(prepared['known_context'], balise.code)
        if invalid or ((balise.required or (balise.code == 'document.numero' and numbering_kind)) and valeur_vide(value)):
            missing.append({'code': balise.code, 'label': labels.get(balise.code) or balise.libelle or balise.code,
                            'reason': 'À corriger' if invalid and not valeur_vide(raw) else 'À renseigner'})
        # Ne jamais injecter une saisie mal typée, ni inventer de valeur métier.
        if invalid or valeur_vide(value):
            value = [] if balise.type == 'LIST' else None
        set_nested_value(context, balise.code, value)
    if numbering_kind and not any(b.code == 'document.numero' for b in prepared['balises']):
        set_nested_value(context, 'document.numero', number)
        if not number:
            missing.append({'code': 'document.numero', 'label': 'Numéro du document',
                            'reason': 'À renseigner'})
    return context, missing

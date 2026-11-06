from django import forms
from django.core.exceptions import ValidationError


class RepeatedTextWidget(forms.Widget):
    template_name = 'document_generation/widgets/repeated_text.html'

    def __init__(self, item_label='Élément', attrs=None):
        super().__init__(attrs)
        self.item_label = item_label or 'Élément'

    def value_from_datadict(self, data, files, name):
        if hasattr(data, 'getlist'):
            return data.getlist(name)
        return data.get(name, [])

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        values = value if isinstance(value, (list, tuple)) else ([] if value is None else [value])
        context['widget'].update(items=values or [''], item_label=self.item_label)
        return context

    def use_required_attribute(self, initial):
        return False  # Seule la liste doit être non vide ; les lignes vides sont ignorées.

    def id_for_label(self, id_):
        return f'{id_}_1' if id_ else ''


class RepeatedTextField(forms.Field):
    def to_python(self, value):
        if value in (None, ''):
            return []
        if not isinstance(value, (list, tuple)) or len(value) > 100:
            raise ValidationError('La liste doit contenir au maximum 100 lignes de texte.')
        result = []
        for item in value:
            if not isinstance(item, str) or len(item) > 500:
                raise ValidationError('Chaque élément doit être un texte de 500 caractères maximum.')
            if item.strip():
                result.append(item.strip())
        return result

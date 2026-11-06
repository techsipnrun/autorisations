import re
from .filename import resolve_filename

LABELS = {'dossier.numero':'Numéro du dossier','num_doss':'Numéro du dossier','date.annee':'Année en cours',
          'date.jour':'Date du jour','beneficiaire.identite':'Bénéficiaire','document.numero':'Numéro du document'}


def filename_editor_context(pattern, dossier, number=None):
    values = {}
    for code in set(re.findall(r'\{([^{}]+)\}', pattern)):
        try:
            value = resolve_filename('{'+code+'}.docx', dossier, document_number=number)
            values[code] = {'label': LABELS.get(code,code), 'value':value[:-5], 'pending':False}
        except (ValueError, KeyError):
            values[code] = {'label':LABELS.get(code,code),'value':'À générer' if code=='document.numero' else 'À compléter','pending':True}
    return values

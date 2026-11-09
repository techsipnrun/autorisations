"""Nommage déclaratif des PDF signés, sans réservation ni écriture de fichier."""
import re
from django.core.exceptions import ValidationError
from django.utils import timezone

DEFAULT_PATTERN = '{prefixe_fichier}{document.numero}_{date.jour_mois}.pdf'
VARIABLES = {'prefixe_fichier', 'document.numero', 'dossier.numero', 'date.jour_mois',
             'date.jour', 'date.annee', 'beneficiaire.identite'}


def validate_act_filename(value):
    if not value or len(value) > 200 or not value.lower().endswith('.pdf'):
        raise ValidationError('Indiquez un nom de fichier PDF, de 200 caractères maximum.')
    codes = re.findall(r'\{([^{}]+)\}', value)
    if set(codes) - VARIABLES:
        raise ValidationError('Variable de nommage inconnue.')
    if len(codes) != len(set(codes)):
        raise ValidationError('Chaque variable ne peut être utilisée qu’une seule fois.')
    literal = re.sub(r'\{[^{}]+\}', 'valeur', value)
    if re.search(r'[{}<>:"/\\|?*\x00-\x1f]', literal) or literal.startswith('.') or literal.rstrip(' .') != literal:
        raise ValidationError('Le nom ne doit contenir ni chemin ni caractère interdit.')
    if not literal[:-4].strip(' .-_'):
        raise ValidationError('Le nom du fichier est vide.')
    if re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', literal, re.I):
        raise ValidationError('Ce nom de fichier est réservé par Windows.')


def render_act_filename(nature, numero, *, dossier=None, today=None, day_month=None):
    pattern = nature.nom_fichier_signe
    validate_act_filename(pattern)
    today = today or timezone.localdate()
    # Conserver le préfixe, séparateurs inclus, et la référence sans préfixe d’affichage.
    values = {'prefixe_fichier': nature.prefixe_nom_fichier or '',
              'document.numero': numero or '',
              'date.jour_mois': day_month or today.strftime('%d-%m'),
              'date.jour': today.strftime('%d-%m-%y'), 'date.annee': str(today.year)}
    if '{dossier.numero}' in pattern:
        values['dossier.numero'] = getattr(dossier, 'numero', '')
    if '{beneficiaire.identite}' in pattern:
        from document_generation.services.filename import resolve_filename
        try:
            values['beneficiaire.identite'] = resolve_filename('{beneficiaire.identite}.docx', dossier)[:-5]
        except (ValueError, AttributeError) as exc:
            raise ValidationError('Le bénéficiaire doit être renseigné pour nommer le PDF signé.') from exc
    def substitute(match):
        code = match.group(1)
        value = str(values.get(code, ''))
        if not value.strip() and code != 'prefixe_fichier':
            raise ValidationError('Valeur manquante pour la variable ' + code + '.')
        return re.sub(r'[<>:"/\\|?*\x00-\x1f]', '-', re.sub(r'\s+', '-', value)).strip(' .')
    result = re.sub(r'\{([^{}]+)\}', substitute, pattern)
    result = re.sub(r'\s+', '-', result)
    validate_act_filename(result)
    if len(result.encode('utf-8')) > 255:
        raise ValidationError('Le nom du PDF signé est trop long.')
    return result

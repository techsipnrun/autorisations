"""Exemples ajoutés uniquement au Word de test, sans accès BDD ou NAS."""

from io import BytesIO
from docx import Document
from docx.shared import RGBColor


def add_repeated_names_example(source):
    document = Document(BytesIO(source))
    marker = 'Liste de noms à renseigner'
    if any(paragraph.text == marker for paragraph in document.paragraphs):
        return source
    document.add_heading(marker, level=2)
    document.add_paragraph('{%p for nom in projet.noms %}')
    document.add_paragraph('Nom : {{ nom }}')
    document.add_paragraph('{%p endfor %}')
    result = BytesIO()
    document.save(result)
    return result.getvalue()


def enrich_test_template(source):
    document = Document(BytesIO(source))
    marker = 'Exemples de mise en forme et de logique'
    if any(paragraph.text == marker for paragraph in document.paragraphs):
        return source
    document.add_heading(marker, level=1)
    paragraph = document.add_paragraph()
    paragraph.add_run('Commune : ').font.color.rgb = RGBColor.from_string('1F4E79')
    paragraph.add_run('{{ dossier.commune }}')
    document.add_paragraph('{%p if dossier.commune %}')
    paragraph = document.add_paragraph('La commune renseignée est {{ dossier.commune }}.')
    paragraph.runs[0].font.color.rgb = RGBColor.from_string('008040')
    document.add_paragraph('{%p else %}')
    paragraph = document.add_paragraph('Aucune commune renseignée.')
    paragraph.runs[0].font.color.rgb = RGBColor.from_string('C00000')
    document.add_paragraph('{%p endif %}')
    document.add_heading('Exemple de boucle', level=2)
    document.add_paragraph("{%p for element in ['Premier exemple', 'Deuxième exemple', 'Troisième exemple'] %}")
    paragraph = document.add_paragraph('{{ element }} — Dossier {{ dossier.numero }}')
    paragraph.runs[0].font.color.rgb = RGBColor.from_string('7030A0')
    document.add_paragraph('{%p endfor %}')
    document.add_paragraph('Les balises de contrôle occupent des paragraphes dédiés, supprimés au rendu.')
    result = BytesIO()
    document.save(result)
    return result.getvalue()

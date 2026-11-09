from types import SimpleNamespace
from unittest.mock import patch
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase
from document_generation.services import report_file_guard as service


class ReportFileGuardTests(SimpleTestCase):
    def row(self, filename, *, snapshot=None, target=None, reservation=None, folder='Test/Work/'):
        return SimpleNamespace(id_document=SimpleNamespace(titre=filename, emplacement=folder),
            id_numero_id=1 if reservation else None,
            id_numero=SimpleNamespace(id_nature=SimpleNamespace(nature=reservation)),
            template_snapshot=snapshot or {}, id_template=SimpleNamespace(
                id_nature=SimpleNamespace(nature=target)) if target else None)

    def test_nature_figee_prioritaire_et_anciens_templates_sans_numero(self):
        rows = [self.row('rapport.docx', snapshot={'nature_cible':'Rapport CA'}, target='Arrêté directeur'),
                self.row('arrete.docx', reservation='Arrêté directeur'),
                self.row('ancien.docx', target='Rapport CA'), self.row('sans_nature.docx'),
                self.row('ailleurs.docx', target='Rapport CA', folder='Autre/Work/')]
        with patch.object(service.DocumentGeneration, 'objects') as objects:
            objects.filter.return_value.select_related.return_value.defer.return_value = rows
            result = service.generated_report_files(SimpleNamespace(emplacement='Test/'))
        self.assertEqual([(item['filename'],item['is_report']) for item in result],
            [('rapport.docx',True),('arrete.docx',False),('ancien.docx',True)])

    def test_refus_autre_nature_et_acceptation_rapport_ou_manuel(self):
        dossier = SimpleNamespace(emplacement='Test/')
        with patch.object(service, 'generated_report_files', return_value=[
            {'filename':'arrete.docx','is_report':False}, {'filename':'rapport.docx','is_report':True}]):
            with self.assertRaisesMessage(ValidationError, 'Rapport CA'):
                service.validate_generated_report(dossier,'ARRETE.docx')
            self.assertIsNone(service.validate_generated_report(dossier,'rapport.docx'))
            self.assertIsNone(service.validate_generated_report(dossier,'manuel.docx'))

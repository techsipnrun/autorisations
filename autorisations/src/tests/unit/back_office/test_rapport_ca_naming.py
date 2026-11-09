from types import SimpleNamespace
from unittest.mock import patch
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory, SimpleTestCase
from autorisations.models.models_documents import DocumentNature
from autorisations.utils.act_filename import render_act_filename
from backoffice.forms.types_actes import RapportCAForm
from backoffice.views import types_actes
from datetime import date


class RapportCANamingTests(SimpleTestCase):
    def setUp(self):
        self.report=DocumentNature(id=92,nature='Rapport CA',est_acte=False,
            nom_fichier_signe='RapportCA_{date.jour_mois}.pdf')

    def test_regle_initiale_et_personnalisee_sans_numero_propre(self):
        self.assertEqual(render_act_filename(self.report,'2026-012',today=date(2026,11,9)), 'RapportCA_09-11.pdf')
        self.report.nom_fichier_signe='Rapport_{dossier.numero}_{document.numero}.pdf'
        self.assertEqual(render_act_filename(self.report,'2026-012',dossier=SimpleNamespace(numero=123)), 'Rapport_123_2026-012.pdf')

    def test_formulaire_limite_au_nommage(self):
        form=RapportCAForm({'nom_fichier_signe':'Rapport_{date.jour}.pdf','est_acte':'true','nature':'Autre'},instance=self.report)
        self.assertTrue(form.is_valid(),form.errors)
        self.assertEqual(list(form.fields),['nom_fichier_signe'])
        self.assertFalse(form.instance.est_acte)
        self.assertEqual(form.instance.nature,'Rapport CA')

    def test_enregistrement_valide_et_controle_admin(self):
        request=RequestFactory().post('/test',{'nom_fichier_signe':'Rapport_{date.jour}.pdf'})
        request.user=SimpleNamespace(is_authenticated=True,is_superuser=True)
        with patch.object(types_actes,'get_object_or_404',return_value=self.report),patch.object(RapportCAForm,'save') as save:
            response=types_actes.enregistrer_nommage_rapport_ca(request)
        self.assertEqual(response.status_code,200);save.assert_called_once()
        request.user.is_superuser=False
        with self.assertRaises(PermissionDenied):types_actes.enregistrer_nommage_rapport_ca(request)

    def test_regle_invalide_non_enregistree(self):
        request=RequestFactory().post('/test',{'nom_fichier_signe':'../rapport.pdf'})
        request.user=SimpleNamespace(is_authenticated=True,is_superuser=True)
        with patch.object(types_actes,'get_object_or_404',return_value=self.report),patch.object(RapportCAForm,'save') as save:
            response=types_actes.enregistrer_nommage_rapport_ca(request)
        self.assertEqual(response.status_code,400);save.assert_not_called()

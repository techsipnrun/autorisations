import json
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch

from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase, override_settings

from autorisations.models.models_generation import DocumentTemplate
from backoffice.views import documents
from document_generation.services.analyzer import AnalysisReport
from document_generation.services.verification import TemplateVerificationService


@override_settings(ENVIRONMENT="dev")
class TemplateVerificationTests(SimpleTestCase):
    def run_service(self, report):
        template = DocumentTemplate(id=1, chemin_relatif="test.docx")
        with patch("document_generation.services.verification.transaction.atomic", return_value=nullcontext()), patch(
            "document_generation.services.verification.DocumentTemplate.objects.select_for_update"
        ) as locked, patch(
            "document_generation.services.verification.TemplateAnalyzer.analyze", return_value=report
        ), patch("document_generation.services.verification.Balise.objects.filter") as catalogue, patch(
            "document_generation.services.verification.TemplateBalise.objects.filter"
        ) as liens, patch("document_generation.services.verification.TemplateBalise.objects.bulk_create") as create, patch.object(
            template, "save"
        ) as save:
            locked.return_value.get.return_value = template
            catalogue.return_value.values_list.return_value = [("dossier.numero", 7)]
            result = TemplateVerificationService().verify(1)
        return result, liens, create, save

    def test_synchronisation_complete_meme_avec_une_balise_inconnue(self):
        report = AnalysisReport(
            balises=[{"code": "dossier.numero", "statut": "CONNUE"}, {"code": "toto.foo", "statut": "INCONNUE"}],
            erreurs=["Balise inconnue : toto.foo."], syntaxe_valide=True, analyse_complete=True,
        )
        template, liens, create, save = self.run_service(report)
        liens.return_value.delete.assert_called_once()
        entries = create.call_args.args[0]
        self.assertEqual([(e.code, e.id_balise_id) for e in entries], [("dossier.numero", 7), ("toto.foo", None)])
        self.assertFalse(template.rapport_validation["valide"])
        self.assertEqual(template.rapport_validation["compteurs"]["INCONNUE"], 1)
        save.assert_called_once_with(update_fields=("rapport_validation", "date_verification"))

    def test_analyse_incomplete_preserve_les_associations(self):
        report = AnalysisReport(erreurs=["Erreur Jinja"])
        template, liens, create, _ = self.run_service(report)
        liens.assert_not_called()
        create.assert_not_called()
        self.assertFalse(template.rapport_validation["analyse_complete"])

    def test_word_sans_balise_supprime_les_anciens_liens(self):
        _, liens, create, _ = self.run_service(AnalysisReport(syntaxe_valide=True, analyse_complete=True))
        liens.return_value.delete.assert_called_once()
        create.assert_called_once_with([])

    @override_settings(ENVIRONMENT="prod")
    def test_service_interdit_en_prod(self):
        with self.assertRaises(ValueError):
            TemplateVerificationService().verify(1)


@override_settings(ENVIRONMENT="dev")
class DocumentsBackofficeTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def request(self, method="get", superuser=True):
        request = getattr(self.factory, method)("/back-office/documents/templates/")
        request.user = SimpleNamespace(is_authenticated=True, is_superuser=superuser)
        return request

    def test_acces_restreint_aux_superutilisateurs(self):
        with self.assertRaises(PermissionDenied):
            documents.catalogue(self.request(superuser=False))

    @override_settings(ENVIRONMENT="prod")
    def test_routes_inaccessibles_en_prod(self):
        with self.assertRaises(Http404):
            documents.catalogue(self.request())

    def test_verification_refuse_get(self):
        self.assertEqual(documents.verifier(self.request(), 1).status_code, 405)

    def test_telechargement_source_sans_generation(self):
        template = DocumentTemplate(id=1, chemin_relatif="TEST/test_generation.docx")
        with patch("backoffice.views.documents.get_object_or_404", return_value=template), patch(
            "document_generation.services.template_path.read_template_bytes", return_value=b"source-docx"
        ) as read:
            response = documents.telecharger(self.request(), 1)
        try:
            self.assertEqual(b"".join(response.streaming_content), b"source-docx")
            self.assertIn('filename="test_generation.docx"', response["Content-Disposition"])
            self.assertEqual(response["Cache-Control"], "private, no-store")
            read.assert_called_once_with(template)
        finally:
            response.close()

    def test_telechargement_reserve_admin_et_get(self):
        self.assertEqual(documents.telecharger(self.request("post"), 1).status_code, 405)
        with self.assertRaises(PermissionDenied):
            documents.telecharger(self.request(superuser=False), 1)

    @override_settings(ENVIRONMENT="prod")
    def test_telechargement_interdit_en_prod(self):
        with self.assertRaises(Http404):
            documents.telecharger(self.request(), 1)

    def test_catalogue_lit_sans_verifier(self):
        with patch("backoffice.views.documents.DocumentTemplate.objects.select_related") as templates:
            templates.return_value.prefetch_related.return_value = []
            response = documents.catalogue(self.request())
        self.assertEqual(json.loads(response.content), {"templates": []})

    def test_options_demarches_utilisent_seulement_le_type(self):
        with patch("backoffice.views.documents.DocumentNature.objects.order_by", return_value=[]), patch(
            "backoffice.views.documents.Demarche.objects.order_by",
            return_value=[SimpleNamespace(pk=7, type="Travaux")],
        ):
            response = documents.options_edition(self.request())
        self.assertEqual(json.loads(response.content)["demarches"], [{"id": 7, "nom": "Travaux"}])

    @override_settings(NAS_ROOT=r"\\serveur\partage_dev")
    def test_options_affichent_la_racine_configuree_sans_acces_nas(self):
        with patch("backoffice.views.documents.DocumentNature.objects.order_by", return_value=[]), patch(
            "backoffice.views.documents.Demarche.objects.order_by", return_value=[]
        ):
            response = documents.options_edition(self.request())
        self.assertEqual(json.loads(response.content)["nas_root"], "//serveur/partage_dev/")

    def test_serialisation_configuration_sortie(self):
        from document_generation.forms import DocumentTemplateForm
        template = DocumentTemplate(id=1, nom="Test", chemin_relatif="TEST/test.docx",
                                    destination_relative="{dossier.emplacement}/Work/",
                                    nom_fichier="DIR-I-{num_doss}.docx")
        from autorisations.models.models_documents import DocumentNature
        template.id_nature = DocumentNature(id=3, nature="Arrêté directeur")
        with patch.object(type(template.demarches), "all", return_value=[]):
            data = documents.serialiser(template)
        self.assertEqual(data["destination_relative"], "{dossier.emplacement}/Work/")
        self.assertEqual(data["nom_fichier"], "DIR-I-{num_doss}.docx")
        template.id_nature = None
        with patch.object(type(template.demarches), 'all', return_value=[]):
            data = documents.serialiser(template)
        self.assertEqual(data['nature'], '')
        self.assertIsNone(data['id_nature'])
        self.assertTrue(data['configuration_complete'])
        self.assertFalse(DocumentTemplateForm.base_fields['id_nature'].required)

    def test_verification_post_declenche_le_service(self):
        with patch("backoffice.views.documents.get_object_or_404"), patch(
            "document_generation.services.verification.TemplateVerificationService.verify"
        ) as verify, patch("backoffice.views.documents.DocumentTemplate.objects.select_related"), patch(
            "backoffice.views.documents.serialiser", return_value={"rapport": {"valide": True}}
        ):
            response = documents.verifier(self.request("post"), 1)
        verify.assert_called_once_with(1)
        self.assertEqual(response.status_code, 200)

    def test_fiche_contient_bouton_csrf_et_rapport(self):
        html = render_to_string("backoffice/back_office_documents.html", {"csrf_token": "test-token"})
        self.assertNotIn('data-document-verifier', html)
        self.assertIn('data-documents-verification', html)
        self.assertIn("csrfmiddlewaretoken", html)
        self.assertIn("data-document-rapport", html)

    def test_navigation_documents_visible_uniquement_en_dev(self):
        for active in (True, False):
            html = render_to_string("backoffice/back_office.html", {"generation_documents_dev": active, "csrf_token": "test-token"})
            self.assertEqual('id="back-office-documents-nav"' in html, active)

    def test_edition_refuse_get_et_non_admin(self):
        self.assertEqual(documents.enregistrer(self.request(), 1).status_code, 405)
        with self.assertRaises(PermissionDenied):
            documents.enregistrer(self.request("post", superuser=False), 1)

    @override_settings(ENVIRONMENT="prod")
    def test_edition_interdite_en_prod(self):
        with self.assertRaises(Http404):
            documents.enregistrer(self.request("post"), 1)

    def test_formulaire_ne_permet_pas_edition_du_rapport(self):
        from document_generation.forms import DocumentTemplateForm
        self.assertEqual(set(DocumentTemplateForm.base_fields), {"nom", "id_nature", "chemin_relatif", "actif", "demarches", "destination_relative", "nom_fichier"})
        form = DocumentTemplateForm()
        self.assertTrue(form.fields["destination_relative"].required)
        self.assertTrue(form.fields["nom_fichier"].required)

    def test_edition_invalide_ne_sauvegarde_pas(self):
        with patch("backoffice.views.documents.transaction.atomic", return_value=nullcontext()), patch(
            "backoffice.views.documents.DocumentTemplate.objects.select_for_update"
        ), patch("backoffice.views.documents.get_object_or_404"), patch(
            "document_generation.forms.DocumentTemplateForm"
        ) as form:
            form.return_value.is_valid.return_value = False
            form.return_value.errors.get_json_data.return_value = {"chemin_relatif": [{"message": "Chemin invalide"}]}
            response = documents.enregistrer(self.request("post"), 1)
        self.assertEqual(response.status_code, 400)
        form.return_value.save.assert_not_called()

    def test_creation_template_sans_nature_et_associations_enregistrees(self):
        with patch('backoffice.views.documents.transaction.atomic', return_value=nullcontext()), patch(
            'document_generation.forms.DocumentTemplateForm'
        ) as form, patch('document_generation.services.verification.TemplateVerificationService.verify') as verify, patch(
            'backoffice.views.documents.DocumentTemplate.objects.select_related'
        ), patch('backoffice.views.documents.serialiser', return_value={'id': 7, 'id_nature': None}):
            form.return_value.is_valid.return_value = True
            form.return_value.save.return_value.pk = 7
            response = documents.enregistrer(self.request('post'))
        self.assertEqual(response.status_code, 201)
        instance = form.call_args.kwargs['instance']
        self.assertIsNone(instance.pk)
        self.assertIsNone(instance.id_nature_id)
        form.return_value.save.assert_called_once_with(commit=False)
        form.return_value.save_m2m.assert_called_once()
        verify.assert_called_once_with(7)

    def test_creation_invalide_et_acces_refuses(self):
        self.assertEqual(documents.enregistrer(self.request()).status_code, 405)
        with self.assertRaises(PermissionDenied):
            documents.enregistrer(self.request('post', superuser=False))
        with override_settings(ENVIRONMENT='prod'), self.assertRaises(Http404):
            documents.enregistrer(self.request('post'))
        with patch('backoffice.views.documents.transaction.atomic', return_value=nullcontext()), patch(
            'document_generation.forms.DocumentTemplateForm'
        ) as form:
            form.return_value.is_valid.return_value = False
            form.return_value.errors.get_json_data.return_value = {'nom': [{'message': 'Nom déjà utilisé.'}]}
            response = documents.enregistrer(self.request('post'))
        self.assertEqual(response.status_code, 400)
        form.return_value.save.assert_not_called()

    def test_edition_sauvegarde_les_demarches_et_invalide_rapport(self):
        with patch("backoffice.views.documents.transaction.atomic", return_value=nullcontext()), patch(
            "backoffice.views.documents.DocumentTemplate.objects.select_for_update"
        ), patch("backoffice.views.documents.get_object_or_404"), patch(
            "document_generation.forms.DocumentTemplateForm"
        ) as form, patch("document_generation.services.verification.TemplateVerificationService.verify"), patch("backoffice.views.documents.DocumentTemplate.objects.select_related"), patch(
            "backoffice.views.documents.serialiser", return_value={"code": "test"}
        ):
            form.return_value.is_valid.return_value = True
            form.return_value.has_changed.return_value = True
            response = documents.enregistrer(self.request("post"), 1)
        self.assertEqual(response.status_code, 200)
        instance = form.return_value.save.return_value
        self.assertIsNone(instance.rapport_validation)
        self.assertIsNone(instance.date_verification)
        instance.save.assert_called_once()
        form.return_value.save_m2m.assert_called_once()

    def test_verification_automatique_tous_les_templates(self):
        with patch("backoffice.views.documents.DocumentTemplate.objects.order_by") as ids, patch(
            "document_generation.services.verification.TemplateVerificationService.verify"
        ) as verify, patch("backoffice.views.documents.DocumentTemplate.objects.select_related") as templates:
            ids.return_value.values_list.return_value = [1, 2, 3]
            templates.return_value.prefetch_related.return_value = []
            response = documents.verifier_tous(self.request('post'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual([call.args[0] for call in verify.call_args_list], [1, 2, 3])

    def test_verification_automatique_refuse_get(self):
        self.assertEqual(documents.verifier_tous(self.request()).status_code, 405)

    def test_verification_automatique_respecte_permissions(self):
        with self.assertRaises(PermissionDenied):
            documents.verifier_tous(self.request('post', superuser=False))

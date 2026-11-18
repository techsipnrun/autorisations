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


class SharedBaliseMetadataTests(SimpleTestCase):
    def test_meme_code_local_necrase_pas_la_definition_dun_autre_template(self):
        with patch.object(documents.Balise.objects, 'values', return_value=[
            {'id': 1, 'code': 'toto', 'source': 'MANUELLE', 'id_template_id': 10, 'required': True},
            {'id': 2, 'code': 'toto', 'source': 'FORMULAIRE', 'id_template_id': 20, 'required': False},
        ]), patch.object(documents.TemplateBalise.objects, 'values') as usages:
            usages.return_value.order_by.return_value = [
                {'code': 'toto', 'id_template_id': 10, 'id_template__nom': 'Acte'},
                {'code': 'toto', 'id_template_id': 20, 'id_template__nom': 'Fiche'},
                {'code': 'toto', 'id_template_id': 30, 'id_template__nom': 'Autre'},
            ]
            result = documents.catalogue_balises()
        self.assertEqual(set(result), {'10:toto', '20:toto'})
        self.assertEqual(result['10:toto']['templates'], [{'id': 10, 'nom': 'Acte'}])
        self.assertEqual(result['20:toto']['templates'], [{'id': 20, 'nom': 'Fiche'}])
        self.assertTrue(result['10:toto']['required'])
        self.assertFalse(result['20:toto']['required'])

    def test_configuration_globale_et_usages_par_code_sans_lecture_nas(self):
        with patch.object(documents.Balise.objects, 'values', return_value=[{
            'id': 7, 'code': 'dossier.numero', 'source': 'AGIDA', 'mode': 'CONNUE',
            'type': 'INTEGER', 'required': True, 'actif': True,
        }]), patch.object(documents.TemplateBalise.objects, 'values') as usages:
            usages.return_value.order_by.return_value = [
                {'code': 'dossier.numero', 'id_template_id': 1, 'id_template__nom': 'Acte'},
                {'code': 'dossier.numero', 'id_template_id': 2, 'id_template__nom': 'Fiche'},
                {'code': 'inconnue', 'id_template_id': 2, 'id_template__nom': 'Fiche'},
            ]
            result = documents.catalogue_balises()
        self.assertEqual(set(result), {'*:dossier.numero'})
        self.assertEqual(result['*:dossier.numero']['source'], 'AGIDA')
        self.assertTrue(result['*:dossier.numero']['required'])
        self.assertEqual(result['*:dossier.numero']['templates'], [{'id': 1, 'nom': 'Acte'}, {'id': 2, 'nom': 'Fiche'}])


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
        ) as liens, patch("document_generation.services.verification.TemplateBalise.objects.update_or_create") as create, patch.object(
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
        liens.return_value.exclude.return_value.delete.assert_called_once()
        self.assertEqual(create.call_count, 2)
        self.assertEqual(create.call_args_list[0].kwargs['defaults'], {'id_balise_id': 7})
        self.assertNotIn('required', create.call_args_list[0].kwargs['defaults'])
        self.assertEqual(create.call_args_list[1].kwargs['defaults'], {'id_balise_id': None})
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
        liens.return_value.exclude.return_value.delete.assert_called_once()
        create.assert_not_called()

    @override_settings(ENVIRONMENT="prod")
    def test_service_interdit_en_prod(self):
        with self.assertRaises(ValueError):
            TemplateVerificationService().verify(1)


@override_settings(ENVIRONMENT="dev")
class DocumentsBackofficeTests(SimpleTestCase):
    def test_obligation_enregistree_uniquement_pour_le_template_cible(self):
        template=SimpleNamespace(pk=15,balises_detectees=SimpleNamespace(all=lambda:[]),rapport_validation={'balises':[{'code':'dossier.nom'}]})
        request=self.factory.post('/',{'code':'dossier.nom','required':'true'})
        request.user=SimpleNamespace(is_authenticated=True,is_superuser=True)
        with patch('backoffice.views.documents.transaction.atomic',return_value=nullcontext()), patch(
            'backoffice.views.documents.get_object_or_404',return_value=template), patch(
            'backoffice.views.documents.DocumentTemplate.objects.select_for_update'), patch(
            'backoffice.views.documents.Balise.objects.filter') as definition, patch(
            'backoffice.views.documents.Balise.perimetre',return_value=None), patch(
            'backoffice.views.documents.TemplateBalise.objects.update_or_create') as save:
            definition.return_value.first.return_value=None
            response=documents.enregistrer_obligation(request,15)
        self.assertEqual(response.status_code,200)
        save.assert_called_once_with(id_template=template,code='dossier.nom',defaults={'required':True,'id_balise':None})

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

    @patch('backoffice.views.documents.catalogue_balises', return_value={})
    def test_options_demarches_utilisent_seulement_le_type(self, catalogue):
        with patch("backoffice.views.documents.DocumentNature.objects.order_by", return_value=[]), patch(
            "backoffice.views.documents.Demarche.objects.order_by",
            return_value=[SimpleNamespace(pk=7, type="Travaux")],
        ):
            response = documents.options_edition(self.request())
        self.assertEqual(json.loads(response.content)["demarches"], [{"id": 7, "nom": "Travaux"}])

    @override_settings(NAS_ROOT=r"\\serveur\partage_dev")
    @patch('backoffice.views.documents.catalogue_balises', return_value={})
    def test_options_affichent_la_racine_configuree_sans_acces_nas(self, catalogue):
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
        template._prefetched_objects_cache = {"balises_detectees": []}
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

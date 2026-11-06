from contextlib import ExitStack
from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.http import Http404, HttpResponse
from django.core.exceptions import PermissionDenied
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import include, path, reverse

from autorisations.models.models_generation import Balise, DocumentTemplate
from autorisations.models.models_instruction import Dossier
from document_generation.forms import DynamicDocumentForm
from document_generation.services.context_utils import merge_contexts, set_nested_value
from document_generation.services.preparation import DocumentPreparationService
from document_generation.services.analyzer import AnalysisReport, TemplateAnalyzer
from document_generation.services.validation import GenerationContextValidator
from document_generation import views
from document_generation.services.docx_renderer import DocxRenderError
from docx import Document


urlpatterns = [
    path("document-generation/", include("document_generation.urls")),
    path("back-office/", lambda request: HttpResponse(), name="back_office"),
]


def balise(pk=42, code="projet.quantite", type="INTEGER", mode="A_RENSEIGNER", required=True, allow_blank=False):
    return Balise(id=pk, code=code, libelle="Quantité", type=type, mode=mode,
                  required=required, allow_blank=allow_blank, help_text="Valeur attendue.")


class DynamicDocumentFormTests(SimpleTestCase):
    def test_noms_html_et_contexte_imbrique(self):
        form = DynamicDocumentForm({"balise_42": "15"}, balises=[balise()])
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(list(form.fields), ["balise_42"])
        self.assertEqual(form.to_manual_values(), {"projet.quantite": 15})
        self.assertEqual(form.to_context(), {"projet": {"quantite": 15}})

    def test_conversions_des_six_types(self):
        for type, raw, expected in (("TEXT", " texte ", "texte"), ("TEXTAREA", "Ligne 1\nLigne 2", "Ligne 1\nLigne 2"),
                                    ("INTEGER", "0", 0), ("DECIMAL", "1.25", Decimal("1.25")),
                                    ("DATE", "2026-11-03", date(2026, 11, 3)), ("BOOLEAN", "false", False)):
            with self.subTest(type=type):
                form = DynamicDocumentForm({"balise_42": raw}, balises=[balise(type=type)])
                self.assertTrue(form.is_valid(), form.errors)
                self.assertEqual(form.to_manual_values()["projet.quantite"], expected)

    def test_booleen_obligatoire_exige_choix_mais_accepte_non(self):
        for data in ({}, {"balise_42": ""}):
            self.assertFalse(DynamicDocumentForm(data, balises=[balise(type="BOOLEAN")]).is_valid())
        self.assertTrue(DynamicDocumentForm({"balise_42": "false"}, balises=[balise(type="BOOLEAN")]).is_valid())

    def test_saisies_invalides_ne_construisent_pas_de_contexte(self):
        for type, raw in (("INTEGER", "texte"), ("DECIMAL", "NaN"), ("DATE", "2026-99-99"), ("BOOLEAN", "oui")):
            with self.subTest(type=type):
                form = DynamicDocumentForm({"balise_42": raw}, balises=[balise(type=type)])
                self.assertFalse(form.is_valid())
                with self.assertRaises(ValueError):
                    form.to_context()

    def test_facultative_vide_ou_espaces_sont_acceptes(self):
        form = DynamicDocumentForm({"balise_42": ""}, balises=[balise(type="TEXT", required=False)])
        self.assertTrue(form.is_valid())
        self.assertEqual(form.to_manual_values(), {})
        self.assertTrue(DynamicDocumentForm({"balise_42": "  "}, balises=[balise(type="TEXT", required=False)]).is_valid())

    def test_required_refuse_absence_et_vide_meme_si_allow_blank_historique(self):
        definition = balise(type="TEXT", allow_blank=True)
        self.assertFalse(DynamicDocumentForm({}, balises=[definition]).is_valid())
        self.assertFalse(DynamicDocumentForm({"balise_42": ""}, balises=[definition]).is_valid())

    def test_type_non_supporte_refuse_explicitement(self):
        with self.assertRaisesRegex(ValueError, "SELECT"):
            DynamicDocumentForm(balises=[balise(type="SELECT")])

    def test_champ_injecte_hors_formulaire_ignore(self):
        form = DynamicDocumentForm({"balise_42": "3", "dossier.numero": "999", "balise_1": "999"}, balises=[balise()])
        self.assertEqual(form.to_context(), {"projet": {"quantite": 3}})


class ContextUtilsTests(SimpleTestCase):
    def test_structures_imbriquees_et_aucune_mutation(self):
        context = {}
        set_nested_value(context, "projet.quantite", 0)
        original = {"beneficiaire": {"nom": None}}
        merged = merge_contexts(original, {"beneficiaire": {"nom": "DUPONT"}, **context})
        self.assertEqual(merged["beneficiaire"]["nom"], "DUPONT")
        self.assertEqual(original, {"beneficiaire": {"nom": None}})

    def test_collisions_et_ecrasements_refuses(self):
        with self.assertRaises(ValueError):
            set_nested_value({"projet": 1}, "projet.quantite", 2)
        for value in (0, False, "DUPONT"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                merge_contexts({"valeur": value}, {"valeur": 1})


class PreparationTests(SimpleTestCase):
    def test_template_de_formulaire_utilise_les_balises_attendues(self):
        path = Path(__file__).resolve().parents[3] / "document_generation/test_templates/test_formulaire.docx"
        definitions = [balise(1, "dossier.numero", mode="CONNUE"),
                       balise(2, "beneficiaire.nom_complet", mode="CONNUE"),
                       balise(3, "projet.quantite_prelevement", type="DECIMAL"),
                       balise(4, "projet.commentaire", type="TEXTAREA", required=False, allow_blank=True)]
        report = TemplateAnalyzer().analyze_bytes(path.read_bytes(), definitions)
        self.assertTrue(report.valide, report.erreurs)
        self.assertEqual(len(report.balises), 4)

    def test_resout_uniquement_les_balises_connues_et_affiche_manuelle_facultative(self):
        definitions = [balise(1, "dossier.numero", mode="CONNUE"), balise(required=False)]
        report = AnalysisReport(balises=[{"code": b.code, "statut": b.mode} for b in definitions],
                                syntaxe_valide=True, analyse_complete=True)
        with patch("document_generation.services.preparation.TemplateAnalyzer.analyze_with_source", return_value=(b"snapshot", report)), patch(
            "document_generation.services.preparation.Balise.objects.filter", return_value=MagicMock(prefetch_related=MagicMock(return_value=definitions))
        ), patch("document_generation.services.preparation.DocumentContextBuilder.build", return_value={"dossier": {"numero": 30769307}}) as build:
            dossier = Dossier(id=1, numero=30769307)
            result = DocumentPreparationService().prepare(dossier, DocumentTemplate(id=1))
        build.assert_called_once_with(dossier, ["dossier.numero"], balises=definitions)
        self.assertEqual(result["form_balises"], [definitions[1]])
        self.assertEqual(result["known_rows"][0]["value"], 30769307)

    def test_template_invalide_bloque_avant_resolution(self):
        with patch("document_generation.services.preparation.TemplateAnalyzer.analyze_with_source", return_value=(b"", AnalysisReport(erreurs=["Erreur Jinja"]))), patch(
            "document_generation.services.preparation.DocumentContextBuilder.build"
        ) as build:
            result = DocumentPreparationService().prepare(Dossier(id=1), DocumentTemplate(id=1))
        self.assertEqual(result["errors"], ["Erreur Jinja"])
        build.assert_not_called()


@override_settings(ENVIRONMENT="dev", ROOT_URLCONF=__name__)
class GenerationPageTests(SimpleTestCase):
    def setUp(self):
        self.dossier = Dossier(id=1, numero=30769307, nom_dossier="Dossier test", id_demarche_id=7)
        self.template = MagicMock()
        self.template.demarches.exists.return_value = False
        self.definitions = [balise(1, "dossier.numero", mode="CONNUE"), balise()]
        self.known = {"dossier": {"numero": 30769307}}
        self.prepared = {"balises": self.definitions, "known_context": self.known,
                         "known_rows": [{"code": "dossier.numero", "libelle": "Numéro", "value": 30769307}],
                         "form_balises": [self.definitions[1]], "errors": []}

    def call_view(self, data=None, superuser=True, prepared=None, preview_available=False, shell=None, reloads=0, session=None):
        request = RequestFactory().get("/") if data is None else RequestFactory().post("/", data)
        request.user = SimpleNamespace(is_authenticated=True, is_superuser=superuser, pk=42)
        request.session = session if session is not None else {}
        with ExitStack() as stack:
            stack.enter_context(patch("document_generation.views.dossier_history", return_value={"generation_history": []}))
            stack.enter_context(patch("document_generation.views.PdfPreviewService.available", return_value=preview_available))
            stack.enter_context(patch("document_generation.views.get_object_or_404", side_effect=[self.dossier, self.template] * (2 + reloads)))
            stack.enter_context(patch("document_generation.views.DocumentPreparationService.prepare", return_value=prepared or self.prepared))
            rendered = stack.enter_context(patch("document_generation.views.render", return_value=HttpResponse()))
            response = views.generer_document(request, 30769307, 1, _shell=shell)
            if response.status_code == 303:
                self.assertEqual(response['Location'], request.get_full_path())
                restored = RequestFactory().get(response['Location'])
                restored.user, restored.session = request.user, request.session
                response = views.generer_document(restored, 30769307, 1, _shell=shell)
                for _ in range(reloads):
                    response = views.generer_document(restored, 30769307, 1, _shell=shell)
        return response, rendered.call_args.args[2] if rendered.call_args else None

    def test_get_affiche_seulement_champ_manquant(self):
        response, context = self.call_view()
        self.assertEqual(list(context["form"].fields), ["balise_42"])
        self.assertFalse(context["complete"])
        self.assertEqual(response["Cache-Control"], "private, no-store")

    def test_nom_du_brouillon_suit_la_configuration_modifiee_sans_perdre_les_saisies(self):
        from hashlib import sha256
        key = sha256(b'/').hexdigest()
        self.template.nom_fichier = 'nouveau_{dossier.numero}.docx'
        for original, expected in [('ancien.docx', self.template.nom_fichier),
                                   (self.template.nom_fichier, 'personnalise.docx')]:
            with self.subTest(original=original):
                session = {'document_generation_drafts': {key: {
                    'template_filename': original,
                    'values': {'output_filename': ['personnalise.docx'], 'balise_42': ['15']},
                }}}
                _, context = self.call_view(session=session)
                self.assertEqual(context['filename_pattern'], expected)
                self.assertEqual(context['form']['balise_42'].value(), '15')

    def test_brouillon_dune_autre_url_ne_preremplit_pas_les_champs(self):
        from hashlib import sha256
        key = sha256(b'/document-generation/dossier/999/template/8/').hexdigest()
        session = {'document_generation_drafts': {key: {'values': {'balise_42': ['987']}}}}
        _, context = self.call_view(session=session)
        self.assertIsNone(context['form']['balise_42'].value())

    def test_numero_non_repris_du_brouillon_et_retour_post_a_usage_unique(self):
        from hashlib import sha256
        from autorisations.models.models_documents import DocumentNature
        self.template.pk = 1
        self.template.id_nature_id = 3
        self.template.id_nature = DocumentNature(id=3, nature='Arrêté directeur', est_acte=True)
        self.template.nom_fichier = 'test.docx'
        key = sha256(b'/').hexdigest()
        for immediate_return in (False, True):
            with self.subTest(immediate_return=immediate_return):
                session = {'document_generation_drafts': {key: {
                    'values': {'balise_42': ['15'], 'number_selection': ['reservation']},
                    'return_number_once': immediate_return,
                }}, 'document_number_states': {'1:1': {'request_key': 'test', 'selected': 'ancien'}}}
                with patch('document_generation.views.selected_number', return_value=None) as selected:
                    self.call_view(session=session)
                    self.assertEqual(selected.call_args.args[0], 'reservation' if immediate_return else '')
                    self.call_view(session=session)
                    self.assertEqual(selected.call_args.args[0], '')
                self.assertNotIn('selected', session['document_number_states']['1:1'])

    def test_actualisation_ne_regenere_pas_le_fichier_et_conserve_les_saisies(self):
        output = {'filename': 'test.docx', 'destination': '//nas/dev/Work/'}
        with patch('document_generation.views.DocxRenderer.render_to_memory', return_value=BytesIO(b'docx')) as renderer, patch(
            'document_generation.views.RecordGenerationService.save', return_value=output
        ) as save:
            response, context = self.call_view({'action': 'generate_file', 'balise_42': '15'},
                prepared={**self.prepared, 'template_bytes': b'source'}, reloads=2)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(context['complete'])
        self.assertEqual(context['form'].data['balise_42'], '15')
        self.assertEqual(context['generated_file'], output)
        save.assert_called_once()
        renderer.assert_called_once()

    def test_actualisation_ne_reconvertit_pas_le_pdf(self):
        self.template.pk = 1
        with patch('document_generation.views.DocxRenderer.render_to_memory', return_value=BytesIO(b'docx')), patch(
            'document_generation.views.PdfPreviewService.create_preview'
        ) as create:
            _, context = self.call_view({'action': 'preview_pdf', 'balise_42': '15'},
                prepared={**self.prepared, 'template_bytes': b'source'}, preview_available=True, reloads=2)
        self.assertTrue(context['preview_exists'])
        self.assertEqual(context['form'].data['balise_42'], '15')
        create.assert_called_once()

    def test_post_valide_reconstruit_et_revalide_sans_rendu_word(self):
        with patch("docxtpl.DocxTemplate.render", side_effect=AssertionError("Rendu interdit")):
            _, context = self.call_view({"balise_42": "15", "balise_1": "999"})
        self.assertTrue(context["complete"])
        self.assertEqual(context["final_context"], {"dossier": {"numero": 30769307}, "projet": {"quantite": 15}})
        self.assertIn('"quantite": 15', context["context_json"])

    def test_page_integree_revalide_et_conserve_demarche_du_preview(self):
        self.template.pk = 3
        _, context = self.call_view({"balise_42": "15"}, preview_available=True,
                                    shell={"selected_demarche": SimpleNamespace(pk=8), "demarches_generation": []})
        self.assertTrue(context["complete"])
        self.assertEqual(context["final_context"]["projet"]["quantite"], 15)
        self.assertIn("demarche=8", context["preview_url"])
        self.assertEqual(context["selected_demarche"].pk, 8)

    def test_post_invalide_reaffiche_erreur(self):
        _, context = self.call_view({"balise_42": "texte"})
        self.assertFalse(context["complete"])
        self.assertIn("balise_42", context["form"].errors)

    def test_generation_fichier_nas_uniquement_apres_validation(self):
        output = {"filename": "DIR-30769307_2.docx", "destination": "//nas/dev/Dossier/Work/"}
        with patch("document_generation.views.DocxRenderer.render_to_memory", return_value=BytesIO(b"docx")), patch(
            "document_generation.views.RecordGenerationService.save", return_value=output
        ) as save:
            _, context = self.call_view({"balise_42": "15", "action": "generate_file"},
                                        prepared={**self.prepared, "template_bytes": b"source"})
        self.assertEqual(context["generated_file"], output)
        save.assert_called_once()
        html = render_to_string("document_generation/generation_form.html", context)
        self.assertIn("DIR-30769307_2.docx", html)
        self.assertIn("//nas/dev/Dossier/Work/", html)
        with patch("document_generation.views.RecordGenerationService.save") as save:
            self.call_view({"balise_42": "incorrect", "action": "generate_file"})
        save.assert_not_called()

    def test_numero_systeme_ignore_les_saisies_falsifiees_et_est_transmis_au_fichier(self):
        from uuid import uuid4
        from autorisations.models.models_documents import DocumentNature
        self.template.pk=1;self.template.id_nature_id=3
        self.template.id_nature=DocumentNature(id=3,nature='Arrêté directeur',est_acte=True)
        self.template.nom_fichier='jeudi_{document.numero}.docx'
        reservation=SimpleNamespace(pk=uuid4(),numero='2026-112')
        definition=balise(2,'document.numero',mode='CONNUE',type='TEXT')
        prepared={**self.prepared,'balises':[*self.definitions,definition],
            'known_context':{**self.known,'document':{'numero':'2026-112'}},'template_bytes':b'source'}
        with patch('document_generation.views.selected_number',side_effect=lambda token,*args: reservation if token else None), patch(
            'document_generation.views.DocxRenderer.render_to_memory',return_value=BytesIO(b'word')
        ), patch('document_generation.views.RecordGenerationService.save',return_value={'filename':'jeudi_2026-112.docx','destination':'Test/Work/'}) as save:
            _,context=self.call_view({'action':'generate_file','balise_42':'15','edit_known':'1',
                'known-balise_1':'30769307','known-balise_2':'FAUX','number_selection':str(reservation.pk),
                'output_filename':'jeudi_{document.numero}.docx'},prepared=prepared)
        self.assertFalse(context['complete'])
        self.assertIsNone(context['number_reservation'])
        self.assertNotIn('balise_2',context['known_form'].fields)
        self.assertEqual(save.call_args.args[4]['document']['numero'],'2026-112')
        self.assertIs(save.call_args.kwargs['number_reservation'],reservation)

    def test_nature_numerotee_sans_selection_interdit_la_generation(self):
        from autorisations.models.models_documents import DocumentNature
        self.template.pk=1;self.template.id_nature_id=3
        self.template.id_nature=DocumentNature(id=3,nature='Arrêté directeur',est_acte=True)
        self.template.nom_fichier='Test.docx'
        with patch('document_generation.views.RecordGenerationService.save') as save:
            _,context=self.call_view({'action':'generate_file','balise_42':'15'},prepared=self.prepared)
        self.assertFalse(context['complete']);save.assert_not_called()
        self.assertIn('Générez ou récupérez',context['filename_error'])

    def test_generation_fichier_echec_nas_affiche_erreur(self):
        from document_generation.services.output import DocumentOutputError
        with patch("document_generation.views.DocxRenderer.render_to_memory", return_value=BytesIO(b"docx")), patch(
            "document_generation.views.RecordGenerationService.save", side_effect=DocumentOutputError("Droits NAS insuffisants")
        ), self.assertLogs("document_generation.views", level="ERROR"):
            _, context = self.call_view({"balise_42": "15", "action": "generate_file"},
                                        prepared={**self.prepared, "template_bytes": b"source"})
        self.assertIsNone(context["generated_file"])
        self.assertIn("Droits NAS insuffisants", context["generation_error"])
        self.assertEqual(context["errors"], [])
        html = render_to_string("document_generation/generation_form.html", context)
        self.assertGreater(html.index("Droits NAS insuffisants"), html.index('value="generate_file"'))

    def test_scroll_transmis_et_valeurs_invalides_controlees(self):
        _, context = self.call_view({"balise_42": "15", "_scroll_y": "842", "_scroll_x": "0"})
        self.assertEqual(context["scroll_position"], {"x": 0, "y": 842})
        _, context = self.call_view({"balise_42": "incorrect", "_scroll_y": "invalide", "_scroll_x": "-2"})
        self.assertEqual(context["scroll_position"], {"x": 0, "y": 0})

    def test_modification_connue_explicite_locale_et_revalidee(self):
        _, context = self.call_view({"balise_42": "15", "edit_known": "1", "known-balise_1": "123"})
        self.assertTrue(context["complete"])
        self.assertEqual(context["final_context"]["dossier"]["numero"], 123)
        self.assertEqual(self.known["dossier"]["numero"], 30769307)
        self.assertTrue(context["known_edited"])
        self.assertEqual(context["known_form"]["balise_1"].value(), "123")

    def test_modification_connue_invalide_bloque_rendu(self):
        for value in ("", "incorrect"):
            with self.subTest(value=value), patch("document_generation.views.DocxRenderer.render_to_memory") as renderer:
                _, context = self.call_view({"balise_42": "15", "edit_known": "1", "known-balise_1": value,
                                             "action": "generate_docx"})
                self.assertFalse(context["complete"])
                self.assertIn("balise_1", context["known_form"].errors)
                renderer.assert_not_called()

    def test_modification_connue_sans_activation_ignoree(self):
        _, context = self.call_view({"balise_42": "15", "known-balise_1": "123"})
        self.assertEqual(context["final_context"]["dossier"]["numero"], 30769307)

    def test_generation_docx_apres_revalidation_du_post(self):
        doc = Document()
        doc.add_paragraph("Dossier {{ dossier.numero }}, quantité {{ projet.quantite }}")
        snapshot = BytesIO()
        doc.save(snapshot)
        self.template.nom = "Test"
        response, context = self.call_view({"action": "generate_docx", "balise_42": "15"},
                                          prepared={**self.prepared, "template_bytes": snapshot.getvalue()})
        try:
            self.assertIsNone(context)
            self.assertIn("attachment", response["Content-Disposition"])
            self.assertIn("Projet_test_30769307.docx", response["Content-Disposition"])
            self.assertEqual(response["Content-Type"], "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
            self.assertEqual(response["Cache-Control"], "private, no-store")
            output = Document(BytesIO(b"".join(response.streaming_content)))
            self.assertEqual(output.paragraphs[0].text, "Dossier 30769307, quantité 15")
        finally:
            response.close()

    def test_generation_refusee_si_contexte_incomplet_ou_template_invalide(self):
        with patch("document_generation.views.DocxRenderer.render_to_memory") as renderer:
            _, context = self.call_view({"action": "generate_docx", "balise_42": ""})
            self.assertFalse(context["complete"])
            self.call_view({"action": "generate_docx", "balise_42": "15"},
                           prepared={**self.prepared, "errors": ["Erreur Jinja"]})
        renderer.assert_not_called()

    def test_preview_valide_conserve_saisie_et_affiche_iframe(self):
        self.template.pk = 5
        with patch("document_generation.views.DocxRenderer.render_to_memory", return_value=BytesIO(b"docx")), patch(
            "document_generation.views.PdfPreviewService.create_preview"
        ) as create:
            _, context = self.call_view({"action": "preview_pdf", "balise_42": "15"},
                                       prepared={**self.prepared, "template_bytes": b"source"}, preview_available=True)
        self.assertTrue(context["preview_exists"])
        self.assertIn("/preview/30769307/5/?v=", context["preview_url"])
        self.assertEqual(context["form"].data["balise_42"], "15")
        self.assertEqual(create.call_args.args[1:], (42, 1, 5))
        html = render_to_string("document_generation/generation_form.html", {**context, "csrf_token": "test-token"})
        self.assertIn('<iframe src="/document-generation/preview/30769307/5/?v=', html)
        self.assertIn('value="15"', html)

    def test_preview_erreur_conserve_ancien_pdf_et_saisie(self):
        from document_generation.services.pdf_preview import PdfPreviewError
        self.template.pk = 5
        with patch("document_generation.views.DocxRenderer.render_to_memory", return_value=BytesIO(b"docx")), patch(
            "document_generation.views.PdfPreviewService.create_preview", side_effect=PdfPreviewError("LibreOffice absent")
        ), patch("document_generation.views.logger.exception") as log:
            _, context = self.call_view({"action": "preview_pdf", "balise_42": "15"},
                                       prepared={**self.prepared, "template_bytes": b"source"}, preview_available=True)
        self.assertTrue(context["preview_exists"])
        self.assertEqual(context["form"].data["balise_42"], "15")
        self.assertIn("LibreOffice absent", context["errors"])
        log.assert_called_once()

    def test_template_casse_ne_lance_pas_preview_et_conserve_ancien(self):
        self.template.pk = 5
        with patch("document_generation.views.PdfPreviewService.create_preview") as create:
            _, context = self.call_view({"action": "preview_pdf"},
                                       prepared={**self.prepared, "errors": ["Erreur Jinja"]}, preview_available=True)
        self.assertTrue(context["preview_exists"])
        create.assert_not_called()

    def test_erreur_renderer_est_affichee_et_journalisee(self):
        with patch("document_generation.views.DocxRenderer.render_to_memory", side_effect=DocxRenderError("Erreur de rendu.")), patch(
            "document_generation.views.logger.exception"
        ) as log:
            _, context = self.call_view({"action": "generate_docx", "balise_42": "15"},
                                       prepared={**self.prepared, "template_bytes": b"source"})
        self.assertIn("Impossible de générer", context["errors"][0])
        self.assertIsNotNone(context["form"])
        log.assert_called_once()

    def test_connue_vide_peut_etre_completee(self):
        definition = balise(mode="CONNUE")
        prepared = {**self.prepared, "balises": [definition], "known_context": {"projet": {"quantite": None}}, "form_balises": [definition]}
        _, context = self.call_view({"balise_42": "0"}, prepared=prepared)
        self.assertTrue(context["complete"])
        self.assertEqual(context["final_context"], {"projet": {"quantite": 0}})

    def test_template_invalide_sans_formulaire(self):
        _, context = self.call_view(prepared={**self.prepared, "errors": ["Balise inconnue : toto.foo"]})
        self.assertIsNone(context["form"])
        self.assertFalse(context["complete"])

    def test_template_hors_demarche_refuse(self):
        self.template.demarches.exists.return_value = True
        self.template.demarches.filter.return_value.exists.return_value = False
        with self.assertRaises(Http404):
            self.call_view()

    def test_utilisateur_non_concerne_refuse(self):
        with patch("document_generation.views.est_concerne_par_le_dossier", return_value=False), self.assertRaises(PermissionDenied):
            self.call_view(superuser=False)

    @override_settings(ENVIRONMENT="prod")
    def test_prod_refusee(self):
        request = RequestFactory().get("/")
        request.user = SimpleNamespace(is_authenticated=True)
        with self.assertRaises(Http404):
            views.generer_document(request, 1, 1)

    def test_url_et_template_html(self):
        self.assertEqual(reverse("document_generation:generer_document", args=[30769307, 1]),
                         "/document-generation/dossier/30769307/template/1/")
        html = render_to_string("document_generation/generation_form.html", {
            "dossier": self.dossier, "document_template": SimpleNamespace(nom="Arrêté test"),
            "form": DynamicDocumentForm(balises=[self.definitions[1]]),
            "resolved_balises": self.prepared["known_rows"], "csrf_token": "test-token",
        })
        self.assertIn('name="balise_42"', html)
        self.assertIn("csrfmiddlewaretoken", html)
        self.assertIn("30769307", html)
        self.assertIn('value="generate_file" data-requires-valid-form disabled', html)
        self.assertNotIn('value="validate"', html)
        html = render_to_string("document_generation/generation_form.html", {
            "dossier": self.dossier, "document_template": SimpleNamespace(nom="Arrêté test"),
            "form": DynamicDocumentForm(balises=[self.definitions[1]]), "complete": True, "csrf_token": "test-token",
        })
        self.assertIn('value="generate_file"', html)

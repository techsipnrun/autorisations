from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.http import Http404, HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.template.loader import render_to_string

from document_generation import views


@override_settings(ENVIRONMENT="dev")
class GenerationDossierTests(SimpleTestCase):
    def setUp(self):
        self.demarche = SimpleNamespace(pk=7, type="Travaux", numero=123)
        self.other = SimpleNamespace(pk=8, type="Agriculture", numero=456)
        self.dossier = SimpleNamespace(pk=1, numero=30655697, id_demarche_id=7,
                                       id_demarche=self.demarche,
                                       id_etape_dossier=SimpleNamespace(etape="En instruction"))
        self.valid = MagicMock(pk=3)
        self.valid.erreurs_configuration.return_value = {}
        self.incomplete = MagicMock(pk=4)
        self.incomplete.erreurs_configuration.return_value = {"nom_fichier": ["Vide"]}

    def call(self, query="", method="get"):
        request = getattr(RequestFactory(), method)("/document-generation/dossier/30655697/" + query)
        request.user = SimpleNamespace(is_authenticated=True, is_superuser=True)
        with ExitStack() as stack:
            stack.enter_context(patch("document_generation.views.dossier_history", return_value={"generation_history": []}))
            stack.enter_context(patch("document_generation.views._dossier_context", return_value=self.dossier))
            get = stack.enter_context(patch("document_generation.views.get_object_or_404", return_value=self.other if "demarche=8" in query else self.demarche))
            stack.enter_context(patch("document_generation.views.Demarche.objects.exclude"))
            candidates = stack.enter_context(patch("document_generation.views.DocumentTemplate.objects.filter"))
            candidates.return_value.filter.return_value.distinct.return_value.order_by.return_value = [self.valid, self.incomplete]
            stack.enter_context(patch("instruction.utils.dossier_utils.build_timeline_for_dossier", return_value=[]))
            rendered = stack.enter_context(patch("document_generation.views.render", return_value=HttpResponse()))
            generation = stack.enter_context(patch("document_generation.views.generer_document", return_value=HttpResponse()))
            response = views.dossier_generation(request, self.dossier.numero)
        return response, rendered, generation, candidates, get

    def test_selection_par_defaut_et_catalogue_complet_uniquement(self):
        response, rendered, generation, candidates, get = self.call()
        context = rendered.call_args.args[2]
        self.assertEqual(rendered.call_args.args[1], "document_generation/dossier_generation.html")
        self.assertEqual(context["selected_demarche"], self.demarche)
        self.assertEqual(context["templates_generation"], [self.valid])
        self.assertEqual(context["breadcrumb_items"][-1]["label"], "Génération de fichier")
        self.assertEqual(context["etape_actuelle"].etape, "En instruction")
        self.assertEqual(response["Cache-Control"], "private, no-store")
        candidates.assert_called_once_with(actif=True, rapport_validation__valide=True)
        generation.assert_not_called()
        get.assert_not_called()

    def test_breadcrumb_reutilise_le_dossier_de_la_requete(self):
        from instruction.context_processors import get_demarche_from_num_dossier
        request = SimpleNamespace(dossier_courant=self.dossier)
        with patch("instruction.context_processors.Dossier.objects.select_related") as query:
            self.assertIs(get_demarche_from_num_dossier(self.dossier.numero, request), self.demarche)
        query.assert_not_called()

    def test_autre_demarche_ne_change_pas_le_dossier(self):
        _, _, generation, _, get = self.call("?demarche=8&template=3")
        get.assert_called_once_with(views.Demarche, pk=8)
        self.assertEqual(self.dossier.id_demarche_id, 7)
        self.assertEqual(generation.call_args.kwargs["_work"], (self.dossier, self.valid))
        self.assertEqual(generation.call_args.kwargs["_shell"]["selected_demarche"], self.other)

    def test_post_utilise_le_meme_formulaire_de_generation(self):
        _, rendered, generation, _, _ = self.call("?demarche=8&template=3", method="post")
        generation.assert_called_once()
        rendered.assert_not_called()

    def test_template_incomplet_ou_non_propose_refuse(self):
        for value in ("4", "999", "abc"):
            with self.subTest(value=value), self.assertRaises(Http404):
                self.call("?template=" + value)

    def test_demarche_invalide_et_post_sans_selection_refuses(self):
        with self.assertRaises(Http404):
            self.call("?demarche=abc")
        with self.assertRaises(Http404):
            self.call(method="post")

    @override_settings(ROOT_URLCONF="autorisations.urls")
    def test_coquille_dossier_conserve_navigation_et_timeline_sans_actions(self):
        _, rendered, _, _, _ = self.call()
        context = rendered.call_args.args[2]
        context["demarches_generation"] = [self.demarche, self.other]
        context["request"] = SimpleNamespace(path="/document-generation/", user=SimpleNamespace(is_superuser=True))
        html = render_to_string("document_generation/dossier_generation.html", context)
        for content in ('id="left-sidebar"', 'class="mini_timeline"', 'class="navigation_header"',
                        'Génération de fichier', 'DOSSIER n° 30655697', 'value="7" selected',
                        'Revenir sur le dossier', 'href="/instruction/30655697/"'):
            self.assertIn(content, html)
        self.assertRegex(html, r'<li class="active">\s*Vue d\x27ensemble')
        for content in ('class="nav_preinstruction"', 'btn-liaison-ds', 'dropdown-arrow', 'copie_chemin.js'):
            self.assertNotIn(content, html)

    def test_dossier_non_autorise_refuse_avant_catalogue(self):
        request = RequestFactory().get("/")
        request.user = SimpleNamespace(is_authenticated=True, is_superuser=False)
        from django.core.exceptions import PermissionDenied
        with patch("document_generation.views.get_object_or_404", return_value=self.dossier), patch(
            "document_generation.views.est_concerne_par_le_dossier", return_value=False
        ), patch("document_generation.views.DocumentTemplate.objects.filter") as catalogue:
            with self.assertRaises(PermissionDenied):
                views.dossier_generation(request, self.dossier.numero)
        catalogue.assert_not_called()

    @override_settings(ENVIRONMENT="prod")
    def test_acces_production_interdit(self):
        request = RequestFactory().get("/")
        request.user = SimpleNamespace(is_authenticated=True, is_superuser=True)
        with self.assertRaises(Http404):
            views.dossier_generation(request, self.dossier.numero)

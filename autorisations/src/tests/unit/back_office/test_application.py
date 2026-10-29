"""Contrat HTTP du Back Office et découverte de ses ressources, sans BDD réelle."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.apps import apps
from django.contrib.auth.models import AnonymousUser
from django.contrib.staticfiles import finders
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.template.loader import get_template
from django.test import RequestFactory, SimpleTestCase
from django.urls import resolve, reverse

from backoffice.views import accueil, services


# Adresses et noms publics existant avant l'extraction de l'application.
ROUTES = (
    ("back_office", "/back-office/", {}, "get"),
    ("back_office_avis_formulaire", "/back-office/avis/formulaires/dossier/", {"contexte":"dossier"}, "get"),
    ("back_office_avis_thematiques", "/back-office/avis/thematiques/", {}, "get"),
    ("back_office_cartographie", "/back-office/cartographie/", {}, "get"),
    ("back_office_cartographie_convertir", "/back-office/cartographie/convertir/", {}, "post"),
    ("back_office_cartographie_ajouter_source", "/back-office/cartographie/source/", {}, "post"),
    ("back_office_cartographie_source", "/back-office/cartographie/source/7/", {"source_id":7}, "post"),
    ("back_office_cartographie_supprimer_source", "/back-office/cartographie/source/7/supprimer/", {"source_id":7}, "post"),
    ("back_office_cartographie_carte", "/back-office/cartographie/carte/edition/", {"code":"edition"}, "post"),
    ("back_office_enregistrer_type_acte", "/back-office/types-actes/7/", {"type_id":7}, "post"),
    ("back_office_deplacer_type_acte", "/back-office/types-actes/7/ordre/", {"type_id":7}, "post"),
    ("back_office_enregistrer_noms", "/back-office/demarche/7/noms/", {"demarche_id":7}, "post"),
    ("back_office_apercu_nom", "/back-office/demarche/7/noms/apercu/", {"demarche_id":7}, "post"),
    ("back_office_recalculer_noms", "/back-office/demarche/7/noms/recalculer/", {"demarche_id":7}, "post"),
    ("back_office_autocomplete_numeros_noms", "/back-office/demarche/7/noms/numeros/", {"demarche_id":7}, "get"),
    ("back_office_enregistrer_date_activite", "/back-office/demarche/7/date-activite/", {"demarche_id":7}, "post"),
    ("back_office_enregistrer_personnalisation_tableau", "/back-office/demarche/7/personnalisation-tableau/", {"demarche_id":7}, "post"),
    ("back_office_services_status", "/back-office/services-status/", {}, "get"),
)


class ContratBackOfficeTests(SimpleTestCase):
    def test_application_installee(self):
        self.assertTrue(apps.is_installed("backoffice"))
        self.assertEqual(list(apps.get_app_config("backoffice").get_models()), [])

    def test_urls_publiques_et_noms_conserves(self):
        for nom, chemin, kwargs, _ in ROUTES:
            with self.subTest(nom=nom):
                self.assertEqual(reverse(nom, kwargs=kwargs), chemin)
                resolution = resolve(chemin)
                self.assertEqual(resolution.url_name, nom)
                self.assertEqual(resolution.namespace, "")
                self.assertTrue(resolution.func.__module__.startswith("backoffice.views."))
        self.assertEqual(reverse("cartographie_geojson", kwargs={"source_id": 7}), "/cartographie/couche/7/")
        self.assertEqual(resolve("/cartographie/couche/7/").func.__module__, "instruction.views.cartographie")

    def test_aucun_doublon_de_nom_de_route(self):
        from backoffice.urls import urlpatterns
        self.assertEqual(len(urlpatterns), len(ROUTES))
        self.assertEqual(len({route.name for route in urlpatterns}), len(urlpatterns))

    def test_toutes_les_routes_exigent_une_authentification(self):
        for nom, chemin, _, methode in ROUTES:
            with self.subTest(nom=nom):
                requete = getattr(RequestFactory(), methode)(chemin)
                requete.user = AnonymousUser()
                resolution = resolve(chemin)
                reponse = resolution.func(requete, **resolution.kwargs)
                self.assertEqual(reponse.status_code, 302)
                self.assertIn("next=", reponse["Location"])

    def test_toutes_les_routes_exigent_un_superutilisateur(self):
        for nom, chemin, _, methode in ROUTES:
            with self.subTest(nom=nom):
                requete = getattr(RequestFactory(), methode)(chemin)
                requete.user = SimpleNamespace(is_authenticated=True, is_superuser=False)
                resolution = resolve(chemin)
                with self.assertRaises(PermissionDenied):
                    resolution.func(requete, **resolution.kwargs)

    def test_accueil_rend_les_sections_et_ressources_deplacees(self):
        requete = RequestFactory().get("/back-office/")
        requete.user = SimpleNamespace(is_authenticated=True, is_superuser=True)

        def rendre(request, template, contexte):
            self.assertEqual(template, "backoffice/back_office.html")
            return HttpResponse(get_template(template).render(contexte))

        with (
            patch.object(accueil.Demarche, "objects") as demarches,
            patch.object(accueil.DemarcheColonneVueEnsemble, "objects") as colonnes,
            patch.object(accueil.DemarcheDateActiviteConfiguration, "objects") as dates,
            patch("backoffice.views.types_actes.contexte_types_actes", return_value={}),
            patch.object(accueil, "render", side_effect=rendre),
        ):
            demarches.exclude.return_value.exclude.return_value.order_by.return_value.prefetch_related.return_value = []
            colonnes.filter.return_value = []
            dates.filter.return_value = []
            reponse = accueil.back_office(requete)
        self.assertEqual(reponse.status_code, 200)
        html = reponse.content.decode()
        for section in ("demarche", "carto", "types-actes", "avis", "avis-thematiques", "services-externes"):
            with self.subTest(section=section):
                self.assertIn(f'data-panel="{section}"', html)
        self.assertIn("/static/backoffice/css/back_office.css", html)
        self.assertIn("/static/backoffice/js/back_office_nommage.js", html)

    def test_tous_les_templates_et_statics_sont_decouverts_par_django(self):
        racine = Path(apps.get_app_config("backoffice").path)
        for template in (racine / "templates/backoffice").glob("*.html"):
            with self.subTest(template=template.name):
                get_template(f"backoffice/{template.name}")
        for fichier in (racine / "static/backoffice").rglob("*"):
            if fichier.is_file():
                nom = fichier.relative_to(racine / "static").as_posix()
                with self.subTest(static=nom):
                    self.assertEqual(Path(finders.find(nom)), fichier)

    def test_services_json_conserve_contrat_et_isole_un_echec(self):
        requete = RequestFactory().get("/back-office/services-status/")
        requete.user = SimpleNamespace(is_authenticated=True, is_superuser=True)
        with (
            patch.object(services, "get_etat_expiration_token_dn", return_value={}),
            patch.object(services, "verifier_disponibilite_demarche_numerique", side_effect=RuntimeError),
            patch.object(services, "verifier_disponibilite_declaration_manifestations_preprod", return_value={}),
            patch.object(services, "verifier_disponibilite_declaration_manifestations", return_value={}),
            patch.object(services, "verifier_acces_bdd_developpement", return_value={}),
            patch.object(services, "verifier_acces_bdd_production", return_value={}),
        ):
            reponse = services.back_office_services_status(requete)
        self.assertEqual(reponse.status_code, 200)
        self.assertIn(b'"disponible": false', reponse.content)

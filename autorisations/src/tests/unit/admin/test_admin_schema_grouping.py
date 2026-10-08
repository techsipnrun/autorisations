from types import SimpleNamespace

from django.contrib import admin
from django.contrib.auth.models import Group
from django.test import RequestFactory, SimpleTestCase
from django.urls import reverse

from autorisations.admin_site import (
    SchemaGroupedAdminSite,
    get_database_schema,
    get_schema_label,
)
from autorisations.models.models_avis import Avis
from autorisations.models.models_documents import Document
from autorisations.models.models_instruction import Dossier
from autorisations.models.models_utilisateurs import Instructeur


class UserWithAllAdminPermissions:
    is_active = True
    is_staff = True
    is_authenticated = True

    def has_module_perms(self, app_label):
        return True

    def has_perm(self, permission, obj=None):
        return True


class UserWithDossierPermissionOnly(UserWithAllAdminPermissions):
    def has_perm(self, permission, obj=None):
        return permission.endswith("_dossier")


class DatabaseSchemaAdminTests(SimpleTestCase):
    def setUp(self):
        self.request_factory = RequestFactory()

    def site_with(self, *models):
        site = SchemaGroupedAdminSite(name="admin")
        site.register(models)
        return site

    def app_list(self, site, user=None):
        request = self.request_factory.get("/admin/")
        request.user = user or UserWithAllAdminPermissions()
        return site.get_app_list(request)

    def test_detecte_les_schemas_des_modeles_existants(self):
        self.assertEqual(get_database_schema(Dossier), "instruction")
        self.assertEqual(get_database_schema(Document), "documents")
        self.assertEqual(get_database_schema(Avis), "avis")
        self.assertEqual(get_database_schema(Instructeur), "utilisateurs")

    def test_detection_schema_inconnu_et_absent(self):
        modele_carto = SimpleNamespace(_meta=SimpleNamespace(db_table='"cartographie"."couche"'))
        modele_sans_schema = SimpleNamespace(_meta=SimpleNamespace(db_table="ma_table"))

        self.assertEqual(get_database_schema(modele_carto), "cartographie")
        self.assertEqual(get_schema_label(get_database_schema(modele_carto)), "Cartographie")
        self.assertIsNone(get_database_schema(modele_sans_schema))
        self.assertEqual(get_schema_label(get_database_schema(modele_sans_schema)), "Autres")

    def test_regroupe_les_modeles_visibles_sans_doublon_et_dans_l_ordre(self):
        site = self.site_with(Dossier, Document, Avis, Instructeur)
        app_list = self.app_list(site)

        self.assertEqual([app["name"] for app in app_list], [
            "Instruction", "Documents", "Avis", "Utilisateurs",
        ])
        visibles = [model["model"] for app in app_list for model in app["models"]]
        self.assertCountEqual(visibles, [Dossier, Document, Avis, Instructeur])
        self.assertEqual(len(visibles), len(set(visibles)))

    def test_place_autres_en_premier(self):
        site = self.site_with(Group, Dossier)

        self.assertEqual([app["name"] for app in self.app_list(site)], [
            "Autres", "Instruction",
        ])

    def test_conserve_l_url_admin_existante_du_dossier(self):
        site = self.site_with(Dossier)
        dossier_data = self.app_list(site)[0]["models"][0]

        self.assertEqual(
            dossier_data["admin_url"],
            reverse("admin:autorisations_dossier_changelist"),
        )

    def test_respecte_les_permissions_deja_appliquees_par_django(self):
        site = self.site_with(Dossier, Document)
        app_list = self.app_list(site, UserWithDossierPermissionOnly())
        visibles = [model["model"] for app in app_list for model in app["models"]]

        self.assertEqual(visibles, [Dossier])

    def test_le_site_admin_global_utilise_la_classe_de_regroupement(self):
        self.assertIsInstance(admin.site, SchemaGroupedAdminSite)

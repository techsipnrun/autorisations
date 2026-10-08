"""Configuration des préfixes : modèles, admin, templates et état de migration."""
import importlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError
from django.db.migrations.loader import MigrationLoader
from django.template.loader import render_to_string
from django.test import SimpleTestCase

from autorisations.models.models_documents import Document, DocumentNature
from instruction.utils.document_utils import formater_numero_acte


class PrefixesActesTests(SimpleTestCase):
    def test_les_deux_prefixes_sont_independants(self):
        nature = DocumentNature(
            nature="Déliberation CA", prefixe_numero="CA/", prefixe_nom_fichier="DELIB-CA-",
        )
        document = Document(id_nature=nature, numero="2026-042")
        self.assertEqual(document.numero_affiche, "CA/2026-042")
        self.assertEqual(nature.formater_nom_acte(document.numero, "08-10"), "DELIB-CA-2026-042_08-10")
        self.assertEqual(document.numero, "2026-042")

    def test_nouvelle_nature_sans_mapping_python(self):
        nature = DocumentNature(
            nature="Nouveau type", prefixe_numero="NOUVEAU/", prefixe_nom_fichier="NOUVEAU-",
        )
        self.assertEqual(formater_numero_acte("2026-123", nature), "NOUVEAU/2026-123")
        self.assertEqual(nature.formater_nom_acte("2026-123", "08-10"), "NOUVEAU-2026-123_08-10")
        nature.prefixe_numero = "AUTRE-"
        self.assertEqual(formater_numero_acte("2026-123", nature), "AUTRE-2026-123")

    def test_prefixe_vide_et_numero_absent(self):
        nature = DocumentNature(nature="Sans préfixe")
        self.assertEqual(nature.formater_numero("2026-042"), "2026-042")
        self.assertEqual(nature.formater_nom_acte("2026-042", "08-10"), "2026-042_08-10")
        self.assertEqual(nature.formater_numero(None), "")
        self.assertEqual(formater_numero_acte(None, None), "")

    def test_pas_de_double_prefixe_numero(self):
        nature = DocumentNature(nature="Test", prefixe_numero="TEST-")
        self.assertEqual(nature.formater_numero("TEST-2026-042"), "TEST-2026-042")

    def test_configuration_invalide_refusee_avant_nom_fichier(self):
        for caractere in '/\\:*?"<>|\n\x00':
            with self.subTest(caractere=caractere):
                nature = DocumentNature(nature="Test", prefixe_nom_fichier=f"TEST{caractere}")
                with self.assertRaises(ValidationError):
                    nature.formater_nom_acte("2026-042", "08-10")

    def test_admin_presente_les_deux_champs_et_valide_le_prefixe_fichier(self):
        model_admin = admin.site._registry[DocumentNature]
        self.assertIn("prefixe_numero", model_admin.list_display)
        self.assertIn("prefixe_nom_fichier", model_admin.list_display)
        formulaire = model_admin.get_form(SimpleNamespace(user=AnonymousUser()))
        for champ in ("prefixe_numero", "prefixe_nom_fichier"):
            self.assertIn(champ, formulaire.base_fields)
        instance = formulaire(data={
            "nature": "Test", "prefixe_numero": "CA/", "prefixe_nom_fichier": "CA/",
        })
        # Les validateurs du modèle passent par le formulaire, sans contrôle SQL d'unicité.
        with patch.object(DocumentNature, "validate_unique"):
            self.assertFalse(instance.is_valid())
        self.assertIn("prefixe_nom_fichier", instance.errors)
        self.assertNotIn("prefixe_numero", instance.errors)
        self.assertEqual(formulaire.base_fields["prefixe_numero"].clean("CA/"), "CA/")

    def test_badges_utilisent_le_prefixe_configure(self):
        document = Document(
            id=1, numero="2026-042", titre="projet.docx", emplacement="test/Work/",
            id_nature=DocumentNature(nature="Arrêté directeur", prefixe_numero="PERSONNALISE-"),
        )
        for template in ("document_copy_row", "document_download_row"):
            with self.subTest(template=template):
                html = render_to_string(f"instruction/refacto/{template}.html", {
                    "doc": document, "show_numero": True,
                    "request": SimpleNamespace(user=AnonymousUser()),
                })
                self.assertIn("PERSONNALISE-2026-042", html)
                self.assertNotIn("DIR-I-", html)

    def test_migration_et_modele_declarent_les_memes_champs(self):
        loader = MigrationLoader(None, ignore_no_migrations=True)
        state = loader.project_state([("autorisations", "0037_document_nature_prefixes")])
        model_state = state.models["autorisations", "documentnature"]
        for nom in ("prefixe_numero", "prefixe_nom_fichier"):
            with self.subTest(champ=nom):
                actuel = DocumentNature._meta.get_field(nom).deconstruct()[1:]
                historique = model_state.fields[nom].deconstruct()[1:]
                self.assertEqual(actuel, historique)

    def test_script_sql_correspond_a_la_migration(self):
        migration = importlib.import_module("autorisations.migrations.0037_document_nature_prefixes")
        path = Path(__file__).resolve().parents[5] / "sql/0037_document_nature_prefixes.sql"
        # Comparer les instructions en ignorant seulement les commentaires/espaces.
        def normaliser(sql):
            return " ".join(ligne.strip() for ligne in sql.splitlines()
                            if ligne.strip() and not ligne.lstrip().startswith("--"))

        script = path.read_text(encoding="utf-8")
        script = script[script.index("DO $migration$"):script.index("COMMIT;")]
        self.assertEqual(normaliser(script), normaliser(migration.SQL))

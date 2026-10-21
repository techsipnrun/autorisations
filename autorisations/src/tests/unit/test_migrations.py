"""Les migrations ne modifient pas le schéma PostgreSQL administré dans pgAdmin."""
import importlib

from django.test import SimpleTestCase


MIGRATIONS_SCHEMA_EXTERNE = (
    "0038_types_actes_configurables",
    "0039_cartographie",
    "0040_avis_reservations",
    "0041_avis_formulaires",
    "0042_avis_numero_externe",
    "0043_avis_formulaire_existant",
    "0044_avis_aides_et_thematiques",
    "0045_actes_numerotation_manuelle",
    "0046_contact_raison_sociale_raccourci",
)


class MigrationsSchemaExterneTests(SimpleTestCase):
    def test_les_migrations_conservent_uniquement_l_etat_django(self):
        for nom in MIGRATIONS_SCHEMA_EXTERNE:
            with self.subTest(migration=nom):
                module = importlib.import_module(f"autorisations.migrations.{nom}")
                operation = module.Migration.operations[0]
                self.assertEqual(operation.database_operations, [])

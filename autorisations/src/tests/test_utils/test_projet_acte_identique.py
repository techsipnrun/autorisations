from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from instruction.utils.document_utils import (
    get_projet_acte_source,
    reprendre_numero_projet_acte,
)


class ProjetActeIdentiqueTests(SimpleTestCase):
    @patch("instruction.utils.document_utils.DossierDocument.objects")
    def test_refuse_un_projet_sans_numero(self, objets_liaisons):
        objets_liaisons.select_related.return_value.filter.return_value.exclude.return_value.first.return_value = None

        with self.assertRaises(ValidationError):
            get_projet_acte_source(42, SimpleNamespace(id=1))

    def test_le_numero_est_remplace(self):
        nature = SimpleNamespace(nature="Arrêté directeur")
        document = MagicMock(
            id=12,
            numero="2026-1106",
            id_nature_id=3,
            id_nature=nature,
        )
        source = SimpleNamespace(
            id=19,
            numero="2026-1105",
            id_nature_id=3,
        )
        dossier = SimpleNamespace(numero=32737536)

        fonction = getattr(
            reprendre_numero_projet_acte,
            "__wrapped__",
            reprendre_numero_projet_acte,
        )
        ancien_numero = fonction(document, source, dossier, "agent@test")

        self.assertEqual(ancien_numero, "2026-1106")
        self.assertEqual(document.numero, "2026-1105")
        document.save.assert_called_once_with(update_fields=["numero"])

    def test_refuse_de_partager_un_numero_entre_types_differents(self):
        document = SimpleNamespace(
            id_nature_id=3,
            id_nature=SimpleNamespace(nature="Arrêté directeur"),
        )
        source = SimpleNamespace(id_nature_id=4)

        fonction = getattr(
            reprendre_numero_projet_acte,
            "__wrapped__",
            reprendre_numero_projet_acte,
        )
        with self.assertRaises(ValidationError):
            fonction(
                document,
                source,
                SimpleNamespace(numero=32737536),
                "agent@test",
            )

from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase

from instruction.utils.document_utils import (
    get_projet_acte_source,
    reprendre_numero_projet_acte,
)
from instruction.views import changement_etape


class ProjetActeIdentiqueTests(SimpleTestCase):
    @patch("instruction.utils.document_utils.DossierDocument.objects")
    def test_refuse_un_projet_sans_numero(self, objets_liaisons):
        objets_liaisons.select_related.return_value.filter.return_value.exclude.return_value.first.return_value = None

        with self.assertRaises(ValidationError):
            get_projet_acte_source(42, SimpleNamespace(id=1))

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


class RemplacementNumeroProjetActeTests(SimpleTestCase):
    def setUp(self):
        stack = self.enterContext(ExitStack())

        def mocker(nom):
            return stack.enter_context(patch.object(changement_etape, nom))

        self.instructeurs = mocker("Instructeur")
        self.documents = mocker("Document")
        self.liaisons = mocker("DossierDocument")
        self.get_objet = mocker("get_object_or_404")
        self.get_source = mocker("get_projet_acte_source")
        self.remplacer = mocker("reprendre_numero_projet_acte")
        self.erreur = mocker("redirect_error")
        self.redirection = mocker("_redirect_instruction_dossier")
        self.messages = mocker("messages")
        self.erreur.return_value = HttpResponse(status=302)
        self.redirection.return_value = HttpResponse(status=302)
        self.instructeurs.objects.filter.return_value.exists.return_value = True
        self.dossier = SimpleNamespace(
            id=1, numero=31770683,
            id_etape_dossier=SimpleNamespace(etape="Avis à envoyer"),
        )
        self.document = SimpleNamespace(
            id=12, numero="2026-1106",
            id_nature=SimpleNamespace(nature="Arrêté directeur"),
        )
        self.source = SimpleNamespace(id=19, numero="2026-1105")
        self.get_source.return_value = self.source
        self.liaisons.objects.filter.return_value.exclude.return_value.exists.return_value = False
        self.liaisons.objects.filter.return_value.exists.return_value = True
        self.request = RequestFactory().post("/changer-etape/remplacer-numero-projet-acte/", {
            "dossier_id": "1", "document_id": "12", "source_document_id": "19",
        })
        self.request.user = SimpleNamespace(is_authenticated=True, email="agent@example.test")

    def appeler(self, etape):
        self.dossier.id_etape_dossier.etape = etape
        self.get_objet.side_effect = [self.dossier, self.document]
        return changement_etape.remplacer_numero_projet_acte(self.request)

    def test_autorise_les_deux_etapes_avis_et_les_etapes_deja_autorisees(self):
        for etape in (
            "Avis à envoyer", "En attente réponse d'avis",
            "À valider avant signature", "En relecture qualité", "En attente de signature",
        ):
            with self.subTest(etape=etape):
                self.remplacer.reset_mock()
                reponse = self.appeler(etape)
                self.assertEqual(reponse.status_code, 302)
                self.erreur.assert_not_called()
                self.get_source.assert_called_with(
                    "19", self.dossier, nature="Arrêté directeur",
                )
                self.remplacer.assert_called_once_with(
                    self.document, self.source, self.dossier, self.request.user,
                )

    def test_refuse_les_autres_etapes(self):
        for etape in ("En instruction", "En pré-instruction", "Avis envoyé", "Accepté"):
            with self.subTest(etape=etape):
                self.erreur.reset_mock()
                self.appeler(etape)
                self.erreur.assert_called_once_with(
                    self.request,
                    "Le numéro du projet d’acte ne peut pas être remplacé à cette étape.",
                )
                self.remplacer.assert_not_called()

    def test_refuse_sans_profil_instructeur(self):
        self.instructeurs.objects.filter.return_value.exists.return_value = False
        self.appeler("Avis à envoyer")
        self.erreur.assert_called_once()
        self.get_objet.assert_not_called()
        self.remplacer.assert_not_called()

    def test_conserve_les_controles_sur_les_documents_aux_deux_etapes_avis(self):
        for etape in ("Avis à envoyer", "En attente réponse d'avis"):
            for appartient, partage in ((False, False), (True, True)):
                with self.subTest(etape=etape, appartient=appartient, partage=partage):
                    self.erreur.reset_mock()
                    self.liaisons.objects.filter.return_value.exists.return_value = appartient
                    self.liaisons.objects.filter.return_value.exclude.return_value.exists.return_value = partage
                    self.appeler(etape)
                    self.erreur.assert_called_once()
                    self.get_source.assert_not_called()
                    self.remplacer.assert_not_called()

    def test_conserve_la_validation_de_la_source(self):
        self.get_source.side_effect = ValidationError("Type d’acte incompatible.")
        self.appeler("En attente réponse d'avis")
        self.erreur.assert_called_once()
        self.remplacer.assert_not_called()

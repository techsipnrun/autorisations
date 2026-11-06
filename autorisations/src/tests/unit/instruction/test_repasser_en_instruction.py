from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from instruction.views import changement_etape


class RepasserEnInstructionTests(SimpleTestCase):
    @override_settings(ENVIRONMENT='dev')
    def test_actes_generes_conservent_document_numero_et_lien(self):
        with patch.object(changement_etape.Document, 'objects') as documents:
            response = changement_etape.repasser_en_instruction(self.request)
        self.assertEqual(response.status_code, 302)
        self.liaisons.exclude.assert_called_once_with(id_document__generation__isnull=False)
        documents.filter.assert_called_once_with(generation__id_dossier=self.dossier, id_nature__est_acte=True)
        documents.filter.return_value.filter.return_value.update.assert_called_once_with(id_statut=None)
        documents.filter.return_value.delete.assert_not_called()

    def setUp(self):
        stack = self.enterContext(ExitStack())

        def mocker(nom):
            return stack.enter_context(patch.object(changement_etape, nom))

        self.dossier = SimpleNamespace(
            numero=34865338,
            id_ds="dossier-dn-test",
            present_sur_ds=True,
            id_etape_dossier=SimpleNamespace(etape="En attente de signature"),
            id_etat_dossier=SimpleNamespace(nom="en_construction"),
        )
        self.instructeur = SimpleNamespace(email="agent@example.test")
        mocker("get_dossier_or_redirect").return_value = (self.dossier, None)
        mocker("get_instructeur_or_redirect").return_value = (self.instructeur, None)
        self.api = mocker("repasser_en_instruction_ds")
        self.api.return_value = {"success": True}
        self.etape = mocker("safe_update_etape")
        self.etat = mocker("safe_update_etat")
        self.action = mocker("safe_enregistrer_action")
        self.erreur = mocker("redirect_error")
        self.erreur.return_value = HttpResponse(status=302)

        self.roles = [
            stack.enter_context(patch.object(modele, "objects"))
            for modele in (
                changement_etape.DossierSignataire,
                changement_etape.DossierRelecteurQualite,
                changement_etape.DossierValideur,
            )
        ]
        self.liaisons = stack.enter_context(
            patch.object(changement_etape.DossierDocument, "objects")
        )
        self.liaisons.filter.return_value.filter.return_value.values_list.return_value = []
        self.document = Mock(
            id_statut=SimpleNamespace(statut="À relire"),
            titre="Document de test",
            id_nature=SimpleNamespace(nature="Courrier"),
        )
        self.liaisons.filter.return_value.exclude.return_value.select_related.return_value = [
            SimpleNamespace(id_document=self.document),
        ]
        self.avis = Mock(id=42, statut="À valider")
        self.avis_objets = stack.enter_context(patch.object(changement_etape.Avis, "objects"))
        self.avis_objets.filter.return_value = [self.avis]

        self.request = RequestFactory().post(
            "/changer-etape/repasser-en-instruction/",
            {"dossierId": self.dossier.id_ds},
            HTTP_REFERER="/instruction/34865338/",
        )
        self.request.user = SimpleNamespace(is_authenticated=True)

    def verifier_retour_local(self, reponse):
        self.assertEqual(reponse.status_code, 302)
        self.assertEqual(reponse.url, "/instruction/34865338/")
        self.erreur.assert_not_called()
        self.etape.assert_called_once_with(
            self.dossier, "En instruction", self.request, break_si_erreur=False,
        )
        self.etat.assert_called_once_with(
            self.dossier, "en_instruction", self.request, break_si_erreur=False,
        )
        self.action.assert_called_once_with(
            self.dossier, self.instructeur, "Repassage en instruction", self.request,
        )
        for objets in self.roles:
            objets.filter.assert_called_once_with(id_dossier=self.dossier)
            objets.filter.return_value.delete.assert_called_once_with()
        self.assertIsNone(self.document.id_statut)
        self.document.save.assert_called_once_with()
        self.assertEqual(self.avis.statut, "Brouillon")
        self.avis.save.assert_called_once_with()

    def test_succes_dn_poursuit_le_retour_local(self):
        reponse = changement_etape.repasser_en_instruction(self.request)
        self.api.assert_called_once_with(self.dossier.id_ds, self.instructeur)
        self.verifier_retour_local(reponse)

    def test_deja_en_instruction_sur_dn_poursuit_le_retour_local(self):
        self.api.return_value = {
            "success": False, "message": "Le dossier est déjà en instruction",
        }
        self.verifier_retour_local(changement_etape.repasser_en_instruction(self.request))
        self.api.assert_called_once_with(self.dossier.id_ds, self.instructeur)

    def test_deja_en_instruction_avec_espace_insecable(self):
        self.api.return_value = {
            "success": False, "message": "Le dossier est déjà en\u00a0instruction",
        }
        self.verifier_retour_local(changement_etape.repasser_en_instruction(self.request))

    def test_etat_local_deja_en_instruction_ne_sollicite_pas_dn(self):
        self.dossier.id_etat_dossier.nom = "en_instruction"
        self.verifier_retour_local(changement_etape.repasser_en_instruction(self.request))
        self.api.assert_not_called()

    def test_absence_de_dn_ne_sollicite_pas_api(self):
        self.dossier.present_sur_ds = False
        self.verifier_retour_local(changement_etape.repasser_en_instruction(self.request))
        self.api.assert_not_called()

    def test_autres_erreurs_dn_bloquent_sans_modification_locale(self):
        for message in (
            "Le dossier est déjà en construction",
            "Accès refusé",
            "Le dossier est déjà en instruction; autre erreur",
            None,
        ):
            with self.subTest(message=message):
                self.erreur.reset_mock()
                self.api.return_value = {"success": False, "message": message}
                reponse = changement_etape.repasser_en_instruction(self.request)
                self.assertIs(reponse, self.erreur.return_value)
                self.erreur.assert_called_once()
                self.etape.assert_not_called()
                self.etat.assert_not_called()
                self.action.assert_not_called()
                for objets in self.roles:
                    objets.filter.assert_not_called()
                self.liaisons.filter.assert_not_called()
                self.document.save.assert_not_called()
                self.avis_objets.filter.assert_not_called()
                self.avis.save.assert_not_called()

"""Historisation des reprises de numéro, sans accès au NAS ni à la BDD réelle."""
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase
from django.utils import timezone

from instruction.utils import document_utils, dossier_utils
from instruction.views import changement_etape
from autorisations.models.models_documents import DocumentNature


class HistoriqueNumeroActeTests(SimpleTestCase):
    def setUp(self):
        stack = self.enterContext(ExitStack())
        self.atomic = stack.enter_context(patch.object(document_utils.transaction, "atomic"))
        self.modeles = {
            nom: stack.enter_context(patch.object(document_utils, nom))
            for nom in ("Document", "DossierDocument", "Instructeur", "Action", "DossierAction")
        }
        self.document = MagicMock(
            pk=12, numero="2026-1106", id_nature_id=3,
            id_nature=DocumentNature(nature="Arrêté directeur", prefixe_numero="DIR-I-"),
        )
        self.source = SimpleNamespace(id=19, numero="2026-1105", id_nature_id=3)
        self.dossier = SimpleNamespace(id=1, numero=32737536)
        self.utilisateur = SimpleNamespace(email=" Agent@Example.test ")
        self.actuel = SimpleNamespace(numero=self.document.numero)
        self.modeles["Document"].objects.select_for_update.return_value.get.return_value = self.actuel
        self.modeles["DossierDocument"].objects.filter.return_value.exclude.return_value.order_by.return_value.values_list.return_value.first.return_value = 31770683
        self.create = self.modeles["DossierAction"].objects.create

    def reprendre(self, **kwargs):
        return document_utils.reprendre_numero_projet_acte(
            self.document, self.source, self.dossier, self.utilisateur, **kwargs,
        )

    def test_le_numero_est_remplace_et_historise_sur_le_dossier_courant(self):
        self.assertEqual(self.reprendre(), "2026-1106")
        self.assertEqual(self.document.numero, "2026-1105")
        self.document.save.assert_called_once_with(update_fields=["numero"])
        self.modeles["Document"].objects.select_for_update.return_value.get.assert_called_once_with(pk=12)
        self.modeles["Instructeur"].objects.filter.assert_called_once_with(email__iexact="Agent@Example.test")
        self.modeles["Action"].objects.filter.assert_called_once_with(action="Numéro d'acte changé")
        self.create.assert_called_once_with(
            id_dossier=self.dossier,
            id_instructeur=self.modeles["Instructeur"].objects.filter.return_value.first.return_value,
            id_action=self.modeles["Action"].objects.filter.return_value.first.return_value,
            description=("Arrêté directeur : 2026-1106 → 2026-1105\n"
                         "Numéro repris depuis le dossier n° 31770683\n"
                         "Numéro d’acte affiché : DIR-I-2026-1105"),
        )
        self.atomic.return_value.__exit__.assert_called_once_with(None, None, None)

    def test_snapshot_avant_la_regeneration_intermediaire(self):
        self.actuel.numero = self.document.numero = "2026-9999"
        self.assertEqual(self.reprendre(ancien_numero="2026-1106"), "2026-1106")
        self.assertIn("2026-1106 → 2026-1105", self.create.call_args.kwargs["description"])
        self.assertNotIn("9999", self.create.call_args.kwargs["description"])

    def test_attribution_initiale_sans_faux_ancien_numero(self):
        self.reprendre(ancien_numero=None)
        self.assertIn("Numéro attribué : 2026-1105", self.create.call_args.kwargs["description"])
        self.assertNotIn("1106", self.create.call_args.kwargs["description"])

    def test_pas_de_doublon_si_numero_inchange(self):
        self.actuel.numero = self.document.numero = self.source.numero
        self.reprendre()
        self.create.assert_not_called()
        self.document.save.assert_not_called()

    def test_restaure_le_numero_partage_sans_fausse_action_apres_regeneration(self):
        self.reprendre(ancien_numero=self.source.numero)
        self.document.save.assert_called_once_with(update_fields=["numero"])
        self.assertEqual(self.document.numero, self.source.numero)
        self.create.assert_not_called()

    def test_references_manquantes_bloquent_avant_le_remplacement(self):
        for modele in ("Action", "Instructeur"):
            with self.subTest(modele=modele):
                with patch.object(self.modeles[modele].objects.filter.return_value, "first", return_value=None):
                    with self.assertRaises(ValidationError):
                        self.reprendre()
                self.create.assert_not_called()
                self.document.save.assert_not_called()

    def test_source_sans_dossier_bloque_avant_le_remplacement(self):
        self.modeles["DossierDocument"].objects.filter.return_value.exclude.return_value.order_by.return_value.values_list.return_value.first.return_value = None
        with self.assertRaises(ValidationError):
            self.reprendre()
        self.document.save.assert_not_called()
        self.create.assert_not_called()

    def test_echec_ecriture_historique_sort_de_la_transaction_en_erreur(self):
        self.create.side_effect = RuntimeError("Échec SQL simulé")
        with self.assertRaisesRegex(RuntimeError, "Échec SQL simulé"):
            self.reprendre()
        self.assertIs(self.atomic.return_value.__exit__.call_args.args[0], RuntimeError)

    def test_echec_sauvegarde_document_ne_cree_pas_action(self):
        self.document.save.side_effect = RuntimeError("Échec SQL simulé")
        with self.assertRaises(RuntimeError):
            self.reprendre()
        self.create.assert_not_called()


class BranchementHistoriqueNumeroActeTests(SimpleTestCase):
    def test_les_trois_formulaires_transmettent_le_vrai_ancien_numero(self):
        for nom_vue in (
            "faire_valider_une_demande_d_avis", "faire_valider_le_projet_d_acte",
            "acte_pret_a_la_signature",
        ):
            for nouveau in (False, True):
                with self.subTest(vue=nom_vue, nouveau=nouveau), ExitStack() as stack:
                    mocks = {
                        nom: stack.enter_context(patch.object(changement_etape, nom))
                        for nom in (
                            "Dossier", "Document", "DocumentNature", "DocumentFormat", "DocumentStatut",
                            "Instructeur", "DossierDocument", "DossierValideur", "Avis",
                            "get_dossier_or_redirect", "get_instructeur_or_redirect",
                            "get_projets_work_manquants", "creer_dossier_sur_nas",
                            "redirect_error", "_appliquer_numero_partage",
                        )
                    }
                    stack.enter_context(patch.object(changement_etape.transaction, "atomic"))
                    stack.enter_context(patch.object(changement_etape.smbclient.path, "exists", return_value=True))
                    # Couper le workflow juste après le branchement testé, sans mail ni changement d'étape.
                    mocks["_appliquer_numero_partage"].side_effect = ValidationError("Fin du test")
                    mocks["get_projets_work_manquants"].return_value = []
                    mocks["redirect_error"].return_value = HttpResponse(status=302)
                    dossier = SimpleNamespace(numero=32737536, emplacement="test/Work")
                    document = MagicMock(numero="2026-1106")
                    mocks["Document"].objects.get_or_create.return_value = (document, nouveau)
                    mocks["DossierValideur"].objects.filter.return_value.delete.return_value = (0, {})
                    mocks["get_dossier_or_redirect"].return_value = (dossier, None)
                    mocks["get_instructeur_or_redirect"].return_value = (SimpleNamespace(id=2), None)
                    request = RequestFactory().post("/test", {
                        "dossierId": "1", "nature_document": "Arrêté directeur",
                        "choix-validant": "2", "piece_jointe_work": "projet.docx",
                        "avis_selectionnes": ["3"],
                    })
                    request.user = SimpleNamespace(is_authenticated=True, email="agent@example.test")
                    getattr(changement_etape, nom_vue)(request)
                    mocks["_appliquer_numero_partage"].assert_called_once_with(
                        request, dossier, document, "Arrêté directeur",
                        ancien_numero=None if nouveau else "2026-1106",
                    )
                    self.assertIs(mocks["redirect_error"].call_args.args[0], request)

    @patch.object(changement_etape, "reprendre_numero_projet_acte")
    @patch.object(changement_etape, "_source_numero_partagee")
    def test_option_non_cochee_ne_cree_pas_historique(self, source, reprendre):
        source.return_value = None
        changement_etape._appliquer_numero_partage(None, None, None, None, ancien_numero=None)
        reprendre.assert_not_called()

    @patch.object(dossier_utils.DocumentNature, "objects")
    @patch.object(dossier_utils.DossierAction, "objects")
    def test_timeline_affiche_un_resume_sans_auteur_et_conserve_historique(self, objets_actions, objets_natures):
        action = SimpleNamespace(
            date=timezone.now(),
            id_action=SimpleNamespace(action=document_utils.ACTION_CHANGEMENT_NUMERO_ACTE),
            logo=dossier_utils.LOGO_MAPPING[document_utils.ACTION_CHANGEMENT_NUMERO_ACTE],
            description="Arrêté directeur : 2026-1106 → 2026-1105\nNuméro repris depuis le dossier n° 31770683 <test>",
            id_instructeur=SimpleNamespace(
                id_agent_autorisations=SimpleNamespace(nom="Calu", prenom="Louis"),
            ),
        )
        description_originale = action.description
        objets_natures.filter.return_value.in_bulk.return_value = {
            "Arrêté directeur": DocumentNature(nature="Arrêté directeur", prefixe_numero="DIR-I-"),
        }
        objets_actions.filter.return_value.select_related.return_value.order_by.return_value = [action]
        actions = dossier_utils.build_timeline_for_dossier(SimpleNamespace(id=1))
        html = render_to_string("instruction/timeline.html", {"dossier_actions": actions})
        self.assertIn("changement_num_acte.png", html)
        self.assertIn("timeline-item-numero-acte", html)
        self.assertIn("Numéro d&#x27;acte changé", html)
        self.assertIn("Repris du dossier n° 31770683 &lt;test&gt;: DIR-I-2026-1105", html)
        self.assertNotIn("Arrêté directeur", html)
        self.assertNotIn("2026-1106", html)
        self.assertNotIn("CALU", html)
        self.assertNotIn("Louis", html)
        self.assertEqual(action.description, description_originale)
        objets_natures.filter.assert_called_once_with(nature__in={"Arrêté directeur"})

    def test_resume_attribution_initiale_et_changement_numero(self):
        for detail in (
            "Arrêté directeur : Numéro attribué : 2026-044",
            "Arrêté directeur : 2026-040 → 2026-044",
        ):
            with self.subTest(detail=detail):
                self.assertEqual(
                    dossier_utils._resume_changement_numero_acte(
                        f"{detail}\nNuméro repris depuis le dossier n° 29859769",
                        {"Arrêté directeur": DocumentNature(nature="Arrêté directeur", prefixe_numero="DIR-I-")},
                    ),
                    "Repris du dossier n° 29859769: DIR-I-2026-044",
                )

    def test_prefixes_coherents_sans_doublon_et_sans_changer_numero_stocke(self):
        for nature, numero, attendu in (
            ("Arrêté directeur", "2026-042", "DIR-I-2026-042"),
            ("Arrêté directeur", "DIR-I-2026-042", "DIR-I-2026-042"),
            ("Déliberation CA", "2026-042", "CA/2026-042"),
            ("Déliberation CA", "CA/2026-042", "CA/2026-042"),
            ("Avis simple", "2026-042", "AVIS-SIMPLE-2026-042"),
            ("Avis simple", "AVIS-SIMPLE-2026-042", "AVIS-SIMPLE-2026-042"),
            ("Avis conforme", "2026-042", "AVIS-CONFORME-2026-042"),
            ("Avis conforme", "AVIS-CONFORME-2026-042", "AVIS-CONFORME-2026-042"),
        ):
            with self.subTest(nature=nature, numero=numero):
                prefixe = attendu.removesuffix("2026-042")
                self.assertEqual(
                    dossier_utils._resume_changement_numero_acte(
                        f"{nature} : Numéro attribué : {numero}\n"
                        "Numéro repris depuis le dossier n° 29859769",
                        {nature: DocumentNature(nature=nature, prefixe_numero=prefixe)},
                    ),
                    f"Repris du dossier n° 29859769: {attendu}",
                )

    def test_snapshot_du_prefixe_reste_identique_apres_reconfiguration(self):
        description = (
            "Arrêté directeur : 2026-040 → 2026-044\n"
            "Numéro repris depuis le dossier n° 29859769\n"
            "Numéro d’acte affiché : ANCIEN-2026-044"
        )
        self.assertEqual(
            dossier_utils._resume_changement_numero_acte(description, {
                "Arrêté directeur": DocumentNature(nature="Arrêté directeur", prefixe_numero="NOUVEAU-"),
            }),
            "Repris du dossier n° 29859769: ANCIEN-2026-044",
        )

    @patch.object(dossier_utils.DocumentNature, "objects")
    @patch.object(dossier_utils.DossierAction, "objects")
    def test_timeline_avec_snapshot_ne_recharge_pas_les_natures(self, objets_actions, objets_natures):
        action = SimpleNamespace(
            id_action=SimpleNamespace(action="Numéro d'acte changé"),
            description=("Arrêté directeur : Numéro attribué : 2026-044\n"
                         "Numéro repris depuis le dossier n° 29859769\n"
                         "Numéro d’acte affiché : DIR-I-2026-044"),
        )
        objets_actions.filter.return_value.select_related.return_value.order_by.return_value = [action]
        dossier_utils.build_timeline_for_dossier(SimpleNamespace(id=1))
        self.assertEqual(action.description_timeline, "Repris du dossier n° 29859769: DIR-I-2026-044")
        objets_natures.filter.assert_not_called()

    def test_resume_description_inconnue_reste_lisible(self):
        for description in (None, "", "Description ancienne sans provenance"):
            with self.subTest(description=description):
                self.assertEqual(dossier_utils._resume_changement_numero_acte(description), description)

"""Références manuelles, sans accès réel à la base, au NAS ou aux mails."""
import importlib
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.exceptions import ValidationError
from django.db import models
from django.db.migrations.loader import MigrationLoader
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase

from autorisations.models.models_documents import Document, DocumentNature
from instruction.forms_types_actes import TypeActeForm
from instruction.utils import document_utils
from instruction.views import changement_etape


class NumerotationManuelleTests(SimpleTestCase):
    def setUp(self):
        self.nature = DocumentNature(id=99, nature="Autorisation PF", est_acte=True,
            mode_numerotation="manuelle", prefixe_numero="PF-", prefixe_nom_fichier="PF-")

    def document(self, **kwargs):
        return Document(id_nature=self.nature, emplacement="test/Work/", titre="projet.docx", **kwargs)

    def test_reference_conservee_sans_compteur_lors_creation_et_mises_a_jour(self):
        doc = self.document(numero_reference="2025-018/PF")
        with patch.object(models.Model, "save"), patch.object(Document, "objects") as objets:
            doc.save()
            objets.filter.assert_not_called()
            self.assertIsNone(doc.numero)
            self.assertEqual(doc.numero_affiche, "PF-2025-018/PF")
            doc.pk = 25
            objets.only.return_value.get.return_value = self.document()
            doc.save(update_fields=["id_statut"])
            objets.filter.assert_not_called()
            self.assertEqual(doc.numero_reference, "2025-018/PF")

    def test_reference_brute_et_prefixes_separes_du_nom_nas(self):
        for ref in ("2025-018/PF", "2025-018\\PF"):
            with self.subTest(ref=ref):
                doc = self.document(numero_reference=ref)
                self.assertEqual(doc.numero_affiche, "PF-" + ref)
                self.assertEqual(self.nature.formater_nom_acte(doc.numero_effectif, "20-10"), "PF-2025-018-PF_20-10")
                self.assertEqual(doc.numero_reference, ref)

    def test_deux_references_identiques_ne_lient_pas_les_dossiers(self):
        a = self.document(id=1, numero_reference="2025-018/PF")
        b = self.document(id=2, numero_reference="2025-018/PF")
        self.assertNotEqual(document_utils.cle_acte(a), document_utils.cle_acte(b))
        b.id_document_reference_id = a.pk
        self.assertEqual(document_utils.cle_acte(a), document_utils.cle_acte(b))

    def test_reference_vide_trop_longue_ou_controle_refusee(self):
        for reference in ("", "   ", "x" * 151, "2026\n018", "a\x00b"):
            with self.subTest(reference=reference), self.assertRaises(ValidationError):
                document_utils.valider_reference_acte(reference)
        self.assertEqual(document_utils.valider_reference_acte(" 2025-018/PF "), "2025-018/PF")

    def test_reprise_explicite_et_historique_meme_si_reference_identique(self):
        doc = self.document(id=2, numero_reference="2025-018/PF")
        source = self.document(id=1, numero_reference=doc.numero_reference)
        with patch.object(document_utils.transaction, "atomic"), \
             patch.object(Document, "objects") as objets, \
             patch.object(Document, "save"), \
             patch.object(document_utils, "Instructeur"), \
             patch.object(document_utils, "Action"), \
             patch.object(document_utils, "DossierAction") as actions, \
             patch.object(document_utils, "DossierDocument") as liens:
            objets.select_for_update.return_value.get.return_value = self.document(id=2, numero_reference=doc.numero_reference)
            liens.objects.filter.return_value.exclude.return_value.order_by.return_value.values_list.return_value.first.return_value = 123
            document_utils.reprendre_numero_projet_acte(doc, source, SimpleNamespace(pk=3), SimpleNamespace(email="a@example.test"))
            self.assertEqual(doc.id_document_reference_id, 1)
            self.assertIsNone(doc.numero)
            self.assertIn("Numéro d’acte affiché : PF-2025-018/PF", actions.objects.create.call_args.kwargs["description"])

    def test_reference_enregistree_dans_les_trois_parcours_et_controle_avant_creation(self):
        for vue in ("faire_valider_une_demande_d_avis", "faire_valider_le_projet_d_acte", "acte_pret_a_la_signature"):
            for reference in ("", "2025-018/PF"):
                with self.subTest(vue=vue, reference=reference), ExitStack() as stack:
                    mocks = {nom: stack.enter_context(patch.object(changement_etape, nom)) for nom in (
                        "Dossier", "Document", "DocumentNature", "DocumentFormat", "DocumentStatut", "Instructeur",
                        "DossierDocument", "DossierValideur", "Avis", "get_dossier_or_redirect", "get_instructeur_or_redirect",
                        "get_projets_work_manquants", "creer_dossier_sur_nas", "redirect_error", "get_type_acte")}
                    stack.enter_context(patch.object(changement_etape.transaction, "atomic"))
                    stack.enter_context(patch.object(changement_etape.smbclient.path, "exists", return_value=True))
                    mocks["get_projets_work_manquants"].return_value = []
                    mocks["get_type_acte"].return_value = self.nature
                    mocks["get_dossier_or_redirect"].return_value = (SimpleNamespace(numero=1, emplacement="test/"), None)
                    mocks["get_instructeur_or_redirect"].return_value = (SimpleNamespace(pk=1), None)
                    mocks["redirect_error"].return_value = HttpResponse(status=400)
                    doc = self.document()
                    doc.save = Mock()
                    mocks["Document"].objects.get_or_create.return_value = (doc, True)
                    request = RequestFactory().post("/test", {"dossierId": "1", "nature_document": "99",
                        "choix-validant": "2", "piece_jointe_work": "projet.docx", "avis_selectionnes": ["3"],
                        "numero_reference": reference})
                    request.user = SimpleNamespace(is_authenticated=True, email="a@example.test")
                    appliquer = changement_etape._appliquer_numero_partage
                    def fin(*args, **kwargs):
                        appliquer(*args, **kwargs)
                        raise ValidationError("Fin du test avant changement d’étape")
                    with patch.object(changement_etape, "_appliquer_numero_partage", side_effect=fin):
                        getattr(changement_etape, vue)(request)
                    if reference:
                        self.assertEqual(doc.numero_reference, reference)
                        doc.save.assert_called_once_with(update_fields=["numero_reference"])
                    else:
                        mocks["Document"].objects.get_or_create.assert_not_called()

    def test_affichage_du_numero_dans_les_composants_communs(self):
        doc = self.document(id=1, numero_reference="2025-018/PF")
        for template in ("document_copy_row.html", "document_download_row.html"):
            html = render_to_string("instruction/refacto/" + template, {"doc": doc, "show_numero": True})
            self.assertIn("PF-2025-018/PF", html)

    def test_changement_mode_interdit_sur_type_deja_utilise(self):
        form = TypeActeForm({"nature": self.nature.nature, "actif": "true", "mode_numerotation": "automatique",
            "prefixe_numero": "PF-", "prefixe_nom_fichier": "PF-", "circuit_signature": "direction",
            "rapport_ca_obligatoire": "false", "mode_publication_raa": "non_requise", "autorise_dm": "false"}, instance=self.nature)
        with patch.object(DocumentNature, "validate_unique"), patch.object(Document, "objects") as objets:
            objets.filter.return_value.exists.return_value = True
            self.assertFalse(form.is_valid())
            self.assertIn("ne peut plus être changé", str(form.errors))

    def test_depot_acte_signe_utilise_reference_et_nom_nas_sur_les_deux_circuits(self):
        for circuit in ("direction", "ca"):
            with self.subTest(circuit=circuit), ExitStack() as stack:
                self.nature.circuit_signature = circuit
                doc = self.document(id=1, numero_reference="2025-018/PF")
                mocks = {nom: stack.enter_context(patch.object(changement_etape, nom)) for nom in (
                    "get_dossier_or_redirect", "get_instructeur_or_redirect", "get_type_acte",
                    "Dossier", "get_projets_work_manquants", "Document", "DocumentStatut", "DocumentFormat", "get_object_or_404",
                    "creer_dossier_sur_nas", "generate_unique_filename", "ecrire_file_sur_nas", "redirect_error")}
                stack.enter_context(patch.dict("os.environ", {"NAS_ROOT": "test-nas"}))
                mocks["get_dossier_or_redirect"].return_value = (SimpleNamespace(numero=1, emplacement="test/"), None)
                mocks["get_projets_work_manquants"].return_value = []
                mocks["get_instructeur_or_redirect"].return_value = (SimpleNamespace(pk=1), None)
                mocks["get_type_acte"].return_value = self.nature
                mocks["Document"].objects.filter.return_value.first.return_value = doc
                mocks["generate_unique_filename"].return_value = ("PF-2025-018-PF_test", "test-nas/test/Actes/PF-2025-018-PF_test.pdf")
                mocks["ecrire_file_sur_nas"].return_value = False  # Arrêt avant toute mutation ultérieure.
                mocks["redirect_error"].return_value = HttpResponse(status=400)
                from django.core.files.uploadedfile import SimpleUploadedFile
                request = RequestFactory().post("/test", {"dossierId": "1", "nature_document": "99", "id_doc_a_signer": "1",
                    "choix-signataire": "2", "choix-envoi-acte-peti": "3",
                    "piece_jointe": SimpleUploadedFile("signe.pdf", b"%PDF-test", content_type="application/pdf")})
                request.user = SimpleNamespace(is_authenticated=True, email="a@example.test")
                changement_etape.acte_pret_a_etre_envoye(request)
                self.assertTrue(mocks["generate_unique_filename"].called, str(mocks["redirect_error"].call_args))
                base = mocks["generate_unique_filename"].call_args.kwargs["base_filename"]
                self.assertTrue(base.startswith("PF-2025-018-PF_"), base)
                self.assertNotIn("/", base)
                self.assertEqual(doc.numero_reference, "2025-018/PF")

    def test_migration_sql_et_modeles_coherents(self):
        migration = importlib.import_module("autorisations.migrations.0045_actes_numerotation_manuelle")
        script = (Path(__file__).resolve().parents[5] / "sql/0045_actes_numerotation_manuelle.sql").read_text(encoding="utf-8")
        self.assertIn(migration.SQL.strip(), script)
        state = MigrationLoader(None, ignore_no_migrations=True).project_state([("autorisations", "0045_actes_numerotation_manuelle")])
        for model, nom in ((DocumentNature, "mode_numerotation"), (Document, "numero_reference"), (Document, "id_document_reference")):
            self.assertEqual(model._meta.get_field(nom).deconstruct()[1:],
                state.models["autorisations", model._meta.model_name].fields[nom].deconstruct()[1:])

"""Types d'actes configurables, sans appel réel aux BDD, NAS, mails ou API."""
import importlib
import json
from contextlib import ExitStack
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.core.exceptions import PermissionDenied
from django.db import models
from django.db.migrations.loader import MigrationLoader
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase

from autorisations.models.models_documents import Document, DocumentNature, DocumentStatut
from instruction.utils import document_utils
from instruction.views import changement_etape


class MoteurTypesActesTests(SimpleTestCase):
    def test_calcul_prochain_numero_partage_avec_attribution(self):
        for dernier, attendu in ((None, "2026-1000"), ("2026-1043", "2026-1044"), ("2026-0099", "2026-0100"), ("2026-invalide", "2026-1000")):
            with self.subTest(dernier=dernier):
                self.assertEqual(Document.prochain_numero(dernier, 2026), attendu)

    def test_blocs_documentaires_independants_du_libelle(self):
        for signature, rapport, publication in (("direction", True, "non_requise"), ("ca", False, "manuelle")):
            with self.subTest(signature=signature), patch.object(document_utils, "DossierDocument") as liaisons, patch.object(document_utils, "Document") as documents, patch.object(document_utils, "get_types_actes_selectionnables"), patch.object(document_utils.smbclient.path, "exists", return_value=False), patch.dict("os.environ", {"NAS_ROOT": "test-nas"}):
                nature = DocumentNature(est_acte=True, nature="Type inédit", circuit_signature=signature, rapport_ca_obligatoire=rapport, mode_publication_raa=publication)
                document = Document(id_nature=nature, emplacement="test/Work/", titre="projet.docx")
                document.id_statut = DocumentStatut(statut="À signer")
                liaisons.objects.filter.return_value.select_related.return_value = [SimpleNamespace(id_document=document)]
                documents.objects.filter.return_value.values_list.return_value = []
                contexte = document_utils.build_documents_for_dossier(SimpleNamespace(emplacement="test", numero=1))
                self.assertEqual(contexte["signature_ca"], signature == "ca")
                self.assertEqual(contexte["rapport_ca_requis"], rapport)
                self.assertEqual(contexte["publication_raa_requise"], publication == "manuelle")
                self.assertEqual(contexte["doc_a_signer"], [document])

    def test_numerotation_nouveau_type_et_numero_fourni_conserve(self):
        for fourni in (None, "2025-0042"):
            with self.subTest(fourni= fourni), patch.object(Document, "objects") as objets, patch.object(models.Model, "save"), patch("autorisations.models.models_documents.transaction.atomic"):
                objets.filter.return_value.aggregate.return_value = {"max_num": None}
                document = Document(id_nature=DocumentNature(id=99, nature="Nouveau type", est_acte=True), numero=fourni)
                document.save()
                self.assertEqual(document.numero, fourni or f"{date.today().year}-1000")
                if fourni:
                    objets.filter.assert_not_called()

    def test_acte_sans_publication_reste_visible_apres_envoi(self):
        nature = DocumentNature(est_acte=True, mode_publication_raa="non_requise")
        document = Document(id_nature=nature, id_statut=DocumentStatut(statut="Envoyé"), titre="acte.pdf", emplacement="test/Actes/")
        with patch.object(document_utils, "DossierDocument") as liaisons, patch.object(document_utils, "Document") as documents, patch.object(document_utils, "get_types_actes_selectionnables"), patch.object(document_utils.smbclient.path, "exists", return_value=False), patch.dict("os.environ", {"NAS_ROOT": "test-nas"}):
            liaisons.objects.filter.return_value.select_related.return_value = [SimpleNamespace(id_document=document)]
            documents.objects.filter.return_value.values_list.return_value = []
            contexte = document_utils.build_documents_for_dossier(SimpleNamespace(emplacement="test", numero=1))
        self.assertEqual(contexte["acte_envoye_et_pas_publie"], [document])
        self.assertFalse(contexte["publication_raa_requise"])
        self.assertFalse(contexte["doc_envoye_et_publie"])

    def test_document_ordinaire_ne_recoit_pas_de_numero_acte(self):
        with patch.object(Document, "objects") as objets, patch.object(models.Model, "save"):
            document = Document(id_nature=DocumentNature(id=99, nature="Annexe", est_acte=False))
            document.save()
        self.assertIsNone(document.numero)
        objets.filter.assert_not_called()

    def test_type_desactive_reste_reconnu_pour_historique(self):
        nature = DocumentNature(id=99, est_acte=True, actif=False)
        self.assertTrue(document_utils.est_projet_acte_ou_rapport(Document(id_nature=nature)))
        with patch.object(DocumentNature, "objects") as objets:
            document_utils.get_types_actes_selectionnables()
            objets.filter.assert_called_once_with(est_acte=True, actif=True)

    def test_identifiant_et_ancien_libelle_acceptes(self):
        with patch.object(DocumentNature, "objects") as objets:
            document_utils.get_type_acte("99")
            objets.filter.assert_called_with(est_acte=True, pk=99)
            document_utils.get_type_acte("Nouveau type", nouveau=True)
            objets.filter.assert_called_with(est_acte=True, nature="Nouveau type")
            objets.filter.return_value.filter.assert_called_once_with(actif=True)

    def test_dm_interdit_ne_depose_pas_le_fichier(self):
        with patch.object(changement_etape, "reception_traiter_fichier_avis_dm") as deposer, patch.object(changement_etape, "messages"), patch.object(changement_etape, "get_access_token") as token:
            document = Document(id_nature=DocumentNature(est_acte=True, autorise_dm=False))
            changement_etape._deposer_acte_sur_dm(None, {}, document, None, "nas")
        deposer.assert_not_called()
        token.assert_not_called()

    def test_dm_autorise_conserve_nature_et_document_source(self):
        document = Document(id_nature=DocumentNature(nature="Nouveau type", est_acte=True, autorise_dm=True), numero="2026-1042")
        resultat = {"token": None, "avis_id": 12, "dossier_dm": SimpleNamespace(emplacement="dm/")}
        with patch.object(changement_etape, "reception_traiter_fichier_avis_dm") as deposer, patch.object(changement_etape, "get_access_token", return_value="jeton"):
            changement_etape._deposer_acte_sur_dm(None, resultat, document, None, "nas")
        self.assertEqual(deposer.call_args.kwargs["nature_document"], "Nouveau type")
        self.assertEqual(deposer.call_args.kwargs["token"], "jeton")
        self.assertIs(deposer.call_args.kwargs["document_source"], document)

    def test_six_decisions_selon_mode_raa(self):
        for nom_vue, etape_finale in (("envoyer_l_acte", "Accepté"), ("envoyer_l_acte_de_refus", "Refusé")):
            for mode in DocumentNature.PublicationRAA.values:
                with self.subTest(vue=nom_vue, mode=mode), ExitStack() as stack:
                    mocks = {nom: stack.enter_context(patch.object(changement_etape, nom)) for nom in (
                        "get_dossier_or_redirect", "get_instructeur_or_redirect", "get_type_acte",
                        "Document", "DocumentStatut", "DocumentFormat", "Instructeur", "DossierDocument",
                        "accepter_dossier_ds", "refuser_dossier_ds", "safe_update_etape", "safe_update_etat",
                        "safe_enregistrer_action", "set_dossier_role", "_enregistrer_motif_decision_sans_bloquer",
                        "envoyer_copie_document_par_mail", "_envoyer_annexes_decision_sur_ds", "_get_contexte_dossier_dm", "redirect_error",
                    )}
                    stack.enter_context(patch.object(changement_etape.transaction, "atomic"))
                    fichier_nas = stack.enter_context(patch.object(changement_etape.smbclient, "open_file"))
                    fichier_nas.return_value.__enter__.return_value.read.return_value = b"%PDF-simule"
                    stack.enter_context(patch.dict("os.environ", {"NAS_ROOT": "test-nas"}))
                    nature = DocumentNature(id=99, nature="Nouveau type", est_acte=True, mode_publication_raa=mode)
                    document = MagicMock(id=1, titre="acte.pdf", id_nature=nature, id_nature_id=99, id_statut=SimpleNamespace(statut="À envoyer"), id_format=SimpleNamespace(format="pdf"), publie_au_raa=False)
                    dossier = SimpleNamespace(numero=123, present_sur_ds=True, emplacement="test/")
                    mocks["get_type_acte"].return_value = nature
                    mocks["get_dossier_or_redirect"].return_value = (dossier, None)
                    mocks["get_instructeur_or_redirect"].return_value = (SimpleNamespace(email="agent@example.test"), None)
                    mocks["Document"].objects.filter.return_value.select_related.return_value.first.return_value = document
                    mocks["DossierDocument"].objects.filter.return_value.select_related.return_value = [SimpleNamespace(id_document=document)]
                    for nom in ("safe_update_etape", "safe_update_etat", "safe_enregistrer_action", "set_dossier_role", "envoyer_copie_document_par_mail", "_envoyer_annexes_decision_sur_ds"):
                        mocks[nom].return_value = None
                    mocks["_get_contexte_dossier_dm"].return_value = (None, None)
                    mocks["accepter_dossier_ds"].return_value = mocks["refuser_dossier_ds"].return_value = {"success": True}
                    mocks["redirect_error"].return_value = HttpResponse(status=400)
                    request = RequestFactory().post("/test", {"dossierId": "1", "document_id_existant": "1", "nature_document": "99", "choix-publieur-raa": "2"})
                    request.user = SimpleNamespace(is_authenticated=True, email="agent@example.test")
                    response = getattr(changement_etape, nom_vue)(request)
                    mocks["redirect_error"].assert_not_called()
                    self.assertEqual(response.status_code, 302)
                    self.assertEqual(mocks["safe_update_etape"].call_args.args[1], "À publier au RAA" if mode == "manuelle" else etape_finale)
                    self.assertEqual(document.publie_au_raa, mode == "deja_realisee")
                    self.assertEqual(mocks["set_dossier_role"].called, mode == "manuelle")

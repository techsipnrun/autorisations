"""Notes : métadonnées réelles, contrôle du déposant et erreurs d'upload."""
from contextlib import ExitStack
from datetime import datetime, timezone
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import Http404
from django.template.loader import get_template, render_to_string
from django.test import RequestFactory, SimpleTestCase

from autorisations.models.models_documents import Document
from instruction.utils.annexes_notes import auteur_annexe, peut_supprimer_annexe, preparer_annexes_notes
from instruction.views import views


class AnnexesNotesTests(SimpleTestCase):
    def setUp(self):
        self.user = User(username="louis.calu", email="louis@example.test", is_superuser=True)
        self.dossier = SimpleNamespace(id=12, numero=123456, emplacement="Travaux/123456/")
        self.doc = Document(
            id=3, titre="annexe.pdf", emplacement="Travaux/123456/Annexes/", id_nature_id=2,
            description="Annexe ajouté par l'instructeur louis.calu sur le dossier 123456",
            date=datetime(2026, 10, 15, 8, tzinfo=timezone.utc),
        )

    def request(self, data=None, upload=False):
        if upload:
            data = {"annexe": SimpleUploadedFile("annexe.pdf", b"contenu", content_type="application/pdf")}
        request = RequestFactory().post("/", data or {}, HTTP_ACCEPT="application/json", HTTP_REFERER="/instruction/123456/")
        request.user = self.user
        request.session = {}
        return request

    def test_auteur_exact_sans_confondre_des_identifiants_proches(self):
        self.assertEqual(auteur_annexe(self.doc, self.dossier), "louis.calu")
        self.assertTrue(peut_supprimer_annexe(self.doc, self.dossier, self.user))
        self.assertFalse(peut_supprimer_annexe(self.doc, self.dossier, User(username="louis", is_superuser=True)))
        self.assertFalse(peut_supprimer_annexe(self.doc, SimpleNamespace(numero=999), self.user))
        self.doc.description = "Annexe sans déposant connu"
        self.assertFalse(peut_supprimer_annexe(self.doc, self.dossier, self.user))

    def test_nom_affiche_resolu_en_lot_depuis_agent_et_date_conservee(self):
        compte = User(username="louis.calu", email="louis@example.test")
        instructeur = SimpleNamespace(email="louis@example.test", id_agent_autorisations=SimpleNamespace(prenom="Louis", nom="Calu"))
        with patch("instruction.utils.annexes_notes.get_user_model") as modele_user, \
             patch("instruction.utils.annexes_notes.Instructeur.objects.annotate") as agents:
            modele_user.return_value.objects.filter.return_value = [compte]
            agents.return_value.filter.return_value.select_related.return_value = [instructeur]
            resultat = preparer_annexes_notes([self.doc], self.dossier, self.user)
        self.assertEqual(resultat[0].depose_par, "Louis Calu")
        self.assertTrue(resultat[0].peut_supprimer)
        self.assertEqual(resultat[0].date.day, 15)
        modele_user.return_value.objects.filter.assert_called_once()
        agents.assert_called_once()

    def test_suppression_autre_auteur_refusee_meme_superutilisateur_sans_toucher_nas(self):
        self.user.username = "autre"
        with patch.object(views, "get_object_or_404", side_effect=[self.doc, self.dossier]), \
             patch.object(views.smbclient.path, "exists") as existe, \
             patch.object(self.doc, "delete") as supprimer:
            with self.assertRaises(PermissionDenied):
                views.supprimer_annexe_instructeur(self.request({"document_id": 3, "dossier_id": 12}))
        existe.assert_not_called()
        supprimer.assert_not_called()

    def test_suppression_controle_le_rattachement_au_dossier(self):
        with patch.object(views, "get_object_or_404", side_effect=[self.doc, self.dossier, Http404()]), \
             patch.object(views.smbclient.path, "exists") as existe:
            with self.assertRaises(Http404):
                views.supprimer_annexe_instructeur(self.request({"document_id": 3, "dossier_id": 12}))
        existe.assert_not_called()

    def test_suppression_autorisee_au_deposant(self):
        with patch.object(views, "get_object_or_404", side_effect=[self.doc, self.dossier, object()]), \
             patch.object(views.smbclient.path, "exists", return_value=True), \
             patch.object(views, "supprimer_file_sur_nas", return_value=True) as supprimer_nas, \
             patch.object(self.doc, "delete") as supprimer:
            resultat = views.supprimer_annexe_instructeur(self.request({"document_id": 3, "dossier_id": 12}))
        self.assertEqual(resultat.status_code, 302)
        supprimer_nas.assert_called_once()
        supprimer.assert_called_once()

    def upload(self, ecriture=True, ancien=None):
        with ExitStack() as stack:
            stack.enter_context(patch.object(views, "get_object_or_404", return_value=self.dossier))
            stack.enter_context(patch.object(views, "est_concerne_par_le_dossier", return_value=True))
            stack.enter_context(patch.object(views, "ajouter_message_action_courante"))
            formats = stack.enter_context(patch.object(views.DocumentFormat.objects, "filter"))
            formats.return_value.first.return_value = SimpleNamespace(pk=1)
            natures = stack.enter_context(patch.object(views.DocumentNature.objects, "filter"))
            natures.return_value.first.return_value = SimpleNamespace(pk=2)
            documents = stack.enter_context(patch.object(views.Document.objects, "filter"))
            documents.return_value.first.return_value = ancien
            existe = stack.enter_context(patch.object(views.smbclient.path, "exists", return_value=False))
            ecrire = stack.enter_context(patch.object(views, "ecrire_file_sur_nas", return_value=ecriture))
            creer_doc = stack.enter_context(patch.object(views.Document.objects, "create", return_value=self.doc))
            creer_lien = stack.enter_context(patch.object(views.DossierDocument.objects, "create"))
            stack.enter_context(patch.object(views.transaction, "atomic"))
            response = views.ajouter_annexe_dossier(self.request(upload=True), self.dossier.id)
        return response, existe, ecrire, creer_doc, creer_lien

    def test_upload_echoue_sans_creer_document_ni_lien_et_retourne_json(self):
        response, _, ecrire, creer_doc, creer_lien = self.upload(ecriture=False)
        self.assertEqual(response.status_code, 500)
        self.assertFalse(json.loads(response.content)["success"])
        ecrire.assert_called_once()
        creer_doc.assert_not_called()
        creer_lien.assert_not_called()

    def test_upload_reussi_enregistre_le_deposant(self):
        response, _, ecrire, creer_doc, creer_lien = self.upload()
        self.assertEqual(response.status_code, 201)
        self.assertTrue(json.loads(response.content)["success"])
        self.assertIn("louis.calu sur le dossier 123456", creer_doc.call_args.kwargs["description"])
        creer_lien.assert_called_once()

    def test_remplacement_ne_contourne_pas_interdiction_de_suppression(self):
        self.doc.description = "Annexe ajouté par l'instructeur quelquun sur le dossier 123456"
        response, existe, ecrire, creer_doc, creer_lien = self.upload(ancien=self.doc)
        self.assertEqual(response.status_code, 403)
        existe.assert_not_called()
        ecrire.assert_not_called()
        creer_doc.assert_not_called()
        creer_lien.assert_not_called()

    def test_composant_partage_affiche_infos_et_suppression_uniquement_pour_auteur(self):
        self.doc.depose_par = "Louis Calu"
        for autorise in (True, False):
            self.doc.peut_supprimer = autorise
            html = render_to_string("instruction/refacto/notes_annexes.html", {
                "dossier": self.dossier, "request": SimpleNamespace(user=self.user),
                "annexes_instructeur": [self.doc], "csrf_token": "test", "NAS_ROOT": "//nas/",
            })
            self.assertIn("Déposé par Louis Calu le 15/10/2026", html)
            self.assertIn("instruction/img/copy.png", html)
            self.assertNotIn("notes-annexe-document-icon", html)
            self.assertNotIn("instruction/img/filetypes/file.png", html)
            self.assertIn('data-path="//nas/Travaux/123456/Annexes/annexe.pdf"', html)
            self.assertEqual('class="form-supprimer-annexe"' in html, autorise)
            if autorise:
                self.assertLess(html.index('class="btn-copier-chemin"'), html.index('class="form-supprimer-annexe"'))
        for template in ("instruction/instruction_dossier.html", "instruction/preinstruction_dossier.html"):
            get_template(template)

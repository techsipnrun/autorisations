"""Création numérotée d'un avis, brouillons et conservation des pièces jointes."""
from contextlib import ExitStack, nullcontext
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase

from instruction.views import avis as vues


class CreationAvisTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = SimpleNamespace(email="admin@example.test", is_authenticated=True)
        self.dossier = SimpleNamespace(id=1, numero=123456, emplacement="Dossier/", id_demarche=SimpleNamespace(type="Travaux"))
        self.nature = SimpleNamespace(id=1, nature="Demande à une instance")
        self.thematique = SimpleNamespace(id=1)
        self.contact = SimpleNamespace(id=2, nom=None, prenom=None, raison_sociale="Conseil Scientifique", organisation=None)
        self.expert = SimpleNamespace(id=3, est_interne=False, id_contact_externe=self.contact)
        self.document = SimpleNamespace(id=40, pk=40, titre="piece.pdf", emplacement="Dossier/Avis/instance/Annexes/")
        self.ancien = None
        self.crees = []
        stack = self.enterContext(ExitStack())
        self.modeles = {nom: stack.enter_context(patch.object(vues, nom)) for nom in (
            "Dossier", "Avis", "Instructeur", "ContactExterne", "Expert", "AvisNature", "AvisThematique", "DossierAvis", "AvisDocument", "Message", "MessageDocument",
        )}
        self.modeles["Dossier"].objects.filter.return_value.first.return_value = self.dossier
        self.modeles["Instructeur"].objects.filter.return_value.first.return_value = self.user
        self.modeles["ContactExterne"].objects.get.return_value = self.contact
        self.modeles["Expert"].objects.get_or_create.return_value = (self.expert, False)
        self.modeles["AvisNature"].objects.get.return_value = self.nature
        self.modeles["AvisThematique"].objects.get.return_value = self.thematique
        self.modeles["Avis"].objects.create.side_effect = self.creer_avis
        self.modeles["Avis"].Destinataire.choices = [("CS", "CS"), ("BCS", "BCS")]
        self.modeles["Avis"].objects.filter.return_value.first.side_effect = lambda: self.ancien
        self.modeles["AvisDocument"].objects.filter.return_value.first.return_value = None
        self.modeles["AvisDocument"].objects.filter.return_value.select_related.return_value = []
        stack.enter_context(patch.object(vues, "emplacement_demande_avis_dossier", return_value="Dossier/Avis/instance/"))
        self.creer_dossier = stack.enter_context(patch.object(vues, "creer_dossier_sur_nas", return_value=True))
        self.enregistrer = stack.enter_context(patch.object(vues, "enregistrer_document", return_value=self.document))
        stack.enter_context(patch.object(vues, "get_or_create_expert_from_form", return_value=(self.expert, "instance")))
        stack.enter_context(patch.object(vues, "redirect_error", side_effect=lambda request, texte: HttpResponse(texte, status=400)))
        stack.enter_context(patch.object(vues, "NOTIFS_PROD", False))
        stack.enter_context(patch.object(vues, "compute_dedupe_key", return_value="test"))
        self.outbox = stack.enter_context(patch.object(vues, "create_EmailOutbox", return_value=SimpleNamespace(id=1, to=[])))
        stack.enter_context(patch.object(vues, "envoi_mail", return_value=(True, None)))
        self.reservation = SimpleNamespace(numero=101, id_avis_id=None)
        self.verrouiller = stack.enter_context(patch.object(vues, "creation_avis_reservee", side_effect=lambda *args: nullcontext(self.reservation)))
        stack.enter_context(patch.object(vues, "modification_brouillon_verrouillee", side_effect=lambda *args: nullcontext(self.ancien)))
        self.utiliser = stack.enter_context(patch.object(vues, "utiliser_reservation"))
        stack.enter_context(patch.object(vues.transaction, "on_commit", side_effect=lambda callback: callback()))

    def creer_avis(self, **champs):
        valeurs = dict(id=len(self.crees) + 101, id_projet_avis=None, id_projet_acte=None, id_rapport_instance=None,
                       id_projet_avis_id=None, id_projet_acte_id=None, id_rapport_instance_id=None,
                       id_avis_nature_id=1, statut="Brouillon", date_demande_avis=None, save=Mock())
        valeurs.update(champs)
        for champ in ("id_projet_avis", "id_projet_acte", "id_rapport_instance"):
            if valeurs.get(champ):
                valeurs[f"{champ}_id"] = valeurs[champ].id
        avis = SimpleNamespace(**valeurs)
        self.crees.append(avis)
        return avis

    def requete(self, **champs):
        donnees = {"nature": "1", "thematique": "1", "expert_externe": "2", "destinataire": "CS"}
        donnees.update(champs)
        request = self.factory.post("/avis/", donnees)
        request.user = self.user
        return request

    def test_generer_numero_cree_brouillon_et_redirige_edition_sans_notifier(self):
        response = vues.instruction_dossier_enregistrer_brouillon_avis(self.requete(generer_numero="1", mode_contact="Mail"), 123456)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.endswith("/avis/101/edit"))
        self.assertEqual(self.crees[0].statut, "Brouillon")
        self.assertEqual(self.crees[0].mode_contact, "Application")
        self.assertEqual(self.crees[0].destinataire, "CS")
        self.assertEqual(self.crees[0].formulation, "")
        self.assertIs(self.crees[0].id_demarche, self.dossier.id_demarche)
        self.outbox.assert_not_called()
        self.modeles["Message"].objects.create.assert_not_called()
        self.assertEqual(self.modeles["Avis"].objects.create.call_args.kwargs["id"], self.reservation.numero)
        self.utiliser.assert_called_once()

    def test_generation_rejouee_retourne_le_brouillon_sans_nouvelle_creation(self):
        self.reservation.id_avis_id = 101
        response = vues.instruction_dossier_enregistrer_brouillon_avis(self.requete(generer_numero="1"), 123456)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.endswith("/avis/101/edit"))
        self.modeles["Avis"].objects.create.assert_not_called()
        self.utiliser.assert_not_called()
        self.outbox.assert_not_called()

    def test_generation_refusee_si_numero_existe_deja_ou_mauvaise_nature(self):
        response = vues.instruction_dossier_enregistrer_brouillon_avis(self.requete(generer_numero="1"), 123456, avis_id=101)
        self.assertEqual(response.status_code, 400)
        self.nature.nature = "Consultation en interne"
        response = vues.instruction_dossier_enregistrer_brouillon_avis(self.requete(generer_numero="1"), 123456)
        self.assertEqual(response.status_code, 400)
        self.modeles["Avis"].objects.create.assert_not_called()

    def test_generation_cs_exige_destinataire(self):
        response = vues.instruction_dossier_enregistrer_brouillon_avis(self.requete(generer_numero="1", destinataire=""), 123456)
        self.assertEqual(response.status_code, 400)
        self.modeles["Avis"].objects.create.assert_not_called()

    def test_autres_pj_sauvegardees_avec_nouveau_brouillon(self):
        response = vues.instruction_dossier_enregistrer_brouillon_avis(self.requete(pj_lie_avis=SimpleUploadedFile("piece.pdf", b"pdf")), 123456)
        self.assertEqual(response.status_code, 302)
        self.modeles["AvisDocument"].objects.get_or_create.assert_called_once_with(id_avis=self.crees[0], id_document=self.document)
        self.outbox.assert_not_called()

    def test_toutes_les_pj_multiples_sont_sauvegardees_dans_le_brouillon(self):
        documents = [SimpleNamespace(id=pk, pk=pk) for pk in (40, 41, 42)]
        self.enregistrer.side_effect = documents
        response = vues.instruction_dossier_enregistrer_brouillon_avis(self.requete(
            pj_lie_avis=[SimpleUploadedFile(f"piece-{pk}.pdf", b"pdf") for pk in (40, 41, 42)]), 123456)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.enregistrer.call_count, 3)
        self.assertEqual([appel.kwargs["id_document"] for appel in
            self.modeles["AvisDocument"].objects.get_or_create.call_args_list], documents)
        self.outbox.assert_not_called()

    def test_autres_pj_partagees_avec_les_trois_champs_principaux_sont_liees(self):
        noms = ["formulaire_modifie.png", "logo_edit.png", "fiche de suivi (1).docx", "Statistiques AGIDA.pdf"]
        documents = {
            nom: SimpleNamespace(id=pk, pk=pk, titre=nom)
            for pk, nom in enumerate(noms, start=40)
        }
        # Comme sur le NAS : même emplacement et titre => même Document.
        self.enregistrer.side_effect = lambda fichier, **kwargs: documents[fichier.name]
        response = vues.instruction_dossier_enregistrer_brouillon_avis(self.requete(
            pj_demande_avis=SimpleUploadedFile(noms[2], b"word"),
            pj_projet_acte=SimpleUploadedFile(noms[3], b"pdf"),
            pj_rapport_cs=SimpleUploadedFile(noms[3], b"pdf"),
            pj_lie_avis=[SimpleUploadedFile(nom, b"contenu") for nom in noms],
        ), 123456)
        self.assertEqual(response.status_code, 302)
        avis = self.crees[0]
        self.assertIs(avis.id_projet_avis, documents[noms[2]])
        self.assertIs(avis.id_projet_acte, documents[noms[3]])
        self.assertIs(avis.id_rapport_instance, documents[noms[3]])
        self.assertEqual([appel.kwargs["id_document"] for appel in
            self.modeles["AvisDocument"].objects.get_or_create.call_args_list], list(documents.values()))
        self.outbox.assert_not_called()

    def test_nature_brouillon_verrouillee_cote_serveur_pour_sauvegarde_et_envoi(self):
        self.ancien = self.creer_avis()
        for vue in (vues.instruction_dossier_enregistrer_brouillon_avis, vues.instruction_dossier_confirmer_ajout_avis):
            with self.subTest(vue=vue.__name__):
                response = vue(self.requete(nature="2"), 123456, avis_id=101)
                self.assertEqual(response.status_code, 400)
                self.assertIn("nature", response.content.decode())
        self.ancien.save.assert_not_called()
        self.enregistrer.assert_not_called()
        self.outbox.assert_not_called()

    def test_brouillon_interne_conserve_message_note_et_pj_sans_notifier(self):
        self.nature.nature = "Consultation en interne"
        self.expert.est_interne = True
        self.modeles["Instructeur"].objects.get.return_value = SimpleNamespace(
            id_agent_autorisations=SimpleNamespace(nom="TEST", prenom="Agent"))
        response = vues.instruction_dossier_enregistrer_brouillon_avis(self.requete(
            expert_externe="", expert_interne="8", note_demandeur="Note interne",
            formulation_avis="Bonjour, je sollicite votre avis sur le dossier 123456…",
            pj_lie_avis=SimpleUploadedFile("piece.pdf", b"pdf")), 123456)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.crees[0].note, "Note interne")
        self.assertIn("123456", self.crees[0].formulation)
        self.assertIsNone(self.crees[0].destinataire)
        self.modeles["AvisDocument"].objects.get_or_create.assert_called_once()
        self.outbox.assert_not_called()

    def test_autres_pj_sauvegardees_avec_brouillon_existant_et_conservees_sans_reupload(self):
        self.ancien = self.creer_avis(id_dossier=self.dossier, id_demarche=self.dossier.id_demarche,
            id_expert=self.expert, id_avis_nature=self.nature, id_avis_thematique=self.thematique,
            destinataire="BCS", note="", formulation="Texte", mode_contact="Application", emplacement="Dossier/Avis/instance/")
        response = vues.instruction_dossier_enregistrer_brouillon_avis(self.requete(pj_lie_avis=SimpleUploadedFile("piece.pdf", b"pdf")), 123456, avis_id=101)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(self.crees), 1)
        self.modeles["AvisDocument"].objects.get_or_create.assert_called_once()
        self.modeles["AvisDocument"].objects.get_or_create.reset_mock()
        vues.instruction_dossier_enregistrer_brouillon_avis(self.requete(), 123456, avis_id=101)
        self.modeles["AvisDocument"].objects.get_or_create.assert_not_called()
        self.modeles["AvisDocument"].objects.delete.assert_not_called()

    def test_remplacement_pj_complementaire_limite_aux_documents_de_cet_avis(self):
        avis = SimpleNamespace(id=101, emplacement="Dossier/Avis/instance/")
        lien = SimpleNamespace(id_document_id=39, delete=Mock())
        self.modeles["AvisDocument"].objects.filter.return_value.select_related.return_value = [lien]
        vues._enregistrer_pj_complementaires(self.requete(remplacer_pj_39=SimpleUploadedFile("piece.pdf", b"nouveau")), avis)
        self.modeles["AvisDocument"].objects.get_or_create.assert_called_once_with(id_avis=avis, id_document=self.document)
        lien.delete.assert_called_once()
        with self.assertRaisesMessage(ValueError, "n'appartient pas"):
            vues._enregistrer_pj_complementaires(self.requete(remplacer_pj_999=SimpleUploadedFile("piece.pdf", b"pdf")), avis)

    def test_echec_ecriture_pj_non_masque_et_pas_de_lien_invalide(self):
        self.enregistrer.return_value = None
        response = vues.instruction_dossier_enregistrer_brouillon_avis(self.requete(pj_lie_avis=SimpleUploadedFile("piece.pdf", b"pdf")), 123456)
        self.assertEqual(response.status_code, 400)
        self.modeles["AvisDocument"].objects.get_or_create.assert_not_called()

    def test_echec_remplacement_document_principal_refuse_sauvegarde_et_envoi(self):
        self.enregistrer.return_value = None
        for vue in (vues.instruction_dossier_enregistrer_brouillon_avis, vues.instruction_dossier_confirmer_ajout_avis):
            with self.subTest(vue=vue.__name__):
                response = vue(self.requete(pj_demande_avis=SimpleUploadedFile("projet.docx", b"word")), 123456)
                self.assertEqual(response.status_code, 400)
        self.modeles["Avis"].objects.create.assert_not_called()
        self.outbox.assert_not_called()

    def test_envoi_brouillon_joint_le_projet_deja_enregistre_au_message(self):
        self.ancien = self.creer_avis(id_dossier=self.dossier, id_demarche=self.dossier.id_demarche,
            id_expert=self.expert, id_instructeur=self.user, id_avis_nature=self.nature, id_avis_thematique=self.thematique,
            destinataire="BCS", note="", formulation="Texte", mode_contact="Application", emplacement="Dossier/Avis/instance/",
            id_projet_avis=self.document, id_projet_acte=self.document)
        response = vues.instruction_dossier_confirmer_ajout_avis(self.requete(formulation_avis="Demande finale", mode_contact="Mail"), 123456, avis_id=101)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.modeles["Message"].objects.create.call_args.kwargs["piece_jointe"])
        self.assertIs(self.modeles["MessageDocument"].objects.create.call_args.kwargs["id_document"], self.document)
        self.assertEqual(self.ancien.mode_contact, "Application")

    def test_envoi_instance_refuse_sans_documents_obligatoires(self):
        for fichiers in ({}, {"pj_demande_avis": SimpleUploadedFile("avis.docx", b"word")}):
            with self.subTest(fichiers=list(fichiers)):
                response = vues.instruction_dossier_confirmer_ajout_avis(self.requete(formulation_avis="Demande", **fichiers), 123456)
                self.assertEqual(response.status_code, 400)
        self.modeles["Avis"].objects.create.assert_not_called()
        self.outbox.assert_not_called()

    def test_brouillon_deja_envoye_ne_declenche_pas_un_second_envoi(self):
        self.ancien = self.creer_avis(statut="Envoyé")
        response = vues.instruction_dossier_confirmer_ajout_avis(self.requete(), 123456, avis_id=101)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.endswith("/consultation"))
        self.modeles["Message"].objects.create.assert_not_called()
        self.outbox.assert_not_called()

    def test_suppression_refuse_document_etranger_et_detache_document_principal(self):
        self.ancien = self.creer_avis()
        request = self.requete()
        response = vues.supprimer_pj_avis(request, 101, 999)
        self.assertEqual(response.status_code, 403)
        self.ancien.id_projet_avis_id = 40
        self.ancien.id_projet_avis = self.document
        response = vues.supprimer_pj_avis(request, 101, 40)
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(self.ancien.id_projet_avis)

    def test_suppression_pj_partagee_ne_retire_que_le_champ_cible(self):
        champs = ("id_projet_avis", "id_projet_acte", "id_rapport_instance")
        for cible in champs:
            with self.subTest(champ=cible):
                self.ancien = self.creer_avis(**{champ: self.document for champ in champs},
                    **{f"{champ}_id": self.document.id for champ in champs})
                lien_annexe = Mock()
                self.modeles["AvisDocument"].objects.filter.return_value.first.return_value = lien_annexe
                response = vues.supprimer_pj_avis(self.requete(source=cible), 101, self.document.id)
                self.assertEqual(response.status_code, 302)
                for champ in champs:
                    self.assertIs(getattr(self.ancien, champ), None if champ == cible else self.document)
                self.ancien.save.assert_called_once_with(update_fields=[cible])
                lien_annexe.delete.assert_not_called()

    def test_suppression_annexe_partagee_conserve_les_champs_principaux(self):
        self.ancien = self.creer_avis(id_projet_acte=self.document, id_projet_acte_id=self.document.id,
            id_rapport_instance=self.document, id_rapport_instance_id=self.document.id)
        for source in ("annexe", None):
            with self.subTest(source=source):
                lien_annexe = Mock()
                self.modeles["AvisDocument"].objects.filter.return_value.first.return_value = lien_annexe
                request = self.requete(**({"source": source} if source else {}))
                response = vues.supprimer_pj_avis(request, 101, self.document.id)
                self.assertEqual(response.status_code, 302)
                lien_annexe.delete.assert_called_once()
                self.assertIs(self.ancien.id_projet_acte, self.document)
                self.assertIs(self.ancien.id_rapport_instance, self.document)
        self.ancien.save.assert_not_called()

    def test_suppression_sans_source_refuse_si_plusieurs_champs_partagent_le_document(self):
        self.ancien = self.creer_avis(id_projet_acte=self.document, id_projet_acte_id=self.document.id,
            id_rapport_instance=self.document, id_rapport_instance_id=self.document.id)
        response = vues.supprimer_pj_avis(self.requete(), 101, self.document.id)
        self.assertEqual(response.status_code, 400)
        self.ancien.save.assert_not_called()
        self.assertIs(self.ancien.id_projet_acte, self.document)
        self.assertIs(self.ancien.id_rapport_instance, self.document)

    def test_suppression_source_invalide_ou_ne_correspondant_pas_au_document_refusee(self):
        self.ancien = self.creer_avis(id_projet_acte=self.document, id_projet_acte_id=self.document.id)
        for source, statut in (("id_rapport_instance", 403), ("emplacement", 400), ("annexe", 403)):
            with self.subTest(source=source):
                response = vues.supprimer_pj_avis(self.requete(source=source), 101, self.document.id)
                self.assertEqual(response.status_code, statut)
        self.ancien.save.assert_not_called()

from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import patch

from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase

from instruction.views import avis as vues
from . import test_creation_avis as support


class AvisGeneriqueTests(SimpleTestCase):
    setUp = support.CreationAvisTests.setUp
    creer_avis = support.CreationAvisTests.creer_avis
    def requete(self, **champs):
        champs.setdefault("pj_projet_acte", SimpleUploadedFile("acte.pdf", b"pdf"))
        return support.CreationAvisTests.requete(self, **champs)

    def preparer(self):
        demarches = self.enterContext(patch.object(vues, "Demarche"))
        demarches.objects.get.return_value = self.dossier.id_demarche
        self.enterContext(patch.object(vues, "messages"))

    def test_ouverture_get_presente_le_post_csrf_sans_reserver(self):
        self.preparer()
        with patch.object(vues, "reserver_numero") as reserver, patch.object(vues, "render", return_value=HttpResponse()) as render:
            request = self.factory.get("/nouvelle-demande/")
            request.user = self.user
            vues.nouvelle_demande_avis_generique(request)
            self.assertEqual(render.call_args.args[1], "instruction/avis_reserver_numero.html")
            self.assertIn("reservation_cle", render.call_args.args[2])
            reserver.assert_not_called()
        self.modeles["Avis"].objects.create.assert_not_called()
        self.outbox.assert_not_called()

    def test_post_reserve_et_redirige_vers_url_stable_sans_creer_un_avis(self):
        self.preparer()
        cle = uuid4()
        with patch.object(vues, "reserver_numero", return_value=SimpleNamespace(pk=cle)) as reserver:
            response = vues.nouvelle_demande_avis_generique(self.requete(reservation=str(cle)))
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response.url.endswith("?reservation=" + str(cle)))
            reserver.assert_called_once_with(self.user, cle=str(cle))
        self.modeles["Avis"].objects.create.assert_not_called()
        self.outbox.assert_not_called()

    def test_actualisation_relit_la_reservation_sans_consumer_un_autre_numero(self):
        self.preparer()
        request = self.factory.get("/nouvelle-demande/", {"reservation": str(uuid4())})
        request.user = self.user
        with patch.object(vues, "lire_reservation", return_value=self.reservation), patch.object(vues, "reserver_numero") as reserver, patch.object(vues, "render", return_value=HttpResponse()) as render:
            for _ in range(2):
                vues.nouvelle_demande_avis_generique(request)
            self.assertIs(render.call_args.args[2]["reservation"], self.reservation)
            reserver.assert_not_called()

    def test_reservation_etrangere_refusee(self):
        self.preparer()
        with patch.object(vues, "lire_reservation", side_effect=PermissionDenied("Interdit")):
            request = self.factory.get("/avis/", {"reservation": str(uuid4())})
            request.user = self.user
            self.assertEqual(vues.nouvelle_demande_avis_generique(request).status_code, 403)

    def test_echec_reservation_ne_provoque_pas_de_boucle_de_redirection(self):
        self.preparer()
        with patch.object(vues, "reserver_numero", side_effect=RuntimeError("Service indisponible")):
            response = vues.nouvelle_demande_avis_generique(self.requete(reservation=str(uuid4())))
            self.assertEqual(response.status_code, 503)

    def test_envoi_instance_utilise_le_numero_reserve_et_le_chemin_distinct(self):
        self.preparer()
        request = self.requete(demarche="1", formulation_avis="Demande à l'instance", pj_demande_avis=SimpleUploadedFile("projet.docx", b"word"))
        response = vues.avis_confirmer_nouvelle_demande_generique(request)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.modeles["Avis"].objects.create.call_args.kwargs["id"], 101)
        self.assertTrue(self.crees[0].emplacement.endswith("_101/"))
        self.utiliser.assert_called_once_with(request, self.crees[0])
        self.assertTrue(request.creation_avis_validee)
        self.outbox.assert_called_once()
        self.assertEqual(self.outbox.call_args.args[0], [vues.EMAIL_NOTIF_TEST])

    def test_projet_acte_requis_comme_pour_les_demandes_depuis_consultation(self):
        self.preparer()
        response = vues.avis_confirmer_nouvelle_demande_generique(self.requete(demarche="1", formulation_avis="Demande",
            pj_demande_avis=SimpleUploadedFile("avis.docx", b"word"), pj_projet_acte=""))
        self.assertEqual(response.status_code, 400)
        self.modeles["Avis"].objects.create.assert_not_called()
        self.outbox.assert_not_called()

    def test_consultation_interne_ignore_les_champs_instance_masques(self):
        self.preparer()
        self.nature.nature = "Consultation en interne"
        self.expert.est_interne = True
        request = self.requete(demarche="1", expert_interne="8", expert_externe="", formulation_avis="Demande interne",
            pj_demande_avis=SimpleUploadedFile("ne-pas-transmettre.docx", b"word"), pj_rapport_cs=SimpleUploadedFile("ne-pas-transmettre.pdf", b"pdf"),
            pj_lie_avis=[SimpleUploadedFile("piece1.pdf", b"pdf"), SimpleUploadedFile("piece2.pdf", b"pdf")])
        response = vues.avis_confirmer_nouvelle_demande_generique(request)
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(self.crees[0].id_projet_avis)
        self.assertIsNone(self.crees[0].id_rapport_instance)
        self.assertEqual(self.enregistrer.call_count, 2)
        self.assertEqual(self.modeles["AvisDocument"].objects.get_or_create.call_count, 2)

    def test_double_soumission_redirige_sans_second_avis_ni_notification(self):
        self.preparer()
        self.reservation.id_avis_id = 101
        response = vues.avis_confirmer_nouvelle_demande_generique(self.requete())
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.endswith("/101/"))
        self.modeles["Avis"].objects.create.assert_not_called()
        self.outbox.assert_not_called()

    def test_rejouer_un_envoi_reussi_ne_cree_pas_de_second_avis(self):
        self.preparer()
        self.utiliser.side_effect = lambda request, avis: setattr(self.reservation, "id_avis_id", avis.id)
        request = self.requete(demarche="1", formulation_avis="Demande", pj_demande_avis=SimpleUploadedFile("projet.docx", b"word"))
        vues.avis_confirmer_nouvelle_demande_generique(request)
        response = vues.avis_confirmer_nouvelle_demande_generique(self.requete())
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(self.crees), 1)
        self.outbox.assert_called_once()

    def test_notification_attend_le_commit(self):
        self.preparer()
        with patch.object(vues.transaction, "on_commit") as apres_commit, patch.object(vues, "envoi_mail", return_value=(True, None)) as envoyer:
            request = self.requete(demarche="1", formulation_avis="Demande", pj_demande_avis=SimpleUploadedFile("projet.docx", b"word"))
            vues.avis_confirmer_nouvelle_demande_generique(request)
            envoyer.assert_not_called()
            apres_commit.assert_called_once()
            apres_commit.call_args.args[0]()
            envoyer.assert_called_once_with(1)

    def test_erreur_upload_ne_valide_pas_la_creation_ni_la_notification(self):
        self.preparer()
        self.enregistrer.return_value = None
        request = self.requete(demarche="1", formulation_avis="Demande", pj_demande_avis=SimpleUploadedFile("projet.docx", b"word"))
        response = vues.avis_confirmer_nouvelle_demande_generique(request)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(getattr(request, "creation_avis_validee", False))
        self.modeles["Avis"].objects.create.assert_not_called()
        self.utiliser.assert_not_called()
        self.outbox.assert_not_called()

    def test_notifs_prod_conserve_les_destinataires_reels(self):
        self.preparer()
        with patch.object(vues, "NOTIFS_PROD", True), patch.object(vues, "get_email_expert", return_value="expert@example.test"):
            request = self.requete(demarche="1", formulation_avis="Demande", pj_demande_avis=SimpleUploadedFile("projet.docx", b"word"))
            vues.avis_confirmer_nouvelle_demande_generique(request)
        self.assertEqual(self.outbox.call_args.args[0], ["expert@example.test"])

"""Réservation immédiate depuis Consultation, sans création de brouillon implicite."""
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import patch

from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.test import SimpleTestCase

from instruction.views import avis as vues
from . import test_creation_avis as support


class OuvertureAvisDossierTests(SimpleTestCase):
    setUp = support.CreationAvisTests.setUp
    creer_avis = support.CreationAvisTests.creer_avis
    requete = support.CreationAvisTests.requete

    def preparer(self):
        self.reservation.pk = self.reservation.id = uuid4()
        self.render = self.enterContext(patch.object(vues, "render", return_value=HttpResponse()))
        self.reserver = self.enterContext(patch.object(vues, "reserver_numero", return_value=self.reservation))
        self.lire = self.enterContext(patch.object(vues, "lire_reservation", return_value=self.reservation))
        self.enterContext(patch.object(vues, "thematiques_avis_liees_a_demarche", return_value=[]))
        for nom in ("get_chemin_complet_dossier", "count_unread_messages_for_dossier", "count_avis_with_unread_messages_for_dossier"):
            self.enterContext(patch.object(vues, nom, return_value=0))

    def get(self, reservation=None):
        request = self.factory.get("/instruction/123456/ajouter_avis", {"reservation": str(reservation)} if reservation else {})
        request.user = self.user
        return vues.instruction_dossier_ajouter_avis(request, 123456)

    def test_get_presente_post_automatique_sans_reserver_sur_un_get(self):
        self.preparer()
        self.assertEqual(self.get().status_code, 200)
        self.assertEqual(self.render.call_args.args[1], "instruction/avis_reserver_numero.html")
        self.assertIs(self.render.call_args.args[2]["dossier"], self.dossier)
        self.reserver.assert_not_called()
        self.modeles["Avis"].objects.create.assert_not_called()

    def test_post_reserve_sans_creer_avis_ni_notifier_et_redirige_url_stable(self):
        self.preparer()
        response = vues.instruction_dossier_ajouter_avis(self.requete(reservation=str(self.reservation.pk)), 123456)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.endswith("/123456/ajouter_avis?reservation=" + str(self.reservation.pk)))
        self.reserver.assert_called_once_with(self.user, self.dossier, str(self.reservation.pk))
        self.modeles["Avis"].objects.create.assert_not_called()
        self.outbox.assert_not_called()

    def test_actualisation_conserve_numero_et_ouvre_formulaire_complet_sans_brouillon(self):
        self.preparer()
        for _ in range(2):
            self.assertEqual(self.get(self.reservation.pk).status_code, 200)
        self.reserver.assert_not_called()
        self.assertEqual(self.render.call_args.args[1], "instruction/instruction_dossier_ajouter_avis.html")
        contexte = self.render.call_args.args[2]
        self.assertEqual(contexte["numero_avis"], 101)
        self.assertIsNone(contexte["avis"])
        self.assertIs(contexte["reservation"], self.reservation)
        self.lire.assert_called_with(str(self.reservation.pk), self.user, self.dossier)

    def test_reservation_utilisee_retrouve_brouillon_sans_dupliquer(self):
        self.preparer()
        self.reservation.id_avis_id = 101
        response = self.get(self.reservation.pk)
        self.assertTrue(response.url.endswith("/avis/101/edit"))
        self.modeles["Avis"].objects.create.assert_not_called()
        self.outbox.assert_not_called()

    def test_reservation_autre_dossier_ou_utilisateur_refusee(self):
        self.preparer()
        self.lire.side_effect = PermissionDenied("Mauvais contexte")
        self.assertEqual(self.get(self.reservation.pk).status_code, 403)

    def test_formulaire_de_reservation_poste_sur_la_route_du_dossier(self):
        html = render_to_string("instruction/avis_reserver_numero.html", {"dossier": self.dossier, "reservation_cle": uuid4()})
        self.assertIn('action="/instruction/123456/ajouter_avis"', html)
        self.assertNotIn("générique</h1>", html)

    def test_reouverture_brouillon_affiche_toutes_les_annexes_meme_partagees(self):
        self.preparer()
        noms = ["formulaire_modifie.png", "logo_edit.png", "fiche de suivi (1).docx", "Statistiques AGIDA.pdf"]
        documents = [SimpleNamespace(id=pk, pk=pk, titre=nom, emplacement="Avis/instance/Annexes/")
                     for pk, nom in enumerate(noms, start=40)]
        self.ancien = self.creer_avis(id_projet_avis=documents[2], id_projet_acte=documents[3],
            id_rapport_instance=documents[3], id_avis_nature=self.nature)
        self.modeles["Avis"].objects.filter.return_value.select_related.return_value.first.return_value = self.ancien
        liens = [SimpleNamespace(id_document=doc, id_document_id=doc.pk) for doc in documents]
        query = self.modeles["AvisDocument"].objects.filter.return_value
        query.exclude.return_value.select_related.return_value.order_by.return_value = liens

        request = self.factory.get("/instruction/123456/avis/101/edit")
        request.user = self.user
        response = vues.instruction_dossier_ajouter_avis(request, 123456, avis_id=101)
        self.assertEqual(response.status_code, 200)
        self.modeles["AvisDocument"].objects.filter.assert_called_once_with(id_avis=self.ancien)
        # Ne pas exclure les références des champs principaux : seul l'avis signé est à part.
        query.exclude.assert_called_once_with(id_document__id_nature__nature="Avis instance")
        contexte = self.render.call_args.args[2]
        self.assertEqual(contexte["pieces_complementaires"], liens)
        html = render_to_string("instruction/refacto/demande_avis_formulaire.html", {
            **contexte, "natures": [self.nature], "thematiques": [self.thematique],
        })
        for doc in documents:
            self.assertIn(f'name="remplacer_pj_{doc.pk}"', html)
        self.assertEqual(html.count('data-pj-source="annexe"'), 4)
        self.reserver.assert_not_called()
        self.outbox.assert_not_called()

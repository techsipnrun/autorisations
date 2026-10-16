"""Réservations et contrôles d'accès sans connexion à une base réelle."""
from contextlib import ExitStack, nullcontext
from importlib import import_module
import re
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import Mock, patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import RequestFactory, SimpleTestCase

from instruction.utils import avis_reservations as service


class AvisReservationsTests(SimpleTestCase):
    def test_contraintes_sql_numero_nont_pas_de_collision_de_nom(self):
        sql = import_module("autorisations.migrations.0040_avis_reservations").SQL
        self.assertIn("numero integer NOT NULL UNIQUE,", sql)
        self.assertIn("CONSTRAINT avis_reservation_numero_positif_check CHECK (numero > 0)", sql)
        self.assertIn("CONSTRAINT avis_reservation_numero_check CHECK (id_avis IS NULL OR id_avis = numero)", sql)
        noms = re.findall(r"CONSTRAINT\s+(\w+)", sql)
        self.assertEqual(len(noms), len(set(noms)))

    def setUp(self):
        self.cle = uuid4()
        self.instructeur = SimpleNamespace(pk=7)
        self.dossier = SimpleNamespace(pk=9)
        self.reservation = SimpleNamespace(pk=self.cle, numero=1050, id_instructeur_id=7,
            contexte="generique", id_dossier_id=None, date_utilisation=None, id_avis_id=None, save=Mock())
        stack = self.enterContext(ExitStack())
        self.modele = stack.enter_context(patch.object(service, "AvisReservation"))
        self.modele.objects.filter.return_value.first.return_value = None
        self.modele.objects.get_or_create.return_value = (self.reservation, True)
        self.modele.objects.select_for_update.return_value.filter.return_value.first.return_value = self.reservation
        self.connexion = stack.enter_context(patch.object(service, "connection"))
        self.curseur = self.connexion.cursor.return_value.__enter__.return_value
        self.curseur.fetchone.return_value = (1050,)
        self.transaction = stack.enter_context(patch.object(service, "transaction"))
        self.transaction.atomic.side_effect = lambda: nullcontext()
        self.instructeurs = stack.enter_context(patch.object(service, "Instructeur"))
        self.instructeurs.objects.filter.return_value.first.return_value = self.instructeur
        self.dossiers = stack.enter_context(patch.object(service, "Dossier"))
        self.dossiers.objects.filter.return_value.first.return_value = self.dossier
        self.avis = stack.enter_context(patch.object(service, "Avis"))

    def test_reserve_depuis_la_sequence_des_avis_sans_creer_un_avis(self):
        resultat = service.reserver_numero(self.instructeur, cle=self.cle)
        self.assertIs(resultat, self.reservation)
        self.curseur.execute.assert_called_once_with("SELECT nextval(pg_get_serial_sequence('avis.avis', 'id'))")
        champs = self.modele.objects.get_or_create.call_args.kwargs["defaults"]
        self.assertEqual(champs["numero"], 1050)
        self.assertEqual(champs["contexte"], "generique")
        self.assertIsNone(champs["id_dossier"])

    def test_rejouer_la_meme_cle_conserve_le_numero_sans_consumer_la_sequence(self):
        self.modele.objects.filter.return_value.first.return_value = self.reservation
        self.assertIs(service.reserver_numero(self.instructeur, cle=self.cle), self.reservation)
        self.connexion.cursor.assert_not_called()

    def test_reservation_consultation_liee_au_dossier(self):
        self.reservation.contexte, self.reservation.id_dossier_id = "dossier", 9
        service.reserver_numero(self.instructeur, self.dossier, self.cle)
        self.assertIs(self.modele.objects.get_or_create.call_args.kwargs["defaults"]["id_dossier"], self.dossier)

    def test_refuse_utilisateur_ou_contexte_etranger(self):
        for instructeur, dossier in ((SimpleNamespace(pk=8), None), (self.instructeur, self.dossier)):
            with self.subTest(instructeur=instructeur, dossier=dossier), self.assertRaises(PermissionDenied):
                service.verifier_reservation(self.reservation, instructeur, dossier)
        self.reservation.contexte, self.reservation.id_dossier_id = "dossier", 9
        with self.assertRaises(PermissionDenied):
            service.verifier_reservation(self.reservation, self.instructeur, SimpleNamespace(pk=10))

    def test_avis_supprime_ne_libere_jamais_son_numero(self):
        self.reservation.date_utilisation = "utilisée"
        with self.assertRaises(ValidationError):
            service.verifier_reservation(self.reservation, self.instructeur)

    def test_uuid_invalide_ou_reservation_absente_refuse(self):
        for valeur in (None, "", "123", "invalide"):
            with self.subTest(valeur=valeur), self.assertRaises(ValidationError):
                service.cle_reservation(valeur)
        with self.assertRaises(ValidationError):
            service.lire_reservation(self.cle, self.instructeur)
        self.connexion.cursor.assert_not_called()

    def test_utilisation_lie_avis_et_date_et_refuse_reutilisation(self):
        request = SimpleNamespace(reservation_avis=self.reservation)
        avis = SimpleNamespace(pk=1050)
        service.utiliser_reservation(request, avis)
        self.assertIs(self.reservation.id_avis, avis)
        self.assertIsNotNone(self.reservation.date_utilisation)
        self.reservation.save.assert_called_once_with(update_fields=["id_avis", "date_utilisation"])
        with self.assertRaises(ValidationError):
            service.utiliser_reservation(request, avis)

    def test_numero_different_refuse(self):
        with self.assertRaises(ValidationError):
            service.utiliser_reservation(SimpleNamespace(reservation_avis=self.reservation), SimpleNamespace(pk=1))
        self.reservation.save.assert_not_called()

    def requete(self):
        request = RequestFactory().post("/avis/", {"reservation": str(self.cle)})
        request.user = SimpleNamespace(email="agent@example.test")
        return request

    def test_verrou_de_ligne_et_rollback_si_formulaire_invalide(self):
        with service.creation_avis_reservee(self.requete()) as reservation:
            self.assertIs(reservation, self.reservation)
            self.modele.objects.select_for_update.assert_called_once()
        self.transaction.set_rollback.assert_called_once_with(True)

    def test_creation_validee_ne_demande_pas_de_rollback(self):
        request = self.requete()
        with service.creation_avis_reservee(request):
            request.creation_avis_validee = True
        self.transaction.set_rollback.assert_not_called()

    def test_creation_dossier_ne_reserve_plus_implicitement_un_numero_absent(self):
        self.modele.objects.select_for_update.return_value.filter.return_value.first.return_value = None
        with self.assertRaises(ValidationError), service.creation_avis_reservee(self.requete(), 12345):
            pass
        self.connexion.cursor.assert_not_called()
        self.modele.objects.get_or_create.assert_not_called()

    def test_lecture_verrouillee_dossier_ne_modifie_pas_le_perimetre(self):
        self.reservation.contexte, self.reservation.id_dossier_id = "dossier", 9
        self.modele.objects.filter.return_value.first.return_value = self.reservation
        request = self.requete()
        with service.creation_avis_reservee(request, 12345):
            self.assertIs(request.dossier_reservation, self.dossier)
            request.creation_avis_validee = True
        self.dossiers.objects.filter.assert_called_once_with(numero=12345)

    def test_absence_de_profil_instructeur_refusee_avant_verrou(self):
        self.instructeurs.objects.filter.return_value.first.return_value = None
        with self.assertRaises(PermissionDenied), service.creation_avis_reservee(self.requete()):
            pass
        self.modele.objects.select_for_update.assert_not_called()

    def test_modification_brouillon_verrouille_le_bon_avis_du_bon_dossier(self):
        request = self.requete()
        self.avis.objects.select_for_update.return_value.filter.return_value.first.return_value = SimpleNamespace(id=55)
        with service.modification_brouillon_verrouillee(request, 12345, 55) as avis:
            self.assertEqual(avis.id, 55)
            request.creation_avis_validee = True
        self.avis.objects.select_for_update.return_value.filter.assert_called_once_with(id=55, id_dossier__numero=12345)
        self.transaction.set_rollback.assert_not_called()

    def test_echec_modification_brouillon_rollback(self):
        with service.modification_brouillon_verrouillee(self.requete(), 12345, 55):
            pass
        self.transaction.set_rollback.assert_called_once_with(True)

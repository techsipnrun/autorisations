from contextlib import ExitStack
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from synchronisation.utils.conversion import parse_datetime_with_tz
from synchronisation.synchro.sync_dossier_champs import notifier_formulaire_modifie
from tests.support.constants import CHAMPS


class NotificationFormulaireTests(SimpleTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.dossier = SimpleNamespace(numero=123, id_demarche=SimpleNamespace(type="Démarche de test"))
        self.date = parse_datetime_with_tz(datetime(2026, 10, 7, 11, 7))
        self.prod = self.stack.enter_context(patch(f"{CHAMPS}.NOTIFS_PROD", True))
        self.instructeurs = self.stack.enter_context(patch(f"{CHAMPS}.DossierInstructeur.objects.filter"))
        self.instructeurs.return_value.values_list.return_value = [
            "Premier@example.test", " premier@example.test ", None, "", "second@example.test",
        ]
        self.notification = self.stack.enter_context(patch(
            f"{CHAMPS}.create_EmailOutbox", return_value=SimpleNamespace(id=1),
        ))
        self.envoi = self.stack.enter_context(patch(f"{CHAMPS}.envoi_mail", return_value=(True, None)))
        self.logger = self.stack.enter_context(patch(f"{CHAMPS}.loggerMail"))

    def test_prod_destinataires_instructeurs_dedoublonnes_et_nombre_dans_le_mail(self):
        from django.template.loader import render_to_string

        notifier_formulaire_modifie(self.dossier, {"champ-1", "champ-2"}, self.date)

        self.instructeurs.assert_called_once_with(id_dossier=self.dossier)
        arguments = self.notification.call_args.args
        self.assertEqual(arguments[0], ["premier@example.test", "second@example.test"])
        self.assertIn("2 champs ajoutés ou modifiés", arguments[1])
        self.assertEqual(arguments[4]["nombre_champs"], 2)
        self.assertEqual(arguments[5], self.dossier)
        html = render_to_string("emails/dossier_modifie.html", arguments[4])
        self.assertIn("2 champs de son formulaire", html)
        self.envoi.assert_called_once_with(1)

    def test_mode_test_utilise_uniquement_email_notif_test(self):
        with patch(f"{CHAMPS}.NOTIFS_PROD", False), patch(f"{CHAMPS}.EMAIL_NOTIF_TEST", "test@example.test"):
            notifier_formulaire_modifie(self.dossier, {"champ-1"}, self.date)

        self.instructeurs.assert_not_called()
        self.assertEqual(self.notification.call_args.args[0], ["test@example.test"])
        self.assertIn("1 champ ajouté ou modifié", self.notification.call_args.args[1])

    def test_pas_de_destinataires_aucun_mail(self):
        self.instructeurs.return_value.values_list.return_value = [None, " "]

        notifier_formulaire_modifie(self.dossier, {"champ-1"}, self.date)

        self.notification.assert_not_called()
        self.envoi.assert_not_called()
        self.logger.warning.assert_called_once()

    def test_deux_modifications_successives_ne_sont_pas_dedoublonnees_ensemble(self):
        notifier_formulaire_modifie(self.dossier, {"champ-1"}, self.date)
        notifier_formulaire_modifie(self.dossier, {"champ-1"}, self.date + timedelta(days=1))

        appels = self.notification.call_args_list
        self.assertNotEqual(appels[0].args[3], appels[1].args[3])

    def test_echec_creation_outbox_pas_d_envoi(self):
        self.notification.return_value = None

        notifier_formulaire_modifie(self.dossier, {"champ-1"}, self.date)

        self.envoi.assert_not_called()
        self.logger.error.assert_called_once()

    def test_exception_mail_est_loggee_sans_interrompre_la_synchro(self):
        self.envoi.side_effect = RuntimeError("SMTP indisponible")

        notifier_formulaire_modifie(self.dossier, {"champ-1"}, self.date)

        self.logger.exception.assert_called_once()

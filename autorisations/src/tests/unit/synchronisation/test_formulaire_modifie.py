from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from autorisations.models.models_documents import Document
from synchronisation.utils.conversion import parse_datetime_with_tz
from synchronisation.synchro.sync_dossier_champs import sync_dossier_champs
from tests.support.constants import CHAMPS, URL_SIGNEE

from tests.support.synchronisation import SynchroChampsMixin, donnees_champ, donnees_document


class FormulaireModifieTests(SynchroChampsMixin, SimpleTestCase):
    def test_ancienne_pj_garde_sa_date_et_seule_la_nouvelle_est_signalee(self):
        from synchronisation.utils.model_helpers import update_fields

        depot = parse_datetime_with_tz(datetime(2026, 6, 5, 11, 11))
        ajout = parse_datetime_with_tz(datetime(2026, 10, 7, 11, 7))
        self.dossier.date_depot = depot
        self.dossier.id_etape_dossier.etape = "En attente de compléments"
        self.dossier.id_demarche = SimpleNamespace(type="Démarche de test")
        documents = [donnees_document("ancienne.pdf"), donnees_document("nouvelle.pdf")]
        ancienne = Mock(id=1, url_ds=URL_SIGNEE, description="ancienne.pdf")
        ancien_champ = Mock(
            date_saisie=depot, valeur="ancienne valeur", geometrie=None,
            id_document_id=1, ordre=0,
        )
        self.pj_connues[1] = ancien_champ
        self.doc_get.side_effect = [ancienne, Document.DoesNotExist]
        self.telecharger.return_value = r"\\nas\nouvelle.pdf"
        self.stack.enter_context(patch(f"{CHAMPS}.update_fields", side_effect=update_fields))
        instructeurs = self.stack.enter_context(patch(f"{CHAMPS}.Instructeur.objects.order_by"))
        instructeur = SimpleNamespace(id=99)
        instructeurs.return_value.first.return_value = instructeur
        action = self.stack.enter_context(patch(f"{CHAMPS}.safe_enregistrer_action"))
        self.stack.enter_context(patch(f"{CHAMPS}.NOTIFS_PROD", False))
        self.stack.enter_context(patch(f"{CHAMPS}.EMAIL_NOTIF_TEST", "test@example.test"))
        notification = self.stack.enter_context(patch(f"{CHAMPS}.create_EmailOutbox", return_value=SimpleNamespace(id=1, to=["test@example.test"])))
        envoi = self.stack.enter_context(patch(f"{CHAMPS}.envoi_mail", return_value=(True, None)))
        champs = [donnees_champ("pj", documents), donnees_champ("pj", documents)]
        for champ in champs:
            champ["champ"].update(date_saisie=ajout, date_saisie_fichier_precise=True)

        sync_dossier_champs(champs, 1)

        self.assertEqual(ancien_champ.date_saisie, depot)
        self.assertEqual(self.champ_create.call_args.kwargs["date_saisie"], ajout)
        action.assert_called_once_with(
            self.dossier, instructeur, "Formulaire modifié", request=None,
            description="1 champ concerné", date=ajout,
        )
        notification.assert_called_once()
        self.assertEqual(notification.call_args.args[4]["nombre_champs"], 1)
        envoi.assert_called_once_with(1)
        # La synchronisation suivante doit conserver les deux dates sans action supplémentaire.
        self.pj_connues[10] = Mock(
            date_saisie=ajout, valeur="valeur", geometrie=None, id_document_id=10, ordre=1,
        )
        self.doc_get.side_effect = [ancienne, Mock(id=10, url_ds=URL_SIGNEE, description="nouvelle.pdf")]
        for champ in champs:
            champ["champ"]["date_saisie"] = ajout + timedelta(days=1)
        sync_dossier_champs(champs, 1)
        self.assertEqual(ancien_champ.date_saisie, depot)
        self.assertEqual(self.pj_connues[10].date_saisie, ajout)
        self.assertEqual(action.call_count, 1)
        self.assertEqual(notification.call_count, 1)
        self.assertEqual(envoi.call_count, 1)

    def test_modifications_multiples_apres_depot_creent_une_seule_action(self):
        self.dossier.id_etape_dossier.etape = "En attente de compléments"
        self.dossier.id_demarche = SimpleNamespace(type="Démarche de test")
        self.dossier.date_depot = datetime(2026, 10, 1, 8, 0)
        premiere_modification = datetime(2026, 10, 2, 8, 40)
        derniere_modification = premiere_modification + timedelta(minutes=10)
        champs = [donnees_champ("champ-1"), donnees_champ("champ-2")]
        champs[0]["champ"]["date_saisie"] = premiere_modification
        champs[1]["champ"]["date_saisie"] = derniere_modification
        self.stack.enter_context(patch(
            f"{CHAMPS}.update_fields_dossier_champs",
            return_value=(["valeur", "date_saisie"], {}),
        ))
        instructeur = SimpleNamespace(id=99)
        instructeurs = self.stack.enter_context(patch(f"{CHAMPS}.Instructeur.objects.order_by"))
        instructeurs.return_value.first.return_value = instructeur
        action = self.stack.enter_context(patch(f"{CHAMPS}.safe_enregistrer_action"))
        self.stack.enter_context(patch(f"{CHAMPS}.NOTIFS_PROD", False))
        self.stack.enter_context(patch(f"{CHAMPS}.EMAIL_NOTIF_TEST", "test@example.test"))
        notification = self.stack.enter_context(patch(f"{CHAMPS}.create_EmailOutbox", return_value=SimpleNamespace(id=1, to=["test@example.test"])))
        envoi = self.stack.enter_context(patch(f"{CHAMPS}.envoi_mail", return_value=(True, None)))

        sync_dossier_champs(champs, 1)

        action.assert_called_once_with(
            self.dossier, instructeur, "Formulaire modifié", request=None,
            description="2 champs concernés",
            date=parse_datetime_with_tz(derniere_modification),
        )
        notification.assert_called_once()
        self.assertEqual(notification.call_args.args[0], ["test@example.test"])
        self.assertEqual(notification.call_args.args[4]["nombre_champs"], 2)
        envoi.assert_called_once_with(1)

    def test_modification_hors_attente_de_complements_ne_cree_pas_action(self):
        self.dossier.date_depot = datetime(2026, 10, 1, 8, 0)
        champ = donnees_champ("champ")
        champ["champ"]["date_saisie"] = datetime(2026, 10, 2, 8, 40)
        self.stack.enter_context(patch(
            f"{CHAMPS}.update_fields_dossier_champs",
            return_value=(["valeur", "date_saisie"], {}),
        ))
        action = self.stack.enter_context(patch(f"{CHAMPS}.safe_enregistrer_action"))

        sync_dossier_champs([champ], 1)

        action.assert_not_called()
        self.demandes_complements.assert_not_called()
        self.notification.assert_not_called()
        self.envoi.assert_not_called()

    def test_modification_avant_derniere_demande_ne_notifie_pas_mais_synchronise(self):
        action = self.preparer_modifications_en_attente()
        self.derniere_demande.return_value = parse_datetime_with_tz("2026-10-07T14:00:00+04:00")
        champ = donnees_champ("champ")
        champ["champ"]["date_saisie"] = "2026-10-06T23:59:00+04:00"

        resultat = sync_dossier_champs([champ], 1)

        self.assertTrue(resultat["success"])
        self.existant.save.assert_called_once()
        action.assert_not_called()
        self.notification.assert_not_called()
        self.envoi.assert_not_called()

    def test_meme_jour_meme_avant_heure_demande_et_jours_suivants_sont_comptes(self):
        action = self.preparer_modifications_en_attente()
        self.derniere_demande.return_value = parse_datetime_with_tz("2026-10-07T14:00:00+04:00")
        champs = [donnees_champ("meme-jour"), donnees_champ("lendemain")]
        champs[0]["champ"]["date_saisie"] = "2026-10-07T08:00:00+04:00"
        champs[1]["champ"]["date_saisie"] = "2026-10-08T08:00:00+04:00"

        sync_dossier_champs(champs, 1)

        self.assertEqual(action.call_args.kwargs["description"], "2 champs concernés")
        self.notification.assert_called_once()
        self.assertEqual(self.notification.call_args.args[4]["nombre_champs"], 2)
        self.demandes_complements.assert_called_once_with(
            id_dossier_id=1, id_action__action="Demande de compléments",
        )
        self.demandes_complements.return_value.order_by.assert_called_once_with("-date", "-id")

    def test_aucune_demande_complements_pas_de_mail_ni_action(self):
        action = self.preparer_modifications_en_attente()
        self.derniere_demande.return_value = None
        champ = donnees_champ("champ")
        champ["champ"]["date_saisie"] = "2026-10-07T08:00:00+04:00"

        sync_dossier_champs([champ], 1)

        self.existant.save.assert_called_once()
        action.assert_not_called()
        self.notification.assert_not_called()
        self.envoi.assert_not_called()
        self.logger.warning.assert_called_once()

    def test_comparaison_jours_utilise_fuseau_reunion_pas_utc(self):
        action = self.preparer_modifications_en_attente()
        self.derniere_demande.return_value = parse_datetime_with_tz("2026-10-07T01:00:00+04:00")
        champs = [donnees_champ("veille-locale"), donnees_champ("meme-jour-local")]
        champs[0]["champ"]["date_saisie"] = "2026-10-06T19:59:00Z"
        champs[1]["champ"]["date_saisie"] = "2026-10-06T20:00:00Z"

        sync_dossier_champs(champs, 1)

        self.assertEqual(action.call_args.kwargs["description"], "1 champ concerné")
        self.assertEqual(self.notification.call_args.args[4]["champs_modifies"], ["meme-jour-local"])

    def test_nouvelle_pj_ancienne_ignoree_pour_notifications(self):
        action = self.preparer_modifications_en_attente()
        self.derniere_demande.return_value = parse_datetime_with_tz("2026-10-07T14:00:00+04:00")
        self.telecharger.return_value = r"\\nas\ancienne.pdf"
        champ = donnees_champ("pj", [donnees_document("ancienne.pdf")])
        champ["champ"]["date_saisie"] = "2026-10-06T12:00:00+04:00"

        sync_dossier_champs([champ], 1)

        self.champ_create.assert_called_once()
        action.assert_not_called()
        self.notification.assert_not_called()

    def test_champ_cree_recent_est_notifie_mais_ancien_ne_l_est_pas(self):
        action = self.preparer_modifications_en_attente()
        self.derniere_demande.return_value = parse_datetime_with_tz("2026-10-07T14:00:00+04:00")
        self.sans_pj.return_value = (self.existant, True)
        champs = [donnees_champ("ancien"), donnees_champ("recent")]
        champs[0]["champ"]["date_saisie"] = "2026-10-05T08:00:00+04:00"
        champs[1]["champ"]["date_saisie"] = "2026-10-07T08:00:00+04:00"

        sync_dossier_champs(champs, 1)

        self.assertEqual(action.call_args.kwargs["description"], "1 champ concerné")
        self.assertEqual(self.notification.call_args.args[4]["champs_modifies"], ["recent"])

    def test_champ_date_du_depot_ne_notifie_pas_meme_en_attente(self):
        self.dossier.date_depot = datetime(2026, 10, 1, 8, 0)
        self.dossier.id_etape_dossier.etape = "En attente de compléments"
        champ = donnees_champ("champ")
        champ["champ"]["date_saisie"] = self.dossier.date_depot
        self.stack.enter_context(patch(
            f"{CHAMPS}.update_fields_dossier_champs", return_value=(["valeur"], {}),
        ))

        sync_dossier_champs([champ], 1)

        self.notification.assert_not_called()
        self.envoi.assert_not_called()

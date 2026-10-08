from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from synchronisation.utils.conversion import parse_datetime_with_tz
from synchronisation.synchro.sync_dossier_champs import sync_dossier_champs
from tests.support.constants import CHAMPS, URL_SIGNEE

from tests.support.synchronisation import SynchroChampsMixin, donnees_champ, donnees_document


class SynchroPJTests(SynchroChampsMixin, SimpleTestCase):
    def test_echec_pj_pas_de_document_ni_champ_et_continuer_autres_champs(self):
        resultat = sync_dossier_champs([donnees_champ("pj", [donnees_document("erreur.pdf")]), donnees_champ("texte")], 1)
        self.assertEqual(resultat, {"success": False, "pj_en_erreur": [{"champ": "pj", "titre": "erreur.pdf", "url": URL_SIGNEE}]})
        self.doc_create.assert_not_called()
        self.champ_create.assert_not_called()
        self.sans_pj.assert_called_once()
        self.assertEqual(self.sans_pj.call_args.kwargs["defaults"]["ordre"], 1)
        self.assertNotIn("SECRET_A_NE_PAS_LOGGER", str(self.logger.mock_calls))

    def test_multi_pj_echec_premiere_reussite_seconde_et_aucune_reutilisation_de_champ(self):
        docs = [donnees_document("erreur.pdf"), donnees_document("ok.pdf")]
        self.telecharger.side_effect = [None, r"\\nas\ok.pdf"]
        resultat = sync_dossier_champs([donnees_champ("texte"), donnees_champ("pj", docs), donnees_champ("pj", docs)], 1)
        self.assertFalse(resultat["success"])
        self.assertEqual([c.args[1] for c in self.telecharger.call_args_list], ["erreur.pdf", "ok.pdf"])
        self.assertEqual(self.existant.save.call_count, 1)
        self.doc_create.assert_called_once()
        self.champ_create.assert_called_once()
        self.assertEqual(self.champ_create.call_args.kwargs["id_document_id"], 10)
        self.assertEqual(self.champ_create.call_args.kwargs["ordre"], 2)

    def test_echec_ne_supprime_pas_document_precedent_ni_liens_du_champ(self):
        ancien_document = Mock()
        self.doc_filter.return_value.first.return_value = ancien_document
        ancien_champ = Mock(id_champ=SimpleNamespace(id_ds="pj"), id_document=SimpleNamespace(id=42))
        self.champs_existants = [ancien_champ]
        sync_dossier_champs([donnees_champ("pj", [donnees_document("erreur.pdf")])], 1)
        ancien_document.delete.assert_not_called()
        ancien_champ.delete.assert_not_called()

    def test_aucune_pj_retour_structure_reussi(self):
        self.assertEqual(sync_dossier_champs([donnees_champ("texte")], 1), {"success": True, "pj_en_erreur": []})
        self.notification.assert_not_called()
        self.envoi.assert_not_called()

    def test_premier_import_pj_constitue_une_reference_sans_faux_ajouts(self):
        self.premier_import = True
        depot = parse_datetime_with_tz(datetime(2026, 6, 5, 11, 11))
        self.dossier.date_depot = depot
        self.telecharger.return_value = r"\\nas\initiale.pdf"
        champ = donnees_champ("pj", [donnees_document("initiale.pdf")])
        champ["champ"]["date_saisie"] = depot + timedelta(days=5)
        action = self.stack.enter_context(patch(f"{CHAMPS}.safe_enregistrer_action"))

        sync_dossier_champs([champ], 1)

        self.assertEqual(self.champ_create.call_args.kwargs["date_saisie"], depot)
        action.assert_not_called()

from contextlib import ExitStack
from unittest.mock import patch

from django.test import SimpleTestCase

from synchronisation.synchro.sync_dossier_champs import sync_dossier_champs
from synchronisation.synchro.sync_dossiers import sync_dossiers
from tests.support.constants import DOSSIERS, URL_SIGNEE


class SynchroDossiersTests(SimpleTestCase):
    def test_dossier_partiel_continue_messages_documents_demandes_sans_logger_url(self):
        doss = {"dossier": {"id_ds": "dn-id", "numero": 123}, "contacts_externes": {},
                "dossier_champs": [], "dossier_interlocuteur": {}, "dossier_document": {}, "messages": [], "demandes": []}
        with ExitStack() as stack:
            stack.enter_context(patch(f"{DOSSIERS}.DemarcheDateActiviteChamp.objects.filter"))
            stack.enter_context(patch(f"{DOSSIERS}.DemarcheNomDossierRegle.objects.filter"))
            stack.enter_context(patch(f"{DOSSIERS}.compiler_regles_nommage", return_value=[]))
            manager = stack.enter_context(patch(f"{DOSSIERS}.Dossier.objects.filter"))
            manager.return_value.exclude.return_value.values_list.return_value = []
            fonctions = {nom: stack.enter_context(patch(f"{DOSSIERS}.{nom}")) for nom in (
                "sync_doss", "sync_contacts_externes", "sync_dossier_interlocuteur", "sync_dossier_beneficiaire",
                "sync_dossier_champs", "sync_dossier_document", "sync_messages", "sync_demandes",
            )}
            fonctions["sync_dossier_champs"].return_value = {"success": False, "pj_en_erreur": [
                {"champ": "Rapport", "titre": "rapport.pdf", "url": URL_SIGNEE},
            ]}
            logger = stack.enter_context(patch(f"{DOSSIERS}.logging.getLogger"))
            sync_dossiers([doss], 123, un_seul_doss=True)
            for nom in ("sync_dossier_document", "sync_messages", "sync_demandes"):
                fonctions[nom].assert_called_once()
            self.assertIn("PARTIELLEMENT SYNCHRONISÉ", str(logger.return_value.warning.call_args))
            self.assertNotIn("SECRET_A_NE_PAS_LOGGER", str(logger.mock_calls))

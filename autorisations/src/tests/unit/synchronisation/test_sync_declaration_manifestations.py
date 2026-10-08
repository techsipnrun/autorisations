from datetime import datetime
from types import SimpleNamespace

from django.test import SimpleTestCase
from django.utils import timezone

from synchronisation.synchro.sync_declaration_manifestations import (
    CHAMPS_IDENTITE_DM,
    doit_preserver_identite_anonymisee,
)


class ConservationIdentiteAnonymiseeDMTest(SimpleTestCase):
    @staticmethod
    def dossier(**surcharges):
        valeurs = {
            "archive": True,
            "date_depot": timezone.make_aware(datetime(2025, 7, 31, 12, 0)),
            **{champ: None for champ in CHAMPS_IDENTITE_DM},
        }
        valeurs.update(surcharges)
        return SimpleNamespace(**valeurs)

    def test_preserve_un_dossier_archive_ancien_et_deja_vide(self):
        self.assertTrue(doit_preserver_identite_anonymisee(self.dossier()))

    def test_ne_preserve_pas_un_dossier_non_archive(self):
        self.assertFalse(
            doit_preserver_identite_anonymisee(self.dossier(archive=False))
        )

    def test_ne_preserve_pas_un_dossier_depose_a_partir_daout_2025(self):
        self.assertFalse(
            doit_preserver_identite_anonymisee(
                self.dossier(
                    date_depot=timezone.make_aware(datetime(2025, 8, 1, 0, 0))
                )
            )
        )

    def test_ne_preserve_pas_une_identite_encore_renseignee(self):
        self.assertFalse(
            doit_preserver_identite_anonymisee(
                self.dossier(nom_organisateur="DUPONT")
            )
        )

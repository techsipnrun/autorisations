from django.db.models import Q
from django.test import SimpleTestCase
from types import SimpleNamespace

from instruction.utils.avis_utils import avis_est_conseil_scientifique
from instruction.views.expert import (
    filtre_avis_conseil_scientifique,
    filtre_demandes_avis_visibles,
)


class FiltreAvisConseilScientifiqueTests(SimpleTestCase):
    def test_cible_raison_sociale_ou_organisation_conseil_scientifique(self):
        self.assertEqual(
            filtre_avis_conseil_scientifique(),
            Q(id_expert__est_interne=False)
            & (
                Q(
                    id_expert__id_contact_externe__raison_sociale__iexact=(
                        "Conseil Scientifique"
                    )
                )
                | Q(
                    id_expert__id_contact_externe__organisation__iexact=(
                        "Conseil Scientifique"
                    )
                )
            ),
        )

    def test_identifie_le_cs_par_raison_sociale(self):
        avis = self._avis_externe(
            raison_sociale=" Conseil Scientifique ",
            organisation="Autre organisation",
        )

        self.assertTrue(avis_est_conseil_scientifique(avis))

    def test_identifie_le_cs_par_organisation(self):
        avis = self._avis_externe(
            raison_sociale="Autre raison sociale",
            organisation="CONSEIL SCIENTIFIQUE",
        )

        self.assertTrue(avis_est_conseil_scientifique(avis))

    def test_ne_considere_pas_un_autre_contact_comme_cs(self):
        avis = self._avis_externe(
            raison_sociale="Autre raison sociale",
            organisation="Autre organisation",
        )

        self.assertFalse(avis_est_conseil_scientifique(avis))

    @staticmethod
    def _avis_externe(*, raison_sociale, organisation):
        contact = SimpleNamespace(
            raison_sociale=raison_sociale,
            organisation=organisation,
        )
        expert = SimpleNamespace(
            est_interne=False,
            id_contact_externe=contact,
        )
        return SimpleNamespace(id_expert=expert)

    def test_utilisateur_standard_ne_voit_que_ses_demandes(self):
        instructeur = object()

        self.assertEqual(
            filtre_demandes_avis_visibles(instructeur, False),
            Q(id_instructeur=instructeur),
        )

    def test_publicateur_voit_ses_demandes_et_celles_du_cs(self):
        instructeur = object()

        self.assertEqual(
            filtre_demandes_avis_visibles(instructeur, True),
            Q(id_instructeur=instructeur) | filtre_avis_conseil_scientifique(),
        )

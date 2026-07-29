from django.db.models import Q
from django.test import SimpleTestCase

from instruction.views.expert import (
    filtre_avis_conseil_scientifique,
    filtre_demandes_avis_visibles,
)


class FiltreAvisConseilScientifiqueTests(SimpleTestCase):
    def test_cible_gerard_collin_du_conseil_scientifique(self):
        self.assertEqual(
            filtre_avis_conseil_scientifique(),
            Q(
                id_expert__est_interne=False,
                id_expert__id_contact_externe__nom__iexact="COLLIN",
                id_expert__id_contact_externe__prenom__iexact="Gérard",
                id_expert__id_contact_externe__raison_sociale__iexact=(
                    "Conseil Scientifique"
                ),
            ),
        )

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

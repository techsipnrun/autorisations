from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from instruction.utils.avis_utils import get_dossiers_lies_affiches_avis


class DossiersLiesAvisTests(SimpleTestCase):
    def setUp(self):
        self.requete = MagicMock()
        self.requete.exclude.return_value = self.requete
        self.requete.select_related.return_value = self.requete
        self.requete.only.return_value = self.requete
        self.requete.order_by.return_value = []
        self.filtrer = self.enterContext(patch(
            "instruction.utils.avis_utils.Dossier.objects.filter",
            return_value=self.requete,
        ))
        self.chemin = self.enterContext(patch(
            "instruction.utils.avis_utils.get_chemin_complet_dossier",
            side_effect=lambda dossier: f"NAS/{dossier.numero}",
        ))

    @staticmethod
    def dossier(identifiant, ensemble=None):
        return SimpleNamespace(
            pk=identifiant, numero=1000 + identifiant,
            id_ensemble_dossiers_id=ensemble,
        )

    def test_avis_sans_dossier_ne_charge_aucun_ensemble(self):
        self.assertEqual(get_dossiers_lies_affiches_avis([]), [])
        self.filtrer.assert_not_called()
        self.chemin.assert_not_called()

    def test_dossier_sans_ensemble_reste_seul_sans_requete_supplementaire(self):
        dossier = self.dossier(1)
        self.assertEqual(get_dossiers_lies_affiches_avis([dossier]), [dossier])
        self.assertEqual(dossier.chemin_complet, "NAS/1001")
        self.filtrer.assert_not_called()

    def test_ajoute_tous_les_membres_en_conservant_le_dossier_direct_en_premier(self):
        principal = self.dossier(3, 10)
        autres = [self.dossier(1, 10), self.dossier(2, 10)]
        self.requete.order_by.return_value = autres
        dossiers_directs = [principal]

        affiches = get_dossiers_lies_affiches_avis(dossiers_directs)

        self.assertEqual(affiches, [principal, *autres])
        self.assertEqual(dossiers_directs, [principal])
        self.filtrer.assert_called_once_with(id_ensemble_dossiers_id__in={10})
        self.requete.exclude.assert_called_once_with(pk__in=(3,))
        self.requete.select_related.assert_called_once_with("id_demarche")
        self.requete.order_by.assert_called_once_with("numero", "pk")
        self.assertTrue(all(d.chemin_complet == f"NAS/{d.numero}" for d in affiches))

    def test_plusieurs_ensembles_sont_charges_en_une_seule_requete(self):
        a, b = self.dossier(1, 10), self.dossier(2, 20)
        sans_ensemble = self.dossier(3)
        c, d = self.dossier(4, 10), self.dossier(5, 20)
        self.requete.order_by.return_value = [c, d]

        self.assertEqual(
            get_dossiers_lies_affiches_avis([a, b, sans_ensemble]),
            [a, b, sans_ensemble, c, d],
        )
        self.filtrer.assert_called_once_with(id_ensemble_dossiers_id__in={10, 20})
        self.requete.exclude.assert_called_once_with(pk__in=(1, 2, 3))

    def test_dossiers_deja_lies_au_meme_ensemble_sans_doublons(self):
        a, b = self.dossier(1, 10), self.dossier(2, 10)
        c = self.dossier(3, 10)
        self.requete.order_by.return_value = [c]

        self.assertEqual(get_dossiers_lies_affiches_avis([a, b, a]), [a, b, c])
        self.filtrer.assert_called_once_with(id_ensemble_dossiers_id__in={10})
        self.requete.exclude.assert_called_once_with(pk__in=(1, 2))

    def test_ensemble_sans_autre_membre_conserve_le_dossier(self):
        dossier = self.dossier(1, 10)
        self.assertEqual(get_dossiers_lies_affiches_avis([dossier]), [dossier])

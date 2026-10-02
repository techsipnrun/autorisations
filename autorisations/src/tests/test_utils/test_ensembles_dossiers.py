from types import SimpleNamespace
from unittest.mock import patch

from django.core import signing
from django.test import SimpleTestCase

from instruction.utils.ensembles_dossiers import (
    EnsembleModifie, empreinte, jeton_ensemble, verifier_jeton,
)


class SelectionEnsembleTests(SimpleTestCase):
    def setUp(self):
        self.a = SimpleNamespace(pk=1, id_ensemble_dossiers_id=10)
        self.b = SimpleNamespace(pk=2, id_ensemble_dossiers_id=10)
        self.c = SimpleNamespace(pk=3, id_ensemble_dossiers_id=None)

    def test_ordre_des_membres_sans_importance(self):
        jeton = jeton_ensemble(self.a, [self.b, self.a], [self.c])
        verifier_jeton(jeton, self.a, [self.a, self.b], [self.c])

    def test_ajout_d_un_membre_invalide_selection(self):
        jeton = jeton_ensemble(self.a, [self.a, self.b])
        with self.assertRaises(EnsembleModifie):
            verifier_jeton(jeton, self.a, [self.a, self.b, self.c])

    def test_changement_d_ensemble_invalide_selection(self):
        jeton = jeton_ensemble(self.a, [self.a, self.b], [self.c])
        self.c.id_ensemble_dossiers_id = 20
        with self.assertRaises(EnsembleModifie):
            verifier_jeton(jeton, self.a, [self.a, self.b], [self.c])

    def test_jeton_non_reutilisable_sur_un_autre_dossier(self):
        jeton = jeton_ensemble(self.a, [self.a, self.b])
        with self.assertRaises(EnsembleModifie):
            verifier_jeton(jeton, self.b, [self.a, self.b])

    def test_jeton_falsifie_refuse(self):
        with self.assertRaises(EnsembleModifie):
            verifier_jeton("jeton-invalide", self.a, [self.a, self.b])

    def test_expiration_refusee(self):
        jeton = jeton_ensemble(self.a, [self.a, self.b])
        with patch("django.core.signing.time.time", return_value=signing.time.time() + 1801):
            with self.assertRaises(EnsembleModifie):
                verifier_jeton(jeton, self.a, [self.a, self.b])

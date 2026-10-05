from types import SimpleNamespace

from django.test import SimpleTestCase

from instruction.utils.colonnes_vue_ensemble import (
    TABLEAU_ARCHIVES,
    TABLEAU_EN_COURS,
    TABLEAU_MES_DOSSIERS,
    TABLEAU_RECEPTION_COMPLET,
    TABLEAU_RECEPTION_DM,
    TABLEAU_RECEPTION_DN,
    colonnes_visibles,
    libelles_colonnes,
)


class ColonnesVueEnsembleTests(SimpleTestCase):
    def test_toutes_les_colonnes_sont_visibles_par_defaut(self):
        colonnes = colonnes_visibles("Activités agricoles")

        self.assertTrue(all(colonnes[TABLEAU_EN_COURS].values()))
        self.assertTrue(all(colonnes[TABLEAU_ARCHIVES].values()))
        self.assertNotIn("date_debut_manifestation", colonnes[TABLEAU_EN_COURS])

    def test_manifestations_utilise_la_date_d_activite_comme_unique_colonne_de_date(self):
        colonnes = colonnes_visibles("Manifestations sportives")
        libelles = libelles_colonnes("Manifestations sportives")

        for tableau in (TABLEAU_EN_COURS, TABLEAU_ARCHIVES, TABLEAU_MES_DOSSIERS):
            self.assertNotIn("date_debut_manifestation", colonnes[tableau])
            self.assertTrue(colonnes[tableau]["date_activite"])
            self.assertEqual(
                libelles[tableau]["date_activite"], "Début activité"
            )

    def test_mes_dossiers_propose_la_date_d_activite(self):
        colonnes = colonnes_visibles("ActivitÃ©s agricoles")

        self.assertTrue(colonnes[TABLEAU_MES_DOSSIERS]["date_activite"])

    def test_une_colonne_desactivee_ne_concerne_que_son_tableau(self):
        configuration = SimpleNamespace(
            tableau=TABLEAU_ARCHIVES,
            colonne="date_activite",
            affiche=False,
        )

        colonnes = colonnes_visibles("Activités agricoles", [configuration])

        self.assertTrue(colonnes[TABLEAU_EN_COURS]["date_activite"])
        self.assertFalse(colonnes[TABLEAU_ARCHIVES]["date_activite"])

    def test_les_colonnes_reception_manifestations_sont_specifiques_a_chaque_tableau(self):
        colonnes = colonnes_visibles("Manifestations sportives")

        self.assertEqual(
            list(colonnes[TABLEAU_RECEPTION_COMPLET]),
            [
                "nom_manifestation", "organisateur", "date_debut_manifestation",
                "coeur_de_parc", "numero_dn", "numero_dm", "date_reception",
            ],
        )
        self.assertEqual(
            list(colonnes[TABLEAU_RECEPTION_DN]),
            [
                "nom_manifestation", "organisateur", "numero_dn",
                "date_debut_manifestation", "date_reception", "numero_dm_renseigne",
            ],
        )
        self.assertEqual(
            list(colonnes[TABLEAU_RECEPTION_DM]),
            [
                "nom_manifestation", "organisateur", "numero_dm",
                "date_debut_evenement", "coeur_de_parc", "date_reception",
                "mails_relance",
            ],
        )

    def test_un_libelle_personnalise_remplace_uniquement_le_libelle_affiche(self):
        configuration = SimpleNamespace(
            tableau=TABLEAU_EN_COURS,
            colonne="date_activite",
            affiche=True,
            libelle_personnalise="Début de la manifestation",
        )

        colonnes = colonnes_visibles("Manifestations sportives", [configuration])
        libelles = libelles_colonnes("Manifestations sportives", [configuration])

        self.assertTrue(colonnes[TABLEAU_EN_COURS]["date_activite"])
        self.assertEqual(
            libelles[TABLEAU_EN_COURS]["date_activite"],
            "Début de la manifestation",
        )

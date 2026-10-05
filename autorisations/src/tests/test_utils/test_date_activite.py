from django.test import SimpleTestCase
from unittest.mock import patch

from synchronisation.utils.date_activite import extraire_date_debut_activite


class DateActiviteTests(SimpleTestCase):
    def test_prend_le_premier_champ_configure_renseigne(self):
        date, nom_champ = extraire_date_debut_activite(
            [("date-prioritaire", "Date prioritaire"), ("date-secours", "Date de secours")],
            [
                {"champ": {"id_ds": "date-prioritaire", "valeur": ""}},
                {"champ": {"id_ds": "date-secours", "valeur": "2026-10-05T09:30:00+04:00"}},
            ],
        )

        self.assertEqual(nom_champ, "Date de secours")
        self.assertEqual(date.isoformat(), "2026-10-05T09:30:00+04:00")

    def test_ignore_une_valeur_invalide_et_utilise_la_source_suivante(self):
        with patch("synchronisation.utils.date_activite.logger.warning"):
            date, nom_champ = extraire_date_debut_activite(
                [("date-invalide", "Date invalide"), ("date-valide", "Date valide")],
                [
                    {"champ": {"id_ds": "date-invalide", "valeur": "pas une date"}},
                    {"champ": {"id_ds": "date-valide", "valeur": "2026-10-06T10:00:00+04:00"}},
                ],
            )

        self.assertEqual(nom_champ, "Date valide")
        self.assertEqual(date.isoformat(), "2026-10-06T10:00:00+04:00")

    def test_parse_le_format_francais_renvoye_par_demarche_numerique(self):
        date, nom_champ = extraire_date_debut_activite(
            [("date", "Date et Heure de début")],
            [{"champ": {"id_ds": "date", "valeur": "20 juin 2026 07:00"}}],
        )

        self.assertEqual(nom_champ, "Date et Heure de début")
        self.assertEqual(date.isoformat(), "2026-06-20T07:00:00+04:00")

    def test_renvoie_none_si_aucune_source_n_est_exploitable(self):
        date, nom_champ = extraire_date_debut_activite(
            [("date", "Date")],
            [{"champ": {"id_ds": "date", "valeur": None}}],
        )

        self.assertIsNone(date)
        self.assertIsNone(nom_champ)

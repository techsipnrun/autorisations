from datetime import datetime, timedelta, timezone as datetime_timezone

from django.test import SimpleTestCase
from django.template.loader import get_template
from django.utils import timezone

from instruction.utils.dossier_utils import build_champs_prepares
from tests.support.champs import creer_champ, creer_dossier


class ChampsModifiesApresDepotTests(SimpleTestCase):
    def setUp(self):
        self.depot = timezone.make_aware(datetime(2026, 9, 9, 10, 0))

    def preparer(self, *champs, date_depot=None):
        dossier = creer_dossier(*champs)
        dossier.date_depot = date_depot if date_depot is not None else self.depot
        return build_champs_prepares(dossier)[0]

    def test_seules_les_saisies_strictement_apres_depot_sont_signalees(self):
        dates = [
            self.depot - timedelta(seconds=1),
            self.depot,
            self.depot + timedelta(seconds=1),
            None,
        ]
        champs = self.preparer(*[
            creer_champ("text", "Projet", "Test", date_saisie=date)
            for date in dates
        ])

        self.assertEqual(
            [champ["modifie_apres_depot"] for champ in champs],
            [False, False, True, False],
        )

    def test_metadonnees_sur_tous_les_types_de_reponses(self):
        date_saisie = self.depot + timedelta(days=1)
        for type_champ, valeur in [
            ("text", "Projet"), ("yes_no", "false"),
            ("piece_justificative", None),
            ("repetition", "{}"), ("drop_down_list", "Option"),
        ]:
            with self.subTest(type_champ=type_champ):
                champ = self.preparer(creer_champ(
                    type_champ, "Réponse", valeur, date_saisie=date_saisie,
                ))[0]
                self.assertTrue(champ["modifie_apres_depot"])
                self.assertEqual(champ["date_saisie"], date_saisie)

    def test_carte_modifiee_ne_recoit_pas_de_surlignage(self):
        champ = self.preparer(creer_champ(
            "carte", "Localisation", date_saisie=self.depot + timedelta(days=1),
        ))[0]
        self.assertFalse(champ["modifie_apres_depot"])
        self.assertEqual(champ["type"], "carte")

    def test_titres_et_explications_ne_sont_pas_des_modifications_demandeur(self):
        date_saisie = self.depot + timedelta(days=1)
        champs = self.preparer(
            creer_champ("explication", "Aide", date_saisie=date_saisie),
            creer_champ("header_section", "Section", date_saisie=date_saisie),
            creer_champ("text", "Projet", "Test", date_saisie=date_saisie),
        )
        self.assertEqual(len(champs), 2)
        self.assertFalse(champs[0]["modifie_apres_depot"])
        self.assertTrue(champs[1]["modifie_apres_depot"])

    def test_date_depot_absente_ne_signale_pas_de_modification(self):
        dossier = creer_dossier(creer_champ(
            "text", "Projet", "Test", date_saisie=self.depot,
        ))
        dossier.date_depot = None
        self.assertFalse(build_champs_prepares(dossier)[0][0]["modifie_apres_depot"])

    def test_fuseaux_differents_comparent_le_meme_instant(self):
        champ = self.preparer(creer_champ(
            "text", "Projet", "Test",
            date_saisie=self.depot.astimezone(datetime_timezone.utc),
        ))[0]
        self.assertFalse(champ["modifie_apres_depot"])

    def test_dates_naives_interpretees_dans_le_fuseau_django(self):
        champ = self.preparer(
            creer_champ("text", "Projet", "Test", date_saisie=self.depot),
            date_depot=timezone.make_naive(self.depot),
        )[0]
        self.assertFalse(champ["modifie_apres_depot"])
        champ = self.preparer(creer_champ(
            "text", "Projet", "Test",
            date_saisie=timezone.make_naive(self.depot + timedelta(minutes=1)),
        ))[0]
        self.assertTrue(champ["modifie_apres_depot"])
        self.assertTrue(timezone.is_aware(champ["date_saisie"]))

    def test_templates_des_deux_interfaces_compilent(self):
        for nom in ["preinstruction_dossier", "instruction_dossier"]:
            with self.subTest(template=nom):
                get_template(f"instruction/{nom}.html")

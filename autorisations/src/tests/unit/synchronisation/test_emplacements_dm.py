"""Année NAS DM : réception au Parc, sans SQL ni accès au NAS/API."""
from contextlib import ExitStack
from datetime import datetime, timezone as datetime_timezone
import importlib
import ntpath
import os
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

from django.db.models.query import QuerySet
from django.test import SimpleTestCase
from django.utils import timezone

from autorisations.models.models_instruction import DossierManifSportive
from synchronisation.normalisation.norma_declaration_manifestations import dossiers_declaration_manifestations_normalize
from synchronisation.synchro import sync_process
from synchronisation.utils import fichiers
from synchronisation.utils.fichiers import construire_emplacement_dossier, construire_emplacement_manif_sportive
from synchronisation.utils.model_helpers import update_fields


synchro_dm = importlib.import_module("synchronisation.synchro.sync_declaration_manifestations")


def donnees_dm():
    return dossiers_declaration_manifestations_normalize([{
        "pk": 123, "nom": "Trail de test", "structure_organisatrice_fk": {},
        "date_creation": "2024-10-12T10:00:00+04:00",
        "date_debut": "2027-02-10T08:00:00+04:00",
        "date_fin": "2027-02-10T18:00:00+04:00",
    }])[0]


class AnneeEmplacementDMTests(SimpleTestCase):
    def test_annee_de_reception_et_non_depot_ni_evenement(self):
        path = construire_emplacement_manif_sportive("Trail de test", "2026-12-15T10:00:00+04:00")
        self.assertEqual(path, "Manifestations_sportives/2026/Declaration Manifestations/trail_de_test/")
        data = donnees_dm()
        self.assertEqual(data["date_depot"].year, 2024)
        self.assertEqual(data["date_debut_evenement"].year, 2027)
        self.assertNotIn("emplacement", data)

    def test_annee_calculee_dans_le_fuseau_local_comme_le_tableau(self):
        self.assertIn("/2027/", construire_emplacement_manif_sportive("Trail", "2026-12-31T22:30:00Z"))

    def test_sans_reception_repli_sur_annee_courante_dans_le_fuseau_local(self):
        maintenant = datetime(2029, 12, 31, 22, 30, tzinfo=datetime_timezone.utc)
        for date_reception in (None, ""):
            with self.subTest(date_reception=date_reception), \
                 patch.object(fichiers.timezone, "now", return_value=maintenant), \
                 patch.object(fichiers.loggerSynchro, "warning") as avertir:
                self.assertEqual(construire_emplacement_manif_sportive("Trail", date_reception),
                                 "Manifestations_sportives/2030/Declaration Manifestations/trail/")
                avertir.assert_called_once()

    def test_date_fournie_invalide_signalee(self):
        with self.assertRaises(ValueError):
            construire_emplacement_manif_sportive("Trail", "date invalide")

    def test_nom_vide_ne_designe_jamais_le_repertoire_parent(self):
        for nom in (None, "", "!!!"):
            with self.subTest(nom=nom):
                self.assertTrue(construire_emplacement_manif_sportive(nom, "2026-12-15T10:00:00+04:00").endswith("/manifestation/"))

    def test_creation_bas_niveau_idempotente_pour_un_chemin_deja_reserve(self):
        racine = r"\\nas-tests.invalid\share\Manifestations_sportives\2026\Declaration Manifestations\trail"
        with patch.object(fichiers, "ensure_dossier_root", return_value=racine), \
             patch("autorisations.utils.nas_fonctions.smbclient.path.exists", return_value=True), \
             patch("autorisations.utils.nas_fonctions.smbclient.makedirs") as creer, \
             patch.object(fichiers, "donner_droits_ecriture_groupe"), \
             patch.object(fichiers, "get_nom_disponible") as suffixer:
            self.assertTrue(fichiers.create_emplacement_manif_sportive("Manifestations_sportives/2026/Declaration Manifestations/trail/"))
            creer.assert_not_called()
            suffixer.assert_not_called()

    def test_selection_derniere_demande_comme_le_tableau_dm(self):
        avis = [
            {"id_dossier_manif_sportive": 123, "date_demande": "2025-12-10T10:00:00+04:00"},
            {"id_dossier_manif_sportive": "123", "date_demande": "2026-12-15T10:00:00+04:00"},
            {"id_dossier_manif_sportive": 123, "date_demande": None},
            {"id_dossier_manif_sportive": 123, "date_demande": "invalide"},
            {"id_dossier_manif_sportive": 124, "date_demande": "2024-04-01"},
        ]
        dates = sync_process._dates_reception_dm(avis)
        self.assertEqual(dates[123].year, 2026)
        self.assertEqual(dates[124].year, 2024)
        self.assertEqual(sync_process._dates_reception_dm(None), {})

    def test_dn_conserve_l_annee_de_depot(self):
        doss = {"number": 456, "dateDepot": "2026-12-15T10:00:00+04:00",
                "champs": [{"label": "Nom de la manifestation", "stringValue": "Trail de test"}]}
        self.assertEqual(construire_emplacement_dossier(doss, {}, "Manifestations sportives"),
                         "Manifestations_sportives/2026/Demarche Numerique/456_trail_de_test/")


class NomsDisponiblesDMTests(SimpleTestCase):
    def setUp(self):
        stack = self.enterContext(ExitStack())
        self.manager = stack.enter_context(patch.object(synchro_dm.DossierManifSportive, "objects"))
        self.manager.filter.return_value.exists.return_value = False
        self.nas = stack.enter_context(patch.object(synchro_dm.smbclient.path, "exists", return_value=False))
        self.creer = stack.enter_context(patch.object(synchro_dm.smbclient, "makedirs"))
        self.connection = stack.enter_context(patch.object(synchro_dm, "connection"))
        self.connection.vendor = "sqlite"

    def choisir(self, nom="Trail"):
        return synchro_dm._choisir_emplacement_nouveau_dm(nom, "2026-12-15T10:00:00+04:00")

    def test_premier_nom_libre_selon_le_nas_et_les_reservations_bdd(self):
        for bdd, nas, attendu in (
            (set(), set(), "trail"),
            (set(), {"trail"}, "trail_2"),
            (set(), {"trail", "trail_2"}, "trail_3"),
            ({"trail"}, set(), "trail_2"),
            ({"trail", "trail_3"}, {"trail_2"}, "trail_4"),
            ({"trail", "trail_3"}, set(), "trail_2"),
        ):
            with self.subTest(bdd=bdd, nas=nas):
                self.manager.filter.side_effect = lambda **kwargs: NS(
                    exists=lambda: kwargs["emplacement__iexact"].rstrip("/").rsplit("/", 1)[1] in bdd,
                )
                self.nas.side_effect = lambda chemin: ntpath.basename(chemin.rstrip("/\\")) in nas
                path = self.choisir()
                self.assertEqual(path, f"Manifestations_sportives/2026/Declaration Manifestations/{attendu}/")
                self.creer.assert_not_called()

    def test_collision_apres_nettoyage_des_accents_et_tirets(self):
        self.manager.filter.return_value.exists.side_effect = [True, False]
        self.assertTrue(self.choisir("TRÀIL").endswith("/trail_2/"))
        self.manager.filter.assert_any_call(emplacement__iexact="Manifestations_sportives/2026/Declaration Manifestations/trail/")

    def test_nom_avec_suffixe_n_est_pas_reinterprete(self):
        self.nas.side_effect = [True, False]
        self.assertTrue(self.choisir("Trail 2").endswith("/trail_2_2/"))

    def test_echec_lecture_nas_ne_permet_pas_de_reutiliser_un_nom_inconnu(self):
        self.nas.side_effect = PermissionError("Accès NAS refusé")
        with self.assertRaises(PermissionError):
            self.choisir()
        self.creer.assert_not_called()

    def test_verrou_postgresql_pris_avant_les_verifications_bdd_et_nas(self):
        self.connection.vendor = "postgresql"
        ordre = []
        curseur = self.connection.cursor.return_value.__enter__.return_value
        curseur.execute.side_effect = lambda *args: ordre.append("verrou")
        self.manager.filter.side_effect = lambda **kwargs: (
            ordre.append("bdd") or NS(exists=lambda: False)
        )
        self.nas.side_effect = lambda chemin: ordre.append("nas") or False
        self.assertTrue(self.choisir().endswith("/trail/"))
        self.assertEqual(ordre, ["verrou", "bdd", "nas"])
        curseur.execute.assert_called_once()
        sql, parametres = curseur.execute.call_args.args
        self.assertEqual(sql, "SELECT pg_advisory_xact_lock(%s, %s)")
        self.assertEqual(parametres[0], 0x444D4E41)
        self.assertGreaterEqual(parametres[1], -(2 ** 31))
        self.assertLess(parametres[1], 2 ** 31)

    def test_verrou_commun_aux_noms_qui_peuvent_se_croiser_par_suffixe(self):
        self.connection.vendor = "postgresql"
        curseur = self.connection.cursor.return_value.__enter__.return_value
        self.choisir("Trail")
        self.choisir("Trail 2")
        self.assertEqual(curseur.execute.call_count, 2)
        self.assertEqual(curseur.execute.call_args_list[0], curseur.execute.call_args_list[1])


class ConservationEmplacementsDMTests(SimpleTestCase):
    def setUp(self):
        stack = self.enterContext(ExitStack())
        self.manager = stack.enter_context(patch.object(synchro_dm.DossierManifSportive, "objects"))
        self.manager.filter.return_value.exists.return_value = False
        self.nas_existe = stack.enter_context(patch.object(synchro_dm.smbclient.path, "exists", return_value=False))
        champ = stack.enter_context(patch.object(synchro_dm.Champ, "objects"))
        champ.get.return_value = NS(pk=1)
        dossiers_dn = stack.enter_context(patch.object(synchro_dm.Dossier, "objects"))
        dossiers_dn.filter.return_value.exclude.return_value.order_by.return_value.first.return_value = None
        liaisons = stack.enter_context(patch.object(synchro_dm.DossierManifestationLiaison, "objects"))
        liaisons.filter.return_value.exists.return_value = False
        self.creer_nas = stack.enter_context(patch.object(synchro_dm, "create_emplacement_manif_sportive"))
        self.geojson = stack.enter_context(patch.object(synchro_dm, "write_geojson"))
        self.update = stack.enter_context(patch.object(synchro_dm, "update_fields", return_value=[]))
        self.data = donnees_dm()
        self.obj = DossierManifSportive(pk=1, **self.data, coeur_de_parc=False, id_etape_id=1,
                                       emplacement="Manifestations_sportives/2027/Declaration Manifestations/Ancien/")
        self.logger = Mock()

    def test_nouveau_dossier_cree_dans_l_annee_de_reception(self):
        def creer(**kwargs):
            defaults = kwargs["defaults"]
            self.assertTrue(callable(defaults["emplacement"]))
            self.obj.emplacement = defaults["emplacement"]()
            return self.obj, True

        self.manager.get_or_create.side_effect = creer
        obj, lie = synchro_dm.sync_declaration_manifestations(
            self.data, self.logger, {}, date_reception="2026-12-15T10:00:00+04:00",
        )
        self.assertIs(obj, self.obj)
        self.assertFalse(lie)
        self.creer_nas.assert_called_once_with("Manifestations_sportives/2026/Declaration Manifestations/trail_de_test/")

    def test_existant_conserve_son_chemin_meme_si_reception_change_ou_manque(self):
        for reception in (None, "2026-12-15T10:00:00+04:00", "2028-01-02T10:00:00+04:00"):
            with self.subTest(reception=reception):
                self.manager.get_or_create.return_value = (self.obj, False)
                ancien = self.obj.emplacement
                # Même un ancien appelant qui fournit encore un chemin doit être ignoré.
                data = {**self.data, "emplacement": "Manifestations_sportives/2099/Autre/"}
                with patch.object(self.obj, "save") as save:
                    obj, _ = synchro_dm.sync_declaration_manifestations(data, self.logger, {}, date_reception=reception)
                self.assertEqual(obj.emplacement, ancien)
                self.assertNotIn("emplacement", self.update.call_args.args[1])
                self.creer_nas.assert_not_called()
                self.nas_existe.assert_not_called()
                self.geojson.assert_not_called()
                save.assert_not_called()

    def test_chemin_suffixe_est_conserve_en_base_et_utilise_pour_le_nas(self):
        def creer(**kwargs):
            self.obj.emplacement = kwargs["defaults"]["emplacement"]()
            return self.obj, True

        self.manager.get_or_create.side_effect = creer
        self.manager.filter.return_value.exists.side_effect = [True, True, False]
        obj, _ = synchro_dm.sync_declaration_manifestations(
            self.data, self.logger, {}, date_reception="2026-12-15T10:00:00+04:00",
        )
        attendu = "Manifestations_sportives/2026/Declaration Manifestations/trail_de_test_3/"
        self.assertEqual(obj.emplacement, attendu)
        self.creer_nas.assert_called_once_with(attendu)
        self.manager.get_or_create.side_effect = None
        self.manager.get_or_create.return_value = (obj, False)
        self.creer_nas.reset_mock()
        self.nas_existe.reset_mock()
        meme_obj, _ = synchro_dm.sync_declaration_manifestations(self.data, self.logger, {})
        self.assertEqual(meme_obj.emplacement, attendu)
        self.creer_nas.assert_not_called()
        self.nas_existe.assert_not_called()

    def test_django_ne_calcule_pas_le_nouveau_chemin_pour_un_existant(self):
        # Exécuter le vrai get_or_create Django, en simulant seulement la lecture.
        queryset = QuerySet(model=DossierManifSportive)
        with patch.object(queryset, "get", return_value=self.obj), \
             patch.object(queryset, "create") as create, \
             patch.object(synchro_dm, "construire_emplacement_manif_sportive") as chemin:
            self.manager.get_or_create.side_effect = queryset.get_or_create
            obj, _ = synchro_dm.sync_declaration_manifestations(self.data, self.logger, {}, date_reception=None)
        self.assertIs(obj, self.obj)
        chemin.assert_not_called()
        create.assert_not_called()
        self.creer_nas.assert_not_called()

    def test_changement_de_date_evenement_ne_deplace_pas_un_existant(self):
        self.manager.get_or_create.return_value = (self.obj, False)
        self.update.side_effect = update_fields
        ancien = self.obj.emplacement
        data = {**self.data, "date_debut_evenement": timezone.now().replace(year=2028)}
        with patch.object(self.obj, "save") as save:
            obj, _ = synchro_dm.sync_declaration_manifestations(data, self.logger, {}, date_reception="2028-01-01T10:00:00+04:00")
        self.assertEqual(obj.date_debut_evenement.year, 2028)
        self.assertEqual(obj.emplacement, ancien)
        save.assert_called_once()
        self.creer_nas.assert_not_called()
        self.geojson.assert_not_called()

    def test_nouveau_dm_sans_date_cree_son_dossier_dans_l_annee_courante(self):
        def creer(**kwargs):
            self.obj.emplacement = kwargs["defaults"]["emplacement"]()
            return self.obj, True

        self.manager.get_or_create.side_effect = creer
        maintenant = datetime(2029, 12, 31, 22, 30, tzinfo=datetime_timezone.utc)
        with patch.object(fichiers.timezone, "now", return_value=maintenant):
            obj, _ = synchro_dm.sync_declaration_manifestations(self.data, self.logger, {})
        self.assertIs(obj, self.obj)
        self.creer_nas.assert_called_once_with("Manifestations_sportives/2030/Declaration Manifestations/trail_de_test/")
        self.logger.error.assert_not_called()


class TransmissionReceptionDMSynchronisationTests(SimpleTestCase):
    def synchroniser(self, dico, resultats):
        with ExitStack() as stack:
            logger = stack.enter_context(patch.object(sync_process.logging, "getLogger")).return_value
            for nom in ("get_access_token", "get_access_token_prod",
                        "sync_avis_declaration_manifestations", "sync_demarche", "sync_champs", "sync_dossiers"):
                stack.enter_context(patch.object(sync_process, nom))
            pjs = stack.enter_context(patch.object(sync_process, "recup_pj_dossiers"))
            stack.enter_context(patch.object(sync_process.Document, "objects"))
            stack.enter_context(patch.dict(os.environ, {"SYNCHRO_DM": "True"}))
            synchro = stack.enter_context(patch.object(sync_process, "sync_declaration_manifestations"))
            synchro.side_effect = resultats
            succes = sync_process.synchro_process(dico, {}, NS(type="Manifestations sportives", numero=124837))
            return succes, synchro, pjs, logger

    def test_synchronisation_transmet_la_reception_avant_creation_des_avis(self):
        dico = {"manif_sportives": [donnees_dm()], "avis_manif_sportives": [
            {"id_dossier_manif_sportive": 123, "date_demande": "2025-12-01T10:00:00+04:00"},
            {"id_dossier_manif_sportive": 123, "date_demande": "2026-12-15T10:00:00+04:00"},
        ], "demarche": {}, "champs": [], "dossiers": []}
        succes, synchro, _, logger = self.synchroniser(dico, [(NS(numero_dossier_declaration_manifestations=123), False)])
        self.assertTrue(succes, logger.mock_calls)
        synchro.assert_called_once()
        reception = synchro.call_args.kwargs["date_reception"]
        self.assertEqual(timezone.localtime(reception).year, 2026)
        self.assertEqual(reception.day, 15)

    def test_echec_initialisation_ne_bloque_pas_la_creation_des_autres_dossiers(self):
        data = donnees_dm()
        dico = {"manif_sportives": [data, {**data, "numero_dossier_declaration_manifestations": 124}],
                "avis_manif_sportives": [{"id_dossier_manif_sportive": 124, "date_demande": "2026-12-15T10:00:00+04:00"}],
                "demarche": {}, "champs": [], "dossiers": []}
        valide = NS(numero_dossier_declaration_manifestations=124)
        succes, synchro, pjs, logger = self.synchroniser(dico, [None, (valide, False)])
        self.assertFalse(succes)
        self.assertEqual(synchro.call_count, 2)
        self.assertIsNone(synchro.call_args_list[0].kwargs["date_reception"])
        pjs.assert_called_once()
        self.assertIs(pjs.call_args.args[0], valide)
        logger.error.assert_called_once()

"""Archivage piloté par le référentiel, sans BDD, NAS ou notifications réelles."""
import importlib
import json
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase

from autorisations.models.models_instruction import EtapeDossier
from instruction import utils_instru
from instruction.views import declaration_manifestations as vues


class EtapesArchivageTests(SimpleTestCase):
    def test_cloture_et_notifications_suivent_le_booleen_pas_le_nom(self):
        for label, archive in (("Nouvelle clôture", True), ("Non répondu", True), ("Accepté", False)):
            with self.subTest(label=label, archive=archive), \
                 patch.object(utils_instru.EtapeDossier, "objects") as etapes, \
                 patch.object(utils_instru.Instructeur, "objects"), \
                 patch.object(utils_instru, "get_instructeurs_a_actionner", return_value=[]) as roles, \
                 patch.object(utils_instru, "envoi_mail") as mail, \
                 patch.object(utils_instru, "create_EmailOutbox") as outbox:
                cible = NS(etape=label, est_archivage=archive)
                etapes.filter.return_value.first.return_value = cible
                dossier = NS(numero=123, id_etape_dossier=NS(etape="En instruction"),
                             date_fin_instruction=None, save=Mock())
                utils_instru.changer_etape_si_differente(dossier, label, NS(email="agent@example.test"), NS())
                self.assertIs(dossier.id_etape_dossier, cible)
                self.assertEqual(dossier.date_fin_instruction is not None, archive)
                dossier.save.assert_called_once()
                self.assertEqual(roles.called, not archive)
                mail.assert_not_called()
                outbox.assert_not_called()

    def test_etape_inchangee_ne_recloture_pas_le_dossier(self):
        cible = NS(etape="Clôture", est_archivage=True)
        dossier = NS(numero=123, id_etape_dossier=cible, save=Mock())
        with patch.object(utils_instru.EtapeDossier, "objects") as etapes:
            etapes.filter.return_value.first.return_value = cible
            utils_instru.changer_etape_si_differente(dossier, cible.etape, NS(), NS())
        dossier.save.assert_not_called()

    def test_liaison_archivee_exige_deux_dossiers_archives_et_la_bonne_demarche(self):
        for archive_dn, archive_dm, demarche in (
            (True, True, "Manifestations sportives"),
            (False, True, "Manifestations sportives"),
            (True, False, "Manifestations sportives"),
            (True, True, "Travaux"),
        ):
            with self.subTest(dn=archive_dn, dm=archive_dm, demarche=demarche), \
                 patch.object(vues, "get_object_or_404") as obtenir, \
                 patch.object(vues, "archive_lier_dossier_dm_au_dossier_dn", return_value=True) as lier, \
                 patch.object(vues, "redirect_error", return_value=HttpResponse(status=302)), \
                 patch.object(vues, "messages"):
                dm = NS(archive=archive_dm, numero_dossier_declaration_manifestations=456, nom_dossier="Projet")
                dn = NS(numero=123, id_demarche=NS(type=demarche),
                        id_etape_dossier=NS(etape="Clôture personnalisée", est_archivage=archive_dn))
                obtenir.side_effect = [dm, dn]
                request = RequestFactory().post("/liaison/", {"id_dossier_dm": 1, "dossier_dn_id": 2})
                request.user = NS(is_authenticated=True)
                self.assertEqual(vues.archive_lier_dossier_manif_sportive_a_DN(request).status_code, 302)
                self.assertEqual(lier.called, archive_dn and archive_dm and demarche == "Manifestations sportives")

    def test_fixture_initialise_les_cinq_etapes_finales(self):
        fixture = Path(__file__).resolve().parents[3] / "autorisations/fixtures/referentiels.json"
        etapes = [ligne["fields"] for ligne in json.loads(fixture.read_text(encoding="utf-8"))
                  if ligne["model"] == "autorisations.etapedossier"]
        self.assertEqual({e["etape"] for e in etapes if e["est_archivage"]},
                         {"Accepté", "Refusé", "Non soumis à autorisation", "Annulé", "Non répondu"})
        self.assertFalse(EtapeDossier(etape="Nouvelle étape").est_archivage)

    def test_migration_ne_modifie_pas_la_bdd(self):
        migration = importlib.import_module("autorisations.migrations.0049_etapes_archivage")
        self.assertEqual(migration.Migration.operations[0].database_operations, [])

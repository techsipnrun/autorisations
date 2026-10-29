"""Administration des formulaires d'avis, sans accès SQL."""
import json
from types import SimpleNamespace
from unittest.mock import patch

from django.core.exceptions import PermissionDenied
from django.db import IntegrityError
from django.test import RequestFactory, SimpleTestCase

from backoffice.views import avis as avis_configuration
from instruction.utils.avis_formulaires import configuration_standard


class AdministrationFormulairesAvisTests(SimpleTestCase):
    def requete(self, data=None, admin=True, methode="post"):
        request = getattr(RequestFactory(), methode)("/back-office/avis/formulaires/dossier/", json.dumps(data) if data is not None else "{}", content_type="application/json") if methode == "post" else RequestFactory().get("/back-office/avis/formulaires/dossier/")
        request.user = SimpleNamespace(is_authenticated=True, is_superuser=admin)
        return request

    def test_admin_seul_peut_lire_et_ecrire(self):
        for methode in ("get", "post"):
            with self.assertRaises(PermissionDenied):
                avis_configuration.configurer_formulaire(self.requete(admin=False, methode=methode), "dossier")

    def test_contexte_et_donnees_invalides_refuses(self):
        self.assertEqual(avis_configuration.configurer_formulaire(self.requete(), "absent").status_code, 404)
        self.assertEqual(avis_configuration.configurer_formulaire(self.requete({"champs": []}), "dossier").status_code, 400)

    def test_enregistrement_atomique_sans_toucher_aux_avis(self):
        with patch.object(avis_configuration, "AvisFormulaireConfiguration") as configuration, patch.object(avis_configuration, "AvisFormulaireChamp") as champ, patch.object(avis_configuration.transaction, "atomic"):
            configuration.objects.get_or_create.return_value = (SimpleNamespace(pk=1), True)
            response = avis_configuration.configurer_formulaire(self.requete({"champs": configuration_standard("dossier")}), "dossier")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(champ.objects.update_or_create.call_count, 11)
            configuration.objects.select_for_update.assert_called_once()

    def test_enregistrement_du_troisieme_contexte_et_permissions(self):
        with self.assertRaises(PermissionDenied):
            avis_configuration.configurer_formulaire(self.requete(admin=False), "existant")
        with patch.object(avis_configuration, "AvisFormulaireConfiguration") as configuration, patch.object(avis_configuration, "AvisFormulaireChamp") as champ, patch.object(avis_configuration.transaction, "atomic"):
            configuration.objects.get_or_create.return_value = (SimpleNamespace(pk=3), True)
            response = avis_configuration.configurer_formulaire(self.requete({"champs": configuration_standard("existant")}), "existant")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(champ.objects.update_or_create.call_count, 13)
            self.assertEqual(configuration.objects.get_or_create.call_args.kwargs["code"], "existant")

    def test_import_favorable_sous_reserve_et_aide_acceptes(self):
        champs = configuration_standard("existant")
        next(c for c in champs if c["code"] == "reponse").update(defaut="favorable_sous_reserve", aide="Précisez les réserves.")
        with patch.object(avis_configuration, "AvisFormulaireConfiguration") as configuration, patch.object(avis_configuration, "AvisFormulaireChamp") as champ, patch.object(avis_configuration.transaction, "atomic"):
            configuration.objects.get_or_create.return_value = (SimpleNamespace(pk=3), True)
            response = avis_configuration.configurer_formulaire(self.requete({"champs": champs}), "existant")
            self.assertEqual(response.status_code, 200)
            enregistrement = next(appel for appel in champ.objects.update_or_create.call_args_list if appel.kwargs["code"] == "reponse")
            self.assertEqual(enregistrement.kwargs["defaults"]["defaut"], "favorable_sous_reserve")
            self.assertEqual(enregistrement.kwargs["defaults"]["aide"], "Précisez les réserves.")

    def test_contrainte_ancienne_retourne_erreur_json_avec_script_a_appliquer(self):
        cause = Exception("ancienne contrainte")
        cause.pgcode = "23514"
        cause.diag = SimpleNamespace(table_name="avis_formulaire_configuration")
        erreur = IntegrityError("contexte refusé")
        erreur.__cause__ = cause
        with patch.object(avis_configuration, "AvisFormulaireConfiguration") as configuration, patch.object(avis_configuration.transaction, "atomic"), patch.object(avis_configuration.logger, "exception") as log:
            configuration.objects.get_or_create.side_effect = erreur
            response = avis_configuration.configurer_formulaire(self.requete({"champs": configuration_standard("existant")}), "existant")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.headers["Content-Type"], "application/json")
        self.assertIn("0043_avis_formulaire_existant.sql", json.loads(response.content)["error"])
        log.assert_called_once()

"""Composants réels, codes stables et rendu des menus, sans BDD réelle."""
import json
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

from django.template import Context, Template, TemplateDoesNotExist
from django.test import SimpleTestCase
from django.urls import reverse

from autorisations.models.models_instruction import ChangementEtape
from instruction.utils.actions_interface import (
    charger_actions, construire_menu, disponibilite, fragment_action,
)


def action(code, label="Libellé renommé"):
    return ChangementEtape(pk=1, code=code, action=label)


class ActionsInterfaceTests(SimpleTestCase):
    def test_exactement_cinq_actions_a_affecter_sans_scan_html(self):
        fixture = Path(__file__).resolve().parents[3] / "autorisations/fixtures/referentiels.json"
        actions = [ChangementEtape(pk=ligne["pk"], **ligne["fields"]) for ligne in json.loads(fixture.read_text(encoding="utf-8")) if ligne["model"] == "autorisations.changementetape"]
        disponibles = {objet.code for objet in actions if disponibilite(objet, "dn", "À affecter")[0]}
        self.assertEqual(disponibles, {"passer_en_pre_instruction", "classer_le_dossier_comme_accepte", "classer_le_dossier_comme_refuse", "dossier_non_soumis_a_autorisation", "classer_comme_annule"})
        self.assertFalse(disponibilite(action("valider_et_envoyer_pour_relecture_qualite"), "dn", "À affecter")[0])

    def test_dm_et_dn_ne_partagent_pas_les_composants(self):
        dm = action("declaration_manifestations_accepter")
        self.assertTrue(disponibilite(dm, "dm", "En réception")[0])
        self.assertFalse(disponibilite(dm, "dn", "En instruction")[0])
        self.assertFalse(disponibilite(action("passer_en_instruction"), "dm", "En réception")[0])

    def test_plus_de_parametrage_bdd_pour_la_disponibilite(self):
        self.assertNotIn("etapes_autorisees", {champ.name for champ in ChangementEtape._meta.fields})
        objet = action("passer_en_instruction")
        # Même un ancien attribut résiduel ne doit pas influencer le rendu.
        objet.etapes_autorisees = {"dn": []}
        self.assertTrue(disponibilite(objet, "dn", "En pré-instruction")[0])

    def test_changer_libelle_ne_change_pas_le_branchement(self):
        objet = action("passer_en_pre_instruction", "Nouveau texte")
        menu = construire_menu([objet], [objet.action], "dn", "À affecter", "preinstruction")
        self.assertEqual(len(menu), 1)
        self.assertIn("passer_en_pre_instruction.html", menu[0]["template"])
        html = Template("{% include action.template %}").render(Context({"action": menu[0], "dossier": NS(id_ds="id"), "csrf_token": "test"}))
        self.assertIn("/changer-etape/passer-en-pre-instruction/", html)

    def test_pas_de_chemin_template_libre(self):
        for code in (None, "../secret", "<script>", "back_office", "nom_inconnu"):
            with self.subTest(code=code):
                self.assertIsNone(fragment_action(action(code), "instruction")[0])

    def test_une_route_seule_ne_suffit_pas(self):
        self.assertTrue(reverse("remplacer_numero_projet_acte_url"))
        self.assertIsNone(fragment_action(action("remplacer_numero_projet_acte"), "instruction")[0])

    def test_disponibilite_reagit_au_chargeur_de_templates(self):
        objet = action("passer_en_instruction")
        with patch("instruction.utils.actions_interface.get_template", side_effect=TemplateDoesNotExist("composant retiré")) as charger:
            self.assertFalse(disponibilite(objet, "dn", "En instruction")[0])
            charger.assert_called_once_with("instruction/refacto/actions/instruction/passer_en_instruction.html")

    def test_chargement_des_actions_sans_colonne_specifique(self):
        objet = action("passer_en_instruction")
        with patch.object(ChangementEtape, "objects") as manager:
            manager.order_by.return_value = [objet]
            self.assertEqual(charger_actions(), [objet])
            manager.filter.assert_not_called()
            manager.update.assert_not_called()

    def test_archive_dn_et_hors_dn_conservent_les_variantes(self):
        objet = action("dossier_non_soumis_a_autorisation")
        for present in (True, False):
            menu = construire_menu([objet], [objet.action], "dn", "À affecter", "preinstruction")
            html = Template("{% include action.template %}").render(Context({"action": menu[0], "dossier": NS(id_ds="id", present_sur_ds=present), "csrf_token": "test"}))
            self.assertEqual("data-ouvrir-formulaire=" in html, present)
            self.assertEqual("data-confirmer-action=" in html, not present)

    def test_signature_ca_conserve_son_formulaire(self):
        objet = action("pret_a_la_signature")
        menu = construire_menu([objet], [objet.action], "dn", "En relecture qualité", "instruction")
        for ca in (True, False):
            html = Template("{% include action.template %}").render(Context({"action": menu[0], "signature_ca": ca}))
            self.assertEqual("afficherFormulaireTransmissionCA()" in html, ca)
            self.assertEqual("afficherFormulaireTransmissionDirecteur()" in html, not ca)

    def test_anciens_cas_directs_gardent_un_composant_explicite(self):
        for code in ("passer_en_pre_instruction", "passer_en_instruction", "avis_envoye",
                     "valider_le_modele_de_demande_d_avis_et_le_projet_d_acte",
                     "envoyer_les_modifications_de_l_acte_pour_validation"):
            with self.subTest(code=code):
                objet = action(code)
                fragment, _ = fragment_action(objet, "instruction")
                self.assertTrue(fragment.endswith(f"instruction/{code}.html"))
                html = Template("{% include action.template %}").render(Context({"action": {"template": fragment, "url_name": f"{code}_url", "label": objet.action}, "dossier": NS(id_ds="id"), "csrf_token": "test"}))
                self.assertIn(reverse(f"{code}_url"), html)

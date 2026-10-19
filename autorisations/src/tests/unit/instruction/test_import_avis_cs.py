"""Import CS : référence affichée et état RAA, sans BDD, mail ou NAS."""
from types import SimpleNamespace
from io import BytesIO
from unittest.mock import patch

from django.db.models import Q
from django.contrib.auth.models import AnonymousUser
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase

from autorisations.models.models_avis import Avis
from instruction.utils.avis_utils import filtre_numero_avis
from instruction.utils.avis_formulaires import configuration_standard
from instruction.views import avis as vues
from instruction.views.requete import _export_avis_xlsx
from openpyxl import load_workbook
from . import test_creation_avis as support


class ImportAvisCSTests(SimpleTestCase):
    creer_avis = support.CreationAvisTests.creer_avis

    def setUp(self):
        support.CreationAvisTests.setUp(self)
        self.modeles["Avis"].Reponse.choices = Avis.Reponse.choices
        self.modeles["Instructeur"].objects.get.return_value = self.user
        self.joindre = self.enterContext(patch.object(vues, "attach_pj_to_avis"))

    def importer(self, **champs):
        donnees = {"nature": "1", "thematique": "1", "expert_externe": "2", "demandeur_avis": "8",
                   "reponse": "favorable", "mode_contact": "Mail", "date_demande_avis": "2026-10-01T08:00",
                   "date_reponse_avis": "2026-10-12T08:00"}
        donnees.update(champs)
        request = self.factory.post("/instruction/123456/ajouter-avis-hors-appli/", donnees)
        request.user = self.user
        return vues.ajouter_avis_hors_appli(request, 123456)

    def test_les_trois_etats_raa_et_numero_externe_sans_modifier_identifiant(self):
        for statut, attendu in (("a_publier", None), ("deja_publie", True), ("non_requise", True)):
            with self.subTest(statut=statut):
                response = self.importer(publication_raa=statut, numero_avis_externe="  CS-2026-042  ")
                self.assertEqual(response.status_code, 302)
                self.assertEqual(self.crees[-1].numero_avis_externe, "CS-2026-042")
                self.assertIs(self.crees[-1].publie_au_raa, attendu)
                self.assertNotIn("id", self.modeles["Avis"].objects.create.call_args.kwargs)
        self.utiliser.assert_not_called()
        self.outbox.assert_not_called()

    def test_numero_facultatif_et_ancien_formulaire_conservent_les_defaults(self):
        response = self.importer(numero_avis_externe="   ")
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(self.crees[-1].numero_avis_externe)
        self.assertIsNone(self.crees[-1].publie_au_raa)

    def test_donnees_cs_forgees_pour_autre_expert_ignorees(self):
        self.contact.raison_sociale = "Autre instance"
        response = self.importer(publication_raa="non_requise", numero_avis_externe="Fausse référence")
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(self.crees[-1].numero_avis_externe)
        self.assertIsNone(self.crees[-1].publie_au_raa)

    def test_statut_invalide_et_reference_trop_longue_refuses(self):
        for donnees in ({"publication_raa": "true"},
                        {"publication_raa": "a_publier", "numero_avis_externe": "X" * 101},
                        {"publication_raa": "a_publier", "numero_avis_externe": "nul\x00"}):
            with self.subTest(donnees=donnees):
                response = self.importer(**donnees)
                self.assertEqual(response.status_code, 400)
        self.modeles["Avis"].objects.create.assert_not_called()
        self.joindre.assert_not_called()
        self.creer_dossier.assert_not_called()

    def test_valeur_initiale_configuree_appliquee_au_raa_vide(self):
        response = self.importer(publication_raa="")
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(self.crees[-1].publie_au_raa)

    def test_import_refuse_champs_requis_et_dates_invalides_avant_ecriture(self):
        for champs in ({"demandeur_avis": ""}, {"thematique": ""}, {"expert_externe": ""},
                       {"date_demande_avis": "incorrecte"}, {"date_reponse_avis": ""}, {"mode_contact": "Inconnu"}):
            with self.subTest(champs=champs):
                self.assertEqual(self.importer(**champs).status_code, 400)
        self.modeles["Expert"].objects.get_or_create.assert_not_called()
        self.modeles["Avis"].objects.create.assert_not_called()
        self.joindre.assert_not_called()

    def test_obligation_note_personnalisee_verifiee_par_la_route_import(self):
        config = configuration_standard("existant")
        next(c for c in config if c["code"] == "note_demandeur")["requis_envoi"] = True
        with patch.object(vues, "charger_configuration", return_value=config):
            self.assertEqual(self.importer().status_code, 400)
            self.modeles["Avis"].objects.create.assert_not_called()
            self.assertEqual(self.importer(note_demandeur="Note requise").status_code, 302)
        self.assertEqual(self.crees[-1].note, "Note requise")

    def test_champs_masques_ignores_et_defaults_valides_enregistres(self):
        config = configuration_standard("existant")
        for c in config:
            if c["code"] in {"note_demandeur", "pj_lie_avis", "date_reponse_avis", "reponse"}:
                c.update(visible=False, requis_envoi=False)
            if c["code"] == "publication_raa":
                c["regles"][0]["defaut"] = "non_requise"
        with patch.object(vues, "charger_configuration", return_value=config):
            response = self.importer(note_demandeur="Fausse note", date_reponse_avis="faux", reponse="fausse")
        self.assertEqual(response.status_code, 302)
        self.assertFalse(self.crees[-1].note)
        self.assertIsNone(self.crees[-1].reponse)
        self.assertIsNone(self.crees[-1].date_reponse_avis)
        self.assertIs(self.crees[-1].publie_au_raa, True)
        self.assertTrue(self.crees[-1].date_demande_avis.tzinfo)
        self.utiliser.assert_not_called()


class NumeroAfficheAvisTests(SimpleTestCase):
    def test_reference_externe_prioritaire_et_identifiant_interne_inchange(self):
        for reference in ("2026-42", "CS-2026-042", "Autre référence"):
            avis = Avis(id=1058, numero_avis_externe=reference)
            self.assertEqual(avis.numero_affiche, reference)
            self.assertEqual(avis.pk, 1058)
        for reference in (None, "", "  "):
            self.assertEqual(Avis(id=1058, numero_avis_externe=reference).numero_affiche, "1058")

    def test_recherche_reference_externe_ou_id_sans_conversion_abusive(self):
        self.assertEqual(filtre_numero_avis(" CS-2026-042 "), Q(numero_avis_externe__iexact="CS-2026-042"))
        self.assertEqual(filtre_numero_avis("1058"), Q(numero_avis_externe__iexact="1058") | Q(id=1058))
        self.assertEqual(filtre_numero_avis("99999999999999999999"), Q(numero_avis_externe__iexact="99999999999999999999"))

    def test_cinq_tableaux_mes_avis_affichent_reference_mais_gardent_urls_internes(self):
        avis = SimpleNamespace(id=1058, numero_affiche="CS-2026-042", dossieravis_set=SimpleNamespace(all=[]))
        contexte = {cle: [avis] for cle in ("avis_a_rendre", "avis_rendus", "demandes_en_cours", "demandes_traitees", "demandes_avis_a_publier_au_RAA")}
        request = RequestFactory().get("/reception_avis/")
        request.user = AnonymousUser()
        request.user._instruction_group_names_cache = {"Publication RAA Avis CS"}
        contexte["request"] = request
        html = render_to_string("instruction/avis.html", contexte)
        self.assertEqual(html.count("<td>CS-2026-042</td>"), 5)
        self.assertIn('/reception_avis/1058/', html)
        self.assertNotIn('/reception_avis/CS-2026-042/', html)

    def test_tableau_requete_conserve_lien_interne(self):
        avis = SimpleNamespace(id=1058, numero_affiche="CS-2026-042", dossieravis_set=SimpleNamespace(all=[]))
        with patch("instruction.templatetags.cartographie_tags.charger_configurations", return_value={}):
            html = render_to_string("instruction/requetes.html", {"avis_list": [avis], "active_tab": "avis", "recherche_avis_effectuee": True})
        self.assertIn("<td>CS-2026-042</td>", html)
        self.assertIn("/reception_avis/1058", html)

    def test_tableau_consultation_affiche_reference_mais_url_utilise_id(self):
        request = RequestFactory().get("/instruction/123456/consultation")
        request.user = AnonymousUser()
        avis = {"numero": 1058, "numero_affiche": "CS-2026-042", "statut": "Envoyé"}
        html = render_to_string("instruction/instruction_dossier_consultation.html", {
            "request": request, "dossier": SimpleNamespace(numero=123456), "avis": [avis], "est_instructeur": True,
        })
        self.assertIn("<td>CS-2026-042</td>", html)
        self.assertIn("/instruction/123456/consultation/1058/", html)

    def test_export_excel_reference_texte_et_id_numerique_sans_reference(self):
        avis_externe = Avis(id=1058, numero_avis_externe="=CS-2026-042")
        avis_interne = Avis(id=1059)
        with patch.object(Avis, "dossieravis_set") as liens:
            liens.all.return_value = []
            response = _export_avis_xlsx([avis_externe, avis_interne])
        feuille = load_workbook(BytesIO(response.content)).active
        self.assertEqual(feuille["A2"].value, "=CS-2026-042")
        self.assertEqual(feuille["A2"].data_type, "s")
        self.assertEqual(feuille["A3"].value, 1059)

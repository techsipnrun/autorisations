"""Pyramides historiques, simulateur et écritures administratives, sans SQL réel."""
from contextlib import ExitStack
from itertools import product
import json
from types import SimpleNamespace as NS
from unittest.mock import MagicMock, patch

from django.db import IntegrityError, ProgrammingError
from django.middleware.csrf import CsrfViewMiddleware
from django.test import RequestFactory, SimpleTestCase

from backoffice.views import actions as vues
from instruction.utils import actions_possibles as moteur
from instruction.utils import dossier_utils


def contexte(**kwargs):
    return {"id_etape_id": 1, "id_demarche_id": 1, "id_groupe_instructeur_id": 7,
            "present_sur_dn": True, "coeur_de_parc": None, "type_manif_sportive": None, **kwargs}


def regle(pk=1, label="Passer en instruction", **scope):
    return NS(pk=pk, id_changement_etape_id=pk, id_changement_etape=NS(action=label),
              **contexte(**{"id_demarche_id": None, "id_groupe_instructeur_id": None, **scope}))


def reference_pyramides(circuit, ctx, lignes):
    """Référence indépendante : pyramides DN et deux niveaux DM explicitement typés."""
    if circuit == "dn":
        champs = [("id_groupe_instructeur_id", "id_demarche_id"), ("id_demarche_id",), ()]
    elif circuit == "sportif":
        champs = [("id_groupe_instructeur_id", "id_demarche_id", "coeur_de_parc", "type_manif_sportive"),
                  ("id_demarche_id", "coeur_de_parc", "type_manif_sportive"),
                  ("id_demarche_id", "type_manif_sportive"), ("type_manif_sportive",), ()]
    else:
        champs = [("id_demarche_id", "coeur_de_parc", "type_manif_sportive"),
                  ("type_manif_sportive",)]
    for niveau in champs:
        if any(ctx[champ] is None for champ in niveau):
            continue
        correspondantes = [ligne for ligne in lignes
                            if ligne.id_etape_id == ctx["id_etape_id"] and ligne.present_sur_dn == ctx["present_sur_dn"]
                            and all(getattr(ligne, champ) == (ctx[champ] if champ in niveau else None) for champ in moteur.CRITERES)]
        if correspondantes:
            labels = list(dict.fromkeys(ligne.id_changement_etape.action for ligne in correspondantes))
            return sorted(labels, key=lambda label: 2 if label == "Classer comme annulé" else 1 if label.startswith("Archiver ") else 0)
    return []


class MoteurActionsTests(SimpleTestCase):
    def evaluer(self, circuit, ctx, lignes, ordre=None):
        ordre = ordre or [code for code, _, _ in moteur.PROFILS[circuit]["niveaux"]]
        return moteur.evaluer_actions(circuit, ctx, ordre=ordre, regles=lignes)

    def test_selection_des_trois_pyramides_avec_general_dm_type(self):
        lignes = []
        for index, (demarche, groupe, coeur, type_, present, etape) in enumerate(product(
            (None, 1, 2), (None, 7), (None, True, False),
            (None, "Dossier DN", "Dossier complet", "Dossier DM"), (False, True), (1, 2)), 1):
            # Plusieurs règles de chaque forme, dont des libellés dupliqués.
            lignes.append(regle(index, ["Passer en instruction", "Archiver le dossier comme accepté", "Classer comme annulé"][index % 3],
                                id_demarche_id=demarche, id_groupe_instructeur_id=groupe,
                                coeur_de_parc=coeur, type_manif_sportive=type_, present_sur_dn=present, id_etape_id=etape))
        for circuit, demarche, groupe, coeur, present in product(moteur.PROFILS, (None, 1, 9), (None, 7), (None, True, False), (False, True)):
            type_ = {"dn": None, "sportif": "Dossier complet", "dm": "Dossier DM"}[circuit]
            ctx = contexte(id_demarche_id=demarche, id_groupe_instructeur_id=groupe,
                           coeur_de_parc=coeur, type_manif_sportive=type_, present_sur_dn=present)
            with self.subTest(circuit=circuit, contexte=ctx):
                self.assertEqual(self.evaluer(circuit, ctx, lignes)["actions"], reference_pyramides(circuit, ctx, lignes))

    def test_general_dn_absent_ne_s_applique_plus_aux_dm_seuls(self):
        ancienne = regle(1, "Classer comme annulé", present_sur_dn=False)
        ctx = contexte(id_groupe_instructeur_id=None, present_sur_dn=False, type_manif_sportive="Dossier DM")
        resultat = self.evaluer("dm", ctx, [ancienne])
        self.assertEqual(resultat["actions"], [])
        self.assertIsNone(resultat["niveau_retenu"])
        self.assertEqual(resultat["niveaux"][-1]["statut"], "absente")
        self.assertIsNone(moteur.niveau_regle("dm", moteur.scope_regle(ancienne)))
        for circuit, type_ in (("dn", None), ("sportif", "Dossier DN"), ("sportif", "Dossier complet")):
            with self.subTest(circuit=circuit, type=type_):
                self.assertEqual(self.evaluer(circuit, {**ctx, "type_manif_sportive": type_}, [ancienne])["actions"], [ancienne.id_changement_etape.action])

    def test_general_dm_type_et_priorite_specifique_sans_cumul(self):
        ancienne = regle(1, "Action DN", present_sur_dn=False)
        generale = regle(2, "Action générale DM", present_sur_dn=False, type_manif_sportive="Dossier DM")
        specifique = regle(3, "Action spécifique DM", present_sur_dn=False,
                           type_manif_sportive="Dossier DM", id_demarche_id=1, coeur_de_parc=False)
        lignes = [ancienne, generale, specifique]
        ctx = contexte(id_groupe_instructeur_id=None, present_sur_dn=False, type_manif_sportive="Dossier DM", coeur_de_parc=False)
        self.assertEqual(self.evaluer("dm", ctx, lignes)["actions"], ["Action spécifique DM"])
        resultat = self.evaluer("dm", {**ctx, "coeur_de_parc": True}, lignes)
        self.assertEqual(resultat["actions"], ["Action générale DM"])
        self.assertEqual(resultat["niveau_retenu"]["code"], "general")
        self.assertEqual(moteur.niveau_regle("dm", moteur.scope_regle(generale)), "general")
        ordre = ["general", "demarche_coeur"]
        self.assertEqual(self.evaluer("dm", ctx, lignes, ordre)["actions"], ["Action générale DM"])
        for circuit, type_ in (("dn", None), ("sportif", "Dossier complet")):
            self.assertEqual(self.evaluer(circuit, {**ctx, "type_manif_sportive": type_}, [generale])["actions"], [])

    def test_absence_de_cumul_et_trace_des_niveaux_ecartes(self):
        lignes = [regle(1, "Spécifique", id_demarche_id=1, id_groupe_instructeur_id=7), regle(2, "Générale")]
        resultat = self.evaluer("dn", contexte(), lignes)
        self.assertEqual(resultat["actions"], ["Spécifique"])
        self.assertEqual(resultat["regles_retenues"], [1])
        self.assertEqual([item["statut"] for item in resultat["niveaux"]], ["retenue", "absente", "ecartee"])

    def test_reordonnancement_reel_et_simulation_identiques(self):
        lignes = [regle(1, "Spécifique", id_demarche_id=1), regle(2, "Générale")]
        ordre = ["general", "demarche", "groupe_demarche"]
        with patch.object(moteur, "charger_ordres", return_value=({"dn": ordre}, True)), patch.object(moteur.ActionsPossibles, "objects") as manager:
            manager.filter.return_value.select_related.return_value = lignes
            attendu = moteur.evaluer_actions("dn", contexte())
            self.assertEqual(attendu["actions"], ["Générale"])
            dossier = NS(id_etape_dossier=True, id_etape_dossier_id=1, id_demarche_id=1,
                         id_demarche=NS(type="Travaux"), id_groupeinstructeur_id=7, present_sur_ds=True)
            self.assertEqual(dossier_utils.get_actions_possibles(dossier), attendu["actions"])

    def test_coeur_false_est_un_critere_connu(self):
        ligne = regle(id_demarche_id=1, type_manif_sportive="Dossier complet", coeur_de_parc=False)
        resultat = self.evaluer("sportif", contexte(type_manif_sportive="Dossier complet", coeur_de_parc=False), [ligne])
        self.assertEqual(resultat["niveau_retenu"]["code"], "demarche_coeur")

    def test_combinaisons_inatteignables_non_selectionnees(self):
        self.assertIsNone(moteur.niveau_regle("dn", contexte(id_demarche_id=None)))
        self.assertIsNone(moteur.niveau_regle("sportif", contexte(type_manif_sportive="Dossier complet")))

    def test_chargement_standard_si_table_absente_et_configuration_invalide(self):
        with patch.object(moteur.transaction, "atomic"), patch.object(moteur.ActionsPriorites, "objects") as manager:
            manager.all.side_effect = ProgrammingError("absente")
            ordres, installe = moteur.charger_ordres()
            self.assertFalse(installe)
            self.assertEqual(ordres["dn"], ["groupe_demarche", "demarche", "general"])
            manager.all.side_effect = None
            manager.all.return_value = [NS(code="dn", niveaux=["general"])]
            self.assertEqual(moteur.charger_ordres()[0], ordres)

    def test_ordre_complet_obligatoire(self):
        for ordre in (["general"], ["general", "general", "demarche"], "general", [1, 2, 3]):
            with self.subTest(ordre=ordre), self.assertRaises(ValueError):
                moteur.verifier_ordre("dn", ordre)

    def test_ancien_ordre_dm_conserve_son_classement_sans_reecriture_bdd(self):
        ancien = ["general", "demarche", "demarche_type", "demarche_coeur"]
        with patch.object(moteur.transaction, "atomic"), patch.object(moteur.ActionsPriorites, "objects") as manager:
            manager.all.return_value = [NS(code="dm", niveaux=ancien)]
            ordres, installe = moteur.charger_ordres()
        self.assertTrue(installe)
        self.assertEqual(ordres["dm"], ["general", "demarche_coeur"])
        self.assertEqual(ancien, ["general", "demarche", "demarche_type", "demarche_coeur"])
        manager.update_or_create.assert_not_called()
        manager.update.assert_not_called()
        with self.assertRaises(ValueError):
            moteur.verifier_ordre("dm", ancien)

    def test_niveau_dm_sans_type_retire_du_moteur_et_des_priorites(self):
        ancienne = regle(1, "Ancienne action sans type", id_demarche_id=1, present_sur_dn=False)
        generale = regle(2, "Générale DM", present_sur_dn=False, type_manif_sportive="Dossier DM")
        ctx = contexte(id_groupe_instructeur_id=None, present_sur_dn=False, type_manif_sportive="Dossier DM")
        resultat = self.evaluer("dm", ctx, [ancienne, generale])
        self.assertEqual(resultat["actions"], ["Générale DM"])
        self.assertEqual([n["code"] for n in resultat["niveaux"]], ["demarche_coeur", "general"])
        self.assertIsNone(moteur.niveau_regle("dm", moteur.scope_regle(ancienne)))
        self.assertEqual(moteur.niveau_regle("dn", moteur.scope_regle(ancienne)), "demarche")
        self.assertEqual(self.evaluer("dm", ctx, [ancienne])["actions"], [])

    def test_ordre_dm_invalide_garde_le_controle_apres_retrait_du_niveau(self):
        with patch.object(moteur.transaction, "atomic"), patch.object(moteur.ActionsPriorites, "objects") as manager:
            for ancien in (["general", "demarche", "general", "demarche_coeur"],
                           ["general", "demarche", "inconnu", "demarche_coeur"],
                           ["general", "demarche", "demarche", "demarche_type", "demarche_coeur"]):
                with self.subTest(ancien=ancien):
                    manager.all.return_value = [NS(code="dm", niveaux=ancien)]
                    self.assertEqual(moteur.charger_ordres()[0]["dm"], ["demarche_coeur", "general"])

    def test_retrait_demarche_type_limite_au_circuit_dm(self):
        ancienne = regle(1, "Ancienne action par démarche", id_demarche_id=1,
                         present_sur_dn=False, type_manif_sportive="Dossier DM")
        generale = regle(2, "Action générale DM", present_sur_dn=False,
                         type_manif_sportive="Dossier DM")
        ctx = contexte(id_groupe_instructeur_id=None, present_sur_dn=False,
                       type_manif_sportive="Dossier DM", coeur_de_parc=True)
        resultat = self.evaluer("dm", ctx, [ancienne, generale])
        self.assertEqual(resultat["actions"], ["Action générale DM"])
        self.assertEqual(resultat["niveau_retenu"]["code"], "general")
        self.assertIsNone(moteur.niveau_regle("dm", moteur.scope_regle(ancienne)))
        sportive = regle(3, "Action sportive", id_demarche_id=1,
                         type_manif_sportive="Dossier complet")
        self.assertEqual(moteur.niveau_regle("sportif", moteur.scope_regle(sportive)), "demarche_type")
        self.assertEqual(self.evaluer("sportif", contexte(type_manif_sportive="Dossier complet"), [sportive])["actions"], ["Action sportive"])

    def test_ordre_dm_trois_niveaux_reduit_sans_reinitialiser_le_classement(self):
        ancien = ["general", "demarche_type", "demarche_coeur"]
        with patch.object(moteur.transaction, "atomic"), patch.object(moteur.ActionsPriorites, "objects") as manager:
            manager.all.return_value = [NS(code="dm", niveaux=ancien)]
            self.assertEqual(moteur.charger_ordres()[0]["dm"], ["general", "demarche_coeur"])
            manager.update_or_create.assert_not_called()
        self.assertEqual(ancien, ["general", "demarche_type", "demarche_coeur"])
        for ordre in (["general", "demarche_type", "demarche_coeur"],
                      ["general", "demarche_type", "demarche_type", "demarche_coeur"]):
            with self.subTest(ordre=ordre), self.assertRaises(ValueError):
                moteur.verifier_ordre("dm", ordre)

    def test_contexte_sportif_et_dm_lie_refuse(self):
        dossier = NS(id_etape_dossier_id=1, id_demarche_id=2, id_groupeinstructeur_id=7,
                     present_sur_ds=True, id_demarche=NS(type="Manifestations sportives"))
        with patch.object(moteur.DossierManifestationLiaison, "objects") as manager:
            manager.filter.return_value.first.return_value = NS(id_dossier_manif=NS(coeur_de_parc=False))
            circuit, ctx = moteur.contexte_dossier(dossier)
            self.assertEqual((circuit, ctx["coeur_de_parc"], ctx["type_manif_sportive"]), ("sportif", False, "Dossier complet"))
            manager.filter.return_value.first.return_value = None
            self.assertEqual(moteur.contexte_dossier(dossier)[1]["type_manif_sportive"], "Dossier DN")
            manager.filter.return_value.exists.return_value = True
            with self.assertRaises(ValueError):
                moteur.contexte_dm(NS())


class APIActionsTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.scope = contexte(id_demarche_id=None, id_groupe_instructeur_id=None)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(vues.transaction, "atomic"))
        self.etapes = self.stack.enter_context(patch.object(vues.EtapeDossier, "objects"))
        self.demarches = self.stack.enter_context(patch.object(vues.Demarche, "objects"))
        self.groupes = self.stack.enter_context(patch.object(vues.Groupeinstructeur, "objects"))
        self.regles = self.stack.enter_context(patch.object(vues.ActionsPossibles, "objects"))
        self.actions = self.stack.enter_context(patch.object(vues.ChangementEtape, "objects"))
        self.actions.filter.return_value.values_list.return_value = [1, 2]
        self.catalogue_actions = [vues.ChangementEtape(pk=1, action="Passer en instruction", code="passer_en_instruction"),
                                 vues.ChangementEtape(pk=2, action="Autre action", code="avis_envoye")]
        self.stack.enter_context(patch.object(vues, "charger_actions", return_value=self.catalogue_actions))
        self.etapes.get.side_effect = lambda pk: NS(pk=pk, etape="En instruction")
        self.demarches.get.return_value = NS(type="Travaux")
        self.regles.select_for_update.return_value.filter.return_value = []

    def post(self, vue, donnees, **kwargs):
        request = self.factory.post("/back-office/actions/", json.dumps(donnees), content_type="application/json")
        request.user = NS(is_authenticated=True, is_superuser=True)
        return vue(request, **kwargs)

    def test_action_non_prise_en_charge_a_affecter_refusee(self):
        self.etapes.get.side_effect = None
        self.etapes.get.return_value = NS(pk=10, etape="À affecter")
        response = self.post(vues.enregistrer_configuration, {"circuit": "dn", "scope": {**self.scope, "id_etape_id": 10}, "actions": [1]})
        self.assertEqual(response.status_code, 400)
        self.regles.create.assert_not_called()


    def test_simulateur_signale_les_actions_non_affichables_sans_changer_pyramide(self):
        self.etapes.get.side_effect = None
        self.etapes.get.return_value = NS(pk=10, etape="À affecter")
        ctx = {**self.scope, "id_etape_id": 10, "id_demarche_id": 1}
        with patch.object(vues, "evaluer_actions", return_value={"actions": ["Passer en instruction"], "niveau_retenu": {"code": "general", "priorite": 3}}):
            response = self.post(vues.tester, {"circuit": "dn", "contexte": ctx})
        resultat = json.loads(response.content)
        self.assertEqual(resultat["niveau_retenu"]["priorite"], 3)
        self.assertEqual(resultat["actions"], [])
        self.assertEqual(resultat["actions_selectionnees"], ["Passer en instruction"])
        self.assertEqual(resultat["actions_incompatibles"][0]["nom"], "Passer en instruction")

    def test_creation_et_selection_complete(self):
        reponse = self.post(vues.enregistrer_configuration, {"circuit": "dn", "scope": self.scope, "actions": [1, 2]})
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(self.regles.create.call_count, 2)
        self.regles.create.assert_any_call(**self.scope, id_changement_etape_id=1)

    def test_catalogue_regroupe_les_lignes_sans_les_modifier(self):
        lignes = [regle(1), regle(2, "Autre action")]
        self.regles.select_related.return_value.all.return_value = lignes
        self.etapes.all.return_value.order_by.return_value = [NS(pk=1, etape="En instruction", est_archivage=False)]
        self.demarches.all.return_value.order_by.return_value = [NS(pk=1, type="Travaux")]
        self.groupes.all.return_value.order_by.return_value = [NS(pk=7, nom="Travaux")]
        self.actions.all.return_value.order_by.return_value = [NS(pk=1, action="Passer en instruction")]
        request = self.factory.get("/back-office/actions/")
        request.user = NS(is_authenticated=True, is_superuser=True)
        with patch.object(vues, "charger_ordres", return_value=({"dn": ["general"]}, True)):
            response = vues.catalogue(request)
        contenu = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(contenu["configurations"]), 1)
        self.assertEqual(contenu["configurations"][0]["actions"], [1, 2])
        self.assertEqual(contenu["configurations"][0]["niveaux"], {"dn": "general", "sportif": "general"})
        self.regles.create.assert_not_called()

    def test_etapes_dm_selon_regles_explicites_et_archivage_sans_lire_les_dossiers(self):
        self.etapes.all.return_value.order_by.return_value = [
            NS(pk=1, etape="À affecter", est_archivage=False),
            NS(pk=2, etape="En réception", est_archivage=False),
            NS(pk=3, etape="Clôture personnalisée", est_archivage=True),
            NS(pk=4, etape="À publier au RAA", est_archivage=False),
            NS(pk=5, etape="Étape d’un DN sportif", est_archivage=False),
            NS(pk=6, etape="Nouvelle étape DM", est_archivage=False),
        ]
        self.demarches.all.return_value.order_by.return_value = [NS(pk=1, type="Travaux")]
        self.groupes.all.return_value.order_by.return_value = []
        self.regles.select_related.return_value.all.return_value = [
            regle(1, id_etape_id=1, present_sur_dn=False),
            regle(2, id_etape_id=2, present_sur_dn=False, type_manif_sportive="Dossier DM"),
            regle(3, id_etape_id=5, present_sur_dn=True, type_manif_sportive="Dossier DM"),
            regle(4, id_etape_id=6, present_sur_dn=False, type_manif_sportive="Dossier DM", coeur_de_parc=False),
        ]
        request = self.factory.get("/back-office/actions/")
        request.user = NS(is_authenticated=True, is_superuser=True)
        with patch.object(vues, "charger_ordres", return_value=({"dm": ["general"]}, True)), \
             patch.object(vues.Dossier, "objects") as dossiers_dn, \
             patch.object(vues.DossierManifSportive, "objects") as dossiers_dm:
            resultat = json.loads(vues.catalogue(request).content)
        self.assertEqual({etape["id"] for etape in resultat["etapes"] if etape["disponible_dm"]}, {2, 3, 6})
        self.assertEqual({etape["id"] for etape in resultat["etapes"] if etape["est_archivage"]}, {3})
        self.assertEqual(len(resultat["configurations"]), 4)
        self.assertEqual(dossiers_dn.mock_calls, [])
        self.assertEqual(dossiers_dm.mock_calls, [])
        self.regles.create.assert_not_called()

    def test_catalogue_separe_les_configurations_generales_dn_et_dm(self):
        self.regles.select_related.return_value.all.return_value = [
            regle(1, present_sur_dn=False),
            regle(2, present_sur_dn=False, type_manif_sportive="Dossier DM"),
        ]
        self.etapes.all.return_value.order_by.return_value = [NS(pk=1, etape="Non soumis à autorisation", est_archivage=True)]
        self.demarches.all.return_value.order_by.return_value = []
        self.groupes.all.return_value.order_by.return_value = []
        request = self.factory.get("/back-office/actions/")
        request.user = NS(is_authenticated=True, is_superuser=True)
        with patch.object(vues, "charger_ordres", return_value=({"dm": ["general"]}, True)):
            resultat = json.loads(vues.catalogue(request).content)
        self.assertEqual(resultat["configurations"][0]["niveaux"], {"dn": "general", "sportif": "general"})
        self.assertEqual(resultat["configurations"][1]["niveaux"], {"dm": "general"})
        self.assertTrue(resultat["etapes"][0]["disponible_dm"])
        self.regles.create.assert_not_called()
        self.regles.filter.assert_not_called()

    def test_enregistrer_generale_dm_exige_le_type_et_conserve_les_criteres_vides(self):
        scope = {**self.scope, "present_sur_dn": False}
        self.assertEqual(self.post(vues.enregistrer_configuration, {"circuit": "dm", "scope": scope, "actions": [1]}).status_code, 400)
        self.regles.create.assert_not_called()
        self.catalogue_actions[:] = [vues.ChangementEtape(pk=1, action="Annuler sur DM", code="declaration_manifestations_classer_comme_annule")]
        scope["type_manif_sportive"] = "Dossier DM"
        response = self.post(vues.enregistrer_configuration, {"circuit": "dm", "scope": scope, "actions": [1]})
        self.assertEqual(response.status_code, 200)
        self.regles.create.assert_called_once_with(**scope, id_changement_etape_id=1)

    def test_simulateur_dm_sans_generale_dm_ne_reprend_pas_la_generale_dn(self):
        ctx = {**self.scope, "present_sur_dn": False, "type_manif_sportive": "Dossier DM", "id_demarche_id": 1}
        self.demarches.get.return_value = NS(type="Manifestations sportives")
        self.regles.filter.return_value.select_related.return_value = [regle(1, "Classer comme annulé", present_sur_dn=False)]
        ordres = {code: [cle for cle, _, _ in profil["niveaux"]] for code, profil in moteur.PROFILS.items()}
        with patch.object(moteur, "charger_ordres", return_value=(ordres, True)):
            response = self.post(vues.tester, {"circuit": "dm", "contexte": ctx})
        self.assertEqual(response.status_code, 200)
        resultat = json.loads(response.content)
        self.assertEqual(resultat["actions"], [])
        self.assertEqual(resultat["actions_selectionnees"], [])
        self.assertIsNone(resultat["niveau_retenu"])

    def test_enregistrer_priorites_dm_apres_lecture_d_un_ancien_ordre(self):
        ancien = ["general", "demarche", "demarche_type", "demarche_coeur"]
        nouveau = ["demarche_coeur", "general"]
        with patch.object(vues.ActionsPriorites, "objects") as manager:
            manager.all.return_value = [NS(code="dm", niveaux=ancien)]
            response = self.post(vues.enregistrer_priorites, {
                "circuit": "dm", "ordre": nouveau,
                "original": ["general", "demarche_coeur"],
            })
        self.assertEqual(response.status_code, 200)
        manager.update_or_create.assert_called_once_with(code="dm", defaults={"niveaux": nouveau})

    def test_catalogue_signale_les_regles_de_l_ancien_niveau_sans_les_convertir(self):
        ancienne = regle(1, id_demarche_id=1, present_sur_dn=False)
        self.regles.select_related.return_value.all.return_value = [ancienne]
        self.etapes.all.return_value.order_by.return_value = [NS(pk=1, etape="En réception", est_archivage=False)]
        self.demarches.all.return_value.order_by.return_value = [NS(pk=1, type="Manifestations sportives")]
        self.groupes.all.return_value.order_by.return_value = []
        request = self.factory.get("/back-office/actions/")
        request.user = NS(is_authenticated=True, is_superuser=True)
        with patch.object(vues, "charger_ordres", return_value=({"dm": ["demarche_coeur", "general"]}, True)):
            resultat = json.loads(vues.catalogue(request).content)
        self.assertIsNone(resultat["configurations"][0]["niveaux"]["dm"])
        self.assertEqual(resultat["configurations"][0]["scope"]["type_manif_sportive"], None)
        self.regles.create.assert_not_called()
        self.regles.filter.assert_not_called()

    def test_creation_niveau_demarche_dm_retire_refusee_sans_ecriture(self):
        scope = {**self.scope, "id_demarche_id": 1, "present_sur_dn": False,
                 "type_manif_sportive": "Dossier DM"}
        self.demarches.get.return_value = NS(type="Manifestations sportives")
        response = self.post(vues.enregistrer_configuration, {
            "circuit": "dm", "scope": scope, "actions": [1],
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn("aucun niveau", json.loads(response.content)["error"])
        self.regles.create.assert_not_called()
        self.regles.select_for_update.assert_not_called()

    def test_changement_de_scope_conserve_identifiant(self):
        ligne = vues.ActionsPossibles(pk=1, id_changement_etape_id=1, **self.scope)
        ancien = dict(self.scope)
        self.regles.select_for_update.return_value.filter.return_value = [ligne]
        self.regles.filter.return_value.exists.return_value = False
        nouveau = {**self.scope, "id_etape_id": 2}
        with patch.object(ligne, "save") as save:
            response = self.post(vues.enregistrer_configuration, {"circuit": "dn", "scope": nouveau, "actions": [1],
                "original": {"scope": ancien, "signature": vues.signature([ligne])}})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ligne.pk, 1)
        self.assertEqual(ligne.id_etape_id, 2)
        self.assertIn("id_etape", save.call_args.kwargs["update_fields"])
        self.regles.create.assert_not_called()

    def test_verrou_transactionnel_ne_modifie_pas_les_referentiels(self):
        with patch.object(vues, "connection") as connexion:
            connexion.vendor = "postgresql"
            vues.verrouiller([2, 1, 2])
            curseur = connexion.cursor.return_value.__enter__.return_value
            self.assertEqual(curseur.execute.call_count, 2)
            self.assertEqual(curseur.execute.call_args.args, ("SELECT pg_advisory_xact_lock(%s, %s)", [0x41474944, 2]))

    def test_editer_conserve_les_lignes_inchangees(self):
        ligne = regle(1)
        self.regles.select_for_update.return_value.filter.return_value = [ligne]
        reponse = self.post(vues.enregistrer_configuration, {"circuit": "dn", "scope": self.scope, "actions": [1, 2],
            "original": {"scope": self.scope, "signature": vues.signature([ligne])}})
        self.assertEqual(reponse.status_code, 200)
        self.regles.create.assert_called_once_with(**self.scope, id_changement_etape_id=2)

    def test_modification_concurrente_refusee(self):
        self.regles.select_for_update.return_value.filter.return_value = [regle(1)]
        reponse = self.post(vues.enregistrer_configuration, {"circuit": "dn", "scope": self.scope, "actions": [2],
            "original": {"scope": self.scope, "signature": "ancienne"}})
        self.assertEqual(reponse.status_code, 409)
        self.regles.create.assert_not_called()

    def test_creation_en_double_refusee(self):
        self.regles.select_for_update.return_value.filter.return_value = [regle(1)]
        self.assertEqual(self.post(vues.enregistrer_configuration, {"circuit": "dn", "scope": self.scope, "actions": [1]}).status_code, 409)

    def test_suppression_limitee_au_contexte(self):
        ligne = regle(1)
        self.regles.select_for_update.return_value.filter.return_value = [ligne]
        response = self.post(vues.enregistrer_configuration, {"circuit": "dn", "scope": self.scope, "supprimer": True,
            "original": {"scope": self.scope, "signature": vues.signature([ligne])}})
        self.assertEqual(response.status_code, 200)
        self.regles.filter.assert_called_once_with(pk__in=[1])
        self.regles.filter.return_value.delete.assert_called_once()

    def test_contrainte_bdd_retournee_en_json(self):
        self.regles.create.side_effect = IntegrityError("contrainte")
        response = self.post(vues.enregistrer_configuration, {"circuit": "dn", "scope": self.scope, "actions": [1]})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(json.loads(response.content)["success"])

    def test_scopes_et_actions_invalides_refuses_avant_ecriture(self):
        cas = [("dn", {**self.scope, "present_sur_dn": "false"}, [1]),
               ("dn", {**self.scope, "coeur_de_parc": True}, [1]),
               ("dn", self.scope, []), ("dn", self.scope, [999]),
               ("dm", self.scope, [1]),
               ("dn", {**self.scope, "id_demarche_id": None, "id_groupe_instructeur_id": 7}, [1])]
        for circuit, scope, actions in cas:
            with self.subTest(scope=scope, actions=actions):
                self.assertEqual(self.post(vues.enregistrer_configuration, {"circuit": circuit, "scope": scope, "actions": actions}).status_code, 400)
        self.regles.create.assert_not_called()

    def test_priorites_enregistrees_sans_ddl(self):
        ancien = ["groupe_demarche", "demarche", "general"]
        with patch.object(vues, "charger_ordres", return_value=({"dn": ancien}, True)), patch.object(vues.ActionsPriorites, "objects") as manager:
            ordre = list(reversed(ancien))
            response = self.post(vues.enregistrer_priorites, {"circuit": "dn", "ordre": ordre, "original": ancien})
            self.assertEqual(response.status_code, 200)
            manager.update_or_create.assert_called_once_with(code="dn", defaults={"niveaux": ordre})

    def test_priorites_non_installees_pas_de_creation_automatique(self):
        with patch.object(vues, "charger_ordres", return_value=({}, False)), patch.object(vues.ActionsPriorites, "objects") as manager:
            response = self.post(vues.enregistrer_priorites, {"circuit": "dn", "ordre": ["groupe_demarche", "demarche", "general"]})
            self.assertEqual(response.status_code, 503)
            manager.update_or_create.assert_not_called()

    def test_priorites_modifiees_concurremment_refusees(self):
        with patch.object(vues, "charger_ordres", return_value=({"dn": ["general", "demarche", "groupe_demarche"]}, True)), patch.object(vues.ActionsPriorites, "objects") as manager:
            response = self.post(vues.enregistrer_priorites, {"circuit": "dn", "ordre": ["groupe_demarche", "demarche", "general"], "original": []})
            self.assertEqual(response.status_code, 409)
            manager.update_or_create.assert_not_called()

    def test_regles_sportives_et_dm_seuls_distinctes(self):
        ctx = {**self.scope, "id_demarche_id": 2, "type_manif_sportive": "Dossier DM", "present_sur_dn": False}
        self.demarches.get.return_value = NS(type="Manifestations sportives")
        with patch.object(vues, "evaluer_actions", return_value={}) as evaluer:
            self.assertEqual(self.post(vues.tester, {"circuit": "dm", "contexte": ctx}).status_code, 200)
            evaluer.assert_called_once_with("dm", ctx)
        with patch.object(vues, "evaluer_actions") as evaluer:
            self.assertEqual(self.post(vues.tester, {"circuit": "sportif", "contexte": ctx}).status_code, 400)
            evaluer.assert_not_called()

    def test_simulateur_utilise_le_moteur_et_necrit_rien(self):
        ctx = {**self.scope, "id_demarche_id": 1}
        with patch.object(vues, "evaluer_actions", return_value={"actions": ["Test"], "niveaux": []}) as evaluer:
            response = self.post(vues.tester, {"circuit": "dn", "contexte": ctx})
            self.assertEqual(response.status_code, 200)
            evaluer.assert_called_once_with("dn", ctx)
        self.regles.create.assert_not_called()
        self.regles.select_for_update.assert_not_called()

    def test_simulation_distingue_criteres_retenus_et_contexte(self):
        ctx = {**self.scope, "id_demarche_id": 1, "id_groupe_instructeur_id": 7}
        with patch.object(vues, "evaluer_actions", return_value={"actions": ["Test"], "niveau_retenu": {"code": "general", "priorite": 3}}):
            response = self.post(vues.tester, {"circuit": "dn", "contexte": ctx})
        resultat = json.loads(response.content)
        self.assertEqual(resultat["contexte"], ctx)
        self.assertEqual(resultat["configuration_retenue"]["id_etape_id"], ctx["id_etape_id"])
        self.assertIsNone(resultat["configuration_retenue"]["id_demarche_id"])
        self.assertIsNone(resultat["configuration_retenue"]["id_groupe_instructeur_id"])

    def test_simulation_sans_gagnant_ne_presente_pas_de_configuration(self):
        with patch.object(vues, "evaluer_actions", return_value={"actions": [], "niveau_retenu": None}):
            response = self.post(vues.tester, {"circuit": "dn", "contexte": {**self.scope, "id_demarche_id": 1}})
        self.assertIsNone(json.loads(response.content)["configuration_retenue"])

    def test_dossier_reel_et_etape_fictive(self):
        dossier = NS()
        with patch.object(vues.Dossier, "objects") as manager, patch.object(vues, "contexte_dossier", return_value=("dn", dict(self.scope))), patch.object(vues, "evaluer_actions", return_value={}) as evaluer:
            manager.select_related.return_value.filter.return_value.first.return_value = dossier
            response = self.post(vues.tester, {"circuit": "dn", "numero": "123", "etape_fictive": 2})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(evaluer.call_args.args[1]["id_etape_id"], 2)
            manager.update.assert_not_called()

    def test_etape_fictive_requise_pour_dossier_existant(self):
        with patch.object(vues.Dossier, "objects") as manager, patch.object(vues, "contexte_dossier", return_value=("dn", dict(self.scope))), patch.object(vues, "evaluer_actions") as evaluer:
            manager.select_related.return_value.filter.return_value.first.return_value = NS()
            response = self.post(vues.tester, {"circuit": "dn", "numero": "123"})
            self.assertEqual(response.status_code, 400)
            self.assertIn("étape fictive", json.loads(response.content)["error"])
            evaluer.assert_not_called()

    def test_demarche_requise_pour_contexte_fictif(self):
        with patch.object(vues, "evaluer_actions") as evaluer:
            self.assertEqual(self.post(vues.tester, {"circuit": "dn", "contexte": self.scope}).status_code, 400)
            evaluer.assert_not_called()

    def test_autocompletion_bornee_au_circuit_et_sans_ecriture(self):
        dossier = NS(numero=123, id_etape_dossier_id=2, id_etape_dossier=NS(etape="En instruction"), nom_dossier="Projet")
        with patch.object(vues.Dossier, "objects") as manager:
            queryset = MagicMock()
            for methode in ("exclude", "filter", "annotate", "order_by"):
                getattr(queryset, methode).return_value = queryset
            queryset.__getitem__.return_value = [dossier]
            manager.select_related.return_value = queryset
            for circuit in ("dn", "sportif"):
                request = self.factory.get("/back-office/actions/dossiers/", {"circuit": circuit, "q": "12"})
                request.user = NS(is_authenticated=True, is_superuser=True)
                response = vues.rechercher_dossiers(request)
                self.assertEqual(json.loads(response.content)["dossiers"], [{"numero": "123", "etape": 2, "etape_nom": "En instruction", "nom": "Projet"}])
            queryset.exclude.assert_called_with(id_demarche__type="Manifestations sportives")
            queryset.filter.assert_any_call(id_demarche__type="Manifestations sportives")
            queryset.filter.assert_any_call(numero_texte__startswith="12")
            queryset.__getitem__.assert_called_with(slice(None, 12, None))
            manager.create.assert_not_called()

    def test_autocompletion_dm_exclut_les_dossiers_lies(self):
        dossier = NS(numero_dossier_declaration_manifestations=321, id_etape_id=1, id_etape=NS(etape="En réception"), nom_dossier=None)
        with patch.object(vues.DossierManifSportive, "objects") as manager, patch.object(vues.DossierManifestationLiaison, "objects") as liaisons:
            queryset = MagicMock()
            for methode in ("select_related", "filter", "annotate", "order_by"):
                getattr(queryset, methode).return_value = queryset
            queryset.__getitem__.return_value = [dossier]
            manager.exclude.return_value = queryset
            request = self.factory.get("/back-office/actions/dossiers/", {"circuit": "dm", "q": "32"})
            request.user = NS(is_authenticated=True, is_superuser=True)
            response = vues.rechercher_dossiers(request)
            self.assertEqual(json.loads(response.content)["dossiers"][0]["numero"], "321")
            manager.exclude.assert_called_once_with(pk__in=liaisons.values.return_value)
            liaisons.values.assert_called_once_with("id_dossier_manif_id")

    def test_autocompletion_recherche_invalide_ne_lit_aucun_dossier(self):
        with patch.object(vues.Dossier, "objects") as manager:
            for recherche in ("", "abc", "1" * 16):
                request = self.factory.get("/back-office/actions/dossiers/", {"circuit": "dn", "q": recherche})
                request.user = NS(is_authenticated=True, is_superuser=True)
                self.assertEqual(json.loads(vues.rechercher_dossiers(request).content)["dossiers"], [])
            manager.select_related.assert_not_called()

    def test_csrf_sur_les_endpoints_mutants(self):
        request = self.factory.post("/back-office/actions/configuration/", "{}", content_type="application/json")
        response = CsrfViewMiddleware(lambda req: None).process_view(request, vues.enregistrer_configuration, (), {})
        self.assertEqual(response.status_code, 403)

    def test_json_invalide_message_clair(self):
        request = self.factory.post("/back-office/actions/tester/", "<html>", content_type="application/json")
        request.user = NS(is_authenticated=True, is_superuser=True)
        self.assertEqual(vues.tester(request).status_code, 400)

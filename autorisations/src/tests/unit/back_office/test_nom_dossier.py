from datetime import datetime, timezone as dt_timezone
from contextlib import ExitStack
import json
from types import SimpleNamespace
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import RequestFactory, SimpleTestCase, override_settings

from autorisations.models.models_instruction import Dossier
from instruction.views.nom_dossier import (
    autocomplete_numeros_dossiers, enregistrer_regles_nom_dossier, previsualiser_nom_dossier, recalculer_noms_dossiers,
    valider_regles_nommage,
)
from synchronisation.utils.nom_dossier import construire_contexte_nommage, generer_nom_dossier, compiler_regles_nommage
from synchronisation.synchro.sync_dossiers import sync_dossiers


def texte(value):
    return {"type": "texte", "texte": value}


def attribut(key, transformation="aucune"):
    return {"type": "attribut", "attribut": key, "libelle": key, "transformation": transformation}


def champ(key):
    return {"type": "champ_dn", "id_ds": key, "libelle": key, "transformation": "aucune"}


def champ_dm(key):
    return {"type": "champ_dm", "champ_dm": key, "libelle": key, "transformation": "aucune"}


def personnalise(element, correspondances, comportement="conserver"):
    return {**element, "transformation": "personnalisee", "configuration_transformation": {
        "correspondances": [{"valeur": valeur, "texte": texte} for valeur, texte in correspondances],
        "sans_correspondance": comportement,
    }}


def regle(elements, ordre=1, actif=True):
    return {"elements": elements, "ordre": ordre, "libelle": "Test", "actif": actif}


class NommageTests(SimpleTestCase):
    def contexte(self, champs=None, contacts=None):
        return construire_contexte_nommage(
            {"numero": 123, "date_depot": datetime(2026, 10, 5, tzinfo=dt_timezone.utc)},
            contacts if contacts is not None else {"beneficiaire": {"prenom": "Denis", "nom": "Hoarau"}},
            [{"champ": {"id_ds": key, "valeur": value}} for key, value in (champs or {}).items()],
        )

    def test_genere_exemple_complet_avec_transformation(self):
        resultat = generer_nom_dossier([regle([
            champ("hebergement"), texte(" à "), champ("lieu"), texte(" - "),
            attribut("demandeur.prenom"), texte(" "), attribut("demandeur.nom", "majuscules"),
        ])], self.contexte({"hebergement": "Gîte", "lieu": "Mafate"}))
        self.assertEqual(resultat["nom_genere"], "Gîte à Mafate - Denis HOARAU")

    def test_ajoute_un_espace_entre_chaque_element(self):
        resultat = generer_nom_dossier([regle([
            champ("hebergement"), texte("à"), champ("lieu"),
        ])], self.contexte({"hebergement": "Gîte", "lieu": "Mafate"}))
        self.assertEqual(resultat["nom_genere"], "Gîte à Mafate")

    def test_personnalisee_remplace_un_libelle_sans_casse_ni_espaces_superflus(self):
        element = personnalise(champ("type"), [("Renouvellement de demande", "Renouvellement")])
        resultat = generer_nom_dossier([regle([element, attribut("demandeur.nom")])],
                                      self.contexte({"type": " renouvellement  DE demande "}))
        self.assertEqual(resultat["nom_genere"], "Renouvellement Hoarau")

    def test_personnalisee_booleens_dn_et_dm(self):
        for valeur in (True, "Oui", "true", " TRUE "):
            with self.subTest(valeur=valeur):
                element = personnalise(champ("mafate"), [("Oui", "Mafate")])
                self.assertEqual(generer_nom_dossier([regle([element])], self.contexte({"mafate": valeur}))["nom_genere"], "Mafate")
        contexte = self.contexte()
        contexte["champs_dm"] = {"dans_coeur": False}
        element = personnalise(champ_dm("dans_coeur"), [("Non", "Hors cœur")])
        self.assertEqual(generer_nom_dossier([regle([element])], contexte)["nom_genere"], "Hors cœur")

    def test_personnalisee_sans_correspondance_conserve_ou_passe_a_la_regle_suivante(self):
        for comportement, attendu in (("conserver", "Création"), ("ignorer_regle", "Hoarau")):
            with self.subTest(comportement=comportement):
                element = personnalise(champ("type"), [("Renouvellement", "Renouv.")], comportement)
                resultat = generer_nom_dossier([regle([element]), regle([attribut("demandeur.nom")], 2)],
                                              self.contexte({"type": "Création"}), expliquer=True)
                self.assertEqual(resultat["nom_genere"], attendu)
                if comportement == "ignorer_regle":
                    self.assertEqual(resultat["details"][0]["manquants"], ["type"])

    def test_personnalisee_texte_vide_omet_element_mais_source_absente_ignore_regle(self):
        element = personnalise(champ("mafate"), [("Non", "")])
        regles = [regle([element, attribut("demandeur.nom")])]
        self.assertEqual(generer_nom_dossier(regles, self.contexte({"mafate": False}))["nom_genere"], "Hoarau")
        self.assertIsNone(generer_nom_dossier(regles, self.contexte())["nom_genere"])
        self.assertIsNone(generer_nom_dossier([regle([element])], self.contexte({"mafate": False}))["nom_genere"])

    def test_compilation_conserve_configuration_personnalisee_sans_requetes(self):
        element = personnalise(attribut("demandeur.nom"), [("Hoarau", "HOARAU")])
        modele = SimpleNamespace(type_element=element["type"], texte=None, id_champ_id=None,
                                 champ_dm=None, attribut=element["attribut"], transformation=element["transformation"],
                                 configuration_transformation=element["configuration_transformation"])
        from unittest.mock import Mock
        elements = Mock()
        elements.all.return_value = [modele]
        regles = compiler_regles_nommage([SimpleNamespace(libelle="Test", ordre=1, actif=True, elements=elements)])
        self.assertEqual(regles[0]["elements"][0]["configuration_transformation"], element["configuration_transformation"])
        self.assertEqual(generer_nom_dossier(regles, self.contexte())["nom_genere"], "HOARAU")

    def test_champ_dm_absent_ignore_regle_et_lit_dossier_dm_lie(self):
        regles = [regle([champ_dm("activite")]), regle([attribut("demandeur.nom")], 2)]
        resultat = generer_nom_dossier(regles, self.contexte(), expliquer=True)
        self.assertEqual(resultat["nom_genere"], "Hoarau")
        self.assertEqual(resultat["details"][0]["manquants"], ["activite"])
        contexte = construire_contexte_nommage(
            {"numero": 123}, {"beneficiaire": {"nom": "Hoarau"}}, [],
            dossier_dm={"activite": "Trail"},
        )
        self.assertEqual(generer_nom_dossier(regles, contexte)["nom_genere"], "Trail")

    def test_variable_vide_ignore_toute_la_regle_et_explique(self):
        resultat = generer_nom_dossier([
            regle([champ("conditionnel"), texte(" - "), attribut("demandeur.nom")]),
            regle([attribut("demandeur.prenom"), texte(" "), attribut("demandeur.nom")], 2),
        ], self.contexte({"conditionnel": "   "}), expliquer=True)
        self.assertEqual(resultat["nom_genere"], "Denis Hoarau")
        self.assertEqual(resultat["regle_retenue"], 2)
        self.assertEqual(resultat["details"][0]["manquants"], ["conditionnel"])

    def test_valeurs_zero_et_false_sont_presentes(self):
        resultat = generer_nom_dossier([regle([champ("zero"), texte(" - "), champ("non")])],
                                      self.contexte({"zero": 0, "non": False}))
        self.assertEqual(resultat["nom_genere"], "0 - Non")

    def test_structure_non_interpretable_utilise_fallback(self):
        self.assertIsNone(generer_nom_dossier([regle([champ("bloc")])], self.contexte({"bloc": {"row": []}}))["nom_genere"])

    def test_regle_desactivee_ne_masque_pas_suivante(self):
        resultat = generer_nom_dossier([regle([texte("A")], actif=False), regle([texte("B")], 2)], self.contexte())
        self.assertEqual(resultat["nom_genere"], "B")

    def test_absence_de_regles_ou_toutes_incompletes(self):
        self.assertIsNone(generer_nom_dossier([], self.contexte())["nom_genere"])
        self.assertIsNone(generer_nom_dossier([regle([champ("absent")])], self.contexte())["nom_genere"])

    def test_demandeur_intermediaire_et_beneficiaire_distincts(self):
        contexte = self.contexte(contacts={
            "beneficiaire": {"nom": "Hoarau"}, "demandeur_intermediaire": {"nom": "Calu"},
        })
        resultat = generer_nom_dossier([regle([attribut("demandeur.nom"), texte(" / "), attribut("beneficiaire.nom")])], contexte)
        self.assertEqual(resultat["nom_genere"], "Calu / Hoarau")

    def test_personne_morale_sans_nom_prenom_passe_a_raison_sociale(self):
        resultat = generer_nom_dossier([
            regle([attribut("demandeur.prenom"), texte(" "), attribut("demandeur.nom")]),
            regle([attribut("demandeur.raison_sociale")], 2),
        ], self.contexte(contacts={"beneficiaire": {"raison_sociale": "Les Gîtes de Mafate"}}))
        self.assertEqual(resultat["nom_genere"], "Les Gîtes de Mafate")

    @override_settings(TIME_ZONE="Indian/Reunion")
    def test_format_date_locale_et_date_francaise(self):
        resultat = generer_nom_dossier([regle([attribut("dossier.date_depot", "date_heure")])], self.contexte())
        self.assertEqual(resultat["nom_genere"], "05/10/2026 04h00")
        element = champ("date")
        element["transformation"] = "date"
        self.assertEqual(generer_nom_dossier([regle([element])], self.contexte({"date": "20 juin 2026 07:00"}))["nom_genere"], "20/06/2026")

    def test_date_invalide_ignore_regle(self):
        element = champ("date")
        element["transformation"] = "date"
        self.assertIsNone(generer_nom_dossier([regle([element])], self.contexte({"date": "pas une date"}))["nom_genere"])

    def test_priorite_affichage_manuel_puis_genere_puis_standard(self):
        dossier = Dossier(nom_dossier="Standard", nom_dossier_genere="Généré", nom_dossier_plus_parlant="Manuel")
        self.assertEqual(dossier.nom_affiche, "Manuel")
        dossier.nom_dossier_plus_parlant = None
        self.assertEqual(dossier.nom_affiche, "Généré")
        dossier.nom_dossier_genere = None
        self.assertEqual(dossier.nom_affiche, "Standard")

    def test_template_noms_echappes(self):
        dossier = Dossier(nom_dossier="Standard", nom_dossier_genere="<script>test</script>")
        from django.template import Context, Template
        self.assertEqual(Template("{{ dossier.nom_affiche }}").render(Context({"dossier": dossier})), "&lt;script&gt;test&lt;/script&gt;")


class NommageValidationTests(SimpleTestCase):
    def setUp(self):
        self.field = SimpleNamespace(pk=12, nom="Lieu", id_ds="dn-field", id_champ_type=SimpleNamespace(type="text"))
        self.fields = patch("instruction.views.nom_dossier.Champ.objects.filter")
        self.mock_fields = self.fields.start()
        self.addCleanup(self.fields.stop)
        self.mock_fields.return_value.select_related.return_value = [self.field]

    def test_validation_resout_champ_id_ds_et_ordre(self):
        resultat = valider_regles_nommage({"regles": [regle([
            {"type": "champ_dn", "id_champ": 12}, texte(" - "), attribut("demandeur.nom"),
        ], 99)]}, object())
        self.assertEqual(resultat[0]["ordre"], 1)
        self.assertEqual(resultat[0]["elements"][0]["id_ds"], "dn-field")
        self.assertEqual(resultat[0]["elements"][1]["texte"], " - ")

    def test_champ_autre_demarche_rejete(self):
        with self.assertRaises(ValidationError):
            valider_regles_nommage({"regles": [regle([{"type": "champ_dn", "id_champ": 99}])]}, object())

    def test_champ_dm_restreint_aux_manifestations_sportives(self):
        demarche = SimpleNamespace(type="Manifestations sportives")
        champ_dm_modele = SimpleNamespace(name="activite", verbose_name="activité")
        with patch("instruction.views.nom_dossier.champs_dm_nommage_autorises", return_value=[champ_dm_modele]):
            resultat = valider_regles_nommage({"regles": [regle([champ_dm("activite")])]}, demarche)
        self.assertEqual(resultat[0]["elements"][0]["champ_dm"], "activite")
        with self.assertRaises(ValidationError):
            valider_regles_nommage({"regles": [regle([champ_dm("activite")])]}, SimpleNamespace(type="Autre"))

    def test_donnees_arbitraires_et_transformation_invalide_rejetees(self):
        for element in [attribut("dossier.emplacement"), attribut("demandeur.nom", "eval"),
                        attribut("demandeur.nom", {}), {"type": "attribut", "attribut": {}}, texte("")]:
            with self.subTest(element=element), self.assertRaises(ValidationError):
                valider_regles_nommage({"regles": [regle([element])]}, object())

    def test_regle_vide_ou_texte_seul_rejetee(self):
        for elements in [[], [texte("Nom identique pour tous")]]:
            with self.assertRaises(ValidationError):
                valider_regles_nommage({"regles": [regle(elements)]}, object())

    def test_configuration_vide_est_autorisee(self):
        self.assertEqual(valider_regles_nommage({"regles": []}, object()), [])

    def test_validation_personnalisee_accepte_remplacement_vide(self):
        element = personnalise(attribut("demandeur.nom"), [(" Hoarau ", "")], "ignorer_regle")
        resultat = valider_regles_nommage({"regles": [regle([element])]}, object())
        self.assertEqual(resultat[0]["elements"][0]["configuration_transformation"], {
            "correspondances": [{"valeur": "Hoarau", "texte": ""}], "sans_correspondance": "ignorer_regle",
        })

    def test_validation_personnalisee_rejette_configuration_invalide_ou_ambigue(self):
        configurations = [None, [], {}, {"correspondances": []},
            {"correspondances": [{"valeur": "Oui", "texte": "Mafate"}], "sans_correspondance": "eval"},
            {"correspondances": [{"valeur": "", "texte": "Mafate"}]},
            {"correspondances": [{"valeur": "Oui", "texte": None}]},
            {"correspondances": [{"valeur": "Oui", "texte": "Mafate"}, {"valeur": " TRUE ", "texte": "Autre"}]},
        ]
        for configuration in configurations:
            with self.subTest(configuration=configuration), self.assertRaises(ValidationError):
                element = {**attribut("demandeur.nom", "personnalisee"), "configuration_transformation": configuration}
                valider_regles_nommage({"regles": [regle([element])]}, object())

    def test_enregistrement_persiste_configuration_personnalisee(self):
        element = personnalise(attribut("demandeur.nom"), [("Hoarau", "HOARAU")])
        request = RequestFactory().post("/", data={"regles": [regle([element])]}, content_type="application/json")
        request.user = SimpleNamespace(is_authenticated=True, is_superuser=True)
        from autorisations.models.models_instruction import Demarche, DemarcheNomDossierRegle
        with patch("instruction.views.nom_dossier.get_object_or_404", return_value=Demarche(pk=1)), \
             patch("instruction.views.nom_dossier.Champ.objects.filter") as champs, \
             patch("instruction.views.nom_dossier.transaction.atomic"), \
             patch("instruction.views.nom_dossier.Demarche.objects.select_for_update"), \
             patch("instruction.views.nom_dossier.DemarcheNomDossierRegle.objects.filter"), \
             patch("instruction.views.nom_dossier.DemarcheNomDossierRegle.objects.bulk_create", return_value=[DemarcheNomDossierRegle(pk=2)]), \
             patch("instruction.views.nom_dossier.DemarcheNomDossierElement.objects.bulk_create") as elements:
            champs.return_value.select_related.return_value = []
            response = enregistrer_regles_nom_dossier(request, 1)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(elements.call_args.args[0][0].configuration_transformation, element["configuration_transformation"])

    def test_routes_reservees_aux_superutilisateurs(self):
        request = RequestFactory().post("/", data={}, content_type="application/json")
        request.user = SimpleNamespace(is_authenticated=True, is_superuser=False)
        for view in [enregistrer_regles_nom_dossier, previsualiser_nom_dossier, recalculer_noms_dossiers]:
            with self.subTest(view=view), self.assertRaises(PermissionDenied):
                view(request, 1)

    def test_autocompletion_ne_consulte_que_la_demarche_courante(self):
        request = RequestFactory().get("/?q=342")
        request.user = SimpleNamespace(is_authenticated=True, is_superuser=True)
        with patch("instruction.views.nom_dossier.get_object_or_404") as demarche, \
             patch("instruction.views.nom_dossier.Dossier.objects.filter") as dossiers:
            chaine = dossiers.return_value.annotate.return_value.filter.return_value.order_by.return_value
            chaine.values_list.return_value = [34215599, 34218888]
            resultat = autocomplete_numeros_dossiers(request, 123)
        self.assertEqual(json.loads(resultat.content), {"numeros": ["34215599", "34218888"]})
        dossiers.assert_called_once_with(id_demarche=demarche.return_value)

    def test_recalcul_modifie_seulement_champ_genere_y_compris_archive(self):
        dossier = Dossier(pk=1, numero=123, nom_dossier="Standard", nom_dossier_genere="Ancien", nom_dossier_plus_parlant="Manuel")
        request = RequestFactory().post("/", data={}, content_type="application/json")
        request.user = SimpleNamespace(is_authenticated=True, is_superuser=True)
        with patch("instruction.views.nom_dossier.get_object_or_404"), \
             patch("instruction.views.nom_dossier.DemarcheNomDossierRegle.objects.filter"), \
             patch("instruction.views.nom_dossier.compiler_regles_nommage", return_value=[]), \
             patch("instruction.views.nom_dossier.dossiers_avec_contexte_nommage") as queryset, \
             patch("instruction.views.nom_dossier.contexte_nommage_depuis_bdd", return_value={}), \
             patch("instruction.views.nom_dossier.Dossier.objects.filter"), \
             patch("instruction.views.nom_dossier.Dossier.objects.bulk_update") as update, \
             patch("instruction.views.nom_dossier.transaction.atomic"):
            queryset.return_value.iterator.return_value = iter([dossier])
            resultat = recalculer_noms_dossiers(request, 1)
            self.assertEqual(json.loads(resultat.content)["modifies"], 1)
            self.assertIsNone(dossier.nom_dossier_genere)
            self.assertEqual(dossier.nom_dossier_plus_parlant, "Manuel")
            self.assertEqual(dossier.nom_dossier, "Standard")
            self.assertEqual(update.call_args.args[1], ["nom_dossier_genere"])


class NommageSynchronisationTests(SimpleTestCase):
    def synchroniser(self, regles):
        dossier = {
            "dossier": {"id_ds": "dn-id", "numero": 123, "nom_dossier": "123_HOARAU_Denis_05-10"},
            "contacts_externes": {"beneficiaire": {"nom": "Hoarau", "prenom": "Denis"}},
            "dossier_champs": [], "dossier_interlocuteur": {},
            "dossier_document": {}, "messages": [], "demandes": [],
        }
        module = "synchronisation.synchro.sync_dossiers"
        with ExitStack() as stack:
            dossiers = stack.enter_context(patch(f"{module}.Dossier.objects.filter"))
            dossiers.return_value.exclude.return_value.values_list.return_value = []
            dates = stack.enter_context(patch(f"{module}.DemarcheDateActiviteChamp.objects.filter"))
            dates.return_value.order_by.return_value.select_related.return_value = []
            stack.enter_context(patch(f"{module}.DemarcheNomDossierRegle.objects.filter"))
            stack.enter_context(patch(f"{module}.compiler_regles_nommage", return_value=regles))
            for function in ["sync_doss", "sync_contacts_externes", "sync_dossier_interlocuteur", "sync_dossier_beneficiaire",
                             "sync_dossier_champs", "sync_dossier_document", "sync_messages", "sync_demandes"]:
                stack.enter_context(patch(f"{module}.{function}"))
            sync_dossiers([dossier], 123, un_seul_doss=True)
        return dossier["dossier"]

    def test_point_commun_alimente_champ_genere_et_garde_standard(self):
        dossier = self.synchroniser([regle([attribut("demandeur.prenom"), texte(" "), attribut("demandeur.nom", "majuscules")])])
        self.assertEqual(dossier["nom_dossier_genere"], "Denis HOARAU")
        self.assertEqual(dossier["nom_dossier"], "123_HOARAU_Denis_05-10")
        self.assertNotIn("nom_dossier_plus_parlant", dossier)

    def test_aucune_regle_vide_uniquement_nom_genere(self):
        dossier = self.synchroniser([])
        self.assertIsNone(dossier["nom_dossier_genere"])
        self.assertEqual(dossier["nom_dossier"], "123_HOARAU_Denis_05-10")

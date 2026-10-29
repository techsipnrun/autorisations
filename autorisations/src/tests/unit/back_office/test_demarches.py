"""Conservation des endpoints de configuration des démarches, avec ORM simulé."""
import json
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from autorisations.models.models_instruction import Champ, Demarche
from backoffice.views import demarches
from instruction.utils.colonnes_vue_ensemble import TABLEAU_EN_COURS, colonnes_vue_ensemble


class ConfigurationDemarchesTests(SimpleTestCase):
    def requete(self, donnees):
        request = RequestFactory().post("/back-office/demarche/7/", donnees)
        request.user = SimpleNamespace(is_authenticated=True, is_superuser=True)
        return request

    def test_dates_sources_et_priorites_conservees(self):
        donnees = {
            "champs[]": ["dm:date_debut_evenement", "dn:12"],
            "delai_alerte_jours": "30", "couleur_alerte": "#123456", "couleur_passee": "#654321",
        }
        with (
            patch.object(demarches, "get_object_or_404", return_value=Demarche(id=7)),
            patch.object(demarches.Champ, "objects") as champs,
            patch.object(demarches.DemarcheDateActiviteChamp, "objects") as sources,
            patch.object(demarches.DemarcheDateActiviteConfiguration, "objects") as configuration,
            patch.object(demarches.transaction, "atomic"),
        ):
            champs.filter.return_value.select_related.return_value = [Champ(id=12, nom="Début")]
            reponse = demarches.back_office_enregistrer_date_activite(self.requete(donnees), 7)
        self.assertEqual(reponse.status_code, 200)
        self.assertTrue(json.loads(reponse.content)["success"])
        lignes = sources.bulk_create.call_args.args[0]
        self.assertEqual([(l.ordre, l.source, l.id_champ_id) for l in lignes],
                         [(1, "dm", None), (2, "dn", 12)])
        self.assertEqual(lignes[0].champ_dm, "date_debut_evenement")
        self.assertEqual(configuration.update_or_create.call_args.kwargs["defaults"]["delai_alerte_jours"], 30)

    def test_date_configuration_invalide_refusee_avant_ecriture(self):
        for donnees in ({"delai_alerte_jours": "-1"}, {"delai_alerte_jours": "30", "couleur_alerte": "rouge"}):
            with (
                self.subTest(donnees=donnees),
                patch.object(demarches, "get_object_or_404", return_value=Demarche(id=7)),
                patch.object(demarches.DemarcheDateActiviteChamp, "objects") as sources,
            ):
                self.assertEqual(demarches.back_office_enregistrer_date_activite(self.requete(donnees), 7).status_code, 400)
                sources.bulk_create.assert_not_called()

    def test_tableau_conserve_ordre_visibilite_et_libelle(self):
        demarche = Demarche(id=7, type="Travaux")
        ordre = list(reversed(dict(colonnes_vue_ensemble(demarche.type)[TABLEAU_EN_COURS])))
        donnees = {"tableau": TABLEAU_EN_COURS, "ordre[]": ordre, "colonnes[]": [ordre[0]],
                   f"libelles[{ordre[0]}]": "Mon libellé"}
        with (
            patch.object(demarches, "get_object_or_404", return_value=demarche),
            patch.object(demarches.DemarcheColonneVueEnsemble, "objects") as colonnes,
            patch.object(demarches.transaction, "atomic"),
        ):
            reponse = demarches.back_office_enregistrer_personnalisation_tableau(self.requete(donnees), 7)
        self.assertEqual(reponse.status_code, 200)
        lignes = colonnes.bulk_create.call_args.args[0]
        self.assertEqual([ligne.colonne for ligne in lignes], ordre)
        self.assertEqual([ligne.ordre for ligne in lignes], list(range(1, len(ordre) + 1)))
        self.assertEqual([ligne.affiche for ligne in lignes], [True] + [False] * (len(ordre) - 1))
        self.assertEqual(lignes[0].libelle_personnalise, "Mon libellé")

    def test_tableau_inconnu_refuse_avant_ecriture(self):
        with (
            patch.object(demarches, "get_object_or_404", return_value=Demarche(id=7)),
            patch.object(demarches.DemarcheColonneVueEnsemble, "objects") as colonnes,
        ):
            reponse = demarches.back_office_enregistrer_personnalisation_tableau(
                self.requete({"tableau": "inconnu"}), 7)
        self.assertEqual(reponse.status_code, 400)
        colonnes.bulk_create.assert_not_called()

"""Sélection de plusieurs bénéficiaires/demandeurs, sans accès à la BDD."""
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.db.models import Q
from django.http import HttpResponse
from django.template.loader import get_template
from django.test import RequestFactory, SimpleTestCase

from instruction.views import requete


class RequeteContactsTests(SimpleTestCase):
    def rechercher(self, noms):
        request = RequestFactory().get("/requetes/dossiers/", {"nom": noms})
        request.user = SimpleNamespace(is_authenticated=True)
        querysets = {}
        with ExitStack() as patches:
            for model in (
                requete.Dossier, requete.DossierManifSportive,
                requete.DossierManifestationLiaison, requete.EtapeDossier,
                requete.Demarche, requete.Groupeinstructeur, requete.Avis,
            ):
                queryset = MagicMock()
                for methode in (
                    "all", "filter", "exclude", "none", "select_related",
                    "prefetch_related", "annotate", "order_by", "values", "values_list", "distinct",
                ):
                    getattr(queryset, methode).return_value = queryset
                querysets[model] = queryset
                patches.enter_context(patch.object(model, "objects", queryset))
            rendu = patches.enter_context(patch.object(requete, "render", return_value=HttpResponse()))
            reponse = requete.requete_dossiers(request)
        self.assertEqual(reponse.status_code, 200)
        return rendu.call_args.args[2], querysets

    def test_selection_multiple_union_dn_dm_et_dedoublonnage(self):
        contexte, querysets = self.rechercher([" HOARAU Denis ", "Association Mafate", "HOARAU Denis", ""])
        self.assertEqual(contexte["noms_selectionnes"], ["HOARAU Denis", "Association Mafate"])
        for model, nb_champs in ((requete.Dossier, 8), (requete.DossierManifSportive, 5)):
            with self.subTest(model=model.__name__):
                filtres = [
                    appel.args[0] for appel in querysets[model].filter.call_args_list
                    if appel.args and isinstance(appel.args[0], Q)
                ]
                self.assertEqual(len(filtres), 1)
                self.assertEqual(filtres[0].connector, Q.OR)
                self.assertEqual(len(filtres[0].children), 2 * nb_champs)
                self.assertEqual(
                    {valeur for champ, valeur in filtres[0].children},
                    {"HOARAU Denis", "Association Mafate"},
                )

    def test_ancien_lien_avec_un_seul_nom_reste_accepte(self):
        contexte, _ = self.rechercher("HOARAU Denis")
        self.assertEqual(contexte["noms_selectionnes"], ["HOARAU Denis"])

    def test_selection_du_raccourci_recherche_beneficiaire_et_intermediaire(self):
        _, querysets = self.rechercher("ONF")
        filtres = [appel.args[0] for appel in querysets[requete.Dossier].filter.call_args_list
                   if appel.args and isinstance(appel.args[0], Q)]
        for relation in ("dossierinterlocuteur__dossierbeneficiaire__id_beneficiaire",
                         "dossierinterlocuteur__id_demandeur_intermediaire"):
            self.assertIn((f"{relation}__raison_sociale_raccourci__iexact", "ONF"), filtres[0].children)

    def test_aucun_nom_selectionne_ne_filtre_pas_les_contacts(self):
        contexte, querysets = self.rechercher(["", " "])
        self.assertEqual(contexte["noms_selectionnes"], [])
        for model in (requete.Dossier, requete.DossierManifSportive):
            self.assertFalse(any(appel.args for appel in querysets[model].filter.call_args_list))

    def test_template_compile(self):
        get_template("instruction/requetes.html")

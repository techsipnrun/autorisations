from unittest.mock import patch

from django.test import SimpleTestCase

from autorisations.models.models_instruction import Dossier, Demarche
from autorisations.models.models_utilisateurs import ContactExterne
from document_generation.services.context import (
    BaliseNonResolueError, BaliseResolver, DocumentContextBuilder,
)
from document_generation.services.providers import BeneficiaireAmbiguError, ResolutionSource


class DocumentContextTests(SimpleTestCase):
    def setUp(self):
        self.dossier = Dossier(id=12, numero=30769307, nom_dossier=" Mission scientifique ")
        self.builder = DocumentContextBuilder()

    def contacts(self, *contacts):
        mocked = patch("document_generation.services.providers.ContactExterne.objects.filter")
        manager = mocked.start()
        self.addCleanup(mocked.stop)
        manager.return_value.order_by.return_value.distinct.return_value.__getitem__.return_value = list(contacts)
        return manager

    def test_contexte_complet_et_une_seule_lecture_beneficiaire(self):
        manager = self.contacts(ContactExterne(id=1, nom=" DUPONT ", prenom=" Jean "))
        self.assertEqual(self.builder.build(self.dossier), {
            "dossier": {"numero": 30769307, "nom": "Mission scientifique", "commune": None},
            "beneficiaire": {"nom": "DUPONT", "prenom": "Jean", "nom_complet": "Jean DUPONT"},
        })
        manager.assert_called_once_with(
            dossierbeneficiaire__id_dossier_interlocuteur__id_dossier=self.dossier,
        )

    def test_selection_dossier_uniquement_ne_lit_pas_les_contacts(self):
        self.assertEqual(self.builder.build(self.dossier, ["dossier.numero"]), {
            "dossier": {"numero": 30769307},
        })

    def test_commune_lue_dans_le_formulaire_de_la_demarche_test(self):
        self.dossier.id_demarche = Demarche(id=14, type="Test")
        with patch("document_generation.services.providers.Champ.objects.filter") as fields, patch(
            "document_generation.services.providers.DossierChamp.objects.filter"
        ) as answers:
            fields.return_value.order_by.return_value.values_list.return_value.__getitem__.return_value = [42]
            answers.return_value.order_by.return_value.values_list.return_value.first.return_value = " Saint-Paul "
            result = self.builder.build(self.dossier, ["dossier.commune"])
        self.assertEqual(result, {"dossier": {"commune": "Saint-Paul"}})
        fields.assert_called_once_with(id_demarche_id=14, nom__iexact="Commune")
        answers.assert_called_once_with(id_dossier=self.dossier, id_champ_id=42)

    def test_commune_absente_et_champ_ambigu(self):
        self.dossier.id_demarche = Demarche(id=14, type="Test")
        with patch("document_generation.services.providers.Champ.objects.filter") as fields:
            ids = fields.return_value.order_by.return_value.values_list.return_value.__getitem__
            ids.return_value = []
            self.assertEqual(self.builder.build(self.dossier, ["dossier.commune"]), {"dossier": {"commune": None}})
            ids.return_value = [42, 43]
            with self.assertRaisesRegex(ValueError, "Plusieurs champs Commune"):
                self.builder.build(self.dossier, ["dossier.commune"])

    def test_commune_pas_lue_pour_une_autre_demarche(self):
        self.dossier.id_demarche = Demarche(id=15, type="Travaux")
        with patch("document_generation.services.providers.Champ.objects.filter") as fields:
            self.assertEqual(self.builder.build(self.dossier, ["dossier.commune"]), {"dossier": {"commune": None}})
        fields.assert_not_called()

    def test_beneficiaire_absent(self):
        self.contacts()
        self.assertEqual(self.builder.build(self.dossier)["beneficiaire"], {
            "nom": None, "prenom": None, "nom_complet": None,
        })

    def test_identite_partielle_ou_vide_et_casse_conservee(self):
        for nom, prenom, attendu in (("Dupont", None, "Dupont"), (" ", "Jean", "Jean"), (None, " ", None)):
            with self.subTest(nom=nom, prenom=prenom):
                source = ResolutionSource(self.dossier)
                source.beneficiaire = ContactExterne(nom=nom, prenom=prenom)
                self.assertEqual(BaliseResolver().resolve("beneficiaire.nom_complet", source), attendu)

    def test_plusieurs_beneficiaires_distincts_sont_ambigus(self):
        self.contacts(ContactExterne(id=1), ContactExterne(id=2))
        with self.assertRaises(BeneficiaireAmbiguError):
            self.builder.build(self.dossier)

    def test_erreur_provider_non_masquee(self):
        with patch("document_generation.services.providers.ContactExterne.objects.filter", side_effect=RuntimeError("SQL")):
            with self.assertRaisesRegex(RuntimeError, "SQL"):
                self.builder.build(self.dossier)

    def test_aucun_cache_partage_entre_dossiers(self):
        manager = self.contacts(ContactExterne(nom="DUPONT", prenom="Jean"))
        self.builder.build(self.dossier)
        self.builder.build(Dossier(id=13, numero=42, nom_dossier="Autre"))
        self.assertEqual(manager.call_count, 2)

    def test_code_inconnu_rejete_avant_tout_acces_sql(self):
        with self.assertRaises(BaliseNonResolueError):
            self.builder.build(self.dossier, ["beneficiaire.nom", "inconnu.code"])

    def test_dossier_non_enregistre_refuse(self):
        with self.assertRaisesRegex(ValueError, "enregistré"):
            self.builder.build(Dossier(numero=42), ["dossier.numero"])

    def test_provider_supplementaire_sans_modifier_le_builder(self):
        resolver = BaliseResolver({"projet.titre": lambda source: source.dossier.nom_dossier.strip()})
        self.assertEqual(DocumentContextBuilder(resolver).build(self.dossier), {
            "projet": {"titre": "Mission scientifique"},
        })

    def test_collision_de_codes_refusee(self):
        resolver = BaliseResolver({"projet": lambda source: 1, "projet.titre": lambda source: "Titre"})
        with self.assertRaisesRegex(ValueError, "Collision"):
            DocumentContextBuilder(resolver).build(self.dossier)

    def test_selection_vide_et_codes_dupliques(self):
        self.assertEqual(self.builder.build(self.dossier, []), {})
        self.assertEqual(self.builder.build(self.dossier, ["dossier.numero"] * 2), {
            "dossier": {"numero": 30769307},
        })

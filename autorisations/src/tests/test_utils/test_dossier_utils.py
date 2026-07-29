from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from instruction.utils.dossier_utils import (
    build_champs_prepares,
    get_chemin_complet_dossier,
    has_geojson_geometry,
)


def creer_champ(type_champ, nom, valeur=None, **attributs):
    """Construit un champ minimal sans dépendre de la base de données."""
    valeurs = {
        "id": attributs.pop("id", 1),
        "id_champ": SimpleNamespace(
            id_champ_type=SimpleNamespace(type=type_champ),
            nom=nom,
        ),
        "valeur": valeur,
        "geometrie": None,
        "geometrie_modif": None,
        "id_document": None,
    }
    valeurs.update(attributs)
    return SimpleNamespace(**valeurs)


def creer_dossier(*champs, numero=30769307, emplacement="dossiers/30769307"):
    gestionnaire = MagicMock()
    gestionnaire.select_related.return_value.order_by.return_value = list(champs)
    return SimpleNamespace(
        numero=numero,
        emplacement=emplacement,
        dossierchamp_set=gestionnaire,
    )


class HasGeojsonGeometryTests(SimpleTestCase):
    def test_absence_de_geometrie(self):
        valeurs_vides = [
            None,
            {},
            {"type": "FeatureCollection", "features": []},
            {"type": "Feature", "geometry": None},
            {"type": "Point", "coordinates": []},
        ]

        for valeur in valeurs_vides:
            with self.subTest(valeur=valeur):
                self.assertFalse(has_geojson_geometry(valeur))

    def test_geometrie_directe(self):
        self.assertTrue(
            has_geojson_geometry({"type": "Point", "coordinates": [55.5, -21.1]})
        )

    def test_geometrie_dans_feature_collection(self):
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "geometry": None},
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[55.1, -21.1], [55.2, -21.2]],
                    },
                },
            ],
        }

        self.assertTrue(has_geojson_geometry(geojson))

    def test_geometry_collection(self):
        geojson = {
            "type": "GeometryCollection",
            "geometries": [
                {"type": "Point", "coordinates": []},
                {"type": "Point", "coordinates": [55.5, -21.1]},
            ],
        }

        self.assertTrue(has_geojson_geometry(geojson))


class GetCheminCompletDossierTests(SimpleTestCase):
    @patch("instruction.utils.dossier_utils._normalize_unc_path")
    @patch.dict("os.environ", {"NAS_ROOT": "//nas/autorisations"}, clear=False)
    def test_ajoute_la_racine_nas_a_un_chemin_relatif(self, normaliser):
        normaliser.return_value = "chemin-normalise"

        resultat = get_chemin_complet_dossier(
            SimpleNamespace(emplacement="dossiers/30769307")
        )

        self.assertEqual(resultat, "chemin-normalise")
        chemin_recu = normaliser.call_args.args[0].replace("\\", "/")
        self.assertEqual(chemin_recu, "//nas/autorisations/dossiers/30769307")

    @patch("instruction.utils.dossier_utils._normalize_unc_path")
    @patch.dict("os.environ", {"NAS_ROOT": "//nas/autorisations"}, clear=False)
    def test_ne_duplique_pas_une_racine_deja_presente(self, normaliser):
        normaliser.return_value = "chemin-normalise"
        chemin = "//nas/autorisations/dossiers/30769307"

        get_chemin_complet_dossier(SimpleNamespace(emplacement=chemin))

        normaliser.assert_called_once_with(chemin)


class BuildChampsPreparesTests(SimpleTestCase):
    def test_reference_alphanumerique_ne_declenche_pas_de_recherche_numerique(self):
        champ = creer_champ(
            "text", "Numéro du dossier précédent", "2025-ad-852"
        )
        dossier = creer_dossier(champ)

        with patch("instruction.utils.dossier_utils.Dossier.objects.filter") as filtre:
            champs_prepares, nb_cartes = build_champs_prepares(dossier)

        filtre.assert_not_called()
        self.assertEqual(nb_cartes, 0)
        self.assertFalse(champs_prepares[0]["est_dossier_actuel"])
        self.assertFalse(champs_prepares[0]["dossier_precedent_existe"])

    def test_reference_numerique_existante(self):
        champ = creer_champ("text", "Numéro du dossier précédent :", "123456")
        dossier = creer_dossier(champ)

        with patch("instruction.utils.dossier_utils.Dossier.objects.filter") as filtre:
            filtre.return_value.exists.return_value = True
            champs_prepares, _ = build_champs_prepares(dossier)

        filtre.assert_called_once_with(numero="123456")
        self.assertTrue(champs_prepares[0]["dossier_precedent_existe"])

    def test_reference_vers_le_dossier_actuel(self):
        champ = creer_champ("text", "Numéro du dossier précédent", "30769307")
        dossier = creer_dossier(champ)

        with patch("instruction.utils.dossier_utils.Dossier.objects.filter") as filtre:
            champs_prepares, _ = build_champs_prepares(dossier)

        filtre.assert_not_called()
        self.assertTrue(champs_prepares[0]["est_dossier_actuel"])
        self.assertFalse(champs_prepares[0]["dossier_precedent_existe"])

    def test_normalise_les_champs_oui_non(self):
        dossier = creer_dossier(
            creer_champ("yes_no", "Question vraie", " TRUE "),
            creer_champ("yes_no", "Question fausse", "false"),
            creer_champ("yes_no", "Question vide", None),
        )

        champs_prepares, _ = build_champs_prepares(dossier)

        self.assertEqual(
            [champ["valeur"] for champ in champs_prepares],
            ["Oui", "Non", "Non renseigné"],
        )

    def test_ignore_explication_et_attestations(self):
        dossier = creer_dossier(
            creer_champ("explication", "Une aide", "Texte explicatif"),
            creer_champ("checkbox", "Je certifie être habilité", "true"),
            creer_champ("checkbox", "J'atteste sur l'honneur", "true"),
            creer_champ("checkbox", "Option utile", "true"),
        )

        champs_prepares, _ = build_champs_prepares(dossier)

        self.assertEqual(len(champs_prepares), 1)
        self.assertEqual(champs_prepares[0]["nom"], "Option utile")

    def test_carte_comptee_quand_geometrie_presente(self):
        geometrie = {"type": "Point", "coordinates": [55.5, -21.1]}
        dossier = creer_dossier(
            creer_champ("carte", "Localisation", geometrie=geometrie)
        )

        champs_prepares, nb_cartes = build_champs_prepares(dossier)

        self.assertEqual(nb_cartes, 1)
        self.assertFalse(champs_prepares[0]["geometrie_a_saisir"])
        self.assertIn('"Point"', champs_prepares[0]["geojson"])

    def test_geometrie_modifiee_prioritaire_sur_geometrie_initiale(self):
        initiale = {"type": "Point", "coordinates": [1, 2]}
        modifiee = {"type": "Point", "coordinates": [3, 4]}
        dossier = creer_dossier(
            creer_champ(
                "carte",
                "Localisation",
                geometrie=initiale,
                geometrie_modif=modifiee,
            )
        )

        champs_prepares, nb_cartes = build_champs_prepares(dossier)

        self.assertEqual(nb_cartes, 1)
        self.assertIn("[3, 4]", champs_prepares[0]["geojson"])
        self.assertNotIn("[1, 2]", champs_prepares[0]["geojson"])

    def test_carte_vide_doit_etre_saisie(self):
        dossier = creer_dossier(creer_champ("carte", "Localisation"))

        champs_prepares, nb_cartes = build_champs_prepares(dossier)

        self.assertEqual(nb_cartes, 0)
        self.assertTrue(champs_prepares[0]["geometrie_a_saisir"])
        self.assertEqual(champs_prepares[0]["geojson"], "{}")

    def test_plan_de_vol_fourni_en_piece_jointe_doit_etre_cartographie(self):
        dossier = creer_dossier(
            creer_champ(
                "drop_down_list",
                (
                    "Choix de la méthode pour localiser le plan de vol "
                    "(du point de décollage jusqu’au point d’atterrissage)"
                ),
                "Fournir une pièce justificative",
            )
        )

        champs_prepares, _ = build_champs_prepares(dossier)

        self.assertEqual(champs_prepares[0]["geometrie_a_saisir"], "oui")
        self.assertEqual(champs_prepares[0]["geojson"], "{}")

    def test_plan_de_vol_saisi_dans_le_module_ne_demande_pas_de_cartographie(self):
        dossier = creer_dossier(
            creer_champ(
                "drop_down_list",
                (
                    "Choix de la méthode pour localiser le plan de vol "
                    "(du point de décollage jusqu’au point d’atterrissage)"
                ),
                "Remplir le module de cartographie",
            )
        )

        champs_prepares, _ = build_champs_prepares(dossier)

        self.assertEqual(
            champs_prepares[0]["geometrie_a_saisir"],
            "non pas concerné",
        )

    def test_section_et_piece_justificative(self):
        document = SimpleNamespace(
            emplacement="/pieces/",
            url_ds="https://example.test/document",
            titre="autorisation.pdf",
        )
        dossier = creer_dossier(
            creer_champ("header_section", "Informations générales :"),
            creer_champ(
                "piece_justificative",
                "Autorisation",
                id_document=document,
            ),
        )

        champs_prepares, _ = build_champs_prepares(dossier)

        self.assertEqual(
            champs_prepares[0],
            {"type": "header", "titre": "Informations générales"},
        )
        self.assertEqual(champs_prepares[1]["titre_doc"], "autorisation.pdf")
        self.assertEqual(champs_prepares[1]["emplacement_doc"], "/pieces/")

    def test_piece_justificative_sans_document_signale_erreur(self):
        dossier = creer_dossier(
            creer_champ("piece_justificative", "Autorisation")
        )

        champs_prepares, _ = build_champs_prepares(dossier)

        self.assertEqual(champs_prepares[0]["titre_doc"], "ERROR PARSING URL DS")

    def test_repetition_convertit_les_blocs(self):
        valeur = repr(
            {
                "bloc-1": [
                    {"nom": "Espèce", "valeur": "Pétrel"},
                    {"nom": "Nombre", "valeur": "2"},
                ]
            }
        )
        dossier = creer_dossier(
            creer_champ("repetition", "Observations", valeur)
        )

        champs_prepares, _ = build_champs_prepares(dossier)

        self.assertEqual(
            champs_prepares[0]["valeur"],
            [[
                {"nom": "Espèce", "valeur": "Pétrel"},
                {"nom": "Nombre", "valeur": "2"},
            ]],
        )

    def test_repetition_invalide_ne_casse_pas_affichage(self):
        dossier = creer_dossier(
            creer_champ("repetition", "Observations", "{valeur invalide")
        )

        champs_prepares, _ = build_champs_prepares(dossier)

        self.assertEqual(champs_prepares[0]["valeur"], "Non renseigné")

    def test_champ_texte_vide_affiche_non_renseigne(self):
        dossier = creer_dossier(creer_champ("text", "Commentaire :", None))

        champs_prepares, _ = build_champs_prepares(dossier)

        self.assertEqual(
            champs_prepares[0],
            {
                "type": "champ",
                "nom": "Commentaire",
                "valeur": "Non renseigné",
            },
        )

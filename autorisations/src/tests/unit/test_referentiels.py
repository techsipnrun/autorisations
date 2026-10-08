"""Validité de la fixture de références, sans chargement ni accès à la BDD."""
import json
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core import serializers
from django.test import SimpleTestCase


class ReferentielsTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        chemin = Path(settings.BASE_DIR) / "autorisations/fixtures/referentiels.json"
        cls.texte = chemin.read_text(encoding="utf-8")
        cls.entrees = json.loads(cls.texte)

    def test_utf8_et_accents_lisibles(self):
        self.assertFalse(self.texte.startswith("\ufeff"))
        self.assertNotIn("\ufffd", self.texte)
        for libelle in ("Manœuvres militaires", "En attente de compléments", "Formulaire modifié"):
            with self.subTest(libelle=libelle):
                self.assertIn(libelle, self.texte)

    def test_identifiants_sans_doublon(self):
        identifiants = [(entree["model"], entree["pk"]) for entree in self.entrees]
        self.assertEqual(len(identifiants), len(set(identifiants)))

    def test_champs_conformes_aux_modeles_actuels(self):
        for entree in self.entrees:
            with self.subTest(model=entree["model"], pk=entree["pk"]):
                modele = apps.get_model(entree["model"])
                champs = {
                    champ.name for champ in modele._meta.concrete_fields
                    if champ.serialize and not champ.primary_key
                }
                self.assertEqual(set(entree["fields"]), champs)
        self.assertEqual(len(list(serializers.deserialize("json", self.texte))), len(self.entrees))

    def test_etat_synchronisation_reste_neutre(self):
        etats = [entree for entree in self.entrees if entree["model"] == "autorisations.synchronisationetat"]
        self.assertEqual(len(etats), 1)
        self.assertEqual(etats[0]["fields"], {
            "en_cours": False, "date_maj": None,
            "date_derniere_tentative": None, "dernier_statut": "inconnu",
        })

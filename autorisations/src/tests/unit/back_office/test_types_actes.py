"""Configuration des types d'actes dans le Back Office."""
import importlib
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.core.exceptions import PermissionDenied
from django.db.migrations.loader import MigrationLoader
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase

from autorisations.models.models_documents import Document, DocumentNature
from backoffice.forms.types_actes import TypeActeForm
from backoffice.views import types_actes


class ConfigurationTypesActesTests(SimpleTestCase):
    def donnees(self, **changes):
        return {
            "nature": "Nouveau type", "actif": "true",
            "mode_numerotation": "automatique",
            "prefixe_numero": "TEST/", "prefixe_nom_fichier": "TEST-",
            "circuit_signature": "direction", "rapport_ca_obligatoire": "false",
            "mode_publication_raa": "non_requise", "autorise_dm": "false", **changes,
        }

    def formulaire(self, **changes):
        form = TypeActeForm(self.donnees(**changes), instance=DocumentNature(est_acte=True))
        with patch.object(DocumentNature, "validate_unique"):
            form.is_valid()
        return form

    def test_configuration_complete_et_booleens_non(self):
        form = self.formulaire()
        self.assertFalse(form.errors)
        self.assertFalse(form.cleaned_data["autorise_dm"])
        self.assertFalse(form.cleaned_data["rapport_ca_obligatoire"])
        self.assertTrue(form.instance.est_acte)

    def test_champs_requis_et_choix_invalides_refuses(self):
        for nom in self.donnees():
            if nom == "prefixe_numero":
                continue
            with self.subTest(nom=nom):
                self.assertIn(nom, self.formulaire(**{nom: ""}).errors)
        for nom in ("circuit_signature", "mode_publication_raa", "autorise_dm"):
            with self.subTest(nom=nom):
                self.assertIn(nom, self.formulaire(**{nom: "inconnu"}).errors)
        self.assertIn("prefixe_nom_fichier", self.formulaire(prefixe_nom_fichier="CA/").errors)

    def test_rapport_ca_reference_obligatoire(self):
        with patch.object(DocumentNature, "objects") as objets:
            objets.filter.return_value.values_list.return_value = ["Projet Rapport CA"]
            self.assertIn("__all__", self.formulaire(rapport_ca_obligatoire="true").errors)
            objets.filter.return_value.values_list.return_value = ["Projet Rapport CA", "Rapport CA"]
            self.assertFalse(self.formulaire(rapport_ca_obligatoire="true").errors)

    def test_formulaire_affiche_non_pour_parametres_desactives(self):
        form = TypeActeForm(instance=DocumentNature(est_acte=True, actif=False))
        for nom in ("actif", "rapport_ca_obligatoire", "autorise_dm"):
            self.assertIn('value="false" selected', str(form[nom]))

    def test_aides_en_infobulles_et_ordre_absent_du_formulaire(self):
        form = TypeActeForm(instance=DocumentNature(est_acte=True))
        self.assertEqual(form.fields["actif"].label, "Actif")
        html = render_to_string("backoffice/type_acte_form.html", {"form": form, "type_id": 0, "prochain_numero": "2026-1000"})
        self.assertNotIn('name="ordre_affichage"', html)
        self.assertIn('role="tooltip"', html)
        self.assertIn('class="back-office-acte-help"', html)
        self.assertIn("les actes existants restent accessibles", html)
        self.assertIn('data-next-number="2026-1000"', html)

    def test_aide_raa_trois_lignes_et_apercu_replie_par_defaut(self):
        form = TypeActeForm(instance=DocumentNature(est_acte=True))
        self.assertEqual(len(form.fields["mode_publication_raa"].help_text.splitlines()), 3)
        html = render_to_string("backoffice/type_acte_form.html", {"form": form, "type_id": 0, "prochain_numero": "2026-1000"})
        self.assertIn('<details class="back-office-acte-number-preview">', html)
        self.assertIn('<summary><strong data-type-acte-preview>', html)
        self.assertNotIn('<details class="back-office-acte-number-preview" open', html)

    def test_apercus_tous_types_en_une_agregation_sans_reservation(self):
        natures = [DocumentNature(id=1, nature="Arrêté", est_acte=True), DocumentNature(id=2, nature="Avis", est_acte=True)]
        with patch.object(DocumentNature, "objects") as types_manager, patch.object(Document, "objects") as docs_manager:
            types_manager.filter.return_value.order_by.return_value = natures
            docs_manager.filter.return_value.values.return_value.annotate.return_value = [
                {"id_nature_id": 1, "dernier_numero": f"{date.today().year}-1043"},
            ]
            contexte = types_actes.contexte_types_actes()
            self.assertEqual([ligne["prochain_numero"] for ligne in contexte["formulaires_types_actes"]], [f"{date.today().year}-1044", f"{date.today().year}-1000"])
            self.assertEqual(contexte["premier_numero_acte"], f"{date.today().year}-1000")
            docs_manager.filter.assert_called_once_with(id_nature_id__in=[1, 2], numero__startswith=str(date.today().year))
            docs_manager.filter.return_value.values.assert_called_once_with("id_nature_id")
            docs_manager.filter.return_value.values.return_value.annotate.assert_called_once()
            docs_manager.create.assert_not_called()
            docs_manager.update.assert_not_called()

    def test_creation_reservee_superutilisateur(self):
        request = RequestFactory().post("/back-office/types-actes/0/", self.donnees())
        request.user = SimpleNamespace(is_authenticated=True, is_superuser=False)
        with self.assertRaises(PermissionDenied), patch.object(types_actes, "TypeActeForm") as form:
            types_actes.enregistrer_type_acte(request, 0)
        form.assert_not_called()

    def test_creation_enregistre_une_nature_acte(self):
        request = RequestFactory().post("/back-office/types-actes/0/", self.donnees())
        request.user = SimpleNamespace(is_authenticated=True, is_superuser=True)
        with patch.object(DocumentNature, "validate_unique"), patch.object(DocumentNature, "save") as save, patch.object(types_actes.transaction, "atomic"), patch.object(types_actes, "_types_actes_verrouilles", return_value=[]):
            response = types_actes.enregistrer_type_acte(request, 0)
        self.assertEqual(response.status_code, 200)
        save.assert_called_once()

    def test_nouveau_type_ajoute_en_derniere_position(self):
        request = RequestFactory().post("/test", self.donnees(ordre_affichage="1"))
        request.user = SimpleNamespace(is_authenticated=True, is_superuser=True)
        existants = [DocumentNature(id=1, ordre_affichage=10), DocumentNature(id=2, ordre_affichage=20)]
        with patch.object(DocumentNature, "validate_unique"), patch.object(DocumentNature, "save", autospec=True) as save, patch.object(types_actes.transaction, "atomic"), patch.object(types_actes, "_types_actes_verrouilles", return_value=existants), patch.object(DocumentNature.objects, "bulk_update") as update:
            response = types_actes.enregistrer_type_acte(request, 0)
        self.assertEqual(response.status_code, 200)
        self.assertEqual([nature.ordre_affichage for nature in existants], [1, 2])
        update.assert_called_once_with(existants, ["ordre_affichage"])
        save.assert_called_once()
        self.assertEqual(save.call_args.args[0].ordre_affichage, 3)
        # Le POST ne peut pas imposer un classement : ce champ n'est plus éditable.
        form = TypeActeForm(self.donnees(ordre_affichage="1"), instance=DocumentNature(est_acte=True))
        with patch.object(DocumentNature, "validate_unique"):
            self.assertTrue(form.is_valid())
        self.assertNotIn("ordre_affichage", form.cleaned_data)

    def test_modification_formulaire_conserve_le_classement(self):
        nature = DocumentNature(id=90, est_acte=True, ordre_affichage=3)
        request = RequestFactory().post("/test", self.donnees(ordre_affichage="1"))
        request.user = SimpleNamespace(is_authenticated=True, is_superuser=True)
        with patch.object(types_actes, "get_object_or_404", return_value=nature), patch.object(DocumentNature, "validate_unique"), patch.object(DocumentNature, "save"), patch.object(types_actes.transaction, "atomic"):
            response = types_actes.enregistrer_type_acte(request, 90)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(nature.ordre_affichage, 3)

    def test_deplacement_normalise_et_renvoie_ordre_persistant(self):
        for direction, attendu in (("monter", [2, 1, 3]), ("descendre", [1, 3, 2])):
            with self.subTest(direction=direction):
                natures = [DocumentNature(id=index, ordre_affichage=index * 10) for index in (1, 2, 3)]
                request = RequestFactory().post("/test", {"direction": direction})
                request.user = SimpleNamespace(is_authenticated=True, is_superuser=True)
                with patch.object(types_actes, "_types_actes_verrouilles", return_value=natures), patch.object(types_actes.transaction, "atomic"), patch.object(DocumentNature.objects, "bulk_update") as update:
                    response = types_actes.deplacer_type_acte(request, 2)
                self.assertEqual(json.loads(response.content)["ordre"], attendu)
                self.assertEqual([nature.ordre_affichage for nature in update.call_args.args[0]], [1, 2, 3])

    def test_deplacement_interdit_aux_non_superutilisateurs_et_direction_invalide(self):
        request = RequestFactory().post("/test", {"direction": "invalide"})
        request.user = SimpleNamespace(is_authenticated=True, is_superuser=False)
        with patch.object(types_actes, "_types_actes_verrouilles") as verrouiller:
            with self.assertRaises(PermissionDenied):
                types_actes.deplacer_type_acte(request, 1)
            request.user.is_superuser = True
            self.assertEqual(types_actes.deplacer_type_acte(request, 1).status_code, 400)
        verrouiller.assert_not_called()

    def test_deplacement_en_limite_sans_changement_et_type_absent_refuse(self):
        nature = DocumentNature(id=1, ordre_affichage=1)
        request = RequestFactory().post("/test", {"direction": "monter"})
        request.user = SimpleNamespace(is_authenticated=True, is_superuser=True)
        with patch.object(types_actes, "_types_actes_verrouilles", return_value=[nature]), patch.object(types_actes.transaction, "atomic"), patch.object(DocumentNature.objects, "bulk_update") as update:
            response = types_actes.deplacer_type_acte(request, 1)
            self.assertEqual(json.loads(response.content)["ordre"], [1])
            with self.assertRaises(types_actes.Http404):
                types_actes.deplacer_type_acte(request, 2)
        update.assert_not_called()

    def test_template_formulaire_requis_et_identifiants_uniques(self):
        form = TypeActeForm(instance=DocumentNature(est_acte=True), auto_id="nouveau-acte-%s")
        html = render_to_string("backoffice/type_acte_form.html", {"form": form, "type_id": 0})
        self.assertIn('id="nouveau-acte-prefixe_numero"', str(form["prefixe_numero"]))
        self.assertNotIn('required', str(form["prefixe_numero"]))
        self.assertIn('name="mode_publication_raa"', html)
        self.assertIn("non_requise", html)

    def test_prefixe_facultatif_en_modes_automatique_et_manuel(self):
        for mode in ("automatique", "manuelle"):
            with self.subTest(mode=mode):
                form = self.formulaire(mode_numerotation=mode, prefixe_numero="")
                self.assertFalse(form.errors)
                document = Document(id_nature=form.instance, numero="2026-1000", numero_reference="2025-018/PF")
                self.assertEqual(document.numero_affiche, "2025-018/PF" if mode == "manuelle" else "2026-1000")

    def test_migration_script_et_modeles_coherents(self):
        migration = importlib.import_module("autorisations.migrations.0038_types_actes_configurables")
        state = MigrationLoader(None, ignore_no_migrations=True).project_state([("autorisations", "0038_types_actes_configurables")])
        for nom in ("est_acte", "actif", "ordre_affichage", "circuit_signature", "rapport_ca_obligatoire", "mode_publication_raa", "autorise_dm"):
            self.assertEqual(DocumentNature._meta.get_field(nom).deconstruct()[1:], state.models["autorisations", "documentnature"].fields[nom].deconstruct()[1:])
        sql = (Path(__file__).resolve().parents[5] / "sql/0038_types_actes_configurables.sql").read_text(encoding="utf-8")
        self.assertIn(migration.SQL.strip(), sql)

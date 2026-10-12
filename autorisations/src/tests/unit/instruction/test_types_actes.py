"""Types d'actes configurables, sans appel réel aux BDD, NAS, mails ou API."""
import importlib
import json
from contextlib import ExitStack
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.core.exceptions import PermissionDenied
from django.db import models
from django.db.migrations.loader import MigrationLoader
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase

from autorisations.models.models_documents import Document, DocumentNature, DocumentStatut
from instruction.forms_types_actes import TypeActeForm
from instruction.utils import document_utils
from instruction.views import changement_etape, types_actes


class ConfigurationTypesActesTests(SimpleTestCase):
    def donnees(self, **changes):
        return {
            "nature": "Nouveau type", "actif": "true",
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
        html = render_to_string("instruction/refacto/type_acte_form.html", {"form": form, "type_id": 0, "prochain_numero": "2026-1000"})
        self.assertNotIn('name="ordre_affichage"', html)
        self.assertIn('role="tooltip"', html)
        self.assertIn('class="back-office-acte-help"', html)
        self.assertIn("les actes existants restent accessibles", html)
        self.assertIn('data-next-number="2026-1000"', html)

    def test_aide_raa_trois_lignes_et_apercu_replie_par_defaut(self):
        form = TypeActeForm(instance=DocumentNature(est_acte=True))
        self.assertEqual(len(form.fields["mode_publication_raa"].help_text.splitlines()), 3)
        html = render_to_string("instruction/refacto/type_acte_form.html", {"form": form, "type_id": 0, "prochain_numero": "2026-1000"})
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
        html = render_to_string("instruction/refacto/type_acte_form.html", {"form": form, "type_id": 0})
        self.assertRegex(html, r'<input[^>]*name="prefixe_numero"[^>]* required[^>]*id="nouveau-acte-prefixe_numero"')
        self.assertIn('name="mode_publication_raa"', html)
        self.assertIn("non_requise", html)

    def test_migration_script_et_modeles_coherents(self):
        migration = importlib.import_module("autorisations.migrations.0038_types_actes_configurables")
        state = MigrationLoader(None, ignore_no_migrations=True).project_state([("autorisations", "0038_types_actes_configurables")])
        for nom in ("est_acte", "actif", "ordre_affichage", "circuit_signature", "rapport_ca_obligatoire", "mode_publication_raa", "autorise_dm"):
            self.assertEqual(DocumentNature._meta.get_field(nom).deconstruct()[1:], state.models["autorisations", "documentnature"].fields[nom].deconstruct()[1:])
        sql = (Path(__file__).resolve().parents[5] / "sql/0038_types_actes_configurables.sql").read_text(encoding="utf-8")
        self.assertIn(migration.SQL.strip(), sql)


class MoteurTypesActesTests(SimpleTestCase):
    def test_calcul_prochain_numero_partage_avec_attribution(self):
        for dernier, attendu in ((None, "2026-1000"), ("2026-1043", "2026-1044"), ("2026-0099", "2026-0100"), ("2026-invalide", "2026-1000")):
            with self.subTest(dernier=dernier):
                self.assertEqual(Document.prochain_numero(dernier, 2026), attendu)

    def test_blocs_documentaires_independants_du_libelle(self):
        for signature, rapport, publication in (("direction", True, "non_requise"), ("ca", False, "manuelle")):
            with self.subTest(signature=signature), patch.object(document_utils, "DossierDocument") as liaisons, patch.object(document_utils, "Document") as documents, patch.object(document_utils, "get_types_actes_selectionnables"), patch.object(document_utils.smbclient.path, "exists", return_value=False), patch.dict("os.environ", {"NAS_ROOT": "test-nas"}):
                nature = DocumentNature(est_acte=True, nature="Type inédit", circuit_signature=signature, rapport_ca_obligatoire=rapport, mode_publication_raa=publication)
                document = Document(id_nature=nature, emplacement="test/Work/", titre="projet.docx")
                document.id_statut = DocumentStatut(statut="À signer")
                liaisons.objects.filter.return_value.select_related.return_value = [SimpleNamespace(id_document=document)]
                documents.objects.filter.return_value.values_list.return_value = []
                contexte = document_utils.build_documents_for_dossier(SimpleNamespace(emplacement="test", numero=1))
                self.assertEqual(contexte["signature_ca"], signature == "ca")
                self.assertEqual(contexte["rapport_ca_requis"], rapport)
                self.assertEqual(contexte["publication_raa_requise"], publication == "manuelle")
                self.assertEqual(contexte["doc_a_signer"], [document])

    def test_numerotation_nouveau_type_et_numero_fourni_conserve(self):
        for fourni in (None, "2025-0042"):
            with self.subTest(fourni= fourni), patch.object(Document, "objects") as objets, patch.object(models.Model, "save"), patch("autorisations.models.models_documents.transaction.atomic"):
                objets.filter.return_value.aggregate.return_value = {"max_num": None}
                document = Document(id_nature=DocumentNature(id=99, nature="Nouveau type", est_acte=True), numero=fourni)
                document.save()
                self.assertEqual(document.numero, fourni or f"{date.today().year}-1000")
                if fourni:
                    objets.filter.assert_not_called()

    def test_acte_sans_publication_reste_visible_apres_envoi(self):
        nature = DocumentNature(est_acte=True, mode_publication_raa="non_requise")
        document = Document(id_nature=nature, id_statut=DocumentStatut(statut="Envoyé"), titre="acte.pdf", emplacement="test/Actes/")
        with patch.object(document_utils, "DossierDocument") as liaisons, patch.object(document_utils, "Document") as documents, patch.object(document_utils, "get_types_actes_selectionnables"), patch.object(document_utils.smbclient.path, "exists", return_value=False), patch.dict("os.environ", {"NAS_ROOT": "test-nas"}):
            liaisons.objects.filter.return_value.select_related.return_value = [SimpleNamespace(id_document=document)]
            documents.objects.filter.return_value.values_list.return_value = []
            contexte = document_utils.build_documents_for_dossier(SimpleNamespace(emplacement="test", numero=1))
        self.assertEqual(contexte["acte_envoye_et_pas_publie"], [document])
        self.assertFalse(contexte["publication_raa_requise"])
        self.assertFalse(contexte["doc_envoye_et_publie"])

    def test_document_ordinaire_ne_recoit_pas_de_numero_acte(self):
        with patch.object(Document, "objects") as objets, patch.object(models.Model, "save"):
            document = Document(id_nature=DocumentNature(id=99, nature="Annexe", est_acte=False))
            document.save()
        self.assertIsNone(document.numero)
        objets.filter.assert_not_called()

    def test_type_desactive_reste_reconnu_pour_historique(self):
        nature = DocumentNature(id=99, est_acte=True, actif=False)
        self.assertTrue(document_utils.est_projet_acte_ou_rapport(Document(id_nature=nature)))
        with patch.object(DocumentNature, "objects") as objets:
            document_utils.get_types_actes_selectionnables()
            objets.filter.assert_called_once_with(est_acte=True, actif=True)

    def test_identifiant_et_ancien_libelle_acceptes(self):
        with patch.object(DocumentNature, "objects") as objets:
            document_utils.get_type_acte("99")
            objets.filter.assert_called_with(est_acte=True, pk=99)
            document_utils.get_type_acte("Nouveau type", nouveau=True)
            objets.filter.assert_called_with(est_acte=True, nature="Nouveau type")
            objets.filter.return_value.filter.assert_called_once_with(actif=True)

    def test_dm_interdit_ne_depose_pas_le_fichier(self):
        with patch.object(changement_etape, "reception_traiter_fichier_avis_dm") as deposer, patch.object(changement_etape, "messages"), patch.object(changement_etape, "get_access_token") as token:
            document = Document(id_nature=DocumentNature(est_acte=True, autorise_dm=False))
            changement_etape._deposer_acte_sur_dm(None, {}, document, None, "nas")
        deposer.assert_not_called()
        token.assert_not_called()

    def test_dm_autorise_conserve_nature_et_document_source(self):
        document = Document(id_nature=DocumentNature(nature="Nouveau type", est_acte=True, autorise_dm=True), numero="2026-1042")
        resultat = {"token": None, "avis_id": 12, "dossier_dm": SimpleNamespace(emplacement="dm/")}
        with patch.object(changement_etape, "reception_traiter_fichier_avis_dm") as deposer, patch.object(changement_etape, "get_access_token", return_value="jeton"):
            changement_etape._deposer_acte_sur_dm(None, resultat, document, None, "nas")
        self.assertEqual(deposer.call_args.kwargs["nature_document"], "Nouveau type")
        self.assertEqual(deposer.call_args.kwargs["token"], "jeton")
        self.assertIs(deposer.call_args.kwargs["document_source"], document)

    def test_six_decisions_selon_mode_raa(self):
        for nom_vue, etape_finale in (("envoyer_l_acte", "Accepté"), ("envoyer_l_acte_de_refus", "Refusé")):
            for mode in DocumentNature.PublicationRAA.values:
                with self.subTest(vue=nom_vue, mode=mode), ExitStack() as stack:
                    mocks = {nom: stack.enter_context(patch.object(changement_etape, nom)) for nom in (
                        "get_dossier_or_redirect", "get_instructeur_or_redirect", "get_type_acte",
                        "Document", "DocumentStatut", "DocumentFormat", "Instructeur", "DossierDocument",
                        "accepter_dossier_ds", "refuser_dossier_ds", "safe_update_etape", "safe_update_etat",
                        "safe_enregistrer_action", "set_dossier_role", "_enregistrer_motif_decision_sans_bloquer",
                        "envoyer_copie_document_par_mail", "_envoyer_annexes_decision_sur_ds", "_get_contexte_dossier_dm", "redirect_error",
                    )}
                    stack.enter_context(patch.object(changement_etape.transaction, "atomic"))
                    fichier_nas = stack.enter_context(patch.object(changement_etape.smbclient, "open_file"))
                    fichier_nas.return_value.__enter__.return_value.read.return_value = b"%PDF-simule"
                    stack.enter_context(patch.dict("os.environ", {"NAS_ROOT": "test-nas"}))
                    nature = DocumentNature(id=99, nature="Nouveau type", est_acte=True, mode_publication_raa=mode)
                    document = MagicMock(id=1, titre="acte.pdf", id_nature=nature, id_nature_id=99, id_statut=SimpleNamespace(statut="À envoyer"), id_format=SimpleNamespace(format="pdf"), publie_au_raa=False)
                    dossier = SimpleNamespace(numero=123, present_sur_ds=True, emplacement="test/")
                    mocks["get_type_acte"].return_value = nature
                    mocks["get_dossier_or_redirect"].return_value = (dossier, None)
                    mocks["get_instructeur_or_redirect"].return_value = (SimpleNamespace(email="agent@example.test"), None)
                    mocks["Document"].objects.filter.return_value.select_related.return_value.first.return_value = document
                    mocks["DossierDocument"].objects.filter.return_value.select_related.return_value = [SimpleNamespace(id_document=document)]
                    for nom in ("safe_update_etape", "safe_update_etat", "safe_enregistrer_action", "set_dossier_role", "envoyer_copie_document_par_mail", "_envoyer_annexes_decision_sur_ds"):
                        mocks[nom].return_value = None
                    mocks["_get_contexte_dossier_dm"].return_value = (None, None)
                    mocks["accepter_dossier_ds"].return_value = mocks["refuser_dossier_ds"].return_value = {"success": True}
                    mocks["redirect_error"].return_value = HttpResponse(status=400)
                    request = RequestFactory().post("/test", {"dossierId": "1", "document_id_existant": "1", "nature_document": "99", "choix-publieur-raa": "2"})
                    request.user = SimpleNamespace(is_authenticated=True, email="agent@example.test")
                    response = getattr(changement_etape, nom_vue)(request)
                    mocks["redirect_error"].assert_not_called()
                    self.assertEqual(response.status_code, 302)
                    self.assertEqual(mocks["safe_update_etape"].call_args.args[1], "À publier au RAA" if mode == "manuelle" else etape_finale)
                    self.assertEqual(document.publie_au_raa, mode == "deja_realisee")
                    self.assertEqual(mocks["set_dossier_role"].called, mode == "manuelle")

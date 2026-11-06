from django.contrib import admin
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase
from types import SimpleNamespace

from autorisations.models.models_generation import (
    Balise, BaliseSourceChamp, DocumentTemplate, DocumentTemplateDemarche, TemplateBalise, DocumentGeneration, valider_chemin_template,
    valider_destination_relative, valider_nom_fichier,
)


class GenerationCatalogueTests(SimpleTestCase):
    def test_template_sans_code_mais_balise_garde_son_code(self):
        self.assertNotIn('code', {field.name for field in DocumentTemplate._meta.fields})
        self.assertIn('code', {field.name for field in Balise._meta.fields})

    def test_configuration_destination_et_nom_sans_acces_disque(self):
        for destination in ("{dossier.emplacement}/Work/", "{dossier.emplacement}Work/", "{dossier.emplacement}", "Actes/{num_doss}/", "Work"):
            valider_destination_relative(destination)
        for name in ("DIR-I-{num_doss}.docx", "Acte_{dossier.numero}.docx", "Fiche.docx"):
            valider_nom_fichier(name)
        for destination in ("../Work", "/Work/", "C:/Work", "Work//Actes", "{inconnu}/Work/", "{{ dossier.numero }}/Work/", "Work/{dossier.emplacement}/", "{dossier.emplacement}../Work/", "{dossier.emplacement}//Work/"):
            with self.subTest(destination=destination), self.assertRaises(ValidationError):
                valider_destination_relative(destination)
        for name in ("../acte.docx", "{dossier.emplacement}.docx", "Acte.pdf", "{num_doss!r}.docx", "CON.docx", "{num_doss", ".docx"):
            with self.subTest(name=name), self.assertRaises(ValidationError):
                valider_nom_fichier(name)

    def test_configuration_facultative_mais_paire(self):
        DocumentTemplate().clean()
        DocumentTemplate(destination_relative="{dossier.emplacement}/Work/", nom_fichier="DIR-I-{num_doss}.docx").clean()
        for fields in ({"destination_relative": "Work/"}, {"nom_fichier": "Acte.docx"}):
            with self.subTest(fields=fields), self.assertRaises(ValidationError):
                DocumentTemplate(**fields).clean()

    def test_configuration_incomplete_pour_chacun_des_quatre_champs_obligatoires(self):
        values = dict(nom="Test", chemin_relatif="TEST/test.docx",
                      destination_relative="{dossier.emplacement}/Work/", nom_fichier="DIR-I-{dossier.numero}.docx")
        self.assertEqual(DocumentTemplate(**values).erreurs_configuration(), {})
        for name in values:
            with self.subTest(name=name):
                errors = DocumentTemplate(**{**values, name: ""}).erreurs_configuration()
                self.assertIn(name, errors)
        self.assertTrue(DocumentTemplate._meta.get_field('id_nature').null)
        self.assertTrue(DocumentTemplate._meta.get_field('id_nature').blank)
        for name, invalid in (("chemin_relatif", "../test.docx"),
                              ("destination_relative", "/Work/"), ("nom_fichier", "{inconnu}.docx")):
            with self.subTest(name=name):
                self.assertIn(name, DocumentTemplate(**{**values, name: invalid}).erreurs_configuration())

    def test_variable_unique_par_champ_meme_avec_ancien_alias(self):
        for value in ("{dossier.numero}-{dossier.numero}.docx", "{num_doss}-{dossier.numero}.docx"):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                valider_nom_fichier(value)

    def test_chemins_relatifs_docx_acceptes_sans_acces_nas(self):
        for value in ("modele.docx", "Actes/Modèle scientifique.docx"):
            with self.subTest(value=value):
                valider_chemin_template(value)

    def test_chemins_hors_templates_ou_non_docx_refuses(self):
        for value in (
            "", "/tmp/modele.docx", "../modele.docx", "Actes/../modele.docx",
            "C:/modele.docx", "Actes\\modele.docx", "Templates/modele.docx",
            "Actes//modele.docx", "Actes/./modele.docx", "modele.pdf",
            "Actes/\x00modele.docx",
        ):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                valider_chemin_template(value)

    def test_code_balise_normalise(self):
        field = Balise._meta.get_field("code")
        self.assertEqual(field.clean("beneficiaire.nom_complet", None), "beneficiaire.nom_complet")
        for value in ("{{ dossier.numero }}", "dossier..numero", "dossier.numero\n"):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                field.clean(value, None)

    def test_admin_et_associations_optionnelles(self):
        self.assertIn(Balise, admin.site._registry)
        template_admin = admin.site._registry[DocumentTemplate]
        self.assertEqual(template_admin.check(), [])
        self.assertTrue(DocumentTemplate._meta.get_field("demarches").blank)
        self.assertIs(DocumentTemplate._meta.get_field("demarches").remote_field.through, DocumentTemplateDemarche)
        for model in (Balise, DocumentTemplate, DocumentTemplateDemarche):
            self.assertFalse(model._meta.managed)

    def test_derniers_modeles_visibles_et_editables_en_admin(self):
        request = SimpleNamespace(user=SimpleNamespace(has_perm=lambda permission: True))
        for model in (DocumentTemplateDemarche, BaliseSourceChamp, TemplateBalise, DocumentGeneration):
            with self.subTest(model=model.__name__):
                self.assertIn(model, admin.site._registry)
                self.assertEqual(admin.site._registry[model].check(), [])
        for model in (BaliseSourceChamp, TemplateBalise, DocumentGeneration):
            model_admin = admin.site._registry[model]
            self.assertTrue(model_admin.has_add_permission(request))
            self.assertTrue(model_admin.has_change_permission(request))
            self.assertTrue(model_admin.has_delete_permission(request))
            form = model_admin.get_form(request)
            for field in model._meta.fields:
                if field.editable and not field.primary_key:
                    self.assertIn(field.name, form.base_fields)
        history_admin = admin.site._registry[DocumentGeneration]
        self.assertNotIn('file_corrections', history_admin.get_readonly_fields(request))

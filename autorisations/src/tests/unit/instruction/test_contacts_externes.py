"""Raccourcis de raison sociale : affichage et nommage, sans BDD réelle."""
from types import SimpleNamespace
from unittest.mock import patch

from django.template import Context, Template
from django.test import RequestFactory, SimpleTestCase

from autorisations.models.models_utilisateurs import (
    ContactExterne, TypeContactExterne, raison_sociale_affichee, organisation_affichee,
)
from instruction.templatetags.custom_filters import est_contact_conseil_scientifique
from backoffice.views.nom_dossier import contexte_nommage_depuis_bdd
from synchronisation.synchro.sync_contacts_externes import sync_contacts_externes


class ContactsExternesTests(SimpleTestCase):
    def contact(self, **valeurs):
        return ContactExterne(
            id=173, id_type=TypeContactExterne(id=1, type="Bénéficiaire"),
            raison_sociale="OFFICE NATIONAL DES FORETS", **valeurs,
        )

    def test_raccourci_vide_par_defaut_et_raison_complete_inchangee(self):
        contact = self.contact()
        self.assertEqual(contact.raison_sociale_raccourci, "")
        self.assertEqual(contact.raison_sociale_affichee, "OFFICE NATIONAL DES FORETS")
        self.assertEqual(str(contact), "OFFICE NATIONAL DES FORETS")

    def test_raccourci_prioritaire_dans_les_affichages(self):
        contact = self.contact(raison_sociale_raccourci=" ONF ")
        self.assertEqual(contact.raison_sociale_affichee, "ONF")
        self.assertEqual(contact.get_display_name(), "ONF")
        self.assertEqual(str(contact), "ONF")
        self.assertEqual(contact.raison_sociale, "OFFICE NATIONAL DES FORETS")
        contact.nom, contact.prenom = "HAMEL", "Valentin"
        self.assertEqual(contact.get_display_name(), "HAMEL Valentin (ONF)")

    def test_raccourci_blanc_revient_a_la_raison_sociale(self):
        for valeur in (None, "", "   "):
            with self.subTest(valeur=valeur):
                self.assertEqual(raison_sociale_affichee({
                    "raison_sociale": "Raison complète", "raison_sociale_raccourci": valeur,
                }), "Raison complète")

    def test_raccourci_prioritaire_sur_organisation_sans_modifier_la_valeur(self):
        contact = self.contact(organisation="Organisation complète", raison_sociale_raccourci="ONF")
        self.assertEqual(contact.organisation_affichee, "ONF")
        self.assertEqual(contact.organisation, "Organisation complète")
        for valeur in (None, "", "   "):
            contact.raison_sociale_raccourci = valeur
            self.assertEqual(contact.organisation_affichee, "Organisation complète")
        self.assertEqual(organisation_affichee({"raison_sociale_raccourci": "ONF"}), "ONF")
        self.assertEqual(organisation_affichee({}), "")

    def test_template_organisation_affiche_le_raccourci(self):
        contact = self.contact(organisation="Organisation complète", raison_sociale_raccourci="<ONF>")
        rendu = Template("{% load custom_filters %}{{ contact|organisation_affichee }}").render(
            Context({"contact": contact}),
        )
        self.assertEqual(rendu, "&lt;ONF&gt;")

    def test_template_affiche_le_raccourci_en_echappant_le_html(self):
        contact = self.contact(raison_sociale_raccourci="<ONF>")
        rendu = Template("{% load custom_filters %}{{ contact|raison_sociale_affichee }}").render(
            Context({"contact": contact}),
        )
        self.assertEqual(rendu, "&lt;ONF&gt;")

    def test_identification_cs_reste_basee_sur_la_raison_complete(self):
        contact = ContactExterne(raison_sociale="Conseil scientifique", raison_sociale_raccourci="CS")
        self.assertTrue(est_contact_conseil_scientifique(contact))
        self.assertEqual(contact.raison_sociale_affichee, "CS")

    def test_admin_affiche_et_recherche_le_raccourci(self):
        from autorisations.admin import ContactExterneAdmin
        from django.contrib import admin
        modele_admin = ContactExterneAdmin(ContactExterne, admin.site)
        self.assertEqual(modele_admin.raison_sociale_courte(self.contact(raison_sociale_raccourci="ONF")), "ONF")
        self.assertIn("raison_sociale_raccourci", modele_admin.search_fields)

    def test_contexte_bdd_utilise_le_raccourci_sans_intermediaire(self):
        contact = self.contact(raison_sociale_raccourci="ONF")
        dossier = SimpleNamespace(
            numero=30426066, date_depot=None, champs_nommage=[],
            interlocuteurs_nommage=[SimpleNamespace(
                id_demandeur_intermediaire=None,
                beneficiaires_nommage=[SimpleNamespace(id_beneficiaire=contact)],
            )],
        )
        contexte = contexte_nommage_depuis_bdd(dossier)
        for role in ("demandeur", "beneficiaire"):
            self.assertEqual(contexte["attributs"][f"{role}.raison_sociale"], "ONF")
            self.assertEqual(contexte["attributs"][f"{role}.organisation"], "ONF")

    def test_synchro_preserve_et_restitue_le_raccourci_agida(self):
        contact = self.contact(raison_sociale_raccourci="ONF")
        donnees = {"beneficiaire": {
            "id_type": 1, "email": "contact@example.test", "raison_sociale": "OFFICE NATIONAL DES FORETS",
        }}
        module = "synchronisation.synchro.sync_contacts_externes"
        with patch(f"{module}.ContactExterne.objects.get_or_create", return_value=(contact, False)) as obtenir, \
             patch(f"{module}.update_fields", return_value=[]) as modifier:
            resultat = sync_contacts_externes(donnees)
        self.assertEqual(resultat["beneficiaire"], 173)
        self.assertEqual(donnees["beneficiaire"]["raison_sociale_raccourci"], "ONF")
        self.assertNotIn("raison_sociale_raccourci", obtenir.call_args.kwargs["defaults"])
        self.assertNotIn("raison_sociale_raccourci", modifier.call_args.args[1])
        self.assertEqual(contact.raison_sociale_raccourci, "ONF")

    def test_gestion_contacts_permet_de_saisir_et_effacer_le_raccourci(self):
        from instruction.views.views import gestion_contacts
        contact = self.contact(raison_sociale_raccourci="ONF")
        for valeur in ("  ONF Réunion  ", ""):
            request = RequestFactory().post("/gestion-contacts/", {
                "type_objet": "contact", "id": 173, "raison_sociale": contact.raison_sociale,
                "raison_sociale_raccourci": valeur,
            })
            request.user = SimpleNamespace(is_authenticated=True)
            with patch("instruction.views.views.get_object_or_404", return_value=contact), \
                 patch.object(ContactExterne, "save") as sauvegarder, \
                 patch("instruction.views.views.messages.success"), \
                 patch("instruction.views.views.redirect"):
                gestion_contacts(request)
            sauvegarder.assert_called_once()
            self.assertEqual(contact.raison_sociale_raccourci, valeur.strip())

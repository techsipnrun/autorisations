"""Branchement des composants et conservation des variantes, sans accès BDD."""
from html.parser import HTMLParser
from itertools import product
from types import SimpleNamespace as NS

from django.template import Context, Template
from django.test import SimpleTestCase
from django.urls import reverse

from instruction.utils.actions_interface import construire_menu


CODES = (
    "dossier_non_soumis_a_autorisation", "classer_le_dossier_comme_refuse",
    "classer_le_dossier_comme_accepte", "classer_comme_annule",
)


class Elements(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.tags = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def attributs(self, nom):
        return [attrs[nom] for _, attrs in self.tags if nom in attrs]


def rendre(interface="instruction", present=True, etape="En instruction", etat="accepte", dm=None,
           codes=CODES):
    objets = [NS(code=code, action=code) for code in codes]
    menu = construire_menu(objets, codes, "dn", "À affecter" if interface == "preinstruction" else etape, interface)
    contexte = Context({
        "actions_menu": menu, "csrf_token": "test",
        "dossier": NS(id_ds="id-dossier", numero=123, present_sur_ds=present,
                      id_etat_dossier=NS(nom=etat)),
        "etape_actuelle": NS(etape=etape), "etape_dossier": etape,
        "dossier_lie_manif_sportive": dm is not None,
        "doss_manif_sportive": NS(archive=dm) if dm is not None else None,
    })
    boutons = Template("{% for action in actions_menu %}{% include action.template %}{% endfor %}").render(contexte)
    forms = Template('{% include "instruction/refacto/actions/formulaires.html" %}').render(contexte)
    return menu, boutons, forms


class FormulairesArchivageTests(SimpleTestCase):
    def test_tous_les_boutons_ouvrent_un_formulaire_unique_sur_les_deux_ecrans(self):
        for interface, present, etape, etat, dm in product(
            ("instruction", "preinstruction"), (True, False),
            ("À affecter", "En pré-instruction", "En instruction", "À publier au RAA"),
            ("accepte", "refuse"), (None, True, False),
        ):
            with self.subTest(interface=interface, present=present, etape=etape, etat=etat, dm=dm):
                _, boutons, forms = rendre(interface, present, etape, etat, dm)
                zones = Elements(forms).attributs("data-action-form")
                for code in Elements(boutons).attributs("data-ouvrir-formulaire"):
                    self.assertEqual(zones.count(code), 1)
                ids = Elements(boutons + forms).attributs("id")
                self.assertEqual(len(ids), len(set(ids)))

    def test_contrat_post_messages_et_champs_obligatoires(self):
        for interface, code in product(("instruction", "preinstruction"), CODES):
            with self.subTest(interface=interface, code=code):
                _, _, html = rendre(interface, codes=[code])
                elements = Elements(html)
                form = next(attrs for tag, attrs in elements.tags if tag == "form")
                route = "classer_le_dossier_comme_non_soumis_a_autorisation" if code == CODES[0] else code
                self.assertEqual(form["action"], reverse(route + "_url"))
                self.assertEqual(form["method"], "post")
                self.assertEqual(form["enctype"], "multipart/form-data")
                self.assertIn("confirm(", form["onsubmit"])
                inputs = {attrs["name"]: attrs for tag, attrs in elements.tags if tag in ("input", "textarea")}
                self.assertEqual(inputs["dossierId"]["value"], "id-dossier")
                self.assertEqual(inputs["csrfmiddlewaretoken"]["value"], "test")
                self.assertEqual(inputs["justificatif"]["data-taille-max"], "10485760")
                self.assertEqual("required" in inputs["motivation"], code != "classer_comme_annule")
                self.assertIn("Démarche Numérique", html)
                if code in CODES[1:3]:
                    self.assertIn("accordée par le valideur", html)
                if code == CODES[2]:
                    self.assertIn("dossier 123.", html)

    def test_messages_et_justificatif_du_classement_lie_a_dm(self):
        for present, archive in product((True, False), (True, False)):
            with self.subTest(present=present, archive=archive):
                _, _, html = rendre(present=present, dm=archive, codes=[CODES[0]])
                self.assertEqual('name="justificatif"' in html, present)
                self.assertEqual("Aucune mise à jour" in html, present and archive)
                self.assertEqual("son espace Déclaration Manifestations" in html, not present and not archive)

    def test_formulaire_accompagne_son_code_sans_liste_par_ecran(self):
        menu, _, forms = rendre(codes=[CODES[1]])
        self.assertTrue(menu[0]["formulaire"].endswith(CODES[1] + ".html"))
        self.assertNotIn('data-action-form="classer_comme_annule"', forms)
        menu, _, forms = rendre(codes=["passer_en_pre_instruction"])
        self.assertIsNone(menu[0]["formulaire"])
        self.assertNotIn("<form", forms)

    def test_les_formulaires_dn_ne_sont_pas_charges_pour_dm_seul(self):
        objet = NS(code="declaration_manifestations_accepter", action="Accepter")
        menu = construire_menu([objet], [objet.action], "dm", "En réception", "dm")
        self.assertIsNone(menu[0]["formulaire"])

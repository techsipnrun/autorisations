"""Relances DM : destinataires, affichage et notifications sans envoi réel."""
from contextlib import ExitStack
from html.parser import HTMLParser
import os
from types import SimpleNamespace as NS
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import AnonymousUser
from django.db.models import Model
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase
from django.utils import timezone

from autorisations.models.models_instruction import DossierManifSportive, EtapeDossier
from instruction import utils_instru
from instruction.utils import utilisateurs_utils as utilisateurs
from instruction.views import instruction, messagerie, preinstruction


class Elements(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.tags = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def bouton_relance(self):
        return next(attrs for tag, attrs in self.tags
                    if tag == "button" and attrs.get("class") == "btn-relance-demandeur")


def dossier_dm(structure=None, coordinateur=None):
    return DossierManifSportive(
        pk=1, numero_dossier_declaration_manifestations=123,
        nom_dossier="Manifestation de test", archive=False, coeur_de_parc=True,
        id_etape=EtapeDossier(pk=1, etape="En réception"),
        email_structure=structure, email_coordinateur_securite=coordinateur,
        date_depot=timezone.now(), date_debut_evenement=timezone.now(),
    )


class DestinatairesRelanceDMTests(SimpleTestCase):
    def test_structure_puis_coordinateur_sans_vides_ni_doublons(self):
        for structure, coordinateur, attendus in (
            (None, None, []), ("", " \t", []),
            ("structure@example.test", None, ["structure@example.test"]),
            (None, "securite@example.test", ["securite@example.test"]),
            (" \t", " securite@example.test ", ["securite@example.test"]),
            ("structure@example.test", "securite@example.test", ["structure@example.test", "securite@example.test"]),
            ("Structure@example.test ", " structure@EXAMPLE.test", ["Structure@example.test"]),
        ):
            with self.subTest(structure=structure, coordinateur=coordinateur):
                self.assertEqual(utilisateurs.get_destinataires_relance_dm(dossier_dm(structure, coordinateur)), attendus)

    def test_relance_auto_structure_prioritaire_coordinateur_en_secours(self):
        for structure, coordinateur, attendu in (
            ("structure@example.test", "securite@example.test", "structure@example.test"),
            (None, "securite@example.test", "securite@example.test"),
            (" ", " securite@example.test ", "securite@example.test"),
        ):
            with self.subTest(structure=structure), \
                 patch.dict(os.environ, {"LIEN_FORM_MANIF_SPORTIVE": "https://example.test/formulaire"}), \
                 patch.object(utilisateurs, "NOTIFS_PROD", True), \
                 patch.object(utilisateurs, "create_EmailOutbox_DM", return_value=NS(id=42, to=[attendu])) as creer, \
                 patch.object(utilisateurs, "envoi_mail", return_value=(True, None)) as envoyer:
                dm = dossier_dm(structure, coordinateur)
                self.assertTrue(utilisateurs.envoi_auto_mail_relance(dm))
                self.assertEqual(creer.call_args.args[0], [attendu])
                self.assertIs(creer.call_args.args[5], dm)
                self.assertEqual(creer.call_args.kwargs, {"type_mail": "Relance"})
                envoyer.assert_called_once_with(42)

    def test_sans_adresse_aucune_creation_ni_tentative_d_envoi(self):
        with patch.dict(os.environ, {"LIEN_FORM_MANIF_SPORTIVE": "https://example.test/formulaire"}), \
             patch.object(utilisateurs, "create_EmailOutbox_DM") as creer, \
             patch.object(utilisateurs, "envoi_mail") as envoyer:
            self.assertFalse(utilisateurs.envoi_auto_mail_relance(dossier_dm(" ", None)))
            creer.assert_not_called()
            envoyer.assert_not_called()

    def test_mode_test_ne_cible_jamais_le_coordinateur_reel(self):
        with patch.dict(os.environ, {"LIEN_FORM_MANIF_SPORTIVE": "https://example.test/formulaire"}), \
             patch.object(utilisateurs, "NOTIFS_PROD", False), \
             patch.object(utilisateurs, "EMAIL_NOTIF_TEST", "test@example.test"), \
             patch.object(utilisateurs, "create_EmailOutbox_DM", return_value=NS(id=42, to=["test@example.test"])) as creer, \
             patch.object(utilisateurs, "envoi_mail", return_value=(True, None)):
            self.assertTrue(utilisateurs.envoi_auto_mail_relance(dossier_dm(None, "securite@example.test")))
            self.assertEqual(creer.call_args.args[0], ["test@example.test"])

    def test_relance_auto_declenchee_depuis_reception_avec_coordinateur_seul(self):
        with ExitStack() as stack:
            managers = {}
            for nom, modele in vars(preinstruction).items():
                if isinstance(modele, type) and issubclass(modele, Model) and modele is not Model:
                    managers[nom] = stack.enter_context(patch.object(modele, "objects"))
            managers["EtapeDossier"].filter.return_value.first.return_value = NS(etape="À affecter")
            managers["Instructeur"].filter.return_value.first.return_value = NS(id=7)
            managers["Demarche"].filter.return_value.first.return_value = NS(
                pk=1, id=1, numero=124837, type="Manifestations sportives",
                actualisation_statut=None, actualisation_message=None, actualisation_date=None,
            )
            dm = dossier_dm(None, "securite@example.test")
            dm.date_debut_evenement = timezone.now() + timezone.timedelta(days=60)
            managers["DossierManifSportive"].filter.return_value.exclude.return_value.order_by.return_value = [dm]
            stack.enter_context(patch.object(preinstruction, "load_geojson", return_value={}))
            stack.enter_context(patch.object(preinstruction, "dossiers_reception_action_a_faire", return_value=[]))
            stack.enter_context(patch.object(preinstruction, "get_dates_demande_avis_dm", return_value={}))
            stack.enter_context(patch.object(preinstruction, "_contacts_demandeurs_par_dossier", return_value={}))
            envoyer = stack.enter_context(patch.object(preinstruction, "envoi_auto_mail_relance", return_value=True))
            stack.enter_context(patch.object(preinstruction, "render", return_value=HttpResponse()))
            request = RequestFactory().get("/preinstruction/")
            request.user = NS(is_authenticated=True, email="agent@example.test", groups=MagicMock())
            self.assertEqual(preinstruction.preinstruction(request).status_code, 200)
            envoyer.assert_called_once_with(dm)
            self.assertEqual(dm.nb_relances, 1)

    def test_relance_manuelle_transmet_les_destinataires_du_formulaire(self):
        for structure, coordinateur in (("structure@example.test", "securite@example.test"),
                                         (None, "securite@example.test"),
                                         ("structure@example.test", "STRUCTURE@example.test")):
            with self.subTest(structure=structure, coordinateur=coordinateur), \
                 patch.object(messagerie.DossierManifSportive, "objects") as dossiers, \
                 patch.object(messagerie, "NOTIFS_PROD", True), \
                 patch.object(messagerie, "create_EmailOutbox_DM", return_value=NS(id=42)) as creer, \
                 patch.object(messagerie, "envoi_mail", return_value=(True, None)) as envoyer, \
                 patch.object(messagerie, "ajouter_message_bloc"), patch("builtins.print"):
                dm = dossier_dm(structure, coordinateur)
                dossiers.filter.return_value.first.return_value = dm
                emails = utilisateurs.get_destinataires_relance_dm(dm)
                request = RequestFactory().post("/relance/1/", {
                    "emails[]": emails, "objet": "Dossier DN attendu", "body": "Merci de transmettre votre dossier Parc.",
                })
                request.user = NS(is_authenticated=True)
                response = messagerie.envoi_manuel_mail_relance(request, dm.pk)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(creer.call_args.args[0], emails)
                envoyer.assert_called_once_with(42)


class AffichageRelanceDMTests(SimpleTestCase):
    def rendre(self, dm, affectations=(7,), instructeur_id=7):
        request = RequestFactory().get("/preinstruction/declaration_manifestations/123/")
        request.user = AnonymousUser()
        request.user.email = ""
        with patch("instruction.templatetags.cartographie_tags.charger_configurations", return_value={}):
            return render_to_string("instruction/dossier_manif_sportive_sans_ds.html", {
                "doss_manif_sportive": dm,
                "instructeurs_dm_affectes_ids": set(affectations),
                "instructeur_connecte": NS(id=instructeur_id) if instructeur_id is not None else None,
                "emails_relance_organisateur": utilisateurs.get_destinataires_relance_dm(dm),
            }, request=request)

    def test_rappel_affectation_et_absence_de_mail(self):
        html = self.rendre(dossier_dm())
        self.assertIn('class="dm-relance-information"', html)
        self.assertIn("Si la dernière relance a été effectuée il y a plus de 15 jours", html)
        self.assertIn("Aucune adresse e-mail de la structure ni du coordinateur sécurité", html)

    def test_rappel_reserve_aux_instructeurs_affectes_au_dm(self):
        for instructeur_id, visible in ((7, True), (8, True), (9, False), (None, False)):
            with self.subTest(instructeur_id=instructeur_id):
                html = self.rendre(dossier_dm(), affectations=(7, 8), instructeur_id=instructeur_id)
                self.assertEqual('class="dm-relance-information"' in html, visible)

    def test_aucune_exception_pour_superuser_ou_reception_non_affectes(self):
        for superuser in (False, True):
            with self.subTest(superuser=superuser):
                html = render_to_string("instruction/refacto/dm_relance_information.html", {
                    "request": NS(user=NS(is_superuser=superuser)),
                    "doss_manif_sportive": dossier_dm(),
                    "instructeurs_dm_affectes_ids": {7}, "instructeur_connecte": NS(id=9),
                })
                self.assertNotIn('class="dm-relance-information"', html)

    def test_contact_telephonique_uniquement_sans_mail_et_avec_numero(self):
        for structure, coordinateur, telephone, affiche in (
            (None, None, "06 92 12 34 56", True),
            (None, None, None, False),
            (None, None, "", False),
            ("structure@example.test", None, "06 92 12 34 56", False),
            (None, "securite@example.test", "06 92 12 34 56", False),
        ):
            with self.subTest(structure=structure, coordinateur=coordinateur, telephone=telephone):
                dm = dossier_dm(structure, coordinateur)
                dm.numero_telephone = telephone
                html = self.rendre(dm)
                self.assertEqual("Vous pouvez contacter l’organisation par téléphone" in html, affiche)
                if affiche:
                    self.assertIn("Vous pouvez contacter l’organisation par téléphone.", html)

    def test_rappel_masque_sans_affectation_ou_sur_archive(self):
        self.assertNotIn('class="dm-relance-information"', self.rendre(dossier_dm(), affectations=()))
        dm = dossier_dm()
        dm.archive = True
        self.assertNotIn('class="dm-relance-information"', self.rendre(dm))

    def test_destinataires_du_formulaire_et_bouton_avec_coordinateur_seul(self):
        dm = dossier_dm(None, "securite@example.test")
        html = self.rendre(dm)
        self.assertNotIn("Aucune adresse e-mail de la structure", html)
        self.assertIn('class="chip" data-email="securite@example.test"', html)
        self.assertIn('name="emails[]" value="securite@example.test"', html)
        bouton = Elements(html).bouton_relance()
        self.assertNotIn("disabled", bouton)

    def test_formulaire_prefere_deux_adresses_distinctes_sans_doublon(self):
        for coordinateur, attendu in (("securite@example.test", 2), (" STRUCTURE@example.test ", 1)):
            with self.subTest(coordinateur=coordinateur):
                html = self.rendre(dossier_dm("structure@example.test", coordinateur))
                self.assertEqual(html.count('name="emails[]"'), attendu)
                self.assertEqual(html.count('class="chip" data-email='), attendu)

    def test_sans_adresse_bouton_desactive(self):
        html = self.rendre(dossier_dm())
        bouton = Elements(html).bouton_relance()
        self.assertIn("disabled", bouton)


class PastillesManifestationsReceptionTests(SimpleTestCase):
    def test_dossier_complet_reste_a_la_reception_meme_deja_affecte(self):
        dossiers = [NS(id=1, id_demarche=NS(type="Manifestations sportives", service="SAADD")),
                    NS(id=2, id_demarche=NS(type="Manifestations sportives", service="SAADD"))]
        for reception, affectations, attendus in (
            (False, [(1, 7), (2, 7)], {2}),
            (True, [(1, 7), (2, 7)], {1, 2}),
            (True, [(1, 7)], {1, 2}),
            (False, [(1, 7)], set()),
        ):
            with self.subTest(reception=reception, affectations=affectations), \
                 patch.object(utils_instru.Instructeur, "objects") as agents, \
                 patch.object(utils_instru.DossierManifestationLiaison, "objects") as liaisons, \
                 patch.object(utils_instru.DossierInstructeur, "objects") as liens, \
                 patch.object(utils_instru.Dossier, "objects") as resultats:
                agents.filter.return_value.first.return_value = NS(id=7)
                liaisons.filter.return_value.values_list.return_value = [1]
                liens.filter.return_value.values_list.return_value = affectations
                user = NS(is_authenticated=True, email="agent@example.test", groups=MagicMock())
                user.groups.filter.side_effect = lambda **kw: NS(exists=lambda: reception and kw["name"] == "Réception SAADD")
                utils_instru.dossiers_reception_action_a_faire(dossiers, user)
                resultats.filter.assert_called_once_with(id__in=attendus)

    def test_pas_de_pastille_instruction_pour_complet_a_affecter(self):
        with ExitStack() as stack:
            for modele in (instruction.DossierInstructeur, instruction.DossierValideur,
                           instruction.DossierRelecteurQualite, instruction.DossierPublicationRAA,
                           instruction.DossierEnvoiActe, instruction.DossierIntermediaireSignature,
                           instruction.DossierRelecteur):
                manager = stack.enter_context(patch.object(modele, "objects"))
                manager.filter.return_value.values_list.return_value = [1, 2, 3] if modele is instruction.DossierInstructeur else []
            liaisons = stack.enter_context(patch.object(instruction.DossierManifestationLiaison, "objects"))
            liaisons.filter.return_value.values_list.return_value = [1]
            stack.enter_context(patch.object(instruction, "_messages_non_lus_par_dossier", return_value={}))
            dossiers = MagicMock()
            dossiers.values_list.return_value = [(1, "À affecter", "Manifestations sportives"),
                                                 (2, "À affecter", "Manifestations sportives"),
                                                 (3, "En pré-instruction", "Manifestations sportives")]
            self.assertEqual(instruction._actions_a_faire_ids(dossiers, NS(id=7)), {2, 3})

"""Demandes successives à une même instance : choix, avis distincts et fichiers isolés."""
from contextlib import ExitStack, nullcontext
import errno
from types import SimpleNamespace
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase

from instruction.utils.avis_utils import emplacement_demande_avis_dossier
from instruction.utils import avis_utils
from instruction.views import avis as vues
from instruction.utils.avis_formulaires import configuration_standard


class AvisInstancesMultiplesTests(SimpleTestCase):
    def setUp(self):
        self.enterContext(patch.object(vues, "charger_configuration", side_effect=configuration_standard))
        self.enterContext(patch.object(vues, "thematiques_avis_liees_a_demarche", return_value=[SimpleNamespace(pk=1)]))
        self.factory = RequestFactory()
        self.user = SimpleNamespace(email="instructeur@example.test", is_authenticated=True)
        self.dossier = SimpleNamespace(id=10, numero=123456, emplacement="Dossier/", id_demarche=SimpleNamespace(type="Travaux"))
        self.instance = SimpleNamespace(id=20, email="instance@example.test", nom=None, prenom=None, raison_sociale="Instance test", organisation=None)
        self.expert = SimpleNamespace(id=30, est_interne=False, id_contact_externe=self.instance)
        self.emplacements = []
        self.noms_nas = []
        self.model_avis = self.enterContext(patch.object(avis_utils, "Avis"))
        self.model_avis.objects.filter.return_value.values_list.side_effect = lambda *args, **kwargs: list(self.emplacements)
        self.nas = self.enterContext(patch.object(avis_utils, "smbclient"))
        self.nas.listdir.side_effect = lambda chemin: list(self.noms_nas)
        self.nas.mkdir.side_effect = self.reserver_repertoire
        self.enterContext(patch.dict("os.environ", {"NAS_ROOT": "//nas/"}))

    def reserver_repertoire(self, chemin):
        nom = chemin.rstrip("/").rsplit("/", 1)[1]
        if nom in self.noms_nas:
            raise FileExistsError(errno.EEXIST, "Dossier existant", chemin)
        self.noms_nas.append(nom)

    def test_trois_demandes_utilisent_le_nom_puis_les_suffixes(self):
        chemins = [emplacement_demande_avis_dossier(self.dossier, "COLLIN Gérard") for _ in range(3)]
        self.assertEqual(chemins, ["Dossier/Avis/collin_gerard/", "Dossier/Avis/collin_gerard_2/", "Dossier/Avis/collin_gerard_3/"])
        self.assertEqual(self.model_avis.objects.filter.call_count, 3)
        self.assertEqual(self.nas.listdir.call_count, 3)

    def test_dossier_historique_sur_nas_est_conserve(self):
        self.noms_nas.append("collin_gerard")
        self.assertEqual(emplacement_demande_avis_dossier(self.dossier, "COLLIN Gérard"), "Dossier/Avis/collin_gerard_2/")

    def test_emplacements_en_base_reserves_meme_si_absents_du_nas(self):
        self.emplacements.extend(["Dossier/Avis/collin_gerard/", "Dossier/Avis/collin_gerard_3/"])
        self.assertEqual(emplacement_demande_avis_dossier(self.dossier, "COLLIN Gérard"), "Dossier/Avis/collin_gerard_4/")

    def test_anciens_sous_dossiers_uuid_ne_sont_pas_reutilises(self):
        self.emplacements.append("Dossier/Avis/collin_gerard/Demande_ancien/")
        self.assertEqual(emplacement_demande_avis_dossier(self.dossier, "COLLIN Gérard"), "Dossier/Avis/collin_gerard_2/")

    def test_ignore_autres_experts_et_gere_suffixes_superieurs_a_neuf(self):
        self.noms_nas.extend(["collin_gerard_10", "autre_expert_99", "collin_gerard_autre"])
        self.assertEqual(emplacement_demande_avis_dossier(self.dossier, "COLLIN Gérard"), "Dossier/Avis/collin_gerard_11/")

    def test_collision_concurrente_prend_le_suffixe_suivant(self):
        self.nas.mkdir.side_effect = [OSError(errno.EEXIST, "Créé simultanément"), None]
        self.assertEqual(emplacement_demande_avis_dossier(self.dossier, "COLLIN Gérard"), "Dossier/Avis/collin_gerard_2/")
        self.assertEqual(self.nas.mkdir.call_count, 2)

    def test_erreur_nas_n_est_pas_confondue_avec_un_dossier_existant(self):
        self.nas.mkdir.side_effect = PermissionError(errno.EACCES, "Accès refusé")
        with self.assertRaises(PermissionError):
            emplacement_demande_avis_dossier(self.dossier, "COLLIN Gérard")
        self.nas.mkdir.assert_called_once()

    def test_modification_brouillon_conserve_emplacement_historique(self):
        brouillon = SimpleNamespace(emplacement="Dossier/Avis/Instance_test/")
        self.assertEqual(emplacement_demande_avis_dossier(self.dossier, "Instance test", brouillon), brouillon.emplacement)
        self.model_avis.objects.filter.assert_not_called()
        self.nas.mkdir.assert_not_called()

    def test_brouillon_sans_emplacement_et_instance_sans_nom(self):
        chemin = emplacement_demande_avis_dossier(self.dossier, "", SimpleNamespace(emplacement=""))
        self.assertEqual(chemin, "Dossier/Avis/instance/")

    def test_instance_deja_consultee_reste_dans_le_formulaire(self):
        for avis_id in (None, 5):
            with self.subTest(avis_id=avis_id), ExitStack() as stack:
                dossier = stack.enter_context(patch.object(vues, "Dossier"))
                instructeur = stack.enter_context(patch.object(vues, "Instructeur"))
                contact = stack.enter_context(patch.object(vues, "ContactExterne"))
                avis = stack.enter_context(patch.object(vues, "Avis"))
                stack.enter_context(patch.object(vues, "AvisNature"))
                stack.enter_context(patch.object(vues, "DossierAvis"))
                stack.enter_context(patch.object(vues, "AvisDocument"))
                stack.enter_context(patch.object(vues, "lire_reservation", return_value=SimpleNamespace(id=1, numero=50, id_avis_id=None)))
                stack.enter_context(patch.object(vues, "AvisThematique"))
                stack.enter_context(patch.object(vues, "thematiques_avis_liees_a_demarche", return_value=[]))
                for nom in ("get_chemin_complet_dossier", "count_unread_messages_for_dossier", "count_avis_with_unread_messages_for_dossier"):
                    stack.enter_context(patch.object(vues, nom, return_value=0))
                render = stack.enter_context(patch.object(vues, "render", return_value=HttpResponse()))
                dossier.objects.filter.return_value.first.return_value = self.dossier
                avis.objects.filter.return_value.first.return_value = SimpleNamespace(id=5, id_expert=self.expert)
                avis.objects.filter.return_value.select_related.return_value.first.return_value = SimpleNamespace(
                    id=5, numero_affiche="5", id_expert=self.expert, id_projet_avis_id=None, id_projet_acte_id=None, id_rapport_instance_id=None,
                )
                instructeur_qs = instructeur.objects.filter.return_value
                instructeur_qs.first.return_value = self.user
                instructeur_qs.exclude.return_value = instructeur_qs
                instructeur_qs.order_by.return_value = []
                contacts_qs = contact.objects.filter.return_value
                contacts_qs.exclude.return_value = contacts_qs
                contacts_qs.order_by.return_value = [self.instance]
                request = self.factory.get("/ajouter-avis/", {"reservation": "00000000-0000-0000-0000-000000000001"})
                request.user = self.user
                vues.instruction_dossier_ajouter_avis(request, self.dossier.numero, avis_id=avis_id)
                self.assertEqual(list(render.call_args.args[2]["contacts_externes"]), [self.instance])
                self.assertTrue(all("email__in" not in appel.kwargs for appel in contacts_qs.exclude.call_args_list))
                contact.objects.filter.assert_called_once_with(email__isnull=False, id_type__type="Instance")

    def test_deux_envois_creent_deux_avis_avec_meme_instance_et_isolent_les_pj(self):
        demandes = []

        def creer_avis(**champs):
            demande = SimpleNamespace(**champs)
            demandes.append(demande)
            self.emplacements.append(demande.emplacement)
            return demande

        with ExitStack() as stack:
            stack.enter_context(patch.object(vues, "charger_configuration", side_effect=configuration_standard))
            stack.enter_context(patch.object(vues, "creation_avis_reservee", side_effect=lambda *args: nullcontext(SimpleNamespace(numero=len(demandes) + 1, id_avis_id=None))))
            stack.enter_context(patch.object(vues, "utiliser_reservation"))
            stack.enter_context(patch.object(vues.transaction, "on_commit", side_effect=lambda callback: callback()))
            dossier = stack.enter_context(patch.object(vues, "Dossier"))
            instructeur = stack.enter_context(patch.object(vues, "Instructeur"))
            avis = stack.enter_context(patch.object(vues, "Avis"))
            liaison = stack.enter_context(patch.object(vues, "DossierAvis"))
            nature = stack.enter_context(patch.object(vues, "AvisNature"))
            nature.objects.get.return_value = SimpleNamespace(nature="Demande à une instance")
            contact = stack.enter_context(patch.object(vues, "ContactExterne"))
            contact.objects.get.return_value = self.instance
            stack.enter_context(patch.object(vues, "AvisThematique"))
            stack.enter_context(patch.object(vues, "Message"))
            stack.enter_context(patch.object(vues, "MessageDocument"))
            stack.enter_context(patch.object(vues, "get_or_create_expert_from_form", return_value=(self.expert, "Instance_test")))
            stack.enter_context(patch.object(vues, "_destinataire_cs_depuis_formulaire", return_value=None))
            stack.enter_context(patch.object(vues, "creer_dossier_sur_nas"))
            document = stack.enter_context(patch.object(vues, "enregistrer_document", side_effect=[SimpleNamespace(id=pk) for pk in range(50, 54)]))
            stack.enter_context(patch.object(vues, "NOTIFS_PROD", False))
            stack.enter_context(patch.object(vues, "compute_dedupe_key", return_value="cle-test"))
            outbox = stack.enter_context(patch.object(vues, "create_EmailOutbox", return_value=SimpleNamespace(id=1, to=["test@example.test"])))
            stack.enter_context(patch.object(vues, "envoi_mail", return_value=(True, None)))
            dossier.objects.filter.return_value.first.return_value = self.dossier
            instructeur.objects.filter.return_value.first.return_value = self.user
            avis.objects.create.side_effect = creer_avis

            for _ in range(2):
                request = self.factory.post("/confirmer-avis/", {
                    "nature": "1", "thematique": "1", "expert_externe": "20", "mode_contact": "Application",
                    "formulation_avis": "Nouvelle demande à cette même instance.",
                    "pj_demande_avis": SimpleUploadedFile("demande.docx", b"projet"),
                    "pj_projet_acte": SimpleUploadedFile("acte.pdf", b"pdf"),
                })
                request.user = self.user
                response = vues.instruction_dossier_confirmer_ajout_avis(request, self.dossier.numero)
                self.assertEqual(response.status_code, 302)

            self.assertEqual(len(demandes), 2)
            self.assertIs(demandes[0].id_expert, demandes[1].id_expert)
            self.assertNotEqual(demandes[0].emplacement, demandes[1].emplacement)
            self.assertEqual([demande.emplacement for demande in demandes], ["Dossier/Avis/instance_test/", "Dossier/Avis/instance_test_2/"])
            self.assertEqual(liaison.objects.create.call_count, 2)
            self.assertEqual([appel.kwargs["emplacement_avis"] for appel in document.call_args_list], [demande.emplacement for demande in demandes for _ in range(2)])
            self.assertEqual([appel.args[4]["avis_numero"] for appel in outbox.call_args_list], [1, 2])
            self.assertTrue(all(appel.args[0] == [vues.EMAIL_NOTIF_TEST] for appel in outbox.call_args_list))

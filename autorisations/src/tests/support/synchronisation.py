"""Préparation commune de synchro : ORM, NAS et mails simulés, sans test hérité."""
from contextlib import ExitStack
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch


from autorisations.models.models_documents import Document
from synchronisation.utils.conversion import parse_datetime_with_tz
from tests.support.constants import CHAMPS, URL_SIGNEE


def donnees_champ(id_ds, documents=None):
    return {"champ": {"id_ds": id_ds, "nom_champ": id_ds, "valeur": "valeur", "date_saisie": None},
            "documents": documents or []}


def donnees_document(titre):
    return {"titre": titre, "emplacement": "Dossier/Annexes", "id_nature": 1, "id_format": 1,
            "url_ds": URL_SIGNEE, "description": titre}


class SynchroChampsMixin:
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.dossier = SimpleNamespace(numero=123, id_etape_dossier=SimpleNamespace(etape="En instruction"))
        self.stack.enter_context(patch(f"{CHAMPS}.Dossier.objects.get", return_value=self.dossier))
        self.stack.enter_context(patch(f"{CHAMPS}.get_first_id", side_effect=lambda model, **kw: kw["id_ds"]))
        for modele, resultat in (("Champ", 1), ("ChampType", "text")):
            manager = self.stack.enter_context(patch(f"{CHAMPS}.{modele}.objects.filter"))
            manager.return_value.values_list.return_value.first.return_value = resultat
        self.doc_get = self.stack.enter_context(patch(f"{CHAMPS}.Document.objects.get", side_effect=Document.DoesNotExist))
        self.doc_filter = self.stack.enter_context(patch(f"{CHAMPS}.Document.objects.filter"))
        self.doc_filter.return_value.first.return_value = None
        self.doc_create = self.stack.enter_context(patch(f"{CHAMPS}.Document.objects.create"))
        self.doc_create.return_value = SimpleNamespace(id=10, titre="ok.pdf")
        self.champ_create = self.stack.enter_context(patch(f"{CHAMPS}.DossierChamp.objects.create"))
        self.existant = Mock()
        self.sans_pj = self.stack.enter_context(patch(f"{CHAMPS}.DossierChamp.objects.get_or_create", return_value=(self.existant, False)))
        self.champs_existants = []
        self.premier_import = False
        self.pj_connues = {}

        def filter_champs(**kwargs):
            if "id_dossier" in kwargs:
                return self.champs_existants
            queryset = MagicMock()
            queryset.exists.return_value = not self.premier_import
            queryset.order_by.return_value.first.return_value = self.pj_connues.get(kwargs.get("id_document_id"))
            return queryset

        self.stack.enter_context(patch(f"{CHAMPS}.DossierChamp.objects.filter", side_effect=filter_champs))
        self.stack.enter_context(patch(f"{CHAMPS}.update_fields_dossier_champs", return_value=([], {})))
        self.stack.enter_context(patch(f"{CHAMPS}.update_fields", return_value=[]))
        self.telecharger = self.stack.enter_context(patch(f"{CHAMPS}.write_pj_volumineuse", return_value=None))
        self.logger = self.stack.enter_context(patch(f"{CHAMPS}.logger"))
        self.demandes_complements = self.stack.enter_context(patch(f"{CHAMPS}.DossierAction.objects.filter"))
        self.derniere_demande = self.demandes_complements.return_value.order_by.return_value.values_list.return_value.first
        self.derniere_demande.return_value = parse_datetime_with_tz(datetime(2026, 6, 1, 8, 0))
        self.notification = self.stack.enter_context(patch(f"{CHAMPS}.create_EmailOutbox"))
        self.envoi = self.stack.enter_context(patch(f"{CHAMPS}.envoi_mail", return_value=(True, None)))

    def preparer_modifications_en_attente(self):
        self.dossier.date_depot = parse_datetime_with_tz("2026-10-01T08:00:00+04:00")
        self.dossier.id_etape_dossier.etape = "En attente de compléments"
        self.dossier.id_demarche = SimpleNamespace(type="Démarche de test")
        self.stack.enter_context(patch(
            f"{CHAMPS}.update_fields_dossier_champs", return_value=(["valeur", "date_saisie"], {}),
        ))
        instructeurs = self.stack.enter_context(patch(f"{CHAMPS}.Instructeur.objects.order_by"))
        instructeurs.return_value.first.return_value = SimpleNamespace(id=99)
        self.stack.enter_context(patch(f"{CHAMPS}.NOTIFS_PROD", False))
        self.stack.enter_context(patch(f"{CHAMPS}.EMAIL_NOTIF_TEST", "test@example.test"))
        self.notification.return_value = SimpleNamespace(id=1)
        return self.stack.enter_context(patch(f"{CHAMPS}.safe_enregistrer_action"))

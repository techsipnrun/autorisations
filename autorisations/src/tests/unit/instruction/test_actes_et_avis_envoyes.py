"""Actes déjà envoyés et avis réunis dans le même encadré du dossier."""
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.template import Context, Template
from django.template.loader import get_template
from django.test import SimpleTestCase

from autorisations.models.models_documents import Document, DocumentNature, DocumentStatut
from instruction.utils import document_utils


class ActesEtAvisEnvoyesTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        source = get_template("instruction/instruction_dossier.html").template.source
        bloc = source.split("<!-- ######################## AVIS ENVOYÉS ######################### -->", 1)[1]
        bloc = bloc.split("<!-- ######################## AVIS À ENVOYER ######################### -->", 1)[0]
        cls.template = Template("{% load static %}" + bloc)

    def setUp(self):
        self.acte = Document(
            id=1, titre="acte-premier-envoi.pdf", emplacement="Dossier/Actes/", numero="2026-1002",
            id_nature=DocumentNature(nature="Courrier", est_acte=True, prefixe_numero="C-"),
            id_statut=DocumentStatut(statut="Envoyé"),
        )
        self.avis = SimpleNamespace(id_avis=SimpleNamespace(
            id=42, id_expert="Expert test", reponse="favorable", get_reponse_display="Favorable",
            documents=[SimpleNamespace(titre="avis-signe.pdf", emplacement="Dossier/Avis/")],
        ))

    def rendu(self, actes=(), avis=(), etape="En instruction"):
        return self.template.render(Context({
            "actes_deja_envoyes": actes, "avis_envoye": avis,
            "dossier": SimpleNamespace(numero=123456), "etape_actuelle": SimpleNamespace(etape=etape),
            "request": SimpleNamespace(user=AnonymousUser()),
        }))

    def test_acte_seul_reste_visible_sans_avis(self):
        html = self.rendu([self.acte])
        self.assertEqual(html.count('class="validation-documents"'), 1)
        self.assertIn("Acte déjà envoyé</h2>", html)
        self.assertIn("acte-premier-envoi.pdf", html)
        self.assertIn("C-2026-1002", html)
        self.assertIn('class="document-download-link"', html)
        self.assertNotIn("Demandes d'avis envoyées", html)

    def test_actes_avant_avis_dans_un_seul_bloc(self):
        autre = Document(id=2, titre="acte-second-envoi.pdf", emplacement="Dossier/Actes/",
                         id_nature=self.acte.id_nature)
        html = self.rendu([self.acte, autre], [self.avis])
        self.assertEqual(html.count('class="validation-documents"'), 1)
        self.assertLess(html.index("Actes déjà envoyés"), html.index("Demandes d'avis envoyées"))
        self.assertIn("acte-second-envoi.pdf", html)
        self.assertIn("Expert test", html)
        self.assertIn("Favorable", html)
        self.assertIn("avis-signe.pdf", html)

    def test_avis_seuls_conservent_leur_affichage(self):
        for etape in ("En instruction", "Accepté", "Refusé", "À publier au RAA"):
            with self.subTest(etape=etape):
                html = self.rendu(avis=[self.avis], etape=etape)
                self.assertIn("Demandes d'avis envoyées", html)
                self.assertNotIn("Acte déjà envoyé", html)

    def test_reference_externe_dans_bloc_avis_et_lien_interne_inchange(self):
        self.avis.id_avis.numero_affiche = "CS-2026-042"
        html = self.rendu(avis=[self.avis])
        self.assertIn("Avis n°CS-2026-042", html)
        self.assertIn("/instruction/123456/consultation/42/", html)

    def test_pas_de_bloc_vide(self):
        self.assertNotIn('class="validation-documents"', self.rendu())

    def test_actes_restent_visibles_pendant_une_nouvelle_demande_avis(self):
        self.assertIn("Acte déjà envoyé", self.rendu([self.acte], etape="Avis à envoyer"))

    def test_liste_existante_contient_les_actes_publies_et_non_publies_uniquement_envoyes(self):
        publie = Document(id=2, titre="acte-publie.pdf", emplacement="Dossier/Actes/", publie_au_raa=True,
                          id_nature=self.acte.id_nature, id_statut=DocumentStatut(statut="Envoyé"))
        projet = Document(id=3, titre="projet.docx", emplacement="Dossier/Work/",
                          id_nature=self.acte.id_nature, id_statut=DocumentStatut(statut="À valider"))
        with patch.object(document_utils, "DossierDocument") as liaisons, \
             patch.object(document_utils, "Document") as documents, \
             patch.object(document_utils, "get_types_actes_selectionnables"), \
             patch.object(document_utils.smbclient.path, "exists", return_value=False), \
             patch.dict("os.environ", {"NAS_ROOT": "test-nas"}):
            liaisons.objects.filter.return_value.select_related.return_value = [
                SimpleNamespace(id_document=doc) for doc in (self.acte, publie, projet)
            ]
            documents.objects.filter.return_value.values_list.return_value = []
            contexte = document_utils.build_documents_for_dossier(SimpleNamespace(numero=123456, emplacement="Dossier/"))
        self.assertEqual(contexte["doc_envoye"], [self.acte, publie])

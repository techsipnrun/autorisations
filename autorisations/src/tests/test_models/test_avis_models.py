from django.test import TestCase
from django.db import IntegrityError, connection
from autorisations.src.autorisations.models.models_avis import Avis, AvisDocument, AvisNature, AvisThematique, DemandeAvis, Expert
from autorisations.models.models_instruction import Demande, DemandeType, Dossier, DossierType, EtatDemande, EtatDossier, Priorite
from autorisations.models.models_utilisateurs import ContactExterne, Instructeur, TypeContactExterne
from autorisations.models.models_documents import Document, DocumentFormat, DocumentNature

class AvisNatureTestCase(TestCase):

    def setUp(self):
        assert connection.settings_dict['NAME'] == 'test_autorisations', "Django utilise la mauvaise base de données !"

        self.nature = AvisNature.objects.create(id=1, nature="Environnement")

    def test_is_correct_instance(self):
        """Vérifie que l'objet créé est bien une instance de AvisNature"""
        self.assertIsInstance(self.nature, AvisNature)

    def test_exists(self):
        """Vérifie que l'objet existe bien en base"""
        nature_test = AvisNature.objects.get(id=1)
        self.assertTrue(nature_test)

    def test_delete_avis_nature(self):
        """Vérifie qu'on peut supprimer un AvisNature"""
        self.nature.delete()
        with self.assertRaises(AvisNature.DoesNotExist):
            AvisNature.objects.get(id=1)



class AvisThematiqueTestCase(TestCase):

    def setUp(self):
        assert connection.settings_dict['NAME'] == 'test_autorisations', "Django utilise la mauvaise base de données !"

        self.thematique = AvisThematique.objects.create(id=1, thematique="Urbanisme")

    def test_is_correct_instance(self):
        """Vérifie que l'objet créé est bien une instance de AvisThematique"""
        self.assertIsInstance(self.thematique, AvisThematique)

    def test_exists(self):
        """Vérifie que l'objet existe bien en base"""
        thematique_test = AvisThematique.objects.get(id=1)
        self.assertTrue(thematique_test)

    def test_unique_thematique_constraint(self):
        """Vérifie qu'on ne peut pas créer deux AvisThematique avec la même `thematique`"""
        with self.assertRaises(IntegrityError):
            AvisThematique.objects.create(id=2, thematique="Urbanisme")

    def test_delete_avis_thematique(self):
        """Vérifie qu'on peut supprimer un AvisThematique"""
        self.thematique.delete()
        with self.assertRaises(AvisThematique.DoesNotExist):
            AvisThematique.objects.get(id=1)



class ExpertTestCase(TestCase):

    def setUp(self):
        assert connection.settings_dict['NAME'] == 'test_autorisations', "Django utilise la mauvaise base de données !"

        self.type_contact = TypeContactExterne.objects.create(id=1, type="Entreprise")
        self.contact_externe = ContactExterne.objects.create(
            id=1,
            email="contact@example.com",
            id_type=self.type_contact,
            nom="Martin",
            prenom="Paul"
        )
        self.instructeur = Instructeur.objects.create(id=1, email="instructeur@interne.com")

        self.expert = Expert.objects.create(
            id=1,
            id_expert_ds="EX001",
            email="expert@domaine.com",
            est_interne=True,
            id_contact_externe=self.contact_externe,
            id_agent_autorisations=self.instructeur
        )

    def test_is_correct_instance(self):
        """Vérifie que l'objet créé est bien une instance de Expert"""
        self.assertIsInstance(self.expert, Expert)

    def test_unique_email_constraint(self):
        """Vérifie qu'on ne peut pas créer un Expert avec un email déjà existant"""
        with self.assertRaises(IntegrityError):
            Expert.objects.create(id=2, email="expert@domaine.com")

    def test_delete_expert(self):
        """Vérifie qu'on peut supprimer un Expert"""
        self.expert.delete()
        with self.assertRaises(Expert.DoesNotExist):
            Expert.objects.get(id=1)




class AvisTestCase(TestCase):

    def setUp(self):
        assert connection.settings_dict['NAME'] == 'test_autorisations', "Django utilise la mauvaise base de données !"

        self.nature = AvisNature.objects.create(id=1, nature="Environnement")
        self.thematique = AvisThematique.objects.create(id=1, thematique="Urbanisme")
        self.expert = Expert.objects.create(id=1, email="expert@domaine.com", est_interne=True)
        self.instructeur = Instructeur.objects.create(id=1, email="instructeur@interne.com")
        self.etat = EtatDossier.objects.create(id=1, nom="Ouvert")
        self.dossier_type = DossierType.objects.create(id=1, type="Type A")
        self.dossier = Dossier.objects.create(id=1, 
                                             id_etat_dossier=self.etat,
                                             numero=200,
                                             date_depot="2025-01-01",
                                             id_dossier_type=self.dossier_type,
                                             nom_dossier="Dossier Test",
                                             emplacement="/path/test",
                                             date_limite_traitement="2025-03-11",)

        self.avis = Avis.objects.create(
            id=1,
            id_avis_nature=self.nature,
            id_avis_thematique=self.thematique,
            id_expert_ds="EX001",
            favorable=True,
            date_limite="2025-12-31",
            date_demande_avis="2025-01-01",
            mode_contact="Email",
            id_dossier=self.dossier,
            id_expert=self.expert,
            id_instructeur=self.instructeur
        )

    def test_is_correct_instance(self):
        """Vérifie que l'objet créé est bien une instance de Avis"""
        self.assertIsInstance(self.avis, Avis)

    def test_unique_expert_ds_constraint(self):
        """Vérifie qu'on ne peut pas créer un Avis avec le même `id_expert_ds`"""
        with self.assertRaises(IntegrityError):
            Avis.objects.create(
                id=2,
                id_avis_nature=self.nature,
                id_avis_thematique=self.thematique,
                id_expert_ds="EX001",  # Conflit
                favorable=False,
                date_limite="2025-12-31",
                date_demande_avis="2025-01-01",
                mode_contact="Téléphone"
            )

    def test_delete_avis(self):
        """Vérifie qu'on peut supprimer un Avis"""
        self.avis.delete()
        with self.assertRaises(Avis.DoesNotExist):
            Avis.objects.get(id=1)



class AvisDocumentTestCase(TestCase):

    def setUp(self):
        assert connection.settings_dict['NAME'] == 'test_autorisations', "Django utilise la mauvaise base de données !"

        self.nature = AvisNature.objects.create(id=1, nature="Environnement")
        self.thematique = AvisThematique.objects.create(id=1, thematique="Urbanisme")
        self.expert = Expert.objects.create(id=1, email="expert@domaine.com", est_interne=True)
        self.instructeur = Instructeur.objects.create(id=1, email="instructeur@interne.com")

        self.etat_dossier = EtatDossier.objects.create(id=1, nom="Ouvert")
        self.dossier_type = DossierType.objects.create(id=1, type="Type A")
        self.dossier = Dossier.objects.create(
            id=1, 
            id_etat_dossier=self.etat_dossier,
            numero=200,
            date_depot="2025-01-01",
            id_dossier_type=self.dossier_type,
            nom_dossier="Dossier Test",
            emplacement="/path/test",
            date_limite_traitement="2025-03-11",
        )

        self.avis = Avis.objects.create(
            id=1,
            id_avis_nature=self.nature,
            id_avis_thematique=self.thematique,
            id_expert_ds="EX001",
            favorable=True,
            date_limite="2025-12-31",
            date_demande_avis="2025-01-01",
            mode_contact="Email",
            id_dossier=self.dossier,
            id_expert=self.expert,
            id_instructeur=self.instructeur
        )

        self.doc_format = DocumentFormat.objects.create(id=1, format="PDF")
        self.doc_nature = DocumentNature.objects.create(id=1, nature="Rapport")

        self.document = Document.objects.create(
                id=1,
                id_format=self.doc_format,
                id_nature=self.doc_nature,
                emplacement="serveur/docs/doc1.pdf",  # Même emplacement
                description="Copie"
            )

        self.avis_document = AvisDocument.objects.create(id=1, id_avis=self.avis, id_document=self.document)

    def test_is_correct_instance(self):
        """Vérifie que l'objet créé est bien une instance de AvisDocument"""
        self.assertIsInstance(self.avis_document, AvisDocument)

    def test_exists(self):
        """Vérifie que l'objet existe bien en base"""
        avis_document_test = AvisDocument.objects.get(id=1)
        self.assertTrue(avis_document_test)

    def test_unique_constraint(self):
        """Vérifie qu'on ne peut pas associer deux fois le même document au même avis"""
        with self.assertRaises(IntegrityError):
            AvisDocument.objects.create(id=2, id_avis=self.avis, id_document=self.document)

    def test_delete_avis_document(self):
        """Vérifie qu'on peut supprimer un AvisDocument"""
        self.avis_document.delete()
        with self.assertRaises(AvisDocument.DoesNotExist):
            AvisDocument.objects.get(id=1)



class DemandeAvisTestCase(TestCase):

    @classmethod
    def setUpTestData(cls):
        assert connection.settings_dict['NAME'] == 'test_autorisations', "Django utilise la mauvaise base de données !"

        EtatDemande.objects.all().delete()
        EtatDossier.objects.all().delete()
        Priorite.objects.all().delete()
        DemandeType.objects.all().delete()
        Dossier.objects.all().delete()

        cls.nature = AvisNature.objects.create(id=1, nature="Environnement")
        cls.thematique = AvisThematique.objects.create(id=1, thematique="Urbanisme")
        cls.expert = Expert.objects.create(id=1, email="expert@domaine.com", est_interne=True)
        cls.instructeur = Instructeur.objects.create(id=1, email="instructeur@interne.com")

        cls.etat_dossier = EtatDossier.objects.create(id=1, nom="Ouvert")
        cls.dossier_type = DossierType.objects.create(id=1, type="Type A")
        cls.dossier = Dossier.objects.create(
            id=1, 
            id_etat_dossier=cls.etat_dossier,
            numero=200,
            date_depot="2025-01-01",
            id_dossier_type=cls.dossier_type,
            nom_dossier="Dossier Test",
            emplacement="/path/test",
            date_limite_traitement="2025-03-11",
        )

        cls.priorite = Priorite.objects.create(id=1, niveau="Haute")
        cls.demande_type = DemandeType.objects.create(id=1, type="Dérogation")
        cls.etat_demande = EtatDemande.objects.create(id=1, nom="En cours")
        cls.demande = Demande.objects.create(id=1, id_etat_demande=cls.etat_demande,
                                             id_priorite=cls.priorite,
                                             id_demande_type=cls.demande_type,
                                             date_depot="2025-01-01",
                                             date_fin_instruction=None,
                                             soumis_controle=True,
                                             en_attente_avis=False,
                                             avis_a_faire=True,
                                             en_attente_demandeur=False,
                                             en_attente_validation=False,
                                             pre_instruction_faite=False,
                                             id_interlocuteur_ds="INT001",
                                             id_dossier=cls.dossier)

        cls.avis = Avis.objects.create(
            id=1,
            id_avis_nature=cls.nature,
            id_avis_thematique=cls.thematique,
            id_expert_ds="EX001",
            favorable=True,
            date_limite="2025-12-31",
            date_demande_avis="2025-01-01",
            mode_contact="Email",
            id_dossier=cls.dossier,
            id_expert=cls.expert,
            id_instructeur=cls.instructeur
        )

        cls.demande_avis = DemandeAvis.objects.create(id=1, id_avis=cls.avis, id_demande=cls.demande)

    def test_is_correct_instance(self):
        """Vérifie que l'objet créé est bien une instance de DemandeAvis"""
        self.assertIsInstance(self.demande_avis, DemandeAvis)

    def test_exists(self):
        """Vérifie que l'objet existe bien en base"""
        demande_avis_test = DemandeAvis.objects.get(id=1)
        self.assertTrue(demande_avis_test)

    def test_unique_constraint(self):
        """Vérifie qu'on ne peut pas associer deux fois le même avis à la même demande"""
        with self.assertRaises(IntegrityError):
            DemandeAvis.objects.create(id=2, id_avis=self.avis, id_demande=self.demande)

    def test_delete_demande_avis(self):
        """Vérifie qu'on peut supprimer un DemandeAvis"""
        self.demande_avis.delete()
        with self.assertRaises(DemandeAvis.DoesNotExist):
            DemandeAvis.objects.get(id=1)

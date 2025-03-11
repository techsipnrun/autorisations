from django.test import TestCase  # ⬅ Remplace TestCase
from django.db import connection
from autorisations.models.models_documents import Document, DocumentFormat, DocumentNature, DossierDocument, MessageDocument
from django.db.utils import IntegrityError

from autorisations.models.models_instruction import Dossier, DossierType, EtatDossier, Message


'''
Pour lancer les tests :

python manage.py test --keepdb
'''

class DocumentFormatTestCase(TestCase): 

    def setUp(self):

        # Vérifier que Django utilise bien la base de test
        assert connection.settings_dict['NAME'] == 'test_autorisations', "Django utilise la mauvaise base de données !"

        self.doc_format = DocumentFormat.objects.create(id=27, format='Test de format')


    def test_is_correct_instance(self):
        self.assertIsInstance(self.doc_format, DocumentFormat)

    def test_exists(self):
        format_de_test = DocumentFormat.objects.get(id=27)
        self.assertTrue(format_de_test)

    def test_unique_format_constraint(self):
        """Vérifie qu'on ne peut pas créer un DocumentFormat avec un format déjà existant"""
        with self.assertRaises(IntegrityError):
            DocumentFormat.objects.create(id=28, format="Test de format")  # Même format que self.doc_format

    def test_multiple_document_formats(self):
        """Vérifie qu'on peut ajouter plusieurs formats uniques"""
        DocumentFormat.objects.create(id=1, format="Format 1")
        DocumentFormat.objects.create(format="Format 2")

        self.assertEqual(DocumentFormat.objects.count(), 3)  # 1 dans setUp + 2 nouveaux

    def test_delete_document_format(self):
        """Vérifie qu'on peut supprimer un DocumentFormat"""
        self.doc_format.delete()
        with self.assertRaises(DocumentFormat.DoesNotExist):
            DocumentFormat.objects.get(id=27)



class DocumentNatureTestCase(TestCase):

    def setUp(self):
        assert connection.settings_dict['NAME'] == 'test_autorisations', "Django utilise la mauvaise base de données !"

        self.nature = DocumentNature.objects.create(id=1, nature="Rapport")

    def test_is_correct_instance(self):
        """Vérifie que l'objet créé est bien une instance de DocumentNature"""
        self.assertIsInstance(self.nature, DocumentNature)

    def test_exists(self):
        """Vérifie que l'objet existe bien en base"""
        nature_test = DocumentNature.objects.get(id=1)
        self.assertTrue(nature_test)

    def test_unique_nature_constraint(self):
        """Vérifie qu'on ne peut pas créer deux DocumentNature avec le même `nature`"""
        with self.assertRaises(IntegrityError):
            DocumentNature.objects.create(id=2, nature="Rapport")  # Même valeur

    def test_delete_document_nature(self):
        """Vérifie qu'on peut supprimer un DocumentNature"""
        self.nature.delete()
        with self.assertRaises(DocumentNature.DoesNotExist):
            DocumentNature.objects.get(id=1)




class DocumentTestCase(TestCase):

    def setUp(self):
        assert connection.settings_dict['NAME'] == 'test_autorisations', "Django utilise la mauvaise base de données !"

        # Création des dépendances
        self.doc_format = DocumentFormat.objects.create(id=1, format="PDF")
        self.doc_nature = DocumentNature.objects.create(id=1, nature="Rapport")

        # Création du document
        self.document = Document.objects.create(
            id=1,
            id_format=self.doc_format,
            id_nature=self.doc_nature,
            emplacement="serveur/docs/doc1.pdf",
            description="Rapport 2024"
        )

    def test_is_correct_instance(self):
        """Vérifie que l'objet créé est bien une instance de Document"""
        self.assertIsInstance(self.document, Document)

    def test_exists(self):
        """Vérifie que l'objet existe bien en base"""
        document_test = Document.objects.get(id=1)
        self.assertTrue(document_test)

    def test_unique_emplacement_constraint(self):
        """Vérifie que `emplacement` est unique"""
        with self.assertRaises(IntegrityError):
            Document.objects.create(
                id=2,
                id_format=self.doc_format,
                id_nature=self.doc_nature,
                emplacement="serveur/docs/doc1.pdf",  # Même emplacement
                description="Copie"
            )

    def test_delete_document(self):
        """Vérifie qu'on peut supprimer un Document"""
        self.document.delete()
        with self.assertRaises(Document.DoesNotExist):
            Document.objects.get(id=1)




class DossierDocumentTestCase(TestCase):

    def setUp(self):
        assert connection.settings_dict['NAME'] == 'test_autorisations', "Django utilise la mauvaise base de données !"

        # Création des dépendances
        self.etat = EtatDossier.objects.create(id=1, nom="Ouvert")
        self.dossier_type = DossierType.objects.create(id=1, type="Type A")
        self.dossier = Dossier.objects.create(id=1, numero=200, id_etat_dossier=self.etat, date_depot="2025-01-01", id_dossier_type=self.dossier_type, nom_dossier="Dossier Test", emplacement="/path/test",date_limite_traitement="2025-03-11")
        self.doc_format = DocumentFormat.objects.create(id=1, format="PDF")
        self.doc_nature = DocumentNature.objects.create(id=1, nature="Rapport")
        self.document = Document.objects.create(
            id=1,
            id_format=self.doc_format,
            id_nature=self.doc_nature,
            emplacement="serveur/docs/doc1.pdf",
            description="Rapport"
        )

        # Création du lien dossier-document
        self.dossier_document = DossierDocument.objects.create(
            id_dossier=self.dossier,
            id_document=self.document
        )

    def test_is_correct_instance(self):
        """Vérifie que l'objet créé est bien une instance de DossierDocument"""
        self.assertIsInstance(self.dossier_document, DossierDocument)

    def test_unique_relation_constraint(self):
        """Vérifie que la relation `id_dossier, id_document` est unique"""
        with self.assertRaises(IntegrityError):
            DossierDocument.objects.create(
                id_dossier=self.dossier,
                id_document=self.document  # Même relation
            )

    def test_delete_dossier_document(self):
        """Vérifie qu'on peut supprimer une relation Dossier-Document"""
        self.dossier_document.delete()
        with self.assertRaises(DossierDocument.DoesNotExist):
            DossierDocument.objects.get(id_dossier=self.dossier, id_document=self.document)




class MessageDocumentTestCase(TestCase):

    def setUp(self):
        assert connection.settings_dict['NAME'] == 'test_autorisations', "Django utilise la mauvaise base de données !"

        # Création des dépendances
        self.etat = EtatDossier.objects.create(id=1, nom="Ouvert")
        self.dossier_type = DossierType.objects.create(id=1, type="Type A")
        self.dossier = Dossier.objects.create(
            id=1, numero=200, id_etat_dossier=self.etat, 
            date_depot="2025-01-01", id_dossier_type=self.dossier_type, 
            nom_dossier="Dossier Test", emplacement="/path/test", date_limite_traitement="2025-03-11"
        )
        
        self.doc_format = DocumentFormat.objects.create(id=1, format="PDF")
        self.doc_nature = DocumentNature.objects.create(id=1, nature="Rapport")
        self.document = Document.objects.create(
            id=1,
            id_format=self.doc_format,
            id_nature=self.doc_nature,
            emplacement="serveur/docs/doc1.pdf",
            description="Rapport"
        )

        self.message = Message.objects.create(
            id=1,
            id_ds="MSG001",
            body="Ceci est un message test.",
            date_envoi="2025-03-11",
            piece_jointe=True,
            email_emetteur="auteur@example.com",
            id_dossier=self.dossier
        )

        # Création du lien Message-Document
        self.message_document = MessageDocument.objects.create(
            id=1,
            id_document=self.document,
            id_message=self.message
        )

    def test_is_correct_instance(self):
        """Vérifie que l'objet créé est bien une instance de MessageDocument"""
        self.assertIsInstance(self.message_document, MessageDocument)

    def test_exists(self):
        """Vérifie que l'objet existe bien en base"""
        message_doc_test = MessageDocument.objects.get(id=1)
        self.assertTrue(message_doc_test)

    def test_unique_relation_constraint(self):
        """Vérifie que la relation `id_message, id_document` est unique"""
        with self.assertRaises(IntegrityError):
            MessageDocument.objects.create(
                id=2,
                id_document=self.document,
                id_message=self.message  # Même relation
            )

    def test_delete_message_document(self):
        """Vérifie qu'on peut supprimer une relation Message-Document"""
        self.message_document.delete()
        with self.assertRaises(MessageDocument.DoesNotExist):
            MessageDocument.objects.get(id=1)

from django.test import TestCase, TransactionTestCase
from django.db import connection, IntegrityError
from autorisations.models.models_instruction import (
    Champ, ChampType, DemandeChamp, Demarche, Dossier, DossierGroupe, DossierType, EtatDemande,
    EtatDemarche, EtatDossier, DemandeType, Demande, Groupe, Message, Priorite
)
from django.db import transaction


class ChampTypeTestCase(TestCase):

    def setUp(self):
        assert connection.settings_dict['NAME'] == 'test_autorisations', "Django utilise la mauvaise base de données !"
        self.champ_type = ChampType.objects.create(id=1, type="Numérique")

    def test_is_correct_instance(self):
        """Vérifie que l'objet créé est bien une instance de ChampType"""
        self.assertIsInstance(self.champ_type, ChampType)

    def test_unique_type_constraint(self):
        """Vérifie que `type` est unique"""
        with self.assertRaises(IntegrityError):
            ChampType.objects.create(id=2, type="Numérique")

    def test_delete_champ_type(self):
        """Vérifie qu'on peut supprimer un ChampType"""
        self.champ_type.delete()
        with self.assertRaises(ChampType.DoesNotExist):
            ChampType.objects.get(id=1)



class EtatDemandeTestCase(TestCase):

    @classmethod
    def setUpTestData(cls):
        assert connection.settings_dict['NAME'] == 'test_autorisations'
        EtatDemande.objects.all().delete()  # Supprime tous les objets existants
        cls.etat = EtatDemande.objects.create(id=1, nom="En attente")

    def test_is_correct_instance(self):
        """Vérifie que l'objet créé est bien une instance de EtatDemande"""
        self.assertIsInstance(self.etat, EtatDemande)

    def test_unique_nom_constraint(self):
        """Vérifie que `nom` est unique"""
        with self.assertRaises(IntegrityError):
            EtatDemande.objects.create(id=2, nom="En attente")

    def test_delete_etat_demande(self):
        """Vérifie qu'on peut supprimer un EtatDemande"""
        self.etat.delete()
        with self.assertRaises(EtatDemande.DoesNotExist):
            EtatDemande.objects.get(id=1)


class EtatDemarcheTestCase(TestCase):

    @classmethod
    def setUpTestData(cls):
        assert connection.settings_dict['NAME'] == 'test_autorisations'
        EtatDemarche.objects.all().delete()  # Supprime tous les objets existants
        cls.etat = EtatDemarche.objects.create(id=1, nom="En cours")

    def test_is_correct_instance(self):
        """Vérifie que l'objet créé est bien une instance de EtatDemarche"""
        self.assertIsInstance(self.etat, EtatDemarche)

    def test_unique_nom_constraint(self):
        """Vérifie que `nom` est unique"""
        with self.assertRaises(IntegrityError):
            EtatDemarche.objects.create(id=2, nom="En cours")

    def test_delete_etat_demarche(self):
        """Vérifie qu'on peut supprimer un EtatDemarche"""
        self.etat.delete()
        with self.assertRaises(EtatDemarche.DoesNotExist):
            EtatDemarche.objects.get(id=1)


class EtatDossierTestCase(TestCase):

    def setUp(self):
        assert connection.settings_dict['NAME'] == 'test_autorisations'
        self.etat = EtatDossier.objects.create(id=1, nom="Validé")

    def test_is_correct_instance(self):
        """Vérifie que l'objet créé est bien une instance de EtatDossier"""
        self.assertIsInstance(self.etat, EtatDossier)

    def test_unique_nom_constraint(self):
        """Vérifie que `nom` est unique"""
        with self.assertRaises(IntegrityError):
            EtatDossier.objects.create(id=2, nom="Validé")

    def test_delete_etat_dossier(self):
        """Vérifie qu'on peut supprimer un EtatDossier"""
        self.etat.delete()
        with self.assertRaises(EtatDossier.DoesNotExist):
            EtatDossier.objects.get(id=1)


class PrioriteTestCase(TestCase):

    def setUp(self):
        assert connection.settings_dict['NAME'] == 'test_autorisations'
        self.priorite = Priorite.objects.create(id=1, niveau="Haute")

    def test_is_correct_instance(self):
        """Vérifie que l'objet créé est bien une instance de Priorite"""
        self.assertIsInstance(self.priorite, Priorite)

    def test_unique_niveau_constraint(self):
        """Vérifie que `niveau` est unique"""
        with self.assertRaises(IntegrityError):
            Priorite.objects.create(id=2, niveau="Haute")

    def test_delete_priorite(self):
        """Vérifie qu'on peut supprimer une Priorite"""
        self.priorite.delete()
        with self.assertRaises(Priorite.DoesNotExist):
            Priorite.objects.get(id=1)


class DemandeTypeTestCase(TestCase):

    def setUp(self):
        assert connection.settings_dict['NAME'] == 'test_autorisations'
        self.demande_type = DemandeType.objects.create(id=1, type="Dérogation")

    def test_is_correct_instance(self):
        """Vérifie que l'objet créé est bien une instance de DemandeType"""
        self.assertIsInstance(self.demande_type, DemandeType)

    def test_unique_type_constraint(self):
        """Vérifie que `type` est unique"""
        with self.assertRaises(IntegrityError):
            DemandeType.objects.create(id=2, type="Dérogation")

    def test_delete_demande_type(self):
        """Vérifie qu'on peut supprimer un DemandeType"""
        self.demande_type.delete()
        with self.assertRaises(DemandeType.DoesNotExist):
            DemandeType.objects.get(id=1)


class DossierTypeTestCase(TestCase):

    def setUp(self):
        assert connection.settings_dict['NAME'] == 'test_autorisations'
        self.dossier_type = DossierType.objects.create(id=1, type="Permis de construire")

    def test_is_correct_instance(self):
        """Vérifie que l'objet créé est bien une instance de DossierType"""
        self.assertIsInstance(self.dossier_type, DossierType)

    def test_unique_type_constraint(self):
        """Vérifie que `type` est unique"""
        with self.assertRaises(IntegrityError):
            DossierType.objects.create(id=2, type="Permis de construire")

    def test_delete_dossier_type(self):
        """Vérifie qu'on peut supprimer un DossierType"""
        self.dossier_type.delete()
        with self.assertRaises(DossierType.DoesNotExist):
            DossierType.objects.get(id=1)


class GroupeTestCase(TestCase):

    def setUp(self):
        assert connection.settings_dict['NAME'] == 'test_autorisations'
        self.groupe = Groupe.objects.create(id=1, nom="Groupe A")

    def test_is_correct_instance(self):
        """Vérifie que l'objet créé est bien une instance de Groupe"""
        self.assertIsInstance(self.groupe, Groupe)

    def test_delete_groupe(self):
        """Vérifie qu'on peut supprimer un Groupe"""
        self.groupe.delete()
        with self.assertRaises(Groupe.DoesNotExist):
            Groupe.objects.get(id=1)



class DemarcheTestCase(TestCase):

    @classmethod
    def setUpTestData(cls):
        assert connection.settings_dict['NAME'] == 'test_autorisations'
        EtatDemarche.objects.all().delete()
        cls.etat = EtatDemarche.objects.create(id=1, nom="Initiée")
        cls.demarche = Demarche.objects.create(id=1, numero=100, titre="Demarche Test", id_etat=cls.etat, date_creation="2025-01-01", date_derniere_modif="2025-01-02")

    def test_is_correct_instance(self):
        """Vérifie que l'objet créé est bien une instance de Demarche"""
        self.assertIsInstance(self.demarche, Demarche)

    def test_unique_numero_constraint(self):
        """Vérifie que `numero` est unique"""
        with self.assertRaises(IntegrityError):
            Demarche.objects.create(id=2, numero=100, titre="Duplicate")

    def test_delete_demarche(self):
        """Vérifie qu'on peut supprimer une Demarche"""
        self.demarche.delete()
        with self.assertRaises(Demarche.DoesNotExist):
            Demarche.objects.get(id=1)



class DossierTestCase(TestCase):

    @classmethod
    def setUpTestData(cls):
        assert connection.settings_dict['NAME'] == 'test_autorisations'
        EtatDossier.objects.all().delete()
        DossierType.objects.all().delete()
        cls.etat = EtatDossier.objects.create(id=1, nom="Ouvert")
        cls.dossier_type = DossierType.objects.create(id=1, type="Type A")
        cls.dossier = Dossier.objects.create(id=1, 
                                             id_etat_dossier=cls.etat,
                                             numero=200,
                                             date_depot="2025-01-01",
                                             id_dossier_type=cls.dossier_type,
                                             nom_dossier="Dossier Test",
                                             emplacement="/path/test",
                                             date_limite_traitement="2025-03-11",)

    def test_is_correct_instance(self):
        """Vérifie que l'objet créé est bien une instance de Dossier"""
        self.assertIsInstance(self.dossier, Dossier)

    def test_unique_numero_constraint(self):
        """Vérifie que `numero` est unique"""
        with self.assertRaises(IntegrityError):
            Dossier.objects.create(id=2, numero=200, id_etat_dossier=self.etat, date_depot="2025-01-02", id_dossier_type=self.dossier_type, nom_dossier="Duplicate", emplacement="/path/duplicate")

    def test_delete_dossier(self):
        """Vérifie qu'on peut supprimer un Dossier"""
        self.dossier.delete()
        with self.assertRaises(Dossier.DoesNotExist):
            Dossier.objects.get(id=1)




class DemandeChampTestCase(TestCase):

    def setUp(self):
        assert connection.settings_dict['NAME'] == 'test_autorisations'
        self.champ_type = ChampType.objects.create(id=1, type="Texte")
        self.champ = Champ.objects.create(id=1, nom="Champ Test", id_champ_type=self.champ_type, description="Description")
        self.demande_champ = DemandeChamp.objects.create(id=1, valeur="Valeur Test", date_saisie="2025-01-01", id_champ=self.champ)

    def test_is_correct_instance(self):
        """Vérifie que l'objet créé est bien une instance de DemandeChamp"""
        self.assertIsInstance(self.demande_champ, DemandeChamp)

    def test_delete_demande_champ(self):
        """Vérifie qu'on peut supprimer une DemandeChamp"""
        self.demande_champ.delete()
        with self.assertRaises(DemandeChamp.DoesNotExist):
            DemandeChamp.objects.get(id=1)




class MessageTestCase(TestCase):

    def setUp(self):
        assert connection.settings_dict['NAME'] == 'test_autorisations'
        self.message = Message.objects.create(id=1, id_ds="MSG001", body="Message Test", date_envoi="2025-01-01", piece_jointe=False, email_emetteur="test@example.com")

    def test_is_correct_instance(self):
        """Vérifie que l'objet créé est bien une instance de Message"""
        self.assertIsInstance(self.message, Message)

    def test_delete_message(self):
        """Vérifie qu'on peut supprimer un Message"""
        self.message.delete()
        with self.assertRaises(Message.DoesNotExist):
            Message.objects.get(id=1)



class DossierGroupeTestCase(TestCase):

    def setUp(self):
        assert connection.settings_dict['NAME'] == 'test_autorisations'
        self.groupe = Groupe.objects.create(id=1, nom="Groupe Test")
        self.etat = EtatDossier.objects.create(id=1, nom="Ouvert")
        self.dossier_type = DossierType.objects.create(id=1, type="Type A")
        self.dossier = Dossier.objects.create(id=1, numero=200, id_etat_dossier=self.etat, date_depot="2025-01-01", id_dossier_type=self.dossier_type, nom_dossier="Dossier Test", emplacement="/path/test",date_limite_traitement="2025-03-11")
        self.dossier_groupe = DossierGroupe.objects.create(id_dossier=self.dossier, id_groupe=self.groupe)

    def test_is_correct_instance(self):
        """Vérifie que l'objet créé est bien une instance de DossierGroupe"""
        self.assertIsInstance(self.dossier_groupe, DossierGroupe)

    def test_delete_dossier_groupe(self):
        """Vérifie qu'on peut supprimer un DossierGroupe"""
        self.dossier_groupe.delete()
        with self.assertRaises(DossierGroupe.DoesNotExist):
            DossierGroupe.objects.get(id_dossier=self.dossier, id_groupe=self.groupe)




class DemandeTestCase(TestCase):

    @classmethod
    def setUpTestData(cls):
        """Initialisation des données de test pour Demande"""
        assert connection.settings_dict['NAME'] == 'test_autorisations'
        EtatDemande.objects.all().delete()
        Priorite.objects.all().delete()
        DemandeType.objects.all().delete()
        Dossier.objects.all().delete()

        cls.etat_dossier = EtatDossier.objects.create(id=1, nom="Ouvert")
        cls.dossier_type = DossierType.objects.create(id=1, type="Permis de construire")
        cls.etat_demande = EtatDemande.objects.create(id=1, nom="En attente")
        cls.priorite = Priorite.objects.create(id=1, niveau="Haute")
        cls.demande_type = DemandeType.objects.create(id=1, type="Dérogation")
        cls.dossier = Dossier.objects.create(id=1, numero=300, id_etat_dossier=cls.etat_dossier,
                                             date_depot="2025-01-01", id_dossier_type=cls.dossier_type,
                                             nom_dossier="Dossier Test", emplacement="/path/test",
                                             date_limite_traitement="2025-03-11")
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

    def test_is_correct_instance(self):
        """Vérifie que l'objet créé est bien une instance de Demande"""
        self.assertIsInstance(self.demande, Demande)

    def test_unique_interlocuteur_constraint(self):
        """Vérifie que `id_interlocuteur_ds` est unique"""
        with self.assertRaises(IntegrityError):
            Demande.objects.create(id=2, id_etat_demande=self.etat_demande,
                                   id_priorite=self.priorite,
                                   id_demande_type=self.demande_type,
                                   date_depot="2025-01-02",
                                   id_interlocuteur_ds="INT001")

    def test_delete_demande(self):
        """Vérifie qu'on peut supprimer une Demande"""
        self.demande.delete()
        with self.assertRaises(Demande.DoesNotExist):
            Demande.objects.get(id=1)



class ChampTestCase(TestCase):

    def setUp(self):
        assert connection.settings_dict['NAME'] == 'test_autorisations', "Django utilise la mauvaise base de données !"

        # Création des dépendances
        self.champ_type = ChampType.objects.create(id=1, type="Texte")

        # Création du champ
        self.champ = Champ.objects.create(
            id=1,
            id_ds="CHAMP001",
            nom="Champ Test",
            id_champ_type=self.champ_type,
            description="Champ de test",
        )

    def test_is_correct_instance(self):
        """Vérifie que l'objet créé est bien une instance de Champ"""
        self.assertIsInstance(self.champ, Champ)

    def test_exists(self):
        """Vérifie que l'objet existe bien en base"""
        champ_test = Champ.objects.get(id=1)
        self.assertTrue(champ_test)

    def test_unique_id_ds_constraint(self):
        """Vérifie que `id_ds` est unique"""
        with self.assertRaises(IntegrityError):
            Champ.objects.create(
                id=2,
                id_ds="CHAMP001",  # Même `id_ds`
                nom="Champ Duplicate",
                id_champ_type=self.champ_type,
                description="Autre champ"
            )

    def test_delete_champ(self):
        """Vérifie qu'on peut supprimer un Champ"""
        self.champ.delete()
        with self.assertRaises(Champ.DoesNotExist):
            Champ.objects.get(id=1)


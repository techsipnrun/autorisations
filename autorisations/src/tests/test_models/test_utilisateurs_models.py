from django.test import TestCase
from django.db import IntegrityError, connection
from autorisations.models.models_utilisateurs import AgentAutorisations, AgentAutorisationsUpdateLog, ContactExterne, DemandeBeneficiaire, DemandeInterlocuteur, DossierInstructeur, Groupeinstructeur, GroupeinstructeurDemarche, GroupeinstructeurInstructeur, Instructeur, TypeContactExterne
from autorisations.models.models_instruction import Demande, DemandeType, Demarche, Dossier, DossierType, EtatDemande, EtatDemarche, EtatDossier, Priorite

class AgentAutorisationsTestCase(TestCase):

    def setUp(self):
        assert connection.settings_dict['NAME'] == 'test_autorisations', "Django utilise la mauvaise base de données !"

        self.agent = AgentAutorisations.objects.create(
            id=1,
            acronyme="AGT",
            nom="Dupont",
            prenom="Jean",
            mail_1="jean.dupont@example.com"
        )

    def test_is_correct_instance(self):
        """Vérifie que l'objet créé est bien une instance de AgentAutorisations"""
        self.assertIsInstance(self.agent, AgentAutorisations)

    def test_exists(self):
        """Vérifie que l'objet existe bien en base"""
        agent_test = AgentAutorisations.objects.get(id=1)
        self.assertTrue(agent_test)

    def test_delete_agent(self):
        """Vérifie qu'on peut supprimer un AgentAutorisations"""
        self.agent.delete()
        with self.assertRaises(AgentAutorisations.DoesNotExist):
            AgentAutorisations.objects.get(id=1)



class TypeContactExterneTestCase(TestCase):

    def setUp(self):
        assert connection.settings_dict['NAME'] == 'test_autorisations', "Django utilise la mauvaise base de données !"

        self.type_contact = TypeContactExterne.objects.create(id=1, type="Entreprise")

    def test_is_correct_instance(self):
        """Vérifie que l'objet créé est bien une instance de TypeContactExterne"""
        self.assertIsInstance(self.type_contact, TypeContactExterne)

    def test_exists(self):
        """Vérifie que l'objet existe bien en base"""
        type_test = TypeContactExterne.objects.get(id=1)
        self.assertTrue(type_test)

    def test_unique_type_constraint(self):
        """Vérifie qu'on ne peut pas créer deux TypeContactExterne avec le même `type`"""
        with self.assertRaises(IntegrityError):
            TypeContactExterne.objects.create(id=2, type="Entreprise")

    def test_delete_type_contact(self):
        """Vérifie qu'on peut supprimer un TypeContactExterne"""
        self.type_contact.delete()
        with self.assertRaises(TypeContactExterne.DoesNotExist):
            TypeContactExterne.objects.get(id=1)



class ContactExterneTestCase(TestCase):

    def setUp(self):
        assert connection.settings_dict['NAME'] == 'test_autorisations', "Django utilise la mauvaise base de données !"

        self.type_contact = TypeContactExterne.objects.create(id=1, type="Entreprise")
        self.contact = ContactExterne.objects.create(
            id=1,
            email="contact@example.com",
            id_type=self.type_contact,
            nom="Martin",
            prenom="Paul"
        )

    def test_is_correct_instance(self):
        """Vérifie que l'objet créé est bien une instance de ContactExterne"""
        self.assertIsInstance(self.contact, ContactExterne)

    def test_unique_email_constraint(self):
        """Vérifie qu'on ne peut pas créer un ContactExterne avec le même `email`"""
        with self.assertRaises(IntegrityError):
            ContactExterne.objects.create(
                id=2,
                email="contact@example.com",
                id_type=self.type_contact,
                nom="Dupont",
                prenom="Jean"
            )

    def test_delete_contact(self):
        """Vérifie qu'on peut supprimer un ContactExterne"""
        self.contact.delete()
        with self.assertRaises(ContactExterne.DoesNotExist):
            ContactExterne.objects.get(id=1)



class InstructeurTestCase(TestCase):

    def setUp(self):
        assert connection.settings_dict['NAME'] == 'test_autorisations', "Django utilise la mauvaise base de données !"

        self.agent = AgentAutorisations.objects.create(id=1, nom="Dupont", prenom="Jean")
        self.instructeur = Instructeur.objects.create(
            id=1,
            id_ds="INS001",
            email="instructeur@example.com",
            id_agent_autorisations=self.agent
        )

    def test_is_correct_instance(self):
        """Vérifie que l'objet créé est bien une instance de Instructeur"""
        self.assertIsInstance(self.instructeur, Instructeur)

    def test_unique_email_constraint(self):
        """Vérifie qu'on ne peut pas créer un Instructeur avec le même `email`"""
        with self.assertRaises(IntegrityError):
            Instructeur.objects.create(
                id=2,
                id_ds="INS002",
                email="instructeur@example.com",
                id_agent_autorisations=self.agent
            )

    def test_delete_instructeur(self):
        """Vérifie qu'on peut supprimer un Instructeur"""
        self.instructeur.delete()
        with self.assertRaises(Instructeur.DoesNotExist):
            Instructeur.objects.get(id=1)



class DemandeInterlocuteurTestCase(TestCase):

    @classmethod
    def setUpTestData(cls):
        assert connection.settings_dict['NAME'] == 'test_autorisations', "Django utilise la mauvaise base de données !"

        EtatDemande.objects.all().delete()
        Demande.objects.all().delete()

        cls.type_contact = TypeContactExterne.objects.create(id=1, type="Entreprise")
        cls.contact_externe = ContactExterne.objects.create(
            id=1,
            email="contact@example.com",
            id_type=cls.type_contact,
            nom="Martin",
            prenom="Paul"
        )
        cls.etat_dossier = EtatDossier.objects.create(id=1, nom="Ouvert")
        cls.dossier_type = DossierType.objects.create(id=1, type="Permis de construire")
        cls.dossier = Dossier.objects.create(id=1, numero=300, id_etat_dossier=cls.etat_dossier,
                                             date_depot="2025-01-01", id_dossier_type=cls.dossier_type,
                                             nom_dossier="Dossier Test", emplacement="/path/test",
                                             date_limite_traitement="2025-03-11")
        
        cls.priorite = Priorite.objects.create(id=1, niveau="Haute")
        cls.etat_demande = EtatDemande.objects.create(id=1, nom="En attente")
        cls.demande_type = DemandeType.objects.create(id=1, type="Dérogation")
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

        cls.interlocuteur = DemandeInterlocuteur.objects.create(
            id_interlocuteur_ds="INT001",
            id_demande=cls.demande,
            id_demandeur_intermediaire=cls.contact_externe
        )

    def test_is_correct_instance(self):
        """Vérifie que l'objet créé est bien une instance de DemandeInterlocuteur"""
        self.assertIsInstance(self.interlocuteur, DemandeInterlocuteur)

    def test_unique_interlocuteur_constraint(self):
        """Vérifie qu'on ne peut pas créer un autre DemandeInterlocuteur avec le même `id_interlocuteur_ds`"""
        with self.assertRaises(IntegrityError):
            DemandeInterlocuteur.objects.create(id_interlocuteur_ds="INT001", id_demande=self.demande)

    def test_delete_interlocuteur(self):
        """Vérifie qu'on peut supprimer un DemandeInterlocuteur"""
        self.interlocuteur.delete()
        with self.assertRaises(DemandeInterlocuteur.DoesNotExist):
            DemandeInterlocuteur.objects.get(id_interlocuteur_ds="INT001")




class DemandeBeneficiaireTestCase(TestCase):

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
        self.interlocuteur = DemandeInterlocuteur.objects.create(id_interlocuteur_ds="INT001")

        self.beneficiaire = DemandeBeneficiaire.objects.create(
            id_demandeur_interlocuteur=self.interlocuteur,
            id_beneficiaire=self.contact_externe
        )

    def test_is_correct_instance(self):
        """Vérifie que l'objet créé est bien une instance de DemandeBeneficiaire"""
        self.assertIsInstance(self.beneficiaire, DemandeBeneficiaire)

    def test_delete_beneficiaire(self):
        """Vérifie qu'on peut supprimer un DemandeBeneficiaire"""
        self.beneficiaire.delete()
        with self.assertRaises(DemandeBeneficiaire.DoesNotExist):
            DemandeBeneficiaire.objects.get(id=self.beneficiaire.id)



class GroupeinstructeurTestCase(TestCase):

    def setUp(self):
        assert connection.settings_dict['NAME'] == 'test_autorisations', "Django utilise la mauvaise base de données !"

        self.groupe = Groupeinstructeur.objects.create(id=1, nom="Groupe A")

    def test_is_correct_instance(self):
        """Vérifie que l'objet créé est bien une instance de Groupeinstructeur"""
        self.assertIsInstance(self.groupe, Groupeinstructeur)

    def test_exists(self):
        """Vérifie que l'objet existe bien en base"""
        groupe_test = Groupeinstructeur.objects.get(id=1)
        self.assertTrue(groupe_test)

    def test_unique_nom_constraint(self):
        """Vérifie que `nom` est unique"""
        with self.assertRaises(IntegrityError):
            Groupeinstructeur.objects.create(id=2, nom="Groupe A")

    def test_delete_groupeinstructeur(self):
        """Vérifie qu'on peut supprimer un Groupeinstructeur"""
        self.groupe.delete()
        with self.assertRaises(Groupeinstructeur.DoesNotExist):
            Groupeinstructeur.objects.get(id=1)




class GroupeinstructeurDemarcheTestCase(TestCase):

    def setUp(self):
        assert connection.settings_dict['NAME'] == 'test_autorisations', "Django utilise la mauvaise base de données !"

        EtatDemarche.objects.all().delete()

        self.groupe = Groupeinstructeur.objects.create(id=1, nom="Groupe A")
        self.etat_demarche = EtatDemarche.objects.create(id=1, nom="Active")
        self.demarche = Demarche.objects.create(id=1, numero=101, titre="Demarche Test", id_etat=self.etat_demarche, date_creation="2025-01-01", date_derniere_modif="2025-01-02")

        self.groupe_demarche = GroupeinstructeurDemarche.objects.create(
            id_groupeinstructeur=self.groupe,
            id_demarche=self.demarche
        )

    def test_is_correct_instance(self):
        """Vérifie que l'objet créé est bien une instance de GroupeinstructeurDemarche"""
        self.assertIsInstance(self.groupe_demarche, GroupeinstructeurDemarche)

    def test_unique_relation_constraint(self):
        """Vérifie que la relation `id_groupeinstructeur, id_demarche` est unique"""
        with self.assertRaises(IntegrityError):
            GroupeinstructeurDemarche.objects.create(
                id_groupeinstructeur=self.groupe,
                id_demarche=self.demarche  # Même relation
            )

    def test_delete_groupe_demarche(self):
        """Vérifie qu'on peut supprimer une relation Groupeinstructeur-Demarche"""
        self.groupe_demarche.delete()
        with self.assertRaises(GroupeinstructeurDemarche.DoesNotExist):
            GroupeinstructeurDemarche.objects.get(id_groupeinstructeur=self.groupe, id_demarche=self.demarche)



class DossierInstructeurTestCase(TestCase):

    def setUp(self):
        assert connection.settings_dict['NAME'] == 'test_autorisations', "Django utilise la mauvaise base de données !"

        EtatDossier.objects.all().delete()
        DossierType.objects.all().delete()

        self.etat_dossier = EtatDossier.objects.create(id=1, nom="Ouvert")
        self.dossier_type = DossierType.objects.create(id=1, type="Type A")
        self.dossier = Dossier.objects.create(
            id=1, numero=200, id_etat_dossier=self.etat_dossier, 
            date_depot="2025-01-01", id_dossier_type=self.dossier_type, 
            nom_dossier="Dossier Test", emplacement="/path/test", date_limite_traitement="2025-03-11"
        )

        self.agent = AgentAutorisations.objects.create(id=1, nom="Dupont", prenom="Jean")
        self.instructeur = Instructeur.objects.create(
            id=1,
            id_ds="INS001",
            email="instructeur@example.com",
            id_agent_autorisations=self.agent
        )

        self.dossier_instructeur = DossierInstructeur.objects.create(
            id_dossier=self.dossier,
            id_instructeur=self.instructeur
        )

    def test_is_correct_instance(self):
        """Vérifie que l'objet créé est bien une instance de DossierInstructeur"""
        self.assertIsInstance(self.dossier_instructeur, DossierInstructeur)

    def test_unique_relation_constraint(self):
        """Vérifie que la relation `id_dossier, id_instructeur` est unique"""
        with self.assertRaises(IntegrityError):
            DossierInstructeur.objects.create(
                id_dossier=self.dossier,
                id_instructeur=self.instructeur  # Même relation
            )

    def test_delete_dossier_instructeur(self):
        """Vérifie qu'on peut supprimer une relation Dossier-Instructeur"""
        self.dossier_instructeur.delete()
        with self.assertRaises(DossierInstructeur.DoesNotExist):
            DossierInstructeur.objects.get(id_dossier=self.dossier, id_instructeur=self.instructeur)



class GroupeinstructeurInstructeurTestCase(TestCase):

    def setUp(self):
        assert connection.settings_dict['NAME'] == 'test_autorisations', "Django utilise la mauvaise base de données !"

        self.groupe = Groupeinstructeur.objects.create(id=1, nom="Groupe A")

        self.agent = AgentAutorisations.objects.create(id=1, nom="Dupont", prenom="Jean")
        self.instructeur = Instructeur.objects.create(
            id=1,
            id_ds="INS001",
            email="instructeur@example.com",
            id_agent_autorisations=self.agent
        )

        self.groupe_instructeur = GroupeinstructeurInstructeur.objects.create(
            id_groupeinstructeur=self.groupe,
            id_instructeur=self.instructeur
        )

    def test_is_correct_instance(self):
        """Vérifie que l'objet créé est bien une instance de GroupeinstructeurInstructeur"""
        self.assertIsInstance(self.groupe_instructeur, GroupeinstructeurInstructeur)

    def test_unique_relation_constraint(self):
        """Vérifie que la relation `id_groupeinstructeur, id_instructeur` est unique"""
        with self.assertRaises(IntegrityError):
            GroupeinstructeurInstructeur.objects.create(
                id_groupeinstructeur=self.groupe,
                id_instructeur=self.instructeur  # Même relation
            )

    def test_delete_groupe_instructeur(self):
        """Vérifie qu'on peut supprimer une relation Groupeinstructeur-Instructeur"""
        self.groupe_instructeur.delete()
        with self.assertRaises(GroupeinstructeurInstructeur.DoesNotExist):
            GroupeinstructeurInstructeur.objects.get(id_groupeinstructeur=self.groupe, id_instructeur=self.instructeur)

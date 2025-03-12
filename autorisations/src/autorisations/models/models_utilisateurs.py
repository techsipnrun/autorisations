from django.db import models

# from .models_instruction import Demande, Demarche, Dossier


class AgentAutorisations(models.Model):
    id = models.AutoField(primary_key=True)
    acronyme = models.CharField(blank=True, null=True)
    nom = models.CharField(blank=True, null=True)
    prenom = models.CharField(blank=True, null=True)
    mail_1 = models.CharField(blank=True, null=True)
    mail_2 = models.CharField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = '"utilisateurs"."agent_autorisations"'

    def __str__(self):
        return f"{self.nom} {self.prenom}" if self.nom and self.prenom else f"Agent {self.id}"


class AgentAutorisationsUpdateLog(models.Model):
    last_update = models.DateTimeField(blank=True, null=True, default=models.functions.Now)

    class Meta:
        managed = False
        db_table = '"utilisateurs"."agent_autorisations_update_log"'

    def __str__(self):
        return f"Last update: {self.last_update}"


class TypeContactExterne(models.Model):
    id = models.AutoField(primary_key=True)
    type = models.CharField(unique=True)

    class Meta:
        managed = False
        db_table = '"utilisateurs"."type_contact_externe"'

    def __str__(self):
        return self.type


class ContactExterne(models.Model):
    id = models.AutoField(primary_key=True)
    email = models.CharField(unique=True)
    id_type = models.ForeignKey(TypeContactExterne, models.RESTRICT, db_column='id_type')
    nom = models.CharField()
    prenom = models.CharField()
    adresse = models.CharField(blank=True, null=True)
    telephone = models.CharField(blank=True, null=True)
    siret = models.CharField(blank=True, null=True)
    organisation = models.CharField(blank=True, null=True)
    raison_sociale = models.CharField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = '"utilisateurs"."contact_externe"'

    def __str__(self):
        return f"{self.nom} {self.prenom} - {self.email}"


class DemandeInterlocuteur(models.Model):
    id = models.AutoField(primary_key=True)
    id_interlocuteur_ds = models.CharField(unique=True, blank=True, null=True)
    id_demande = models.ForeignKey('autorisations.Demande', models.SET_NULL, db_column='id_demande', blank=True, null=True)
    id_demandeur_intermediaire = models.ForeignKey(ContactExterne, models.SET_NULL, db_column='id_demandeur_intermediaire', blank=True, null=True)

    class Meta:
        managed = False
        db_table = '"utilisateurs"."demande_interlocuteur"'

    def __str__(self):
        return f"Interlocuteur {self.id_interlocuteur_ds}"


class DemandeBeneficiaire(models.Model):
    id = models.AutoField(primary_key=True)
    id_demande_interlocuteur = models.ForeignKey(DemandeInterlocuteur, models.CASCADE, db_column='id_demande_interlocuteur')
    id_beneficiare = models.ForeignKey(ContactExterne, models.SET_NULL, db_column='id_beneficiare', blank=True, null=True)

    class Meta:
        managed = False
        db_table = '"utilisateurs"."demande_beneficiare"'

    def __str__(self):
        return f"Bénéficiaire {self.id_beneficiare} pour demande {self.id_demandeur_interlocuteur}"


class Instructeur(models.Model):
    id = models.AutoField(primary_key=True)
    id_ds = models.CharField(unique=True, blank=True, null=True)
    email = models.CharField(unique=True)
    id_agent_autorisations = models.ForeignKey(AgentAutorisations, models.SET_NULL, db_column='id_agent_autorisations', blank=True, null=True)

    class Meta:
        managed = False
        db_table = '"utilisateurs"."instructeur"'

    def __str__(self):
        return self.email


class Groupeinstructeur(models.Model):
    id = models.AutoField(primary_key=True)
    nom = models.CharField(unique=True)

    class Meta:
        managed = False
        db_table = '"utilisateurs"."groupeinstructeur"'

    def __str__(self):
        return self.nom


class GroupeinstructeurDemarche(models.Model):
    id = models.AutoField(primary_key=True)
    id_groupeinstructeur_ds = models.CharField(unique=True, blank=True, null=True)
    id_groupeinstructeur = models.ForeignKey(Groupeinstructeur, models.CASCADE, db_column='id_groupeinstructeur')
    id_demarche = models.ForeignKey('autorisations.Demarche', models.CASCADE, db_column='id_demarche')

    class Meta:
        managed = False
        db_table = '"utilisateurs"."groupeinstructeur_demarche"'
        indexes = [
            models.Index(fields=['id_demarche', 'id_groupeinstructeur'], name='idx_Grpinstru_DemarcheUnique')
        ]

    def __str__(self):
        return f"Groupe {self.id_groupeinstructeur.nom} - Démarche {self.id_demarche.id}"


class GroupeinstructeurInstructeur(models.Model):
    id = models.AutoField(primary_key=True)
    id_groupeinstructeur = models.ForeignKey(Groupeinstructeur, models.CASCADE, db_column='id_groupeinstructeur')
    id_instructeur = models.ForeignKey(Instructeur, models.CASCADE, db_column='id_instructeur')

    class Meta:
        managed = False
        db_table = '"utilisateurs"."groupeinstructeur_instructeur"'
        indexes = [
            models.Index(fields=['id_groupeinstructeur', 'id_instructeur'], name='idx_GrpInstru_instru_unique')
        ]

    def __str__(self):
        return f"{self.id_instructeur.email} dans {self.id_groupeinstructeur.nom}"


class DossierInstructeur(models.Model):
    id = models.AutoField(primary_key=True)
    id_dossier = models.ForeignKey('autorisations.Dossier', models.CASCADE, db_column='id_dossier')
    id_instructeur = models.ForeignKey(Instructeur, models.CASCADE, db_column='id_instructeur')

    class Meta:
        managed = False
        db_table = '"utilisateurs"."dossier_instructeur"'
        indexes = [
            models.Index(fields=['id_dossier', 'id_instructeur'], name='idx_dossier_instructeur_unique')
        ]

    def __str__(self):
        return f"Instructeur {self.id_instructeur.email} pour Dossier {self.id_dossier.id}"
    



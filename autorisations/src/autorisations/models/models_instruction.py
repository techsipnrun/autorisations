from django.db import models

from django.apps import apps
from django.utils import timezone

from .models_avis import Avis

from .models_utilisateurs import Groupeinstructeur, Instructeur


class ChampType(models.Model):
    id = models.AutoField(primary_key=True)
    type = models.CharField(unique=True)

    class Meta:
        managed = False
        db_table = '"instruction"."champ_type"'

    def __str__(self):
        return self.type


class EtatDemande(models.Model):
    id = models.AutoField(primary_key=True)
    nom = models.CharField(unique=True)

    class Meta:
        managed = False
        db_table = '"instruction"."etat_demande"'

    def __str__(self):
        return self.nom.capitalize()


class EtatDemarche(models.Model):
    id = models.AutoField(primary_key=True)
    nom = models.CharField(unique=True)

    class Meta:
        managed = False
        db_table = '"instruction"."etat_demarche"'

    def __str__(self):
        return self.nom.capitalize()


class EtatDossier(models.Model):
    id = models.AutoField(primary_key=True)
    nom = models.CharField(unique=True)

    class Meta:
        managed = False
        db_table = '"instruction"."etat_dossier"'

    def __str__(self):
        return self.nom.capitalize()
    

class EtapeDossier(models.Model):
    id = models.AutoField(primary_key=True)
    etape = models.CharField(unique=True)

    class Meta:
        managed = False
        db_table = '"instruction"."etape_dossier"'

    def __str__(self):
        return self.etape


class Priorite(models.Model):
    id = models.AutoField(primary_key=True)
    niveau = models.CharField(unique=True)

    class Meta:
        managed = False
        db_table = '"instruction"."priorite"'

    def __str__(self):
        return self.niveau.capitalize()


class DemandeType(models.Model):
    id = models.AutoField(primary_key=True)
    type = models.CharField(unique=True)

    class Meta:
        managed = False
        db_table = '"instruction"."demande_type"'

    def __str__(self):
        return self.type


class Groupe(models.Model):
    id = models.AutoField(primary_key=True)
    nom = models.CharField()

    class Meta:
        managed = False
        db_table = '"instruction"."groupe"'

    def __str__(self):
        return self.nom


class Demarche(models.Model):
    id = models.AutoField(primary_key=True)
    id_ds = models.CharField(blank=True, null=True)
    numero = models.IntegerField(unique=True)
    titre = models.CharField()
    id_etat = models.ForeignKey(EtatDemarche, models.RESTRICT, db_column='id_etat')
    date_creation = models.DateTimeField()
    date_derniere_modif = models.DateTimeField()
    description = models.CharField(blank=True, null=True)
    delais_jours_instruction = models.IntegerField(blank=True, null=True)
    type = models.CharField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = '"instruction"."demarche"'

    def __str__(self):
        return f"Demarche {self.numero} - {self.titre}"


class DossierType(models.Model):
    id = models.AutoField(primary_key=True)
    type = models.CharField(unique=True)

    class Meta:
        managed = False
        db_table = '"instruction"."dossier_type"'

    def __str__(self):
        return self.type


class Dossier(models.Model):
    id = models.AutoField(primary_key=True)
    id_ds = models.CharField(unique=True, blank=True, null=True)
    id_etat_dossier = models.ForeignKey(EtatDossier, models.RESTRICT, db_column='id_etat_dossier')
    id_etape_dossier = models.ForeignKey(EtapeDossier, models.RESTRICT, db_column='id_etape_dossier', default=10)
    numero = models.IntegerField(unique=True)
    date_depot = models.DateTimeField()
    date_debut_instruction = models.DateTimeField(blank=True, null=True)
    date_fin_instruction = models.DateTimeField(blank=True, null=True)
    id_dossier_type = models.ForeignKey(DossierType, models.DO_NOTHING, db_column='id_dossier_type')
    # id_ds_dossier_parent = models.CharField(blank=True, null=True)
    id_dossier_parent = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, db_column='id_dossier_parent', related_name='dossiers_enfants')
    note = models.CharField(blank=True, null=True)
    nom_dossier = models.CharField()
    emplacement = models.CharField(unique=True)
    date_limite_traitement = models.DateTimeField()
    id_groupeinstructeur = models.ForeignKey(Groupeinstructeur, models.RESTRICT, db_column='id_groupeinstructeur')
    id_demarche = models.ForeignKey(Demarche, models.RESTRICT, db_column='id_demarche')
    geometrie = models.JSONField(blank=True, null=True)
    geometrie_modif = models.JSONField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = '"instruction"."dossier"'
        indexes = [
            models.Index(fields=['id_etat_dossier'], name='idx_dossier_id_etat'),
        ]

    def __str__(self):
        return f"Dossier {self.nom_dossier}"


class Demande(models.Model):
    id = models.AutoField(primary_key=True)
    id_etat_demande = models.ForeignKey(EtatDemande, models.RESTRICT, db_column='id_etat_demande')
    id_priorite = models.ForeignKey(Priorite, models.RESTRICT, db_column='id_priorite')
    id_demande_type = models.ForeignKey(DemandeType, models.RESTRICT, db_column='id_demande_type')
    date_depot = models.DateTimeField()
    date_fin_instruction = models.DateTimeField(blank=True, null=True)
    soumis_controle = models.BooleanField(default=False)
    id_dossier = models.ForeignKey(Dossier, models.CASCADE, db_column='id_dossier')
    suite_controle_conforme = models.BooleanField()
    numero_oscean = models.CharField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = '"instruction"."demande"'
        indexes = [
            models.Index(fields=['id_etat_demande'], name='idx_demande_id_etat'),
            models.Index(fields=['id_priorite'], name='idx_demande_id_priorite'),
        ]

    def __str__(self):
        return f"Demande {self.id} - {self.id_demande_type.type} (Dossier {self.id_dossier.numero})"


class Champ(models.Model):
    id = models.AutoField(primary_key=True)
    id_ds = models.CharField(unique=True, blank=True, null=True)
    nom = models.CharField()
    id_champ_type = models.ForeignKey(ChampType, models.RESTRICT, db_column='id_champ_type')
    description = models.CharField()
    id_demarche = models.ForeignKey(Demarche, models.SET_NULL, db_column='id_demarche', blank=True, null=True)
    requis = models.BooleanField()

    class Meta:
        managed = False
        db_table = '"instruction"."champ"'

    def __str__(self):
        return self.nom
    

class DemandeChamp(models.Model):
    id = models.AutoField(primary_key=True)
    valeur = models.CharField(blank=True, null=True)
    date_saisie = models.DateTimeField()
    geometrie = models.JSONField(blank=True, null=True)
    id_demande = models.ForeignKey(Demande, models.CASCADE, db_column='id_demande')
    id_champ = models.ForeignKey(Champ, models.CASCADE, db_column='id_champ')
    id_document = models.ForeignKey('autorisations.Document', models.SET_NULL, db_column='id_document', blank=True, null=True)

    class Meta:
        managed = False
        db_table = '"instruction"."demande_champ"'
        indexes = [
            models.Index(fields=['id_demande', 'id_champ'], name='idx_demande_champ_unique')
        ]

    def __str__(self):
        return f"Valeur '{self.valeur}' pour Demande {self.id_demande.id}"



class DossierChamp(models.Model):
    id = models.AutoField(primary_key=True)
    valeur = models.CharField(blank=True, null=True)
    date_saisie = models.DateTimeField()
    geometrie = models.JSONField(blank=True, null=True)
    geometrie_modif = models.JSONField(blank=True, null=True)
    id_dossier = models.ForeignKey(Dossier, models.CASCADE, db_column='id_dossier')
    id_champ = models.ForeignKey(Champ, models.CASCADE, db_column='id_champ')
    id_document = models.ForeignKey('autorisations.Document', models.SET_NULL, db_column='id_document', blank=True, null=True)

    class Meta:
        managed = False
        db_table = '"instruction"."dossier_champ"'
        indexes = [
            models.Index(fields=['id_dossier', 'id_champ'], name='idx_dossier_champ_unique')
        ]

    def __str__(self):
        return f"'{self.id_champ.nom}' : Dossier {self.id_dossier.numero}"



class Message(models.Model):
    id = models.AutoField(primary_key=True)
    id_ds = models.CharField(blank=True, null=True)
    body = models.CharField()
    date_envoi = models.DateTimeField()
    piece_jointe = models.BooleanField()
    email_emetteur = models.CharField()
    id_dossier = models.ForeignKey(Dossier, models.CASCADE, db_column='id_dossier', blank=True, null=True)
    id_avis = models.ForeignKey(Avis, models.CASCADE, db_column='id_avis', blank=True, null=True)
    lu = models.BooleanField()

    class Meta:
        managed = False
        db_table = '"instruction"."message"'

    def __str__(self):
        return f"Message {self.id} de {self.email_emetteur}"


class DossierGroupe(models.Model):
    id = models.AutoField(primary_key=True)
    id_dossier = models.ForeignKey(Dossier, models.CASCADE, db_column='id_dossier')
    id_groupe = models.ForeignKey(Groupe, models.CASCADE, db_column='id_groupe')

    class Meta:
        managed = False
        db_table = '"instruction"."dossier_groupe"'
        indexes = [
            models.Index(fields=['id_dossier', 'id_groupe'], name='idx_dossier_groupe_unique')
        ]

    def __str__(self):
        return f"{self.id_dossier} : Groupe '{self.id_groupe.nom}'"


class Action(models.Model):
    id = models.AutoField(primary_key=True)
    action = models.CharField(max_length=255)

    class Meta:
        managed = False
        db_table = '"instruction"."action"'

    def __str__(self):
        return self.action


class DossierAction(models.Model):
    id = models.AutoField(primary_key=True)
    id_dossier = models.ForeignKey(Dossier, models.CASCADE, db_column='id_dossier')
    date = models.DateTimeField(default=timezone.now)
    id_instructeur = models.ForeignKey(Instructeur, models.RESTRICT, db_column='id_instructeur')
    id_action = models.ForeignKey(Action, models.RESTRICT, db_column='id_action')
    description = models.TextField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = '"instruction"."dossier_actions"'

    def __str__(self):
        return (f"{self.id_action.action} - Dossier {self.id_dossier.numero} par {self.id_instructeur}")
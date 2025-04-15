from django.db import models
from django.core.exceptions import ValidationError

from .models_utilisateurs import ContactExterne, Instructeur


class AvisNature(models.Model):
    id = models.AutoField(primary_key=True)
    nature = models.CharField()

    class Meta:
        managed = False
        db_table = '"avis"."avis_nature"'

    def __str__(self):
        return self.nature.capitalize()


class AvisThematique(models.Model):
    id = models.AutoField(primary_key=True)
    thematique = models.CharField(unique=True)

    class Meta:
        managed = False
        db_table = '"avis"."avis_thematique"'

    def __str__(self):
        return self.thematique


class Expert(models.Model):
    id = models.AutoField(primary_key=True)
    id_expert_ds = models.CharField(unique=True, blank=True, null=True)
    est_interne = models.BooleanField()
    id_contact_externe = models.ForeignKey(
        ContactExterne, models.SET_NULL, db_column='id_contact_externe', blank=True, null=True
    )
    id_instructeur = models.ForeignKey(
        Instructeur, models.SET_NULL, db_column='id_instructeur', blank=True, null=True
    )

    class Meta:
        managed = False
        db_table = '"avis"."expert"'

    def clean(self):
        """
        Vérifie la validité des données avant la sauvegarde.
        """
        # Empêcher d'avoir les deux champs remplis
        if self.id_instructeur and self.id_contact_externe:
            raise ValidationError("Un expert ne peut pas être à la fois interne et externe.")

        # Empêcher que les deux champs soient vides
        if not self.id_instructeur and not self.id_contact_externe:
            raise ValidationError("Un expert doit être soit interne (id_instructeur renseigné), soit externe (id_contact_externe renseigné).")

        # Définir automatiquement 'est_interne'
        if self.id_instructeur:
            self.est_interne = True
        elif self.id_contact_externe:
            self.est_interne = False

    def save(self, *args, **kwargs):
        self.clean()  # Vérifier avant de sauvegarder
        super().save(*args, **kwargs)

    def __str__(self):
        if self.est_interne :
            return f"{self.id_instructeur} (Interne au Parc)"
        return f"{self.id_contact_externe}"



class Avis(models.Model):

    MODE_CONTACT_CHOICES = [
        ("Mail", "Mail"),
        ("Téléphone", "Téléphone"),
        ("Courrier papier", "Courrier papier"),
    ]

    id = models.AutoField(primary_key=True)
    id_ds = models.CharField(blank=True, null=True)
    id_avis_nature = models.ForeignKey(
        AvisNature, models.RESTRICT, db_column='id_avis_nature'
    )
    id_avis_thematique = models.ForeignKey(
        AvisThematique, models.RESTRICT, db_column='id_avis_thematique'
    )
    id_expert_ds = models.CharField(unique=True, blank=True, null=True)
    note = models.CharField(blank=True, null=True)
    favorable = models.BooleanField(blank=True, null=True)
    date_limite = models.DateTimeField()
    date_presentation = models.DateTimeField(blank=True, null=True)
    date_demande_avis = models.DateTimeField()
    date_reponse_avis = models.DateTimeField(blank=True, null=True)
    mode_contact = models.CharField(
        blank=True, null=True,
        max_length=20,
        choices=MODE_CONTACT_CHOICES,  # Ajout des choix
        default="Mail",  # Optionnel : valeur par défaut
    )
    id_dossier = models.ForeignKey('autorisations.Dossier', models.RESTRICT, db_column='id_dossier', blank=True, null=True)
    id_expert = models.ForeignKey(Expert, models.RESTRICT, db_column='id_expert')
    id_instructeur = models.ForeignKey(Instructeur, models.RESTRICT, db_column='id_instructeur')

    class Meta:
        managed = False
        db_table = '"avis"."avis"'
        indexes = [
            models.Index(fields=['id'], name='idx_id_avis'),
            models.Index(fields=['id_avis_nature'], name='idx_avis_id_nature'),
            models.Index(fields=['id_avis_thematique'], name='idx_avis_id_thematique'),
        ]
        verbose_name_plural = "Avis"

    def __str__(self):
        if self.id_expert.est_interne :
            return (
                f"{self.id_avis_nature.nature} {self.id} - Expert {self.id_expert.id_instructeur.id_agent_autorisations.prenom} "
                f"{self.id_expert.id_instructeur.id_agent_autorisations.nom} (Interne au Parc) {' : Favorable' if self.favorable else ''}"
            )
        return (
                f"{self.id_avis_nature.nature} {self.id} - Expert {self.id_expert.id_contact_externe.prenom} "
                f"{self.id_expert.id_contact_externe.nom} ({self.id_expert.id_contact_externe.id_type.type}) {' : Favorable' if self.favorable else ''}"
            )


class AvisDocument(models.Model):
    id = models.AutoField(primary_key=True)
    id_avis = models.ForeignKey(Avis, models.CASCADE, db_column='id_avis')
    id_document = models.ForeignKey('autorisations.Document', models.CASCADE, db_column='id_document')

    class Meta:
        managed = False
        db_table = '"avis"."avis_document"'
        indexes = [
            models.Index(fields=['id_avis', 'id_document'], name='idx_avis_document_unique')
        ]

    def __str__(self):

        if self.id_avis.id_expert.est_interne :
                return (f"{self.id_document.id_nature.nature} {self.id_document.id} : {self.id_avis.id_avis_nature.nature} {self.id_avis.id} " 
                        f"(Expert {self.id_avis.id_expert.id_instructeur.id_agent_autorisations.prenom} {self.id_avis.id_expert.id_instructeur.id_agent_autorisations.nom})")
        return (f"{self.id_document.id_nature.nature} {self.id_document.id} : {self.id_avis.id_avis_nature.nature} {self.id_avis.id} " 
                        f"(Expert {self.id_avis.id_expert.id_contact_externe.prenom} {self.id_avis.id_expert.id_contact_externe.nom} - {self.id_avis.id_expert.id_contact_externe.id_type.type})")


class DemandeAvis(models.Model):
    id = models.AutoField(primary_key=True)
    id_avis = models.ForeignKey(Avis, models.CASCADE, db_column='id_avis')
    id_demande = models.ForeignKey('autorisations.Demande', models.CASCADE, db_column='id_demande')

    class Meta:
        managed = False
        db_table = '"avis"."demande_avis"'
        # unique_together = (('id_avis', 'id_demande'),)
        indexes = [
            models.Index(fields=['id_avis', 'id_demande'], name='idx_demande_avis_unique')
        ]
        verbose_name_plural = "Demandes avis"

    def __str__(self):
        return f"Demande {self.id_demande.id} associée à Avis {self.id_avis.id}"

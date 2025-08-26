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

        # cohérence avec est_interne
        if self.est_interne is True and not self.id_instructeur:
            raise ValidationError("Si l'expert est interne, alors 'id_instructeur' doit être renseigné.")

        if self.est_interne is False and not self.id_contact_externe:
            raise ValidationError("Si l'expert est externe, alors 'id_contact_externe' doit être renseigné.")
    
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
            return f"Expert.e : {self.id_instructeur} (Interne au Parc)"
        return f"Expert.e : {self.id_contact_externe}"



class Avis(models.Model):

    MODE_CONTACT_CHOICES = [
        ("Application", "Application"),
        ("Mail", "Mail"),
        ("Téléphone", "Téléphone"),
        ("Courrier papier", "Courrier papier"),
    ]

    STATUT_CHOICES = [
        ("Brouillon", "Brouillon"),
        ("Envoyé", "Envoyé"),
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
    date_limite = models.DateTimeField(blank=True, null=True)
    date_presentation = models.DateTimeField(blank=True, null=True)
    date_demande_avis = models.DateTimeField(blank=True, null=True)
    date_reponse_avis = models.DateTimeField(blank=True, null=True)
    mode_contact = models.CharField(
        blank=True, null=True,
        max_length=20,
        choices=MODE_CONTACT_CHOICES,  # Ajout des choix
        default="Application",  # Optionnel : valeur par défaut
    )
    statut = models.CharField(
        max_length=10,
        choices=STATUT_CHOICES,
        default="Brouillon",
    )
    formulation = models.TextField()
    id_dossier = models.ForeignKey('autorisations.Dossier', models.CASCADE, db_column='id_dossier', blank=True, null=True)
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

    def clean(self):

        if self.statut == "Brouillon":
            # Obligatoires
            champs_obligatoires = {
                "id_avis_nature": self.id_avis_nature,
                "id_avis_thematique": self.id_avis_thematique,
                "mode_contact": self.mode_contact,
                "id_dossier": self.id_dossier,
                "id_instructeur": self.id_instructeur,
            }
        elif self.statut == "Envoyé":
            champs_obligatoires = {
                "id_avis_nature": self.id_avis_nature,
                "id_avis_thematique": self.id_avis_thematique,
                "mode_contact": self.mode_contact,
                "id_dossier": self.id_dossier,
                "date_demande_avis": self.date_demande_avis,
                "id_expert": self.id_expert,
                "id_instructeur": self.id_instructeur,
            }
        else:
            champs_obligatoires = {}

        erreurs = {}
        for champ, valeur in champs_obligatoires.items():
            if not valeur:
                erreurs[champ] = f"{champ} est obligatoire quand le statut est {self.statut}"

        if erreurs:
            raise ValidationError(erreurs)
        

    def __str__(self):
        avis_id = f" {self.pk}" if self.pk else ""
        if self.id_expert.est_interne :
            return (
                f"{self.id_avis_nature.nature} {avis_id} - Expert {self.id_expert.id_instructeur.id_agent_autorisations.prenom} "
                f"{self.id_expert.id_instructeur.id_agent_autorisations.nom} (Interne au Parc) {' : Favorable' if self.favorable else ''}"
            )
        return (
                f"{self.id_avis_nature.nature} {avis_id} - Expert {self.id_expert.id_contact_externe.prenom} "
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


class DossierAvis(models.Model):
    id = models.AutoField(primary_key=True)
    id_avis = models.ForeignKey(Avis, models.CASCADE, db_column="id_avis")
    id_dossier = models.ForeignKey(
        "autorisations.Dossier", models.CASCADE, db_column="id_dossier"
    )

    class Meta:
        managed = False
        db_table = '"avis"."dossier_avis"'
        constraints = [
            models.UniqueConstraint(
                fields=["id_avis", "id_dossier"], name="dossier_avis_unique"
            )
        ]
        indexes = [
            models.Index(fields=["id_avis"], name="idx_dossier_avis_id_avis"),
            models.Index(fields=["id_dossier"], name="idx_dossier_avis_id_dossier"),
        ]
        verbose_name_plural = "Dossiers avis"

    def __str__(self):
        return f"Dossier {self.id_dossier.numero} associée à l'avis {self.id_avis.id}"


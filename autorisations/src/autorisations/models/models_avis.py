from django.db import models
from django.core.exceptions import ValidationError
import uuid

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
    demarche = models.CharField(blank=True, null=True)

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
            return f"{self.id_instructeur}"
        return f"{self.id_contact_externe}"



class Avis(models.Model):

    class Destinataire(models.TextChoices):
        CS = "CS", "CS"
        BCS = "BCS", "BCS"

    class Reponse(models.TextChoices):
        FAVORABLE = "favorable", "Favorable"
        FAVORABLE_SOUS_RESERVE = "favorable_sous_reserve", "Favorable sous réserve"
        DEFAVORABLE = "defavorable", "Défavorable"
        ABSENCE_AVIS_EN_ETAT = "absence_avis_en_etat", "Absence d’avis en l’état"

    MODE_CONTACT_CHOICES = [
        ("Application", "Application"),
        ("Mail", "Mail"),
        ("Téléphone", "Téléphone"),
        ("Courrier papier", "Courrier papier"),
        ("Autre", "Autre"),
    ]

    STATUT_CHOICES = [
        ("Brouillon", "Brouillon"),
        ("Envoyé", "Envoyé"),
        ("À valider", "À valider"),
        ("À envoyer", "À envoyer"),
    ]

    id = models.AutoField(primary_key=True)
    id_ds = models.CharField(blank=True, null=True)
    numero_avis_externe = models.CharField(max_length=100, blank=True, null=True)
    id_avis_nature = models.ForeignKey(AvisNature, models.RESTRICT, db_column='id_avis_nature')
    id_avis_thematique = models.ForeignKey(AvisThematique, models.RESTRICT, db_column='id_avis_thematique')
    id_expert_ds = models.CharField(unique=True, blank=True, null=True)
    note = models.CharField(blank=True, null=True)
    reponse = models.CharField(max_length=30, choices=Reponse.choices, blank=True, null=True)
    publie_au_raa = models.BooleanField(blank=True, null=True)
    date_limite = models.DateTimeField(blank=True, null=True)
    date_presentation = models.DateTimeField(blank=True, null=True)
    date_demande_avis = models.DateTimeField(blank=True, null=True)
    date_reponse_avis = models.DateTimeField(blank=True, null=True)
    date_transmission_cs = models.DateTimeField(blank=True, null=True)
    destinataire = models.CharField(max_length=3, choices=Destinataire.choices, blank=True, null=True)
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
    emplacement = models.CharField()
    id_dossier = models.ForeignKey('autorisations.Dossier', models.SET_NULL, db_column='id_dossier', blank=True, null=True)
    id_demarche = models.ForeignKey('autorisations.Demarche', models.SET_NULL, db_column='id_demarche', blank=True, null=True)
    id_expert = models.ForeignKey(Expert, models.RESTRICT, db_column='id_expert')
    id_instructeur = models.ForeignKey(Instructeur, models.RESTRICT, db_column='id_instructeur')
    id_projet_acte = models.ForeignKey('autorisations.Document', models.SET_NULL, db_column='id_projet_acte', blank=True, null=True, related_name='avis_projet_acte_set')
    id_rapport_instance = models.ForeignKey('autorisations.Document', models.SET_NULL, db_column='id_rapport_instance', blank=True, null=True, related_name='avis_rapport_instance_set')
    id_projet_avis = models.ForeignKey('autorisations.Document', models.SET_NULL, db_column='id_projet_avis', blank=True, null=True, related_name='avis_projet_avis_set')

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
                # "id_dossier": self.id_dossier,
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
    
    @property
    def numero_affiche(self):
        return (self.numero_avis_externe or "").strip() or (str(self.pk) if self.pk is not None else "")

    @property
    def demarche_effective(self):
        if self.id_demarche:
            return self.id_demarche
        da = self.dossieravis_set.first()
        return da.id_dossier.id_demarche if da else None

    def __str__(self):
        avis_id = f" {self.numero_affiche}" if self.numero_affiche else ""
        if self.id_expert.est_interne :
            return (
                f"{self.id_avis_nature.nature} {avis_id} - Expert {self.id_expert.id_instructeur} "
                f" (Interne au Parc){' : ' + self.get_reponse_display() if self.reponse else ''}"
            )
        return (
                f"{self.id_avis_nature.nature} {avis_id} - Expert {self.id_expert} "
                f"{' : ' + self.get_reponse_display() if self.reponse else ''}"
            )


class AvisFormulaireConfiguration(models.Model):
    code = models.CharField(max_length=20, unique=True, choices=(("dossier", "Depuis un dossier"), ("generique", "Demande générique"), ("existant", "Ajouter un avis existant")))
    nom = models.CharField(max_length=100)

    class Meta:
        managed = False
        db_table = '"avis"."avis_formulaire_configuration"'
        verbose_name = "Configuration de formulaire d'avis"

    def __str__(self):
        return self.nom


class AvisFormulaireChamp(models.Model):
    id_configuration = models.ForeignKey(AvisFormulaireConfiguration, models.CASCADE, db_column="id_configuration", related_name="champs")
    code = models.CharField(max_length=40)
    ordre = models.PositiveSmallIntegerField(default=0)
    libelle = models.CharField(max_length=180)
    aide = models.TextField(blank=True, default="")
    placeholder = models.TextField(blank=True, default="")
    choix_autorises = models.JSONField(blank=True, null=True, default=None)  # Compatibilité : listes désormais issues d'AvisThematique.
    visible = models.BooleanField(default=True)
    requis_brouillon = models.BooleanField(default=False)
    requis_envoi = models.BooleanField(default=False)
    defaut = models.TextField(blank=True, default="")
    regles = models.JSONField(default=list, blank=True)

    class Meta:
        managed = False
        db_table = '"avis"."avis_formulaire_champ"'
        ordering = ("ordre", "id")
        constraints = [models.UniqueConstraint(fields=("id_configuration", "code"), name="avis_formulaire_champ_unique")]
        verbose_name = "Champ de formulaire d'avis"

    def __str__(self):
        return self.libelle

    def clean(self):
        super().clean()
        if not self.id_configuration_id:
            return
        from instruction.utils.avis_formulaires import configuration_standard, verifier_configuration
        standards = configuration_standard(self.id_configuration.code)
        if self.code not in {champ["code"] for champ in standards}:
            raise ValidationError({"code": "Champ de formulaire inconnu."})
        champs = [{cle: getattr(self, cle) for cle in champ} if champ["code"] == self.code else champ for champ in standards]
        verifier_configuration(self.id_configuration.code, champs)


class AvisReservation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    numero = models.PositiveIntegerField(unique=True)
    id_instructeur = models.ForeignKey(Instructeur, models.RESTRICT, db_column="id_instructeur")
    contexte = models.CharField(max_length=10, choices=(("generique", "Générique"), ("dossier", "Dossier")))
    id_dossier = models.ForeignKey("autorisations.Dossier", models.SET_NULL, db_column="id_dossier", null=True, blank=True)
    date_creation = models.DateTimeField(auto_now_add=True)
    date_utilisation = models.DateTimeField(null=True, blank=True)
    id_avis = models.OneToOneField(Avis, models.SET_NULL, db_column="id_avis", null=True, blank=True)

    class Meta:
        managed = False
        db_table = '"avis"."avis_reservation"'
        verbose_name = "Réservation de numéro d'avis"
        verbose_name_plural = "Réservations de numéros d'avis"

    def __str__(self):
        return str(self.numero)


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
                return (f"{self.id_document.id_nature.nature} {self.id_document.id} : {self.id_avis.id_avis_nature.nature} {self.id_avis.numero_affiche} "
                        f"(Expert {self.id_avis.id_expert.id_instructeur.id_agent_autorisations.prenom} {self.id_avis.id_expert.id_instructeur.id_agent_autorisations.nom})")
        return (f"{self.id_document.id_nature.nature} {self.id_document.id} : {self.id_avis.id_avis_nature.nature} {self.id_avis.numero_affiche} "
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
        return f"Dossier {self.id_dossier.numero} associée à l'avis {self.id_avis.numero_affiche}"


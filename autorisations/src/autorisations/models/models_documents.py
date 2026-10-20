from django.db import models
from django.db.models import Max
from datetime import date
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.core.validators import RegexValidator
from django.core.exceptions import ValidationError
import re

from .models_utilisateurs import DossierRelecteur

from .models_instruction import Dossier, DossierManifSportive, DossierNote, Message


class DocumentFormat(models.Model):
    id = models.AutoField(primary_key=True)
    format = models.CharField(unique=True)

    class Meta:
        managed = False
        db_table = '"documents"."document_format"'

    def __str__(self):
        return self.format


class DocumentNature(models.Model):
    class Numerotation(models.TextChoices):
        AUTOMATIQUE = "automatique", "Automatique"
        MANUELLE = "manuelle", "Manuelle"

    class CircuitSignature(models.TextChoices):
        DIRECTION = "direction", "Direction"
        CA = "ca", "Conseil d’administration"

    class PublicationRAA(models.TextChoices):
        MANUELLE = "manuelle", "Publication à effectuer dans AGIDA"
        DEJA_REALISEE = "deja_realisee", "Publication considérée comme déjà réalisée hors AGIDA"
        NON_REQUISE = "non_requise", "Publication non requise"

    id = models.AutoField(primary_key=True)
    nature = models.CharField(unique=True)
    est_acte = models.BooleanField(default=False, verbose_name="Type d’acte")
    actif = models.BooleanField(default=True)
    mode_numerotation = models.CharField(max_length=12, choices=Numerotation.choices, default=Numerotation.AUTOMATIQUE)
    ordre_affichage = models.PositiveSmallIntegerField(default=0)
    circuit_signature = models.CharField(max_length=20, choices=CircuitSignature.choices, default=CircuitSignature.DIRECTION)
    rapport_ca_obligatoire = models.BooleanField(default=False)
    mode_publication_raa = models.CharField(max_length=20, choices=PublicationRAA.choices, default=PublicationRAA.MANUELLE)
    autorise_dm = models.BooleanField(default=False, verbose_name="Autoriser l’envoi de l’acte sur DM")
    prefixe_numero = models.CharField(
        max_length=50, blank=True, default="",
        verbose_name="Préfixe du numéro",
        help_text="Préfixe affiché dans l’application, séparateur inclus (ex. DIR-I- ou CA/).",
    )
    prefixe_nom_fichier = models.CharField(
        max_length=50, blank=True, default="",
        verbose_name="Préfixe du nom de fichier",
        help_text="Préfixe des nouveaux fichiers signés, séparateur inclus (ex. DELIB-CA-).",
        validators=[RegexValidator(
            regex=r'[\\/:*?"<>|\x00-\x1f]', inverse_match=True,
            message="Le préfixe ne doit pas contenir de caractère interdit dans un nom de fichier.",
        )],
    )

    class Meta:
        managed = False
        db_table = '"documents"."document_nature"'

    def __str__(self):
        return self.nature

    @property
    def signature_ca(self):
        return self.circuit_signature == self.CircuitSignature.CA

    @property
    def numerotation_manuelle(self):
        return self.mode_numerotation == self.Numerotation.MANUELLE

    @property
    def publication_raa_requise(self):
        return self.mode_publication_raa == self.PublicationRAA.MANUELLE

    def formater_numero(self, numero):
        if not numero:
            return ""
        prefixe = self.prefixe_numero or ""
        return numero if numero.startswith(prefixe) else f"{prefixe}{numero}"

    def formater_nom_acte(self, numero, suffixe_date):
        # Contrôle aussi les configurations saisies directement en SQL.
        self._meta.get_field("prefixe_nom_fichier").clean(self.prefixe_nom_fichier, self)
        # La référence affichée reste intacte ; seuls les noms NAS sont nettoyés.
        reference_fichier = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '-', numero or '').strip(' .')
        if not reference_fichier:
            raise ValidationError("Le numéro de l'acte ne permet pas de former un nom de fichier.")
        return f"{self.prefixe_nom_fichier}{reference_fichier}_{suffixe_date}"
    
class DocumentStatut(models.Model):
    id = models.AutoField(primary_key=True)
    statut = models.CharField(unique=True)

    class Meta:
        managed = False
        db_table = '"documents"."document_statut"'

    def __str__(self):
        return self.statut


class Document(models.Model):
    id = models.AutoField(primary_key=True)
    id_format = models.ForeignKey(DocumentFormat, models.RESTRICT, db_column='id_format')
    id_nature = models.ForeignKey(DocumentNature, models.RESTRICT, db_column='id_nature')
    id_statut = models.ForeignKey(DocumentStatut, models.RESTRICT, db_column='id_statut', blank=True, null=True)
    url_ds = models.CharField(blank=True, null=True)
    url_dm = models.CharField(blank=True, null=True)
    emplacement = models.CharField()
    description = models.CharField(blank=True, null=True)
    numero = models.CharField(blank=True, null=True)
    numero_reference = models.CharField(max_length=150, blank=True, null=True)
    id_document_reference = models.ForeignKey(
        'self', models.SET_NULL, db_column='id_document_reference',
        blank=True, null=True, related_name='references_reprises',
    )
    titre = models.CharField()
    publie_au_raa = models.BooleanField(default=False)
    date = models.DateTimeField(default=timezone.now)
    pj_dm_id = models.IntegerField(unique=True, blank=True, null=True)

    @property
    def numero_affiche(self):
        return self.id_nature.formater_numero(self.numero_effectif)

    @property
    def numero_effectif(self):
        return self.numero_reference if self.id_nature.numerotation_manuelle else self.numero

    class Meta:
        managed = False
        db_table = '"documents"."document"'
        indexes = [
            models.Index(fields=['id_format'], name='idx_document_id_format'),
            models.Index(fields=['id_nature'], name='idx_document_id_nature'),
        ]

    @staticmethod
    def normaliser_emplacement(emplacement: str | None) -> str:
        """
        Uniformise les séparateurs de chemin :
        - remplace les \\ par /
        - supprime les doublons éventuels //
        - supprime les espaces inutiles
        - garantit une terminaison par /
        """
        if not emplacement:
            return "/"

        emplacement = emplacement.strip().replace("\\", "/")

        while "//" in emplacement:
            emplacement = emplacement.replace("//", "/")

        if not emplacement.endswith("/"):
            emplacement += "/"

        return emplacement
    
    @staticmethod
    def prochain_numero(dernier_numero, annee):
        """Même calcul pour l'attribution effective et l'aperçu du back-office."""
        compteur = 1000
        if dernier_numero:
            try:
                compteur = int(dernier_numero.split('-')[-1]) + 1
            except ValueError:
                pass
        return f"{annee}-{compteur:04d}"

    def save(self, *args, **kwargs):
        """
        Incrémente automatiquement le numéro au format AAAA-XXXX
        pour les natures configurées comme actes.
        Si la nature du document change, le numéro est régénéré.
        """

        self.emplacement = self.normaliser_emplacement(self.emplacement)
        
        annee = date.today().year
        nature_actuelle = self.id_nature_id

        # Récupère la nature précédente si le doc existe déjà
        ancienne_nature = None
        if self.pk:
            try:
                ancien_doc = Document.objects.only("id_nature").get(pk=self.pk)
                ancienne_nature = ancien_doc.id_nature_id
            except Document.DoesNotExist:
                pass

        nature_changee = self.pk is not None and ancienne_nature != nature_actuelle

        # Nouveau document cible OU changement de nature
        if self.id_nature.est_acte and self.id_nature.numerotation_manuelle:
            self.numero = None
            if nature_changee:
                self.id_document_reference_id = None
        elif (not self.numero or nature_changee) and self.id_nature.est_acte:
            for _ in range(3):
                dernier = (
                    Document.objects
                    .filter(
                        id_nature=self.id_nature,
                        numero__startswith=str(annee)
                    )
                    .aggregate(max_num=Max('numero'))
                )

                self.numero = self.prochain_numero(dernier["max_num"], annee)

                try:
                    with transaction.atomic():
                        return super().save(*args, **kwargs)
                except IntegrityError:
                    self.numero = None
                    
            raise IntegrityError("Impossible de générer un numéro unique.")

        super().save(*args, **kwargs)


    def __str__(self):
        if self.numero_effectif:
            return f"{self.id_nature} {self.numero_effectif} - {self.emplacement}{self.titre}"
        return f"{self.id_nature} - {self.emplacement}{self.titre}" #Extraire le nom du dossier du Path


class DossierDocument(models.Model):
    id = models.AutoField(primary_key=True)
    id_dossier = models.ForeignKey(
        Dossier, models.CASCADE, db_column='id_dossier'
    )
    id_document = models.ForeignKey(
        Document, models.CASCADE, db_column='id_document'
    )

    class Meta:
        managed = False
        db_table = '"documents"."dossier_document"'
        indexes = [
            models.Index(fields=['id_dossier', 'id_document'], name='idx_dossier_document_unique')
        ]

    def __str__(self):
        return f"{self.id_document.id_nature.nature} {self.id_document.id} lié à {self.id_dossier}"
    

class DossierManifSportiveDocument(models.Model):
    id = models.AutoField(primary_key=True)
    id_dossier_manif_sportive = models.ForeignKey(DossierManifSportive, models.CASCADE, db_column='id_dossier_manif_sportive')
    id_document = models.ForeignKey(Document, models.CASCADE, db_column='id_document')

    class Meta:
        managed = False
        db_table = '"documents"."dossier_manif_sportive_document"'
        indexes = [
            models.Index(fields=['id_dossier_manif_sportive', 'id_document'],
                name='dossier_dm_document_unique_idx'
            )
        ]

    def __str__(self):
        return (
            f"{self.id_document.id_nature.nature} {self.id_document.id} "
            f"lié au dossier manif sportive {self.id_dossier_manif_sportive.numero_dossier_declaration_manifestations} {self.id_dossier_manif_sportive}"
        )
    
    


class MessageDocument(models.Model):
    id_document = models.ForeignKey(Document, models.CASCADE, db_column='id_document')
    id_message = models.ForeignKey(Message, models.CASCADE, db_column='id_message')

    class Meta:
        managed = False
        db_table = '"documents"."message_document"'
        indexes = [
            models.Index(fields=['id_message', 'id_document'], name='idx_message_document_unique')
        ]

    def __str__(self):
        return f"Document {self.id_document.id} attaché à Message {self.id_message.id}"


class DossierRelecteurDocument(models.Model):
    id = models.AutoField(primary_key=True)
    id_dossier_relecteur = models.ForeignKey(DossierRelecteur, models.CASCADE, db_column="id_dossier_relecteur")
    id_document = models.ForeignKey(Document, models.CASCADE, db_column="id_document")

    class Meta:
        managed = False
        db_table = '"documents"."dossier_relecteur_document"'
        

    def __str__(self):
        return f"Document {self.id_document.titre} lié à la relecture du dossier {self.id_dossier_relecteur.id_dossier} par {self.id_dossier_relecteur.id_instructeur}"

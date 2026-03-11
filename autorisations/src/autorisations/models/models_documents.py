from django.db import models
from django.db.models import Max
from datetime import date
from django.db import IntegrityError, transaction

from .models_utilisateurs import DossierRelecteur

from .models_instruction import Dossier, DossierNote, Message


class DocumentFormat(models.Model):
    id = models.AutoField(primary_key=True)
    format = models.CharField(unique=True)

    class Meta:
        managed = False
        db_table = '"documents"."document_format"'

    def __str__(self):
        return self.format


class DocumentNature(models.Model):
    id = models.AutoField(primary_key=True)
    nature = models.CharField(unique=True)

    class Meta:
        managed = False
        db_table = '"documents"."document_nature"'

    def __str__(self):
        return self.nature
    
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
    emplacement = models.CharField()
    description = models.CharField(blank=True, null=True)
    numero = models.CharField(blank=True, null=True)
    titre = models.CharField()
    publie_au_raa = models.BooleanField(default=False)

    class Meta:
        managed = False
        db_table = '"documents"."document"'
        indexes = [
            models.Index(fields=['id_format'], name='idx_document_id_format'),
            models.Index(fields=['id_nature'], name='idx_document_id_nature'),
        ]
    
    def save(self, *args, **kwargs):
        """
        Incrémente automatiquement le numéro au format AAAA-XXXX
        pour les natures : 'Arrêté directeur', 'Déliberation CA', 'Avis simple', 'Avis conforme'.
        Si la nature du document change, le numéro est régénéré.
        """
        natures_cibles = ["Arrêté directeur", "Déliberation CA", "Avis simple", "Avis conforme"]
        annee = date.today().year
        nature_actuelle = self.id_nature.nature if self.id_nature else None

        # Récupère la nature précédente si le doc existe déjà
        ancienne_nature = None
        if self.pk:
            try:
                ancien_doc = Document.objects.get(pk=self.pk)
                ancienne_nature = ancien_doc.id_nature.nature if ancien_doc.id_nature else None
            except Document.DoesNotExist:
                pass

        nature_changee = (ancienne_nature != nature_actuelle)

        # Nouveau document cible OU changement de nature
        if (not self.numero or nature_changee) and nature_actuelle in natures_cibles:
            for _ in range(3):
                dernier = (
                    Document.objects
                    .filter(
                        id_nature=self.id_nature,
                        numero__startswith=str(annee)
                    )
                    .aggregate(max_num=Max('numero'))
                )

                dernier_num = dernier["max_num"]
                if dernier_num:
                    try:
                        last_counter = int(dernier_num.split('-')[-1])
                        nouveau_num = f"{annee}-{last_counter + 1:04d}"
                    except ValueError:
                        nouveau_num = f"{annee}-1000"
                else:
                    nouveau_num = f"{annee}-1000"

                self.numero = nouveau_num

                try:
                    with transaction.atomic():
                        return super().save(*args, **kwargs)
                except IntegrityError:
                    self.numero = None
                    
            raise IntegrityError("Impossible de générer un numéro unique.")

        super().save(*args, **kwargs)


    def __str__(self):
        if self.numero :
            return f"{self.id_nature} {self.numero} - {self.emplacement}{self.titre}"  #Extraire le nom du dossier du Path
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


class MessageDocument(models.Model):
    id_document = models.ForeignKey(
        Document, models.CASCADE, db_column='id_document'
    )
    id_message = models.ForeignKey(
        Message, models.CASCADE, db_column='id_message'
    )

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
    id_dossier_relecteur = models.ForeignKey(
        DossierRelecteur, models.CASCADE, db_column="id_dossier_relecteur"
    )
    id_document = models.ForeignKey(
        Document, models.CASCADE, db_column="id_document"
    )

    class Meta:
        managed = False
        db_table = '"documents"."dossier_relecteur_document"'
        

    def __str__(self):
        return f"Document {self.id_document.titre} lié à la relecture du dossier {self.id_dossier_relecteur.id_dossier} par {self.id_dossier_relecteur.id_instructeur}"
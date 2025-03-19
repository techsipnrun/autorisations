from django.db import models

from .models_instruction import Dossier, Message


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


class Document(models.Model):
    id = models.AutoField(primary_key=True)
    id_format = models.ForeignKey(
        DocumentFormat, models.RESTRICT, db_column='id_format', blank=True, null=True
    )
    id_nature = models.ForeignKey(
        DocumentNature, models.RESTRICT, db_column='id_nature', blank=True, null=True
    )
    url_ds = models.CharField(blank=True, null=True)
    emplacement = models.CharField(unique=True)
    description = models.CharField(blank=True, null=True)
    numero = models.CharField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = '"documents"."document"'
        indexes = [
            models.Index(fields=['id_format'], name='idx_document_id_format'),
            models.Index(fields=['id_nature'], name='idx_document_id_nature'),
        ]

    def __str__(self):
        if self.numero :
            return f"{self.id_nature} {self.numero} - {self.emplacement}"  #Extraire le nom du dossier du Path
        return f"{self.id_nature} - {self.emplacement}" #Extraire le nom du dossier du Path


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
        return f"Document {self.id_document.id} lié à Dossier {self.id_dossier.id}"


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

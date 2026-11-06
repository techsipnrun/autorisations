"""Catalogue de génération : tables créées manuellement par script SQL."""

from pathlib import PurePosixPath
import re
import uuid

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone


def valider_chemin_template(value):
    """Valide un chemin relatif à Templates/, sans accéder au NAS."""
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or "\\" in value
        or ":" in value
        or any(ord(char) < 32 for char in value)
        or any(part in ("", ".", "..") for part in value.split("/"))
        or path.parts[0].casefold() == "templates"
        or path.suffix.lower() != ".docx"
    ):
        raise ValidationError(
            "Saisissez un chemin relatif à Templates/, avec des / et une extension .docx "
            "(ex. Actes/modele.docx), sans chemin absolu ni remontée de dossier."
        )


def _valider_patron_sortie(value, variables):
    """Syntaxe déclarative uniquement : aucun rendu ni accès disque."""
    def remplacer(match):
        if match.group(1) not in variables:
            raise ValidationError("Variable non autorisée : %(variable)s.", params={"variable": match.group(1)})
        return "valeur"
    codes = re.findall(r"\{([^{}]+)\}", value)
    canonical = ["dossier.numero" if code == "num_doss" else code for code in codes]
    if len(canonical) != len(set(canonical)):
        raise ValidationError("Une variable ne peut apparaître qu’une seule fois par champ.")
    literal = re.sub(r"\{([^{}]+)\}", remplacer, value)
    if any(char in literal for char in '{}<>:"\\|?*') or any(ord(char) < 32 for char in literal):
        raise ValidationError("Utilisez un chemin relatif avec des / et les variables proposées, sans caractères spéciaux de fichier.")
    return literal


def valider_destination_relative(value):
    literal = _valider_patron_sortie(value, {"dossier.emplacement", "dossier.numero", "num_doss"})
    if "{dossier.emplacement}" in value:
        if not value.startswith("{dossier.emplacement}"):
            raise ValidationError("Placez {dossier.emplacement} au début de la destination.")
        # L'emplacement stocké inclut déjà son séparateur final ; tolérer les
        # patrons précédents qui ajoutaient un / après cette variable.
        tail = value[len("{dossier.emplacement}"):].removeprefix("/")
        literal = "dossier/" + _valider_patron_sortie(tail, {"dossier.numero", "num_doss"})
    if literal.startswith("/") or any(part in ("", ".", "..") for part in literal.removesuffix("/").split("/")):
        raise ValidationError("La destination doit être relative au NAS, sans remontée de dossier.")


def valider_nom_fichier(value):
    literal = _valider_patron_sortie(value, {"dossier.numero", "num_doss", "date.annee", "date.jour", "beneficiaire.identite", "document.numero"})
    if "/" in literal or not literal.lower().endswith(".docx") or literal[:-5] in ("", ".", ".."):
        raise ValidationError("Saisissez un nom de fichier .docx sans dossier, par exemple DIR-I-{num_doss}.docx.")
    if re.match(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", literal, re.IGNORECASE):
        raise ValidationError("Ce nom de fichier est réservé par Windows.")


class Balise(models.Model):
    class Source(models.TextChoices):
        AGIDA = "AGIDA", "Information AGIDA"
        FORMULAIRE = "FORMULAIRE", "Champ de formulaire"
        MANUELLE = "MANUELLE", "Saisie instructeur"
    class Mode(models.TextChoices):
        CONNUE = "CONNUE", "Connue"
        A_RENSEIGNER = "A_RENSEIGNER", "À renseigner"

    class Type(models.TextChoices):
        TEXT = "TEXT", "Texte"
        TEXTAREA = "TEXTAREA", "Texte multiligne"
        INTEGER = "INTEGER", "Entier"
        DECIMAL = "DECIMAL", "Décimal"
        DATE = "DATE", "Date"
        BOOLEAN = "BOOLEAN", "Oui / Non"
        LIST = "LIST", "Liste répétable (texte)"
        SELECT = "SELECT", "Liste simple"
        MULTISELECT = "MULTISELECT", "Liste à choix multiples"

    id = models.AutoField(primary_key=True)
    code = models.CharField(max_length=150, unique=True, validators=[RegexValidator(
        regex=r"\A[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*\Z",
        message="Utilisez un code comme dossier.numero, sans accolades ni espaces.",
    )])
    libelle = models.CharField(max_length=200, verbose_name="Libellé")
    mode = models.CharField(max_length=12, choices=Mode.choices, default=Mode.CONNUE)
    type = models.CharField(max_length=12, choices=Type.choices, default=Type.TEXT)
    required = models.BooleanField(default=False, verbose_name="Obligatoire")
    allow_blank = models.BooleanField(default=True, editable=False, verbose_name="Valeur vide autorisée (compatibilité)")
    help_text = models.TextField(blank=True, default="", verbose_name="Texte d'aide")
    actif = models.BooleanField(default=True)
    source = models.CharField(max_length=12, choices=Source.choices, blank=True, default="")
    source_propriete = models.CharField(max_length=150, blank=True, default="")
    libelle_element = models.CharField(max_length=100, blank=True, default="Élément", verbose_name="Libellé d'un élément")

    def clean(self):
        super().clean()
        if self.code == 'document.numero' and not (
            self.mode == self.Mode.CONNUE and self.source == self.Source.AGIDA
            and self.source_propriete == 'document.numero' and self.required and self.type == self.Type.TEXT
        ):
            raise ValidationError('document.numero est une balise système obligatoire de type Texte, source AGIDA document.numero.')
        if self.type == self.Type.LIST and self.mode != self.Mode.A_RENSEIGNER:
            raise ValidationError({"type": "La liste répétable est réservée à la saisie instructeur pour le moment."})
        if not self.source:
            return  # Compatibilité des anciennes définitions.
        expected = self.Mode.A_RENSEIGNER if self.source == self.Source.MANUELLE else self.Mode.CONNUE
        if self.mode != expected:
            raise ValidationError({"source": "Le mode de la balise ne correspond pas à son origine."})
        if self.source == self.Source.AGIDA:
            from document_generation.services.catalogue_sources import AVAILABLE_PROPERTIES
            if self.source_propriete not in AVAILABLE_PROPERTIES:
                raise ValidationError({"source_propriete": "Choisissez une information AGIDA disponible."})
        elif self.source_propriete:
            raise ValidationError({"source_propriete": "Cette origine n'utilise pas de propriété AGIDA."})

    class Meta:
        managed = False
        db_table = '"generation"."balise"'
        ordering = ("code",)
        verbose_name = "Balise"
        verbose_name_plural = "Balises"

    def __str__(self):
        return f"{self.code} — {self.libelle}"


class BaliseSourceChamp(models.Model):
    id = models.AutoField(primary_key=True)
    id_balise = models.ForeignKey(Balise, models.CASCADE, db_column="id_balise", related_name="sources_champs")
    id_demarche = models.ForeignKey("autorisations.Demarche", models.RESTRICT, db_column="id_demarche")
    id_champ = models.ForeignKey("autorisations.Champ", models.RESTRICT, db_column="id_champ")

    def clean(self):
        super().clean()
        if self.id_champ_id and self.id_demarche_id and self.id_champ.id_demarche_id != self.id_demarche_id:
            raise ValidationError({"id_champ": "Ce champ n'appartient pas à la démarche sélectionnée."})

    class Meta:
        managed = False
        db_table = '"generation"."balise_source_champ"'
        verbose_name = 'Source formulaire d’une balise'
        verbose_name_plural = 'Sources formulaire des balises'
        constraints = [models.UniqueConstraint(fields=("id_balise", "id_demarche"), name="generation_balise_source_demarche_unique")]


class DocumentTemplate(models.Model):
    id = models.AutoField(primary_key=True)
    nom = models.CharField(max_length=200)
    id_nature = models.ForeignKey(
        "autorisations.DocumentNature", models.RESTRICT, db_column="id_nature",
        related_name="templates_generation", verbose_name="Nature du document",
        null=True, blank=True,
    )
    chemin_relatif = models.CharField(
        max_length=500, validators=[valider_chemin_template],
        help_text="Relatif à Templates/ sur le NAS dev, ex. Actes/modele.docx. Aucun accès au fichier à ce stade.",
    )
    actif = models.BooleanField(default=True)
    demarches = models.ManyToManyField(
        "autorisations.Demarche", through="DocumentTemplateDemarche", blank=True,
        related_name="templates_generation", verbose_name="Démarches",
        help_text="Sans démarche associée, le template est global.",
    )
    rapport_validation = models.JSONField(null=True, blank=True, editable=False)
    date_verification = models.DateTimeField(null=True, blank=True, editable=False)
    destination_relative = models.CharField(
        max_length=500, blank=True, default="", validators=[valider_destination_relative],
        verbose_name="Destination relative",
        help_text="Relatif à la racine NAS. Exemple : {dossier.emplacement}/Work/. Variables : {dossier.emplacement}, {num_doss}, {dossier.numero}.",
    )
    nom_fichier = models.CharField(
        max_length=200, blank=True, default="", validators=[valider_nom_fichier],
        verbose_name="Nom du fichier",
        help_text="Variables : {dossier.numero}, {document.numero}, {date.annee}, {date.jour}, {beneficiaire.identite}. Doublons : suffixes _2, _3, etc.",
    )

    def clean(self):
        super().clean()
        if bool(self.destination_relative) != bool(self.nom_fichier):
            field = "nom_fichier" if self.destination_relative else "destination_relative"
            raise ValidationError({field: "Renseignez la destination et le nom du fichier ensemble, ou laissez les deux vides."})
        if '{document.numero}' in self.nom_fichier and not self.id_nature_id:
            raise ValidationError({'id_nature': 'Choisissez une nature de numérotation pour utiliser Numéro du document.'})

    def erreurs_configuration(self):
        """Contrôle local des métadonnées, distinct de l'analyse du Word."""
        errors = {}
        for name in ("nom", "chemin_relatif", "destination_relative", "nom_fichier"):
            value = getattr(self, name)
            if not value or not value.strip():
                errors[name] = ["Ce champ doit être renseigné."]
                continue
            try:
                self._meta.get_field(name).clean(value, self)
            except ValidationError as exc:
                errors[name] = exc.messages
        if '{document.numero}' in (self.nom_fichier or '') and not self.id_nature_id:
            errors['id_nature'] = ['Une nature de numérotation est nécessaire pour Numéro du document.']
        return errors

    class Meta:
        managed = False
        db_table = '"generation"."document_template"'
        ordering = ("nom", "pk")
        verbose_name = "Template"
        verbose_name_plural = "Templates"

    def __str__(self):
        return self.nom


class DocumentTemplateDemarche(models.Model):
    id = models.AutoField(primary_key=True)
    id_template = models.ForeignKey(
        DocumentTemplate, models.CASCADE, db_column="id_template", related_name="liens_demarches",
        verbose_name="Template",
    )
    id_demarche = models.ForeignKey(
        "autorisations.Demarche", models.CASCADE, db_column="id_demarche",
        related_name="liens_templates_generation", verbose_name="Démarche",
    )

    class Meta:
        managed = False
        db_table = '"generation"."document_template_demarche"'
        constraints = [models.UniqueConstraint(
            fields=("id_template", "id_demarche"), name="generation_template_demarche_unique",
        )]
        verbose_name = "Template demarche"
        verbose_name_plural = "Templates demarches"

    def __str__(self):
        return f"{self.id_template} — {self.id_demarche}"


class TemplateBalise(models.Model):
    """Photographie des codes détectés, synchronisée exclusivement par analyse."""

    id = models.AutoField(primary_key=True)
    id_template = models.ForeignKey(
        DocumentTemplate, models.CASCADE, db_column="id_template", related_name="balises_detectees",
    )
    code = models.CharField(max_length=150)
    id_balise = models.ForeignKey(
        Balise, models.SET_NULL, db_column="id_balise", null=True, blank=True,
    )

    class Meta:
        managed = False
        db_table = '"generation"."template_balise"'
        verbose_name = 'Balise détectée dans un template'
        verbose_name_plural = 'Balises détectées dans les templates'
        ordering = ("code",)
        constraints = [models.UniqueConstraint(
            fields=("id_template", "code"), name="generation_template_balise_unique",
        )]

    def __str__(self):
        return self.code


class DocumentGeneration(models.Model):
    id_template = models.ForeignKey(DocumentTemplate, models.SET_NULL, db_column='id_template',
                                   null=True, blank=True, related_name='generations')
    id_dossier = models.ForeignKey('autorisations.Dossier', models.CASCADE, db_column='id_dossier',
                                  related_name='documents_generes')
    id_document = models.OneToOneField('autorisations.Document', models.RESTRICT, db_column='id_document',
                                      related_name='generation')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, models.SET_NULL, null=True, blank=True,
                             db_column='id_user', related_name='documents_generes')
    date = models.DateTimeField(default=timezone.now)
    context_snapshot = models.JSONField(encoder=DjangoJSONEncoder)
    template_snapshot = models.JSONField()
    file_corrections = models.JSONField(default=list, blank=True)
    circuit_events = models.JSONField(default=list, blank=True, verbose_name='Historique des remplacements de projet')
    id_numero = models.ForeignKey('DocumentNumberReservation', models.RESTRICT, db_column='id_numero',
                                 null=True, blank=True, related_name='generations')

    class Meta:
        managed = False
        db_table = '"generation"."document_generation"'
        verbose_name = 'Génération de document'
        verbose_name_plural = 'Historique des générations'
        ordering = ('-date', '-pk')

    def __str__(self):
        return f'Génération {self.pk} — dossier {self.id_dossier_id}'


class DocumentNumberReservation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    id_template = models.ForeignKey(DocumentTemplate, models.RESTRICT, db_column='id_template')
    id_nature = models.ForeignKey('autorisations.DocumentNature', models.RESTRICT, db_column='id_nature')
    id_dossier = models.ForeignKey('autorisations.Dossier', models.RESTRICT, db_column='id_dossier')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, models.RESTRICT, db_column='id_user')
    numero = models.CharField(max_length=150)
    origine = models.CharField(max_length=10, choices=(('GENERE','Généré'),('RECUPERE','Récupéré')))
    source = models.CharField(max_length=80, blank=True, default='')
    date = models.DateTimeField(default=timezone.now)

    class Meta:
        managed = False
        db_table = '"generation"."numero_reservation"'
        verbose_name = 'Numéro réservé pour génération'
        verbose_name_plural = 'Numéros réservés pour génération'

    def __str__(self):
        return self.numero

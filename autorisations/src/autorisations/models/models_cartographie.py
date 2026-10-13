from django.db import models


class CartographieSource(models.Model):
    code = models.SlugField(max_length=80, unique=True)
    nom = models.CharField(max_length=150)
    format = models.CharField(max_length=10, choices=[("tuiles", "Fond de carte"), ("geojson", "Couche GeoJSON")])
    url = models.TextField(blank=True, default="")
    geojson = models.JSONField(blank=True, null=True)
    attribution = models.CharField(max_length=250, blank=True, default="")
    actif = models.BooleanField(default=True)
    options = models.JSONField(default=dict, blank=True)

    class Meta:
        managed = False
        db_table = '"instruction"."cartographie_source"'
        ordering = ("nom", "id")
        verbose_name = "Source cartographique"
        verbose_name_plural = "Sources cartographiques"

    def __str__(self):
        return self.nom

    def clean(self):
        from django.core.exceptions import ValidationError
        from instruction.utils.cartographie import valider_geojson, valider_options_source, valider_url
        self.options = valider_options_source(self.format, self.options)
        if self.geojson is not None:
            if self.format != "geojson":
                raise ValidationError("Un fond de carte ne peut pas contenir de GeoJSON.")
            valider_geojson(self.geojson)
            self.url = ""
        elif self.url:
            valider_url(self.url, fond=self.format == "tuiles")
        else:
            raise ValidationError("Une URL ou une couche GeoJSON est obligatoire.")
        if self.format == "tuiles" and not self.attribution:
            raise ValidationError("L’attribution du fournisseur est obligatoire.")


class CartographieConfiguration(models.Model):
    code = models.SlugField(max_length=80, unique=True)
    nom = models.CharField(max_length=150)
    options = models.JSONField(default=dict, blank=True)

    class Meta:
        managed = False
        db_table = '"instruction"."cartographie_configuration"'
        ordering = ("id",)
        verbose_name = "Configuration de carte"

    def __str__(self):
        return self.nom

    def clean(self):
        from instruction.utils.cartographie import valider_options_carte
        self.options = valider_options_carte(self.code, self.options)


class CartographieConfigurationSource(models.Model):
    configuration = models.ForeignKey(CartographieConfiguration, models.CASCADE, related_name="sources", db_column="id_configuration")
    source = models.ForeignKey(CartographieSource, models.PROTECT, related_name="configurations", db_column="id_source")
    ordre = models.PositiveSmallIntegerField(default=0)
    visible = models.BooleanField(default=False)

    class Meta:
        managed = False
        db_table = '"instruction"."cartographie_configuration_source"'
        ordering = ("ordre", "id")
        constraints = [models.UniqueConstraint(fields=("configuration", "source"), name="cartographie_configuration_source_unique")]
        verbose_name = "Source d’une carte"

    def __str__(self):
        return f"{self.configuration} · {self.source}"

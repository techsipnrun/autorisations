from django.db import migrations, models


SQL = """
ALTER TABLE avis.avis
    ADD COLUMN IF NOT EXISTS numero_avis_externe varchar(100) NULL;
"""


def ajouter_numero_externe(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(SQL)


class Migration(migrations.Migration):
    dependencies = [("autorisations", "0041_avis_formulaires")]
    operations = [migrations.SeparateDatabaseAndState(
        database_operations=[migrations.RunPython(ajouter_numero_externe, migrations.RunPython.noop)],
        state_operations=[migrations.AddField(
            model_name="avis", name="numero_avis_externe",
            field=models.CharField(max_length=100, blank=True, null=True),
        )],
    )]

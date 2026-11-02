from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("autorisations", "0048_changement_etape_compatibilites")]
    operations = [migrations.SeparateDatabaseAndState(
        database_operations=[],
        state_operations=[migrations.AddField(
            model_name="etapedossier",
            name="est_archivage",
            field=models.BooleanField(default=False, verbose_name="Étape d’archivage"),
        )],
    )]

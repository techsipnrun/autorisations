from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("autorisations", "0032_demarche_colonne_vue_ensemble_libelle")]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql="""
                        ALTER TABLE instruction.demarche_colonne_vue_ensemble
                        ADD COLUMN IF NOT EXISTS ordre smallint NULL;
                    """,
                    reverse_sql="""
                        ALTER TABLE instruction.demarche_colonne_vue_ensemble
                        DROP COLUMN IF EXISTS ordre;
                    """,
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="demarchecolonnevueensemble",
                    name="ordre",
                    field=models.PositiveSmallIntegerField(blank=True, null=True),
                ),
            ],
        ),
    ]

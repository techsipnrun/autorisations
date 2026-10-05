from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("autorisations", "0031_date_activite_source_dm")]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql="""
                        ALTER TABLE instruction.demarche_colonne_vue_ensemble
                        ADD COLUMN IF NOT EXISTS libelle_personnalise varchar(150) NULL;
                    """,
                    reverse_sql="""
                        ALTER TABLE instruction.demarche_colonne_vue_ensemble
                        DROP COLUMN IF EXISTS libelle_personnalise;
                    """,
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="demarchecolonnevueensemble",
                    name="libelle_personnalise",
                    field=models.CharField(blank=True, max_length=150, null=True),
                ),
            ],
        ),
    ]

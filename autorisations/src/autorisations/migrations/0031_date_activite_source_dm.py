from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("autorisations", "0030_demarche_date_activite_configuration")]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunSQL(
                sql="""
                    ALTER TABLE instruction.demarche_date_activite_champ
                        ALTER COLUMN id_champ DROP NOT NULL;
                    ALTER TABLE instruction.demarche_date_activite_champ
                        ADD COLUMN IF NOT EXISTS source varchar(10) NOT NULL DEFAULT 'dn',
                        ADD COLUMN IF NOT EXISTS champ_dm varchar(100) NULL;
                """,
                reverse_sql="""
                    ALTER TABLE instruction.demarche_date_activite_champ
                        DROP COLUMN IF EXISTS champ_dm,
                        DROP COLUMN IF EXISTS source;
                """,
            )],
            state_operations=[
                migrations.AlterField(model_name="demarchedateactivitechamp", name="id_champ", field=models.ForeignKey(
                    to="autorisations.champ", on_delete=models.RESTRICT, db_column="id_champ",
                    related_name="configurations_date_activite", null=True, blank=True,
                )),
                migrations.AddField(model_name="demarchedateactivitechamp", name="source", field=models.CharField(max_length=10, default="dn")),
                migrations.AddField(model_name="demarchedateactivitechamp", name="champ_dm", field=models.CharField(max_length=100, null=True, blank=True)),
            ],
        ),
    ]

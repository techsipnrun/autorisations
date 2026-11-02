from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("autorisations", "0046_contact_raison_sociale_raccourci")]
    operations = [migrations.SeparateDatabaseAndState(
        database_operations=[],
        state_operations=[migrations.CreateModel(
            name="ActionsPriorites",
            fields=[("code", models.CharField(max_length=12, primary_key=True, serialize=False)),
                    ("niveaux", models.JSONField(default=list))],
            options={"managed": False, "db_table": '"instruction"."actions_priorites"',
                     "verbose_name": "Priorités des actions possibles"},
        )],
    )]

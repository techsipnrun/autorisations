from django.db import migrations, models


SQL = """
DO $formulaire$
DECLARE
    contrainte text;
BEGIN
    IF to_regclass('avis.avis_formulaire_configuration') IS NULL THEN
        RAISE EXCEPTION 'La table avis.avis_formulaire_configuration est absente.';
    END IF;
    -- Ne remplacer que le CHECK portant sur le code de contexte.
    FOR contrainte IN
        SELECT conname FROM pg_constraint
        WHERE conrelid = 'avis.avis_formulaire_configuration'::regclass
          AND contype = 'c'
          AND conkey = ARRAY[(SELECT attnum FROM pg_attribute
              WHERE attrelid = 'avis.avis_formulaire_configuration'::regclass
                AND attname = 'code')]::smallint[]
    LOOP
        EXECUTE format('ALTER TABLE avis.avis_formulaire_configuration DROP CONSTRAINT %I', contrainte);
    END LOOP;
    ALTER TABLE avis.avis_formulaire_configuration
        ADD CONSTRAINT avis_formulaire_configuration_contexte_check
        CHECK (code IN ('dossier', 'generique', 'existant'));
END;
$formulaire$;
INSERT INTO avis.avis_formulaire_configuration (code, nom)
VALUES ('existant', 'Ajouter un avis existant')
ON CONFLICT (code) DO NOTHING;
"""


def ajouter_contexte(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(SQL)


class Migration(migrations.Migration):
    dependencies = [("autorisations", "0042_avis_numero_externe")]
    operations = [migrations.SeparateDatabaseAndState(
        database_operations=[migrations.RunPython(ajouter_contexte, migrations.RunPython.noop)],
        state_operations=[migrations.AlterField(
            model_name="avisformulaireconfiguration", name="code",
            field=models.CharField(max_length=20, unique=True, choices=[
                ("dossier", "Depuis un dossier"), ("generique", "Demande générique"),
                ("existant", "Ajouter un avis existant"),
            ]),
        )],
    )]

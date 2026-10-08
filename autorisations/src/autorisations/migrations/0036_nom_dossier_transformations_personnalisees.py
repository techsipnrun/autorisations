from django.db import migrations, models


SQL = """
DO $migration$
DECLARE
    contrainte_transformation text;
BEGIN
    IF to_regclass('instruction.demarche_nom_dossier_element') IS NULL THEN
        RAISE EXCEPTION 'La table de nommage est absente : exécuter les scripts 0034 et 0035 avant celui-ci.';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'instruction' AND table_name = 'demarche_nom_dossier_element'
          AND column_name = 'configuration_transformation'
    ) THEN
        ALTER TABLE instruction.demarche_nom_dossier_element
            ADD COLUMN configuration_transformation jsonb NOT NULL DEFAULT '{}'::jsonb;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'instruction.demarche_nom_dossier_element'::regclass
          AND conname = 'demarche_nom_dossier_element_transformation_personnalisee_check'
    ) THEN
        -- Remplacer uniquement le CHECK portant sur transformation seule.
        -- Le CHECK multi-colonnes validant les sources reste intact.
        FOR contrainte_transformation IN
            SELECT conname FROM pg_constraint
            WHERE conrelid = 'instruction.demarche_nom_dossier_element'::regclass
              AND contype = 'c'
              AND conkey = ARRAY[(
                  SELECT attnum FROM pg_attribute
                  WHERE attrelid = 'instruction.demarche_nom_dossier_element'::regclass
                    AND attname = 'transformation'
              )]::smallint[]
        LOOP
            EXECUTE format(
                'ALTER TABLE instruction.demarche_nom_dossier_element DROP CONSTRAINT %I',
                contrainte_transformation
            );
        END LOOP;
        ALTER TABLE instruction.demarche_nom_dossier_element
            ADD CONSTRAINT demarche_nom_dossier_element_transformation_personnalisee_check
            CHECK (transformation IN ('aucune', 'majuscules', 'minuscules', 'date', 'date_heure', 'personnalisee'));
    END IF;
END;
$migration$;
"""


class Migration(migrations.Migration):
    dependencies = [("autorisations", "0035_nom_dossier_champ_dm")]

    operations = [migrations.SeparateDatabaseAndState(
        database_operations=[migrations.RunSQL(SQL, reverse_sql=migrations.RunSQL.noop)],
        state_operations=[
            migrations.AddField(
                model_name="demarchenomdossierelement",
                name="configuration_transformation",
                field=models.JSONField(
                    default=dict, blank=True,
                    help_text='Correspondances valeur/texte et comportement sans correspondance pour la transformation personnalisée.',
                ),
            ),
            migrations.AlterField(
                model_name="demarchenomdossierelement",
                name="transformation",
                field=models.CharField(max_length=30, default="aucune", choices=[
                    ("aucune", "Aucune"), ("majuscules", "MAJUSCULES"), ("minuscules", "minuscules"),
                    ("date", "Date · JJ/MM/AAAA"), ("date_heure", "Date et heure · JJ/MM/AAAA HHhMM"),
                    ("personnalisee", "Personnalisée"),
                ]),
            ),
        ],
    )]


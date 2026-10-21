from django.db import migrations, models
import django.db.models.deletion


SQL = """
ALTER TABLE documents.document_nature
    ADD COLUMN IF NOT EXISTS mode_numerotation varchar(12) NOT NULL DEFAULT 'automatique';
ALTER TABLE documents.document
    ADD COLUMN IF NOT EXISTS numero_reference varchar(150) NULL;
ALTER TABLE documents.document
    ADD COLUMN IF NOT EXISTS id_document_reference integer NULL;
DO $numerotation$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
        WHERE conrelid = 'documents.document_nature'::regclass AND conname = 'document_nature_numerotation_check') THEN
        ALTER TABLE documents.document_nature ADD CONSTRAINT document_nature_numerotation_check
            CHECK (mode_numerotation IN ('automatique', 'manuelle'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
        WHERE conrelid = 'documents.document'::regclass AND conname = 'document_reference_source_fk') THEN
        ALTER TABLE documents.document ADD CONSTRAINT document_reference_source_fk
            FOREIGN KEY (id_document_reference) REFERENCES documents.document(id)
            ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
        WHERE conrelid = 'documents.document'::regclass AND conname = 'document_reference_pas_soi_check') THEN
        ALTER TABLE documents.document ADD CONSTRAINT document_reference_pas_soi_check
            CHECK (id_document_reference IS NULL OR id_document_reference <> id);
    END IF;
END;
$numerotation$;
CREATE INDEX IF NOT EXISTS document_reference_source_idx ON documents.document(id_document_reference);
"""


def ajouter_numerotation(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(SQL)


class Migration(migrations.Migration):
    dependencies = [("autorisations", "0044_avis_aides_et_thematiques")]
    operations = [migrations.SeparateDatabaseAndState(
        # Le schéma PostgreSQL est administré exclusivement via sql/0045_actes_numerotation_manuelle.sql.
        database_operations=[],
        state_operations=[
            migrations.AddField(model_name="documentnature", name="mode_numerotation",
                field=models.CharField(max_length=12, choices=[("automatique", "Automatique"), ("manuelle", "Manuelle")], default="automatique")),
            migrations.AddField(model_name="document", name="numero_reference",
                field=models.CharField(max_length=150, blank=True, null=True)),
            migrations.AddField(model_name="document", name="id_document_reference",
                field=models.ForeignKey("autorisations.document", on_delete=django.db.models.deletion.SET_NULL,
                    db_column="id_document_reference", related_name="references_reprises", blank=True, null=True)),
        ],
    )]


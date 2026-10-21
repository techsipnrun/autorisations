from django.db import migrations, models
import django.db.models.deletion
import uuid

SQL = """
-- Réservations communes aux avis génériques et aux demandes depuis un dossier.
-- Ne crée aucun avis et ne modifie pas la valeur du compteur existant.
DO $reservation$
BEGIN
    IF pg_get_serial_sequence('avis.avis', 'id') IS NULL THEN
        RAISE EXCEPTION 'Aucune séquence associée à avis.avis.id : vérifier le compteur avant de continuer.';
    END IF;
    IF to_regclass('avis.avis_reservation') IS NULL THEN
        CREATE TABLE avis.avis_reservation (
            id uuid PRIMARY KEY,
            numero integer NOT NULL UNIQUE,
            id_instructeur integer NOT NULL REFERENCES utilisateurs.instructeur(id) ON DELETE RESTRICT,
            contexte varchar(10) NOT NULL CHECK (contexte IN ('generique', 'dossier')),
            id_dossier integer NULL REFERENCES instruction.dossier(id) ON DELETE SET NULL,
            date_creation timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
            date_utilisation timestamptz NULL,
            id_avis integer NULL UNIQUE REFERENCES avis.avis(id) ON DELETE SET NULL,
            CONSTRAINT avis_reservation_numero_positif_check CHECK (numero > 0),
            CONSTRAINT avis_reservation_numero_check CHECK (id_avis IS NULL OR id_avis = numero),
            CONSTRAINT avis_reservation_utilisation_check CHECK (id_avis IS NULL OR date_utilisation IS NOT NULL),
            CONSTRAINT avis_reservation_generique_check CHECK (contexte <> 'generique' OR id_dossier IS NULL)
        );
    END IF;
    IF to_regclass('avis.avis_reservation_instructeur_idx') IS NULL THEN
        CREATE INDEX avis_reservation_instructeur_idx ON avis.avis_reservation(id_instructeur);
    END IF;
    IF to_regclass('avis.avis_reservation_dossier_idx') IS NULL THEN
        CREATE INDEX avis_reservation_dossier_idx ON avis.avis_reservation(id_dossier);
    END IF;
END;
$reservation$;
"""


def preparer_reservations(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(SQL)


class Migration(migrations.Migration):
    dependencies = [("autorisations", "0039_cartographie")]
    operations = [
        migrations.SeparateDatabaseAndState(
            # Le schéma PostgreSQL est administré exclusivement via sql/0040_avis_reservations.sql.
            database_operations=[],
            state_operations=[
                migrations.CreateModel(
                    name="AvisReservation",
                    fields=[
                        ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                        ("numero", models.PositiveIntegerField(unique=True)),
                        ("contexte", models.CharField(max_length=10, choices=[("generique", "Générique"), ("dossier", "Dossier")])),
                        ("date_creation", models.DateTimeField(auto_now_add=True)),
                        ("date_utilisation", models.DateTimeField(null=True, blank=True)),
                        ("id_instructeur", models.ForeignKey(to="autorisations.instructeur", db_column="id_instructeur", on_delete=django.db.models.deletion.RESTRICT)),
                        ("id_dossier", models.ForeignKey(to="autorisations.dossier", db_column="id_dossier", null=True, blank=True, on_delete=django.db.models.deletion.SET_NULL)),
                        ("id_avis", models.OneToOneField(to="autorisations.avis", db_column="id_avis", null=True, blank=True, on_delete=django.db.models.deletion.SET_NULL)),
                    ],
                    options={"managed": False, "db_table": '"avis"."avis_reservation"',
                             "verbose_name": "Réservation de numéro d'avis", "verbose_name_plural": "Réservations de numéros d'avis"},
                ),
            ],
        ),
    ]

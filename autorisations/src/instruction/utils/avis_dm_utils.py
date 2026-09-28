from django.db.models import F

from autorisations.models.models_instruction import AvisManifSportive


def get_avis_dm_le_plus_recent(dossier_dm, *, verrouiller=False):
    """Retourne l'avis DM le plus récent sans supposer une relation unique."""
    if dossier_dm is None:
        return None

    avis = AvisManifSportive.objects.filter(id_dossier_manif_sportive=dossier_dm)
    if verrouiller:
        avis = avis.select_for_update()

    return (
        avis
        .order_by(
            F("date_demande").desc(nulls_last=True),
            "-id_avis_manif_sportive",
            "-id",
        )
        .first()
    )

from django.db.models import F, Max

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


def get_dates_demande_avis_dm(dossier_dm_ids):
    """Retourne la dernière date de demande d'avis, indexée par dossier DM.

    Un dossier DM peut avoir plusieurs avis. Pour les tableaux, la dernière
    demande est celle qui matérialise sa réception la plus récente par le Parc.
    L'agrégation évite une requête par ligne affichée.
    """
    dossier_dm_ids = list(dossier_dm_ids)
    if not dossier_dm_ids:
        return {}

    return {
        ligne["id_dossier_manif_sportive_id"]: ligne["date_demande"]
        for ligne in (
            AvisManifSportive.objects.filter(
                id_dossier_manif_sportive_id__in=dossier_dm_ids,
            )
            .values("id_dossier_manif_sportive_id")
            .annotate(date_demande=Max("date_demande"))
        )
    }

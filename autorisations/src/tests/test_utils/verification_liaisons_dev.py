"""Vérification PostgreSQL explicite, uniquement en dev et toujours annulée.

python manage.py shell -c "from tests.test_utils.verification_liaisons_dev import verifier; verifier()"

Les cinq dossiers utilisés sont verrouillés dans une transaction courte. Aucune
liaison ni action de test n'est conservée ; les séquences peuvent avancer.
"""
import json
from types import SimpleNamespace

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.test import RequestFactory
from django.template.loader import render_to_string
from dotenv import dotenv_values

from autorisations.models.models_instruction import Dossier, EnsembleDossiers
from autorisations.models.models_utilisateurs import Instructeur
from instruction.utils.ensembles_dossiers import (
    EnsembleModifie, contexte_dossiers_lies, jeton_ensemble, lier_dossiers,
    membres_ensemble, retirer_dossier_lie,
)
from instruction.views.dossiers_lies import (
    ajouter_lien_dossier, rechercher_dossiers_lies, retirer_lien_dossier,
)


def verifier():
    dev = dotenv_values(settings.BASE_DIR / ".env.dev")
    prod = dotenv_values(settings.BASE_DIR / ".env.prod")
    cfg = connection.settings_dict
    cles = [("HOST", "BDD_HOSTNAME"), ("NAME", "BDD_NAME")]
    assert settings.ENVIRONMENT == "dev", "Vérification réservée à la BDD dev."
    assert all(str(cfg[k]) == str(dev.get(v) or "") for k, v in cles)
    assert not all(str(cfg[k]) == str(prod.get(v) or "") for k, v in cles)
    assert connection.vendor == "postgresql"
    instructeur = Instructeur.objects.exclude(email="").exclude(email__isnull=True).first()
    assert instructeur, "Un instructeur est nécessaire."
    user = SimpleNamespace(is_authenticated=True, is_superuser=True, email=instructeur.email)
    rf = RequestFactory()

    def actualiser(dossier):
        dossier.refresh_from_db()
        return dossier

    def jeton_liaison(source, cible):
        actualiser(source)
        actualiser(cible)
        return jeton_ensemble(source, membres_ensemble(source), membres_ensemble(cible))

    def lier(source, cible):
        lier_dossiers(user, source.pk, cible.pk, jeton_liaison(source, cible))

    def retirer(source, cible):
        actualiser(source)
        retirer_dossier_lie(user, source.pk, cible.pk,
                           jeton_ensemble(source, membres_ensemble(source)))

    def membres(source):
        return {d.pk for d in membres_ensemble(actualiser(source))}

    def requete(method, url, data=None, utilisateur=user):
        request = getattr(rf, method)(url, data or {})
        request.user = utilisateur
        return request

    with transaction.atomic():
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL statement_timeout = '15s'")
                cursor.execute("SET LOCAL lock_timeout = '5s'")
                cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", [71423, 1])
            dossiers = list(Dossier.objects.filter(id_ensemble_dossiers__isnull=True)
                            .select_for_update().order_by("pk")[:5])
            assert len(dossiers) == 5, "Cinq dossiers indépendants sont nécessaires."
            a, b, c, d, e = dossiers
            ids = [dossier.pk for dossier in dossiers]
            avant_ensembles = EnsembleDossiers.objects.count()

            lier(a, b)
            assert membres(a) == {a.pk, b.pk}
            assert membres(b) == {a.pk, b.pk}
            print('OK: liaison A-B symétrique')

            request = requete("get", "/recherche/", {"recherche": a.numero})
            response = rechercher_dossiers_lies(request, c.pk)
            assert response.status_code == 200, response.content
            data = json.loads(response.content)
            carte = next(r for r in data["resultats"] if any(x["id"] == a.pk for x in r["dossiers"]))
            assert {x["id"] for x in carte["dossiers"]} == {a.pk, b.pk}
            assert sum(any(x["id"] == b.pk for x in r["dossiers"]) for r in data["resultats"]) == 1
            response = ajouter_lien_dossier(requete("post", "/lier/", {
                "cible_id": carte["cible_id"], "jeton": carte["jeton"],
            }), c.pk)
            assert response.status_code == 200, response.content
            assert membres(c) == {a.pk, b.pk, c.pk}
            print('OK: recherche groupée A-B (filtre sur A) et ajout C via API')

            contexte = contexte_dossiers_lies(requete("get", "/"), actualiser(a))
            assert {x["id"] for x in contexte["dossiers_lies"]} == {b.pk, c.pk}
            html = render_to_string("instruction/refacto/dossiers_lies_bloc.html", {
                **contexte, "dossier": a,
            })
            assert "Dossiers liés" in html
            assert "Retirer le lien" in html
            print('OK: bloc pluriel et accès aux deux autres dossiers')

            retirer(a, b)
            assert membres(a) == {a.pk, c.pk}
            assert membres(b) == {b.pk}
            contexte = contexte_dossiers_lies(requete("get", "/"), actualiser(a))
            html = render_to_string("instruction/refacto/dossiers_lies_bloc.html", {**contexte, "dossier": a})
            assert "<h3>Dossier lié</h3>" in html
            retirer(a, c)
            assert membres(a) == {a.pk} and membres(c) == {c.pk}
            assert EnsembleDossiers.objects.count() == avant_ensembles
            assert not contexte_dossiers_lies(requete("get", "/"), actualiser(a))["dossiers_lies"]
            print('OK: retrait B préserve A-C ; retrait C dissout le dernier ensemble')

            lier(a, b)
            lier(c, d)
            ancien_jeton = jeton_liaison(a, c)
            lier(e, b)
            try:
                lier_dossiers(user, a.pk, c.pk, ancien_jeton)
            except EnsembleModifie:
                pass
            else:
                raise AssertionError('Une sélection périmée a été acceptée')
            assert membres(c) == {c.pk, d.pk}
            lier(a, c)
            assert membres(a) == set(ids)
            assert EnsembleDossiers.objects.count() == avant_ensembles + 1
            print('OK: sélection périmée refusée ; fusion de deux ensembles')

            avant_refus = membres(a)
            response = ajouter_lien_dossier(requete("post", "/lier/", {
                "cible_id": a.pk, "jeton": "invalide",
            }), a.pk)
            assert response.status_code == 400
            response = retirer_lien_dossier(requete("post", "/retirer/", {
                "cible_id": b.pk, "jeton": "invalide",
            }), a.pk)
            assert response.status_code == 409
            refuse = SimpleNamespace(is_authenticated=True, is_superuser=False, email="")
            response = retirer_lien_dossier(requete("post", "/retirer/", {
                "cible_id": b.pk, "jeton": jeton_ensemble(a, membres_ensemble(a)),
            }, utilisateur=refuse), a.pk)
            assert response.status_code == 403
            assert membres(a) == avant_refus
            print('OK: auto-liaison, jeton falsifié et accès non autorisé refusés')
        finally:
            transaction.set_rollback(True)

    assert not Dossier.objects.filter(pk__in=ids, id_ensemble_dossiers__isnull=False).exists()
    assert EnsembleDossiers.objects.count() == avant_ensembles
    print('OK: transaction annulée, aucune liaison de test conservée')

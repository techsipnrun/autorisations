import django_filters
from autorisations.models.models_avis import Avis

'''
Fichiers qui définit des filtres de recherche, utilisables via l'API Postgres
'''

class AvisFilter(django_filters.FilterSet):
    favorable = django_filters.BooleanFilter()
    date_reponse_avis = django_filters.DateFromToRangeFilter()  # Filtre entre deux dates
    id_expert = django_filters.NumberFilter(field_name="id_expert__id")  # Filtrer par expert

    class Meta:
        model = Avis
        fields = ['favorable', 'date_reponse_avis', 'id_expert']

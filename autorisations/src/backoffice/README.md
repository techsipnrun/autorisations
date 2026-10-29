# Back Office

Cette application porte les écrans de configuration et d'administration de
l'application. Les modèles métier restent dans `autorisations.models`.

- `views/accueil.py` : page principale et chargement des démarches.
- `views/demarches.py` : date d'activité et personnalisation des tableaux.
- `views/nom_dossier.py` : configuration, test et recalcul du nommage.
- `views/avis.py` : formulaires d'avis et catalogue des thématiques.
- `views/cartographie.py` : catalogue, import et configuration des cartes.
- `views/types_actes.py` et `forms/types_actes.py` : types d'actes.
- `views/services.py` et `services/externes.py` : suivi des services externes.
- `services/import_couches.py` : conversion des couches importées.

`urls.py` conserve les chemins `/back-office/...` et les noms
`back_office_*` sans namespace. Il est inclus depuis les URLs du projet.
Les vues conservent leurs contrôles d'authentification et de superutilisateur.

Les templates sont dans `templates/backoffice/` et les ressources propres
au Back Office dans `static/backoffice/`. Les ressources communes aux
formulaires d'avis et aux cartes restent dans `instruction`.

Les moteurs de configuration utilisés par les dossiers, les modèles, la
synchronisation et la diffusion des GeoJSON restent dans leurs applications
métier. `instruction` n'importe pas `backoffice`.

Tests isolés, depuis `autorisations/src` :

```powershell
python -m tests tests.unit.back_office tests.interface.back_office
```

Cette application ne possède aucun modèle ni migration de base de données.

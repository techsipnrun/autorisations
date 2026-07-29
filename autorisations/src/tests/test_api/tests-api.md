# Tests des API externes

Les tests simulés de Démarche Numérique et Déclaration Manifestations ne
nécessitent ni réseau ni base PostgreSQL :

```powershell
cd autorisations/src
..\..\.env\Scripts\python.exe manage.py test tests.test_api -v 2
```

Deux tests d'intégration réels contrôlent la disponibilité des API et la
validité des identifiants. Ils sont désactivés par défaut pour ne pas rendre la
suite instable en cas de panne externe.

```powershell
cd autorisations/src
$env:RUN_LIVE_API_TESTS = "1"
..\..\.env\Scripts\python.exe manage.py test tests.test_api -v 2
Remove-Item Env:RUN_LIVE_API_TESTS
```

Ces tests réels effectuent uniquement des lectures : une requête GraphQL
`__typename` sur DN et une récupération de jeton OAuth sur DM. Aucun dossier
n'est modifié.

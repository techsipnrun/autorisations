# Tests AGIDA

Depuis `autorisations/src`, utiliser ce point d'entrée isolé :

```powershell
python -m tests
python -m tests tests.unit
python -m tests tests.unit.synchronisation.test_formulaire_modifie
python -m tests tests.unit.notifications.test_notification_formulaire_modifie
```

Équivalent Django : `python manage.py test tests --settings=tests.settings`.
`pytest.ini` utilise également `tests.settings` (nécessite pytest et pytest-django,
non ajoutés aux dépendances de l'application).

## Organisation

| Dossier | Contenu | Dépendances réelles |
| --- | --- | --- |
| `unit/` | Synchronisation, notifications, instruction, back-office, admin et clients API simulés | Aucune BDD, aucun vrai mail/NAS/service externe |
| `integration/test_reprise_http.py` | Reprise d'un téléchargement réellement interrompu | Serveur HTTP local, NAS simulé |
| `integration/models/` | Anciens tests ORM et contraintes SQL | PostgreSQL de test préparé, activation volontaire |
| `interface/` | Éditeur de nommage dans Chrome headless | Chrome local, API simulées ; ignoré si Chrome absent |
| `externes/` | Disponibilité et authentification réelles DN/DM | Activation volontaire et identifiants explicites |
| `support/` | Fabriques, simulations et préparation partagée | Aucun cas de test ; ne pas importer des tests entre eux |
| `verification_manuelle/` | Outils à lancer à la main, hors découverte automatique | BDD dev ou NAS réels selon l'outil |

Les modifications de formulaire sont testées séparément :

- `unit/synchronisation/test_formulaire_modifie.py` : détection, regroupement,
  dates, dernière demande de compléments, timeline et déclenchement du mail ;
- `unit/notifications/test_notification_formulaire_modifie.py` : destinataires,
  mode production/test, contenu et échecs d'envoi ;
- `unit/instruction/test_champs_apres_depot.py` : métadonnées d'affichage et surlignage.

Conserver le préfixe `test_` et les fichiers `__init__.py` pour la découverte Django.
Un test doit rester proche de la fonctionnalité vérifiée ; `support/` ne contient
pas de classe de tests ni de méthode `test_*`, afin d'éviter les doublons.

## Isolation par défaut

`settings.py` réutilise la configuration des applications/templates sans charger
les `.env` ni les connexions BDD de production/développement. Il remplace les
connexions par SQLite en mémoire, utilise le backend mail en mémoire, désactive
les notifications réelles, LDAP et les écritures de logs applicatifs.
Les `SimpleTestCase` interdisent les accès SQL non simulés.

Ne pas utiliser `manage.py test` sans `--settings=tests.settings` : cette commande
seule conserve les paramètres normaux de l'application. `python -m tests` est
le raccourci recommandé ; il impose les paramètres de test, sauf option
`--settings` explicite.

Le lanceur empêche également les modules de recharger les fichiers `.env` pendant
la découverte/exécution et bloque les connexions réseau Python hors localhost,
sauf activation explicite des tests externes ou PostgreSQL. Les tests Chrome
s'exécutent dans un processus séparé, avec le réseau de fond désactivé.
Le contrôle `fields.E120` (varchar sans longueur, autorisé par PostgreSQL) est
neutralisé uniquement dans les paramètres SQLite sans SQL, pas dans ceux PostgreSQL.

## Tests PostgreSQL (volontaires)

Les modèles sont principalement `managed=False` et leurs tables utilisent des
schémas PostgreSQL : SQLite ne peut pas remplacer ces tests. Une base **jetable**
nommée `test_autorisations`, avec les schémas/tables/contraintes nécessaires,
doit être préparée indépendamment de la BDD dev/prod.

```powershell
$env:RUN_DB_TESTS = "1"
$env:TEST_PG_HOST = "localhost"
$env:TEST_PG_USER = "compte_tests_uniquement"
$env:TEST_PG_PASSWORD = "mot_de_passe_du_compte_tests"
python -m tests tests.integration.models --settings=tests.settings_postgresql --keepdb
Remove-Item Env:RUN_DB_TESTS
Remove-Item Env:TEST_PG_HOST
Remove-Item Env:TEST_PG_USER
Remove-Item Env:TEST_PG_PASSWORD
```

`TEST_PG_PORT` est optionnel (5432 par défaut). Aucune reprise des variables
`BDD_*` ou des connexions applicatives n'est effectuée. Le compte de test doit
être limité à cette base. Ces tests créent et suppriment des données ; ne jamais
les pointer vers une base métier. `--keepdb` conserve uniquement la base de test.

Les anciens scénarios de modèles sont conservés. Leur compatibilité avec le
schéma actuel doit être vérifiée lors d'une exécution PostgreSQL dédiée ; cette
réorganisation ne réécrit pas leurs attentes métier.

## Tests des API externes (volontaires)

Configurer explicitement dans le processus les paramètres attendus par les
clients DN/DM ; la configuration de test ne charge pas `.env.dev` ou `.env.prod`.

```powershell
$env:RUN_LIVE_API_TESTS = "1"
python -m tests tests.externes
Remove-Item Env:RUN_LIVE_API_TESTS
```

Ces contrôles ne modifient aucun dossier : lecture GraphQL `__typename` pour DN,
obtention d'un jeton OAuth pour DM. Ils restent ignorés sans le drapeau explicite.

## Vérifications manuelles

Elles sont regroupées dans `tests/verification_manuelle/`. Les fichiers n'ont pas
le préfixe `test_` et ne sont pas exécutés par les lanceurs Django ou pytest :

- `ecriture_nas.py` : écrit réellement un fichier sur le NAS, chemins à adapter ;
- `liaisons_dev.py` : contrôle réservé à la dev dans une transaction annulée
  (les séquences peuvent néanmoins avancer).

La vérification des liaisons s'exécute volontairement avec les paramètres dev :

```powershell
python manage.py shell -c "from tests.verification_manuelle.liaisons_dev import verifier; verifier()"
```

Anciennes commandes à adapter : `tests.test_utils` est remplacé par les
sous-dossiers de `tests.unit`, `tests.test_api` par `tests.unit.api` / `tests.externes`,
et `tests.test_models` par `tests.integration.models`.

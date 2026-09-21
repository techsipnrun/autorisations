# Miroir PROD → DEV et purge des dossiers DEV

Trois traitements distincts s'exécutent **sur la VM de développement** : un miroir quotidien de certains champs depuis la BDD de production, une purge hebdomadaire des vieux dossiers terminés de DEV et un nettoyage quotidien des archives expirées. Aucun traitement n'écrit dans la BDD ou sur le NAS de production.

> « Miroir » ne signifie pas copie intégrale. Les seuls champs synchronisés sont énumérés ci-dessous. Une modification manuelle de ces champs en DEV peut être écrasée lors du passage suivant.

## Calendrier

| Traitement | Planification systemd | Effet |
| --- | --- | --- |
| `agida-miroir-statuts-dev` | Chaque jour à 02:15, délai aléatoire ≤ 5 min | Lit la BDD PROD ; met à jour des dossiers déjà présents en BDD DEV |
| `agida-purge-dev` | Dimanche à 03:15, délai aléatoire ≤ 10 min | Sauvegarde la BDD DEV, puis purge au maximum 25 unités éligibles de plus de 12 mois |
| `agida-nettoyage-purge-dev` | Chaque jour à 04:15, délai aléatoire ≤ 10 min | Supprime les éléments de purge expirés depuis plus de 30 jours |

Chaque timer a `Persistent=true` : systemd rattrape au redémarrage de la **VM** une exécution manquée. Les services sont `Type=oneshot` : `inactive (dead)` après `status=0/SUCCESS` est normal. Le fonctionnement requiert l'accès réseau à PostgreSQL et au NAS DEV.

## Ce que synchronise le miroir

La commande `synchroniser_statuts_prod` lit en production deux vues du schéma `maintenance`, rapproche les dossiers par **numéro** et met à jour les lignes déjà présentes en DEV.

| Type | Champs recopiés de PROD vers DEV |
| --- | --- |
| DN | Étape (`id_etape_dossier`, par libellé), état (`id_etat_dossier`, par nom), `present_sur_ds`, `date_debut_instruction`, `date_fin_instruction` |
| DM | Étape (`id_etape`, par libellé), `etat_dossier`, `archive` |

Les valeurs d'étape et d'état doivent déjà exister en DEV. Une valeur inconnue est bloquante : aucune mise à jour n'est appliquée. Les écritures DEV sont transactionnelles. Le miroir **ne crée pas** les dossiers absents de DEV et ne restaure pas ceux purgés. Il ne copie pas les pièces jointes, fichiers NAS, avis, messages, notes, instructeurs, groupes, actions ou timelines ; il n'effectue aucune action sur Démarche Numérique ou Déclaration Manifestations. « Absents de dev » dans le bilan est donc une information, pas une erreur.

### Accès aux bases et garde-fous

- La connexion Django `default` utilise les variables `BDD_NAME`, `BDD_USER`, `BDD_PASSWORD`, `BDD_HOSTNAME`, `BDD_PORT` de `.env.dev`. C'est elle qui écrit en BDD DEV.
- La connexion `prod_readonly` existe uniquement si `DJANGO_ENV=dev` et si les cinq variables `BDD_PROD_READONLY_NAME`, `BDD_PROD_READONLY_USER`, `BDD_PROD_READONLY_PASSWORD`, `BDD_PROD_READONLY_HOSTNAME`, `BDD_PROD_READONLY_PORT` sont renseignées. Le rôle PostgreSQL de la VM est `miroir_dev`.
- Le rôle `miroir_dev` a `CONNECT` à la BDD PROD, `USAGE` sur `maintenance` et `SELECT` sur `maintenance.v_miroir_statuts_dossiers_dn` et `maintenance.v_miroir_statuts_dossiers_dm`. Il ne doit avoir **aucun accès direct aux tables métier ni droit d'écriture**. Le script `miroir_dev_prod/sql/2026-09-15_miroir_statuts_prod.sql` crée les vues et les droits ; le rôle et son mot de passe sont créés séparément, hors Git.
- `prod_readonly` force aussi `default_transaction_read_only=on`, le `search_path=maintenance` et un délai maximal SQL de 30 s. La commande compare les identités hôte/port/base de `default` et `prod_readonly` et vérifie la lecture seule côté PROD.
- Avant d'écrire, le miroir et les commandes de purge vérifient que `maintenance.environnement_agida` contient `dev` sur la BDD cible. Le script `miroir_dev_prod/sql/2026-09-15_garde_fou_bdd_dev.sql` est à exécuter **uniquement en DEV**.

Ne jamais inscrire les secrets dans Git ni dans cette page. `miroir_dev_prod/` est ignoré par Git : ce répertoire doit être présent séparément sur la VM.

## Éligibilité à la purge : « archivé » et 12 mois

La purge ne classe pas elle-même un dossier : elle ne traite que les dossiers déjà terminés/archivés.

- **DN** : étape `Accepté`, `Refusé`, `Non soumis à autorisation` ou `Annulé`.
- **DM** : champ `archive=True`.
- **Couple DN–DM lié** : les deux membres doivent être éligibles ; jamais de purge d'un membre isolé d'un couple.
- Dans tous les cas, la **dernière activité calculée** doit être strictement antérieure au seuil de 12 mois. Une date indéterminable ne rend pas un dossier éligible.

La dernière activité DN tient notamment compte du dépôt, du début et de la fin d'instruction, des actions, messages, notes, tentatives de mails, documents liés et dates d'avis. Pour DM, elle tient compte du dépôt, du début/de la fin de l'événement, des notes, mails et documents liés. Ce n'est donc **pas simplement la date de création**. Un dossier actif, en réception ou en instruction n'est pas purgé parce qu'il est vieux.

L'inventaire compte les dépendances BDD et peut mesurer les répertoires NAS. Une unité avec erreur de lecture NAS, document partagé ou avis partagé est **exclue du manifeste exécutable** avec son motif ; les autres unités restent traitables. Un avis lié à plusieurs dossiers ne doit pas être supprimé avec un seul dossier.

L'option `--scan-orphelins` inventorie séparément les répertoires anciens du NAS sans dossier correspondant en BDD. Elle ignore notamment `@Recycle` (corbeille du NAS) et `_corbeille_agida`. **Les orphelins ne sont pas inclus dans la purge automatique.**

### Ce qui est supprimé et quand

Pour chaque unité retenue, l'exécuteur déplace d'abord son ou ses répertoires du **NAS DEV** vers `NAS_ROOT/_corbeille_agida/<horodatage>/<clé>/...`. Puis, dans une transaction sur la **BDD DEV**, il supprime les dossiers DN/DM, leurs relations dépendantes, avis et documents non partagés liés à cette unité. En cas d'échec BDD, il tente de remettre les répertoires NAS à leur emplacement initial et écrit un journal d'erreur.

La suppression BDD est donc effective **dès la mise en corbeille NAS**, et non au bout de 30 jours. Une sauvegarde complète de la BDD DEV et le répertoire NAS en corbeille constituent les moyens de récupération temporaires. Il n'existe pas de restauration ciblée automatique d'un seul dossier depuis ce dump : l'opération exigerait une procédure manuelle. La purge ne touche ni la BDD PROD ni le NAS PROD.

## Chaîne d'une exécution hebdomadaire

`python manage.py purger_dossiers_dev --months 12 --limite 25 --execute --confirmation PURGER-DEV-12M` lance :

1. `sauvegarder_bdd_dev` : dump **complet** de la BDD DEV avec `pg_dump` au format custom, contrôle `pg_restore --list`, calcul SHA-256, métadonnées JSON ;
2. `inventorier_purge_dev --scan-nas --rapport-csv --manifeste` : sélection des unités, rapport CSV et manifeste JSON figé contenant IDs, chemins, tailles, compteurs, exclusions et référence à la sauvegarde ;
3. `executer_purge_dev` : contrôle des empreintes, revalidation des unités avant traitement, déplacement NAS puis suppression BDD ; maximum 25 unités par passage, arrêt à la première erreur.

La commande d'exécution seule est en **simulation par défaut** et exige `--cles`, `--execute` et une confirmation calculée à partir du manifeste pour agir. L'orchestrateur hebdomadaire lui fournit ces paramètres. Même lorsqu'aucun dossier n'est éligible, l'orchestrateur crée actuellement une sauvegarde et un rapport, puis s'arrête sans manifeste ni purge.

### Archives et rétention

Par défaut, les fichiers locaux sont sous `/home/ad/autorisations/miroir_dev_prod/archives_bdd/` sur la VM :

| Répertoire | Contenu |
| --- | --- |
| `sauvegardes/` | Dumps `.dump`, empreintes `.dump.sha256`, métadonnées `.dump.json` |
| `rapports/` | Inventaires CSV et éventuels rapports d'orphelins NAS |
| `lots/` | Manifestes JSON et empreintes `.json.sha256` |
| `executions/` | Journaux JSON individuels des unités traitées |

`PURGE_BDD_ARCHIVE_ROOT` peut changer cette racine. `PG_DUMP_PATH` et `PG_RESTORE_PATH` permettent de fournir les exécutables PostgreSQL si absents du `PATH` ; sur la VM, `pg_dump` est dans `/usr/bin`. `NAS_ROOT` doit cibler **le partage DEV** `autodev_data`.

Le nettoyage quotidien supprime les lots horodatés de `_corbeille_agida` âgés de plus de 30 jours et les fichiers locaux des quatre répertoires ci-dessus dont la date de modification remonte à plus de 30 jours. Il ne nettoie pas `@Recycle`. Ces suppressions sont définitives. Les sauvegardes sont conservées au maximum jusqu'au prochain passage après expiration ; la récupération n'est ni automatique ni garantie au-delà de ce délai.

## Fichiers du dispositif

| Fichier | Rôle |
| --- | --- |
| `autorisations/src/autorisations/settings.py` | Connexions BDD et racine des archives |
| `autorisations/src/instruction/management/commands/synchroniser_statuts_prod.py` | Lecture PROD et mises à jour DEV |
| `.../sauvegarder_bdd_dev.py` | Sauvegarde BDD et vérification |
| `.../inventorier_purge_dev.py` | Critères, scan NAS, statistiques, CSV, manifeste |
| `.../executer_purge_dev.py` | Purge des unités DN, DM ou complètes |
| `.../nettoyer_purge_dev.py` | Nettoyage à 30 jours |
| `.../verifier_purge_canari_dev.py`, `.../executer_purge_canari_dev.py` | Commandes du test initial ciblé, non utilisées par les timers |
| `miroir_dev_prod/sql/` | Vues/droits PROD et marqueur de sécurité DEV |
| `miroir_dev_prod/systemd/` | Trois services et trois timers à installer dans `/etc/systemd/system/` |
| `miroir_dev_prod/archives_bdd/` | Sauvegardes, rapports, lots et journaux locaux |

## Changer les 12 mois, les 30 jours ou la fréquence

Modifier `miroir_dev_prod/systemd/agida-purge-dev.service` : **`--months 12` et `PURGER-DEV-12M` doivent toujours porter la même valeur** (par exemple `--months 18` et `PURGER-DEV-18M`). `--limite 25` règle le nombre maximal d'unités par passage ; le code interdit de dépasser 25. Pour modifier les 30 jours, changer ensemble `--days 30` et `NETTOYER-30J` dans `agida-nettoyage-purge-dev.service`.

Les horaires et fréquences sont dans les fichiers `.timer` (`OnCalendar`, `RandomizedDelaySec`) et suivent le fuseau de la VM. Après une modification, recopier les unités concernées depuis `/home/ad/autorisations`, puis recharger systemd ; redémarrer le timer si son calendrier a changé :

```bash
sudo cp miroir_dev_prod/systemd/agida-purge-dev.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart agida-purge-dev.timer
```

Adapter le nom des fichiers pour le nettoyage ou le miroir. Une réduction de la rétention peut entraîner une suppression définitive au prochain passage : vérifier au préalable les archives nécessaires à une restauration.

## Installation et contrôle sur la VM DEV

Depuis `/home/ad/autorisations`, avec le code et `miroir_dev_prod/` déjà déployés :

```bash
sudo cp miroir_dev_prod/systemd/agida-miroir-statuts-dev.service /etc/systemd/system/
sudo cp miroir_dev_prod/systemd/agida-miroir-statuts-dev.timer /etc/systemd/system/
sudo cp miroir_dev_prod/systemd/agida-purge-dev.service /etc/systemd/system/
sudo cp miroir_dev_prod/systemd/agida-purge-dev.timer /etc/systemd/system/
sudo cp miroir_dev_prod/systemd/agida-nettoyage-purge-dev.service /etc/systemd/system/
sudo cp miroir_dev_prod/systemd/agida-nettoyage-purge-dev.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now agida-miroir-statuts-dev.timer agida-purge-dev.timer agida-nettoyage-purge-dev.timer
```

Pour surveiller :

```bash
systemctl list-timers agida-miroir-statuts-dev.timer agida-purge-dev.timer agida-nettoyage-purge-dev.timer
sudo journalctl -u agida-miroir-statuts-dev.service -u agida-purge-dev.service -u agida-nettoyage-purge-dev.service --since "7 days ago" --no-pager
```

Depuis `/home/ad/autorisations/autorisations/src`, simulations sans purge :

```bash
python manage.py synchroniser_statuts_prod --details
python manage.py purger_dossiers_dev --months 12 --limite 25
python manage.py nettoyer_purge_dev --days 30
```

`sudo systemctl start <nom>.service` lance en revanche **la vraie commande `--execute` du service**, pas une simulation. Pour voir les erreurs : `sudo systemctl status <nom>.service --no-pager` et `sudo journalctl -u <nom>.service -n 100 --no-pager`.

Pour désactiver sans supprimer les données existantes :

```bash
sudo systemctl disable --now agida-miroir-statuts-dev.timer agida-purge-dev.timer agida-nettoyage-purge-dev.timer
```

## Limites et précautions

- Le miroir recopie des champs de statut mais ne rejoue pas l'historique métier : la timeline et d'autres données DEV peuvent diverger de PROD.
- `pg_restore --list` prouve que le catalogue du dump est lisible ; **ce n'est pas un test complet de restauration**. Tester une restauration dans une BDD isolée avant d'en dépendre en situation critique.
- Un dump complet restauré par-dessus la BDD courante effacerait les changements DEV postérieurs : une restauration ciblée nécessite une procédure distincte.
- Les orphelins NAS ne sont pas purgés automatiquement. Les fichiers de la corbeille native `@Recycle` ne font pas partie du traitement AGIDA.
- Surveiller régulièrement les journaux, l'espace disque des archives, les droits du compte DEV sur le NAS et les unités exclues des manifestes.

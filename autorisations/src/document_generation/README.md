# Accès depuis le dossier

## Templates sans code technique

Exécuter manuellement en **BDD dev**, après 0019,
`sql/generation_doc/0020_suppression_code_template.sql`. Le champ Code du template
est supprimé du modèle Django, du back-office et de l'admin. Les relations et
URLs utilisent toujours l'ID ; la génération définitive utilise le nom de
fichier configuré. Le téléchargement DOCX de test utilise le nom du template.
Les nouveaux snapshots enregistrent l'ID et le nom ; les anciens snapshots
JSON restent inchangés pour préserver l'historique. Les **codes des balises**
restent indispensables et ne sont pas modifiés.

## Fichiers d'actes générés à réparer (dev)

Le menu **Générer** indique le nombre de fichiers générés numérotés d'actes
introuvables pour ce dossier. La nature de la réservation fait foi ; les avis
d'instance, fichiers sans réservation et documents rédigés manuellement ne sont
pas comptés. Le contrôle lit le NAS sans modifier les fichiers ou la BDD.

Avant **Faire valider le projet d'acte**, **Faire valider le projet d'avis CS**
(qui sélectionne un projet d'acte) et **Raccourci SPPN — Acte prêt à la signature**,
les formulaires restent désactivés si un fichier est absent ou si la vérification
est impossible. Le lien **Réparer les fichiers générés** ouvre directement
l'historique. Réassocier le fichier ou supprimer sa génération de l'historique
permet de lever le blocage ; le numéro réservé reste consommé. Les actes
numérotés restent affichés même au-delà des 50 générations récentes, afin de
pouvoir réparer un ancien fichier bloquant.

Un NAS inaccessible affiche « Vérification impossible », jamais un faux nombre
de fichiers manquants. Une nouvelle vérification est faite côté serveur avant
les mutations du circuit, même si le formulaire avait été débloqué à l'écran.
Les autres changements d'étape et la production restent inchangés.

À la sélection d'un fichier généré numéroté dans Work, la nature est comparée
à celle de sa réservation dès que fichier et nature ont été sélectionnés. Une
incompatibilité bloque la confirmation, y compris côté serveur. Un fichier
compatible affiche provenance et numéro et masque le choix d'un numéro partagé.
Les fichiers non reconnus ou sans réservation conservent le parcours manuel.

À la confirmation des trois parcours ci-dessus, le même Document reçoit nature,
format et statut du circuit, en conservant le numéro réservé. L'écriture est
contrôlée et transactionnelle, sans appeler le compteur ni `Document.save()`
lors du changement de nature. Aucun Word n'est modifié ou déplacé. Le lien au
dossier et l'historique de génération sont conservés. Une incohérence de numéro,
un numéro déjà utilisé par un autre projet/acte au même emplacement ou un document en diffusion
bloquent cette intégration ; aucun nouveau numéro n'est attribué en remplacement.

Après exécution manuelle en BDD dev de
`sql/generation_doc/0018_versions_numerotees_fichiers_generes.sql`, plusieurs
versions de nature **Fichier généré** peuvent porter le même numéro dans un
même emplacement. En revanche, un seul acte de cette nature et de ce numéro
peut être déclaré dans le circuit à cet emplacement. Après exécution manuelle
de `sql/generation_doc/0019_remplacement_projet_genere.sql`, sélectionner une
autre version propose une case de confirmation nommant le projet précédent.
Sans cette confirmation, le changement d'étape est refusé côté serveur.

Le projet précédent doit être généré, appartenir au même dossier et avoir un
statut vide après retour en instruction. Les projets encore dans le circuit,
diffusés/publiés, manuels, partagés ou utilisés comme référence d'un autre acte
ne sont pas remplacés automatiquement. La nouvelle version reprend nature,
statut et numéro dans le circuit ; l'ancienne redevient **Fichier généré**, avec
le même numéro et sans statut. Les deux fichiers et liens d'historique restent
conservés. La date, l'utilisateur et les deux versions sont journalisés dans
`circuit_events` sur les deux générations, sans modifier les snapshots. Tout
échec annule les écritures de ce remplacement. L'historique indique quelle
version remplace l'autre.

Le partage entre emplacements différents est autorisé : le dossier destinataire
choisit le numéro via **Récupérer un existant**, et le dossier source conserve
son numéro initial. L'ordre d'entrée dans le circuit des deux dossiers ne bloque
pas ce partage. Dans tous les cas, le numéro provient de la réservation validée
en BDD, sans saisie libre ni appel au compteur lors de l'intégration.

Le retour en instruction conserve désormais les actes liés à une génération et
leur numéro, et réinitialise le statut des documents non envoyés. Ces Documents
sont exclus de la suppression historique des projets manuels. Les générations
numérotées dont le fichier est absent ressortent en orange dans l'historique,
avec le numéro et la mention **Numéro attribué · À réparer**.

## Numéro réservé ou récupéré et nom du fichier

La page ne demande plus de validation intermédiaire : les boutons **Générer le
fichier** et **Actualiser l’aperçu** s'activent lorsque les contrôles du formulaire
sont satisfaits (champs requis, types, listes et numéro attribué si nécessaire).
Chaque action reconstruit et valide entièrement le contexte côté serveur avant
de générer le DOCX ou le PDF. Les contrôles du navigateur ne remplacent pas cette
validation métier.

Le brouillon conserve les saisies et le nom personnalisé tant que la configuration
du nom du template reste identique. Si elle change dans le back-office, une
actualisation reprend le nouveau nom configuré et conserve les autres saisies.

Les saisies du brouillon sont propres à la session de l'utilisateur et à l'URL
du dossier/template (les variantes de paramètres d'URL ont leurs brouillons
distincts). Elles sont conservées après soumission, pour cinq URLs au maximum.
Avec le moteur Django par défaut, ces sessions sont stockées en BDD dans
`django_session`, séparément des snapshots définitifs de génération.
Le numéro n'est jamais repris automatiquement à une nouvelle ouverture ou une
actualisation. Seul le retour immédiat d'un aperçu ou d'une erreur conserve la
sélection pour poursuivre la préparation. Une génération réussie la retire ;
réutiliser le numéro exige ensuite **Récupérer un existant**. La réservation
reste enregistrée en BDD pour la traçabilité et n'est pas réattribuée.

Exécuter manuellement **en BDD dev**, après 0016,
`sql/generation_doc/0017_numeros_documents.sql` avant de tester cette fonctionnalité
ou la création classique d'un acte en dev. Ce script n'est jamais exécuté par l'application.

La nature facultative du template détermine la série de numérotation. Le Document
créé conserve toujours la nature **Fichier généré** et reçoit uniquement le numéro
choisi. Aucun circuit de signature n'est déclenché.

Dans **Informations déjà connues**, **Générer le numéro** demande confirmation
puis réserve un numéro côté serveur. Ouvrir la page ne réserve rien.
**Récupérer le numéro** propose les numéros de la même nature pour le dossier
et les dossiers de son ensemble lié auxquels l'utilisateur a accès. Il réutilise
le numéro sélectionné sans incrémenter le compteur. Une nature à numérotation
manuelle permet la récupération, mais pas la réservation automatique.

Pour les actes, les créations classiques en dev et les réservations partagent
un compteur PostgreSQL verrouillé par nature et année. Le format existant est
conservé ; un compteur sans antécédent commence à 1000. Pour **Avis Instance**,
le numéro réservé est l'identifiant entier issu de la séquence existante des avis.
Une réservation abandonnée reste consommée. Le fonctionnement de production
n'est pas modifié.

La balise système `{{ document.numero }}` est protégée : elle ne peut pas être
renseignée avec le crayon ni remplacée par une valeur envoyée par le navigateur.
La réservation est liée au dossier, au template, à sa nature et à l'utilisateur.
La génération contrôle ces liens et conserve la référence dans son historique.

Le back-office propose la chip **Numéro du document** pour le nom du fichier.
La page de génération affiche le nom et permet de le modifier pour la préparation
en cours. Une variable sans numéro reste en attente ; il faut générer ou récupérer
le numéro avant de produire le fichier. Le serveur recalcule et valide le nom.
Plusieurs versions peuvent partager le numéro ; les collisions de fichiers
continuent à ajouter `_2`, `_3`, etc. sans changer ce numéro.

Dans **Back-office → Documents → Templates**, **Ajouter un template** ouvre
le formulaire de création (URL `#documents/templates/nouveau`). Il reprend
les champs et chips de l'édition : nom, chemin du Word existant sous
`Templates/`, démarches, activation, destination et nom du fichier généré.
La **Nature (facultative)** peut rester sur `---`. Enregistrer crée le template
et lance son analyse ; les erreurs du Word sont affichées dans son rapport.
Annuler revient au catalogue sans créer de ligne. Aucun nouveau script SQL
n'est nécessaire après 0016 et aucun fichier Word n'est téléversé par ce formulaire.

La nature du template est facultative après exécution manuelle en BDD dev de
`sql/generation_doc/0016_template_nature_facultative.sql`. Le choix `---` du
back-office permet de la laisser vide ; cela ne rend pas la configuration
incomplète. La nature du Document produit reste « Fichier généré ».

## Fichiers de l'historique : vérification et correction

Exécuter manuellement en **BDD dev** `sql/generation_doc/0015_corrections_fichiers_generes.sql`
après 0014. Aucune exécution automatique. Le script ajoute le journal JSON
`file_corrections`, sans modifier les snapshots du contexte et du template.

Après affichage de la page, une requête vérifie les fichiers de l'historique,
en regroupant les lectures par destination NAS : coche verte si trouvé,
croix rouge si absent, état gris si le NAS ou le chemin ne peut être vérifié.
Le téléchargement se fait via l'icône à côté du nom du fichier.

Pour un fichier absent uniquement :
- **Retrouver le fichier** ouvre un dialogue proposant les `.docx` de l'ancien
  emplacement et de la destination actuelle du template. Le serveur contrôle
  de nouveau l'absence de l'ancien fichier, le dossier, le nom et les droits.
  Aucun fichier n'est déplacé ou modifié. Un document utilisé ailleurs dans
  AGIDA ne peut pas être réassocié via cette interface.
- **Supprimer de l'historique** demande confirmation puis supprime la génération
  et son rattachement au dossier, ainsi que le Document s'il n'a aucune autre
  utilisation. Aucun fichier NAS n'est supprimé. Une vérification impossible
  interdit cette action pour ne pas confondre une panne NAS et un fichier absent.

Une réassociation conserve ancien/nouveau nom et chemin, auteur, date et
empreinte SHA-256 du fichier choisi. Le contexte et les empreintes de génération
restent inchangés. Si le contenu diffère du Word initial, un message le signale.
Toutes les mutations sont des POST protégés par CSRF, limités au dossier autorisé
et à l'environnement dev. Elles n'alimentent pas une nouvelle génération.

## Catalogue configurable des balises

Le type **Liste répétable (texte)** (`LIST`) permet de saisir plusieurs textes avec
ajout et suppression de lignes. Exécuter manuellement le script dev
`sql/generation_doc/0013_balise_liste_repetable.sql` avant de l'utiliser.
Ce script ne crée aucune balise. Pour la boucle ajoutée à
`Templates/TEST/test_generation.docx`, créer dans le back-office : code `projet.noms`,
origine Saisie instructeur, type Liste répétable (texte), libellé Noms et libellé
d'un élément Nom. L'option Obligatoire impose au moins un texte renseigné ; sinon
la liste peut être vide. Les lignes blanches sont ignorées. Limites : 100 lignes,
500 caractères par ligne. Le contexte contient une liste Python de chaînes,
ou `[]` si elle est vide, utilisable par `{%p for nom in projet.noms %}`.
L'alias local `nom` n'est pas une balise à créer au catalogue.
Les listes de blocs à plusieurs champs ne sont pas gérées dans cette première version.

Après exécution manuelle en BDD dev de `sql/generation_doc/0012_configuration_balises.sql`,
Documents → Balises permet de créer et modifier les définitions du catalogue.
La fiche règle libellé, origine, type, obligatoire, aide pour la saisie instructeur et
activation. Le code est fixe après création afin de ne pas casser les Word existants.

Trois origines sont proposées : information AGIDA choisie dans une liste contrôlée,
champ de formulaire identifié par démarche et champ, ou saisie instructeur.
Le mode CONNUE / A_RENSEIGNER est déduit de l'origine. Une même balise peut utiliser
un champ différent dans chaque démarche ; une seule source est autorisée par
démarche. Aucune expression Python, SQL ou accès arbitraire aux attributs n'est
interprété. Les champs sont reliés par identifiant, pas par leur libellé.

Les types de cette version sont TEXT, TEXTAREA, INTEGER, DECIMAL, DATE et BOOLEAN.
Les réponses sont converties dans le type déclaré ; une valeur incohérente donne
une erreur explicite. Zéro et False restent des valeurs renseignées. Une réponse
absente est demandée à l'instructeur si la balise est obligatoire ; sinon elle peut rester vide.
Le réglage `allow_blank` n'est plus proposé : la colonne est conservée pour
compatibilité et synchronisée à l'inverse de `required` lors des enregistrements,
mais le moteur utilise uniquement `required`, y compris pour les anciennes fiches.
Le catalogue permet de filtrer les balises actives et inactives. Commune est une
source de formulaire et n'est plus proposée dans le menu des informations AGIDA.
Depuis « Configurer cette balise », le retour mène au template d'origine.
Le moteur continue de prendre en charge les anciens providers et les Word existants.

Le rapport d'analyse propose « Configurer cette balise » pour un code inconnu.
Après enregistrement, les rapports des templates utilisant ce code sont invalidés
puis réanalysés. Si une lecture NAS échoue, la balise reste enregistrée et une
alerte signale le template à revérifier. `TemplateBalise` n'est jamais éditée à la main.
L'écran conserve sa fiche dans une URL `#documents/balises/<id>`.

Les routes sont réservées aux administrateurs en dev, avec POST protégé par CSRF.
Les tests utilisent des bases et NAS simulés ; aucun script SQL n'a été exécuté.

La sélection d'une démarche ou d'un template affiche la même modale de chargement
que les actions du formulaire, même avant le premier template sélectionné. Les
menus se placent côte à côte si leur largeur le permet, puis sur deux lignes sur
écran étroit. Les messages de génération occupent la largeur sous les deux boutons.

Le Word `Templates/TEST/test_generation.docx` a été enrichi avec une condition
sur `dossier.commune`, une boucle sur trois textes fixes et des textes en couleur.
Son original a été conservé dans une sauvegarde `.bak` sur le NAS dev.
Exécuter manuellement `sql/generation_doc/0011_balise_commune_test.sql` pour
déclarer la balise connue qui lit le champ Commune de la démarche Test. Les
contrôles Jinja et les variables locales d'une boucle ne sont pas des entrées
du catalogue ; une nouvelle donnée dynamique doit, elle, y être déclarée.

En dev, l'icône « Générer un fichier » de l'en-tête du dossier ouvre
`/document-generation/dossier/<numero>/`. La navbar, la timeline latérale et la
mini-timeline sont conservées. Le breadcrumb ajoute « Génération de fichier ».

La démarche du dossier est présélectionnée. Le choix d'une autre démarche sert
uniquement à filtrer les modèles ; il ne modifie pas le dossier. Le menu propose
les modèles actifs, à configuration complète et dont le dernier rapport d'analyse
est valide, associés à cette démarche ou globaux. Après sélection, le Word est
relu et analysé avant d'afficher le formulaire commun et l'aperçu PDF.

Un changement de démarche ou de template demande confirmation si des saisies
sont en cours. Les droits sur le dossier s'appliquent à la page et à l'aperçu.
Aucun SQL supplémentaire n'est requis ; aucun enregistrement Document n'est créé.
L'ancienne URL de test avec `/template/<id>/` reste disponible en dev.

## Générer le fichier sur le NAS dev

Après validation du contexte, « Générer le fichier » rend le Word et l'enregistre
selon la destination et le nom configurés dans le back-office. Le message de
confirmation indique le nom réel et le dossier NAS. Le service `services.output`
est strictement limité à `.env.dev`, refuse les racines communes avec la production,
les remontées de dossier et les liens de redirection. Il crée les sous-dossiers
manquants puis ouvre le fichier en mode exclusif `xb` : les collisions donnent
`_2`, `_3`, etc., y compris lors de générations simultanées. Un échec supprime
uniquement le fichier partiel créé par cette tentative. Le template source reste
inchangé. Aucune ligne Document ni historique n'est créé en BDD à cette étape.

« Actualiser l’aperçu » se trouve en haut à droite du panneau PDF et soumet le
même formulaire. Les trois actions affichent une modale plein écran avec un GIF,
bloquent les interactions et transmettent la position de scroll pour la restaurer
au retour, y compris en cas d'erreur. Le résultat de génération est affiché sous
« Générer le fichier ». Les collisions reconnaissent aussi le statut SMB
`STATUS_OBJECT_NAME_COLLISION`/`EEXIST` : `SMBOSError` n'est pas une sous-classe
de `FileExistsError`. Les refus d'accès ne sont pas traités comme des doublons.
L'aperçu reste temporaire et sa purge n'est pas modifiée.
Les tests NAS sont simulés : aucune écriture NAS réelle n'est faite par les tests.

# Contexte normalisé — étape 2

Depuis du code Django en dev, avec une instance `Dossier` enregistrée :

```python
from document_generation.services.context import DocumentContextBuilder

context = DocumentContextBuilder().build(dossier)
# {"dossier": {"numero": 30769307, "nom": "..."},
#  "beneficiaire": {"nom": "DUPONT", "prenom": "Jean", "nom_complet": "Jean DUPONT"}}

# Résolution ciblée : aucune lecture des contacts ici.
context = DocumentContextBuilder().build(dossier, codes=["dossier.numero", "dossier.nom"])
```

Le service ne charge pas lui-même le dossier et ne réalise aucune écriture.
Le nom du dossier provient de `nom_dossier`. Les textes sont débarrassés des
espaces périphériques, sans imposer de casse ; un texte absent ou vide vaut
`None`. Le numéro reste un entier. Le nom complet combine le prénom puis le nom,
en conservant la partie présente si l'autre manque. Aucun nom de société n'est
substitué à l'identité personnelle ; les balises de personne morale viendront
séparément si nécessaire.

Le bénéficiaire est lu via les associations existantes, une seule fois par appel
à `build`, uniquement si nécessaire. Un même contact lié plusieurs fois reste un
seul bénéficiaire grâce à `distinct()`. Plusieurs contacts distincts provoquent
`BeneficiaireAmbiguError`. Aucun bénéficiaire donne des valeurs `None`.
Les erreurs techniques ne sont pas transformées en valeurs absentes.

Pour ajouter une balise connue : écrire une fonction dans `services/providers.py`,
l'enregistrer dans `KNOWN_PROVIDERS` et ajouter son entrée au catalogue via l'admin
ou un script SQL dev. Aucune expression Python ni chemin ORM n'est lu de la BDD.
Un code sans provider lève `BaliseNonResolueError`. Le builder ne consulte pas le
catalogue : il résout tous les codes du registre, ou la sélection explicite reçue.
L'exploitation de `actif`, `mode`, `required`, `allow_blank` et du type du catalogue
pour préparer une génération sera une étape distincte.

Le script `sql/generation_doc/0003_premieres_balises_connues.sql` prépare les cinq
entrées du catalogue sans écraser celles déjà configurées. Il est à exécuter
manuellement en dev ; aucun changement de structure SQL n'est nécessaire.

Vérifications isolées, sans BDD réelle ni NAS :

```powershell
# Depuis autorisations/src
python -m tests tests.unit.admin.test_generation_context tests.unit.admin.test_generation_catalogue tests.unit.admin.test_admin_schema_grouping
```

# Analyse Word — étape 3

`docxtpl==0.20.2` est déclaré dans `requirements.txt`. Le seul template de test
est désormais `Templates/TEST/test_generation.docx` sur le NAS dev ; une copie source est
conservée dans `test_templates/test_generation.docx`. Il s'agit d'un Word de test,
pas d'un document produit par le moteur de génération.

1. Exécuter manuellement en dev `sql/generation_doc/0004_balise_manuelle_test.sql`
   pour ajouter `quantite_prelevement` en mode `A_RENSEIGNER` (sans modifier une
   éventuelle entrée existante). Les balises connues viennent du script 0003.
2. Créer un template dans l'admin, avec une nature existante et le chemin relatif
   `TEST/test_generation.docx`, sans préfixer par `Templates/`.
3. Revenir à la liste des templates (pas à la fiche du template), cocher la case
   à gauche du template, choisir **Vérifier le modèle (lecture seule)** dans le
   menu **Action** (désormais « Vérifier le modèle et synchroniser ses balises »), puis cliquer sur **Envoyer**. Le rapport apparaît en haut de
   la page après l'exécution.

Résultat attendu :

```text
beneficiaire.nom_complet    CONNUE
dossier.numero             CONNUE
quantite_prelevement        A_RENSEIGNER
toto.foo                   INCONNUE
```

Le rapport est volontairement invalide à cause de `toto.foo`. Retirer cette
balise du Word sur le NAS permet de vérifier le cas valide. L'analyseur seul reste
en lecture seule. Depuis l'étape 4, le service de vérification persiste le rapport
et synchronise les balises ; aucun rendu ni conversion PDF.

Depuis du code Django dev :

```python
from document_generation.services.analyzer import TemplateAnalyzer

report = TemplateAnalyzer().analyze(template)
resultat = report.as_dict()  # valide, balises [{code, statut}], erreurs
```

L'analyse ouvre le Word en lecture seule sous `NAS_ROOT` lu explicitement dans
`.env.dev`, puis appelle `get_undeclared_template_variables()`. L'AST Jinja de cet
appel permet de compléter les racines (`dossier`) avec les codes complets
(`dossier.numero`), après la normalisation XML de docxtpl. Corps, tableaux,
en-têtes et pieds de page sont couverts, y compris les balises réparties entre
plusieurs runs Word. Les propriétés du document, commentaires et notes ne font
pas partie du périmètre de cette première analyse.

Les accès statiques, conditions et filtres Jinja standards sont pris en charge.
Les boucles sur séquences littérales sont prises en charge ; les boucles sur
collections dynamiques, macros, affectations, appels, inclusions et accès indexés dynamiques
sont explicitement refusés ; leur prise en charge viendra si le
besoin apparaît. Les balises absentes du catalogue ou inactives et les balises
connues sans provider rendent le rapport invalide. L'analyse vérifie la structure
DOCX et la syntaxe, pas la mise en page ni le comportement d'un futur rendu.

Tests isolés :

```powershell
python -m tests tests.unit.admin.test_generation_analyzer tests.unit.admin.test_generation_context tests.unit.admin.test_generation_catalogue tests.unit.admin.test_admin_schema_grouping
```

# Back-office et synchronisation — étape 4

Avant de démarrer le code de cette étape, exécuter manuellement en BDD dev
`sql/generation_doc/0006_template_balise_et_verification.sql`. Il ajoute
`generation.template_balise`, les droits applicatifs et les champs de rapport
et d'horodatage du template. Aucune exécution SQL automatique au démarrage.

Dans **Back Office → Documents → Templates**, tous les modèles sont désormais
analysés automatiquement à l'ouverture de la rubrique. Ouvrir une fiche pour
consulter le rapport. Celui-ci affiche l'état de la syntaxe, les nombres
de balises par catégorie, les codes détectés et les erreurs. Le rapport et la date
restent conservés en base après rechargement. La date n'est plus affichée dans
la fiche. La fiche présente les métadonnées ;
leur modification est accessible avec le bouton crayon du bloc « Informations
du modèle », ainsi que dans Django Admin.

La vérification est un POST avec protection CSRF, réservé aux superutilisateurs
en dev. Les routes sont inaccessibles et le menu masqué hors dev.

`TemplateVerificationService` verrouille la fiche et effectue la mise à jour
dans une transaction :

- Une analyse complète remplace automatiquement les associations par les codes
  réellement présents, sans doublon ; les anciens codes disparus sont supprimés.
- Chaque code connu est relié à `Balise`. Un code inconnu est également conservé
  avec `id_balise=NULL` et rend le rapport invalide. Une nouvelle vérification
  rattache le code au catalogue après sa création.
- Un Word sans aucune balise produit une liste vide et efface les anciens liens.
- Si le fichier est illisible, la syntaxe erronée ou l'analyse incomplète, les
  derniers liens complets sont conservés ; le nouveau rapport invalide indique
  que la liste n'a pas été actualisée.
- `TemplateBalise` n'a aucun écran d'ajout, modification ou suppression manuels.
  L'action Django Admin utilise le même service que le back-office.

Le service est la seule orchestration d'écriture ; `TemplateAnalyzer` reste
utilisable séparément sans synchronisation. Ni versionnage ni génération de
document n'est ajouté à cette étape.

Tests isolés, sans BDD réelle ni NAS :

```powershell
python -m tests tests.unit.back_office.test_documents tests.unit.admin.test_generation_analyzer tests.unit.admin.test_generation_context tests.unit.admin.test_generation_catalogue tests.unit.admin.test_admin_schema_grouping
```

# Validation du contexte — étape 5

`GenerationContextValidator` reçoit la liste des définitions `Balise` utilisées,
le contexte imbriqué des providers, et éventuellement les valeurs instructeur
dans un dictionnaire indexé par code complet. Il ne charge pas le catalogue,
ne résout pas les providers et n'effectue aucune écriture. Son résultat est :

```python
{
    "resolved": {"dossier": {"numero": 30769307}},
    "missing": [
        {"code": "quantite_prelevement", "libelle": "Quantité prélevée",
         "type": "DECIMAL", "required": True, "allow_blank": False,
         "help_text": "", "reason": "saisie_requise"}
    ],
    "errors": [],
}
```

`missing` contient les informations obligatoires à demander, avec les métadonnées
utiles au futur formulaire. `errors` contient des objets `{code, message}` pour
les saisies interdites ou configurations invalides. Le contexte `resolved` ne
contient que les balises sélectionnées dont la valeur est acceptée. Un contexte
est prêt pour la suite uniquement si `missing` **et** `errors` sont vides.

| Cas | Résultat |
| --- | --- |
| CONNUE, valeur présente (y compris `0` ou `False`) | Résolue |
| CONNUE, vide, `required=True` | À demander (`connue_vide`) |
| A_RENSEIGNER, absente et `required=True` | À demander (`saisie_requise`) |
| Facultative, absente ou vide | Acceptée, valeur `None` si absente |
| Saisie explicite vide et obligatoire | Erreur ; reste à demander |

Une valeur vide est `None`, une chaîne vide ou composée d'espaces, ou une
collection vide. Une clé absente diffère d'une valeur explicitement saisie vide.
Les valeurs connues vides et facultatives ne provoquent pas de demande de saisie.
Les textes acceptés sont débarrassés de leurs espaces périphériques ; les types
Python restent conservés. Aucun contrôle de type, de choix de liste ou de format
de date n'est encore implémenté.

Les saisies peuvent compléter une valeur connue vide, mais ne remplacent pas une
valeur connue présente. Une saisie hors sélection, une balise inactive, un mode
inconnu ou une structure de contexte incorrecte produit une erreur. Le catalogue
sélectionné doit avoir été vérifié : les codes inconnus sont détectés en amont par
`TemplateAnalyzer`, et un provider manquant reste une erreur du resolver.

Exemple, sans accès BDD (les objets `Balise` servent ici de définitions en mémoire) :

```python
from autorisations.models.models_generation import Balise
from document_generation.services.context import DocumentContextBuilder
from document_generation.services.validation import GenerationContextValidator

balises = [
    Balise(code="dossier.numero", mode="CONNUE", required=True, allow_blank=False),
    Balise(code="quantite_prelevement", libelle="Quantité prélevée",
           mode="A_RENSEIGNER", type="DECIMAL", required=True, allow_blank=False),
]
context = DocumentContextBuilder().build(dossier, codes=["dossier.numero"])
validator = GenerationContextValidator()
result = validator.validate(balises, context)  # quantité dans missing
result = validator.validate(balises, context, manual_values={"quantite_prelevement": 0})
# missing et errors vides ; le zéro est conservé dans resolved.
```

Aucune modification SQL n'est nécessaire : `required` et `allow_blank` existent
déjà. Aucun formulaire ni rendu de document n'est ajouté.

Le back-office Templates utilise maintenant des styles dédiés cohérents avec
les formulaires d'avis : recherche, filtre actif/inactif, statut de validation
dans la liste, fiche adaptative, rapport avec compteurs et badges, bouton avec
état de chargement et actualisation du statut dans la liste après vérification.

Tests :

```powershell
python -m tests tests.unit.admin.test_generation_validation tests.unit.back_office.test_documents tests.unit.admin.test_generation_analyzer tests.unit.admin.test_generation_context tests.unit.admin.test_generation_catalogue tests.unit.admin.test_admin_schema_grouping
python -m tests tests.interface.back_office.test_documents
```

# Classement NAS et édition des templates

Le NAS dev contient maintenant sous `Templates/` les dossiers de démarches,
sans niveaux d'année, notamment :

```text
Templates/
  TEST/test_generation.docx
  Activites_agricoles/
  Activites_commerciales/
  Aretes/
  Documents_planification_urbanisme/
  Manifestations_publiques/
  Manifestations_sportives/
  Missions_scientifiques/
    Coeur_de_parc/
    Especes_protegees/
  PDV_et_son/
  Survol_hélicoptere/
  Travaux/
    Aire_adhesion/
    Non_soumis_urbanisme/
    Soumis_urbanisme/
  Autre/
  Declaration_manifestations/
  Manoeuvres_militaires/
```

Un futur `fiche_de_suivi.docx` pourra rester directement à la racine de
`Templates/` ; il n'est pas créé. L'organisation physique ne remplace pas les
associations aux démarches en BDD et ne les modifie pas automatiquement.

Le test a été déplacé physiquement dans `TEST/`, sans modification du contenu.
Mettre à jour son chemin dans la fiche via le crayon, ou exécuter manuellement
`sql/generation_doc/0007_chemin_template_test.sql` sur la BDD dev.

Le crayon en haut à droite d'« Informations du modèle » active l'édition : nom,
nature, chemin relatif, activation et sélection de zéro, une ou plusieurs
démarches. **Annuler** abandonne la saisie ; **Enregistrer** utilise une requête
POST protégée par CSRF, réservée aux administrateurs en dev. Les erreurs sont
affichées dans le formulaire. Une modification invalide le rapport et sa date ;
les derniers liens de balises restent conservés jusqu'à la prochaine analyse
complète. Aucun Word n'est déplacé par la modification de son chemin dans la fiche.

La vérification s'effectue désormais automatiquement à l'ouverture de la rubrique.
Les cartes de la liste occupent la largeur de leur contenu, avec adaptation
aux écrans étroits.

# Analyse automatique et modèles de test complémentaires

Chaque entrée dans la rubrique **Documents → Templates**, y compris après avoir
visité une autre rubrique, déclenche automatiquement un POST protégé par CSRF
sur `back-office/documents/templates/verifier/`. Tous les templates, actifs et
inactifs, sont vérifiés puis affichés. L'ouverture d'une fiche, la recherche et
le retour à la liste ne relancent pas l'analyse. La sauvegarde des métadonnées
relance aussi l'analyse du modèle modifié avant de renvoyer sa fiche.

Le bouton de vérification, l'horodatage et les anciennes notices explicatives
ont été retirés de la fiche. Les dates restent conservées en base pour le suivi.
Les compteurs CONNUES / A RENSEIGNER / INCONNUE utilisent les mêmes couleurs que
les badges du tableau : vert, jaune et rouge.

Trois Word supplémentaires sont disponibles sur le NAS dev sous `Templates/TEST/`
et leurs copies de référence dans `test_templates/` :

- `test_syntaxe_invalide.docx` : un bloc `if` non refermé, rapport invalide avec
  erreur Jinja attendue.
- `test_if.docx` : condition sur `beneficiaire.nom_complet`, puis balise
  `dossier.numero` ; rapport valide avec le catalogue du script 0003.
- `test_for.docx` : boucle sur deux libellés littéraux et `dossier.numero` ;
  rapport valide, les variables locales de boucle ne sont pas des balises.

Exécuter manuellement `sql/generation_doc/0008_templates_tests_analyse.sql` en BDD
dev pour ajouter leurs fiches. Aucune nouvelle table ni balise n'est nécessaire.
Aucun Word n'est rendu par le moteur et aucun PDF n'est créé.

# Étape 6 — page de travail et formulaire dynamique

La route dédiée est disponible uniquement en dev :

```text
/document-generation/dossier/30769307/template/<id_template>/
```

Elle est nommée `document_generation:generer_document`. Aucun bouton n'est ajouté
aux écrans d'instruction à cette étape. L'utilisateur doit être connecté et
concerné par le dossier selon la règle existante d'AGIDA, ou superutilisateur.
Le modèle doit être actif et global, ou associé à la démarche du dossier.

Le GET analyse le Word courant en lecture seule (sans modifier TemplateBalise),
charge les définitions du catalogue et résout uniquement les balises connues de
ce Word. Une erreur de syntaxe, une balise inconnue/inactive ou un provider absent
bloque la préparation avec un message. Les informations déjà connues sont
affichées avec leur libellé et leur code.

`DynamicDocumentForm` construit un champ par balise à compléter : les CONNUES
obligatoires vides dont le vide est interdit, et les A_RENSEIGNER, y compris les
facultatives. Il utilise les noms HTML `balise_<id>` et une correspondance
`balise_map` vers les définitions du catalogue. Les six types pris en charge sont
TEXT, TEXTAREA, BOOLEAN, DATE, INTEGER et DECIMAL. SELECT/MULTISELECT produisent
une erreur explicite de configuration jusqu'à une prochaine étape.

Les booléens utilisent un choix Oui/Non/Choisir pour distinguer `False` d'une
absence de réponse. Les dates attendent le format HTML `YYYY-MM-DD` ; les nombres
sont convertis en `int` ou `Decimal`. Aucune métadonnée `default_value` n'est
ajoutée à la BDD à ce stade ; aucun défaut ne masque une saisie obligatoire.

Un champ facultatif laissé vide peut être omis des valeurs manuelles. Une balise
obligatoire doit être présente et renseignée dans le POST, quelle que soit
l'ancienne valeur de `allow_blank`. Les espaces seuls sont considérés comme vides.

Au POST, les données du dossier et le Word sont relus. Django valide les champs,
puis le validateur métier contrôle les saisies avec le contexte connu. Le service
fusionne les structures imbriquées, puis repasse le contexte final dans le
validateur. Aucun champ envoyé hors du formulaire ne peut remplacer une valeur
connue. Les utilitaires `set_nested_value` et `merge_contexts` rejettent les
collisions et les écrasements silencieux, y compris pour `0` et `False`.

Si les listes `missing` et `errors` sont vides, la page affiche **Contexte complet**,
**Le document est prêt à être généré**, et un bloc JSON de contrôle en dev. Le
contexte Python conserve les dates, booléens et Decimal ; leur affichage JSON
utilise `DjangoJSONEncoder`. Aucune donnée n'est sauvegardée, aucun DOCX n'est
rendu et aucun PDF n'est créé. La réponse est privée et non mise en cache.

## Test manuel du parcours

1. Le modèle `Templates/TEST/test_formulaire.docx` est déposé sur le NAS dev.
2. Exécuter manuellement `sql/generation_doc/0009_template_formulaire_dynamique.sql`
   sur la BDD dev après les scripts précédents. Il ajoute deux balises manuelles
   (`projet.quantite_prelevement` et `projet.commentaire`) et la fiche du modèle,
   sans écraser les configurations existantes. Il affiche l'identifiant du modèle.
3. Ouvrir `/document-generation/dossier/<numero_existant>/template/<id_retourne>/`.
4. Vérifier les informations connues et les deux champs : quantité obligatoire,
   commentaire facultatif.
5. Soumettre une valeur invalide ou manquante : une erreur doit apparaître.
6. Soumettre `0` ou une quantité décimale, et éventuellement un commentaire :
   la page indique que le contexte est complet, avec `projet` imbriqué dans le JSON.

Tests isolés (aucun accès réel BDD/NAS) :

```powershell
python -m tests tests.unit.admin.test_generation_workflow tests.unit.admin.test_generation_validation tests.unit.admin.test_generation_context tests.unit.admin.test_generation_analyzer tests.unit.admin.test_generation_catalogue tests.unit.admin.test_admin_schema_grouping tests.unit.back_office.test_documents
```

# Étape 7 — premier DOCX de test en mémoire

La page de l'étape 6 conserve le même URL. Après un POST de validation réussi,
le bouton **Générer un DOCX de test** apparaît dans le formulaire. Il envoie les
champs courants avec `action=generate_docx` : le serveur recharge les données et
le modèle, valide à nouveau les champs et le contexte métier, puis rend le Word.
Le contexte JSON affiché n'est jamais utilisé comme source de confiance.

`template_path.py` centralise la résolution depuis `.env.dev` : fichier `.docx`
existant sous `NAS_ROOT/Templates/`, chemin relatif contrôlé et lecture seule.
Le partage SMB autorise les autres accès au fichier, notamment son ouverture
dans Word ; notre accès reste strictement `rb`. Le template est lu une fois
par préparation. Les octets analysés sont transmis au renderer, ce qui empêche
de rendre un autre contenu si le fichier est modifié entre analyse et rendu.

`DocxRenderer.render_to_memory(source, context)` accepte ce snapshot binaire
(ou un chemin local/UNC pour un appel isolé avec une source déjà contrôlée).
Il utilise docxtpl, un environnement Jinja sandboxé avec `StrictUndefined` et
l'échappement XML, puis sauvegarde dans un `BytesIO` remis en position zéro.
Une balise absente du contexte provoque une erreur de rendu plutôt qu'un vide
silencieux. Le template original n'est jamais sauvegardé.

Le contexte garde ses types natifs pour les conditions et les boucles. Au moment
de l'affichage Word uniquement : dates/datetimes en `jj/mm/aaaa`, booléens en
`Oui`/`Non`, `None` en texte vide. Les nombres gardent leur précision et le texte
multiligne produit des sauts de ligne Word. Les caractères `&`, `<`, `>` sont
échappés. Les dates restent donc des objets Python dans le validateur, et les
booléens restent de vrais booléens dans les conditions Jinja.

Les boucles peuvent parcourir une liste littérale ou une collection du contexte,
par exemple `projet.especes`. Dans ce dernier cas, la collection doit être une
balise du catalogue résolue par un provider ; ses alias (`espece`, `loop`) ne
sont pas des balises globales. Aucun provider métier fictif d'espèces n'est
ajouté. Le renderer est testé avec une liste de dictionnaires et des conditions
vraies/fausses. Les formulaires ne proposent toujours pas de saisie de listes.

Le navigateur reçoit une `FileResponse` en pièce jointe :

```text
Projet_<nom_template_normalise>_<numero_dossier>.docx
```

Le buffer reste ouvert jusqu'à la fin de la réponse, puis Django le ferme.
Aucun fichier temporaire local, écriture NAS, `Document` AGIDA ni historique de
génération n'est créé. Aucun PDF ou appel LibreOffice. La réponse est privée et
non mise en cache. Aucun nouveau script SQL n'est nécessaire pour cette étape.

## Test avec test_generation

Utiliser la fiche correspondant à `TEST/test_generation.docx` dans l'URL de
travail, valider les informations puis télécharger le DOCX. Ce Word contient
encore, lors de la vérification de développement, `toto.foo`, volontairement
inconnue : le parcours applicatif doit rester bloqué tant que cette ligne n'est
pas retirée du modèle par son auteur ou que le catalogue n'est pas corrigé.
Le test isolé du renderer a utilisé une valeur fictive explicite pour ce code,
sans modifier le fichier ni le catalogue ; il ne contourne pas les contrôles de
la page applicative. Le hash du Word NAS était identique avant/après le test.

## Règles de rédaction Word et erreurs

Saisir chaque balise `{{ ... }}` et chaque bloc `{% ... %}` d'un seul bloc, sans
changement de style au milieu. Le moteur tolère les balises réparties entre
plusieurs runs dans les cas testés, mais cette pratique reste à éviter.
Les styles de paragraphes, tableaux, dimensions de page, en-têtes et pieds de
page sont vérifiés automatiquement sur un Word de test. Cela ne remplace pas
un contrôle visuel dans Word pour un arrêté réel complexe.

Un fichier absent/illisible, une erreur de rendu ou de sauvegarde mémoire
produit un message métier sur la page. Les erreurs de rendu sont journalisées
avec exception, numéro de dossier, identifiant du template et utilisateur.
Les saisies valides restent disponibles pour corriger le modèle et réessayer.

Tests isolés :

```powershell
python -m tests tests.unit.admin.test_docx_renderer tests.unit.admin.test_generation_workflow tests.unit.admin.test_generation_analyzer tests.unit.admin.test_generation_context tests.unit.admin.test_generation_validation tests.unit.admin.test_generation_catalogue tests.unit.admin.test_admin_schema_grouping tests.unit.back_office.test_documents
```

# Étape 8 — aperçu PDF à la demande

Sur la page de génération, **Actualiser l’aperçu PDF** soumet les champs courants.
Le serveur reconstruit et revalide le contexte avant toute conversion. La page
revient avec les valeurs saisies et, après succès, le PDF dans une iframe à
droite. Le bouton est désactivé pendant le POST, avec un message de progression.
La validation seule et le téléchargement DOCX restent deux actions distinctes.
Un GET ou une modification de champ ne lance jamais LibreOffice.

Le renderer produit le DOCX en mémoire comme à l'étape 7. Le service de preview
écrit ce buffer dans un répertoire de travail local uniquement pour LibreOffice :

```text
<répertoire temporaire système>/agida_document_generation/
  user_<id_utilisateur>/
    dossier_<id_interne_dossier>/
      template_<id_template>/
        preview.pdf
  .locks/
```

Il s'agit de `/tmp` sur Linux et du dossier temporaire Windows, jamais du NAS.
Les identifiants internes sont des entiers positifs. Aucun nom de fichier ou
chemin fourni par l'utilisateur n'est utilisé. Le paramètre Django optionnel
`DOCUMENT_PREVIEW_ROOT` doit rester sous le répertoire temporaire système.

Chaque conversion utilise un sous-répertoire de travail et un profil LibreOffice
isolé. Le processus est lancé sans shell, en mode headless, avec un délai borné.
Le code vérifie le retour, l'existence, la taille et l'en-tête `%PDF-` du résultat.
Le PDF courant n'est remplacé qu'après succès, par remplacement atomique. Le DOCX,
le profil et les intermédiaires sont supprimés après succès ou échec. Après une
conversion réussie, seul `preview.pdf` reste dans le dossier du contexte.

En cas de formulaire invalide, template cassé, LibreOffice absent, timeout ou
erreur de conversion, l'ancien PDF reste disponible et un message est affiché.
Les erreurs de conversion sont journalisées avec dossier, template et utilisateur.
Le timeout interrompt l'arbre de processus sous Windows ou le groupe sous Linux.
Un verrou système par contexte sérialise conversion, lecture et nettoyage entre
workers ; une opération concurrente reçoit un message invitant à réessayer.
Les petits fichiers `.locks` sont conservés pour éviter de recréer deux verrous
indépendants pour le même contexte.

## LibreOffice

Le service cherche `libreoffice` ou `soffice` dans PATH et, sous Windows, le
`soffice.com` de `Program Files/LibreOffice/program`. Il peut être configuré avec
`LIBREOFFICE_BINARY` dans les paramètres Django ou l'environnement dev.
Le délai par défaut est **60 secondes**, adapté au démarrage à froid mesuré
localement. `DOCUMENT_PREVIEW_TIMEOUT` dans les paramètres Django ou l'environnement
permet de le modifier. Aucun paramétrage ni installation de production n'est fait.

## Accès HTTP

Le PDF est servi par Django, jamais par une exposition directe du répertoire
temporaire :

```text
/document-generation/preview/<numero_dossier>/<id_template>/?v=<version>
```

La vue exige une connexion et les mêmes droits sur le dossier/template que la
page de travail. Le chemin est reconstruit à partir de `request.user.pk` : aucun
paramètre ne permet de choisir un autre utilisateur. Sans PDF propre à cet
utilisateur, la réponse est 404. Les routes restent réservées au dev.
La réponse est privée, non mise en cache et autorise une iframe de la même origine.
Un paramètre de version renouvelle l'URL à chaque affichage de la page.
Le contenu est lu en mémoire pour ne pas garder le fichier verrouillé par Windows
pendant que le navigateur affiche le PDF.

Deux onglets du même utilisateur, pour le même dossier/template, partagent le
dernier aperçu ; aucun token d'onglet n'est ajouté. N'importe quel worker de la
même VM retrouve le fichier via son chemin déterministe.

## Corrections des informations connues

Le crayon du bloc « Informations déjà connues » permet de corriger les valeurs
pour le document en cours uniquement. Les champs suivent le type et les règles
de la balise ; les corrections sont conservées lors des POST de validation,
d'aperçu et de téléchargement. Aucun dossier ni catalogue n'est modifié.
« Enregistrer » applique les corrections au document en cours, sans écriture BDD.
« Annuler » restaure les dernières valeurs acceptées dans ce bloc.
Un nouveau chargement GET repart également des données du dossier.

Les saisies en cours sont protégées par une confirmation avant de quitter la page.
Le lien Templates affiche « Voulez-vous vraiment abandonner la génération en cours ? ».
Pour l'actualisation et la fermeture de l'onglet, le navigateur impose son propre
message. La validation, la génération DOCX et l'actualisation de l'aperçu restent
possibles sans confirmation d'abandon.

La destination et le nom de la génération sur NAS sont configurables
dans Back-office → Documents → Templates → Informations du modèle, après
exécution manuelle du script `sql/generation_doc/0010_destination_nom_fichier.sql`.
Exemples : `{dossier.emplacement}/Work/` et `DIR-I-{num_doss}.docx`.
Les deux champs sont obligatoires à l'enregistrement dans le back-office.
Les anciennes fiches dont la configuration est vide ou invalide sont signalées
« Configuration incomplète », indépendamment de la validité du Word.
Les variables se sélectionnent via des chips : « Emplacement du dossier / »
(`{dossier.emplacement}`, destination uniquement) et « Numéro du dossier »
(`{dossier.numero}`). L'ancien alias `{num_doss}` reste compatible et est normalisé
à l'enregistrement. Une même variable n'est autorisée qu'une fois par champ.
L'extension `.docx` est affichée par défaut et séparée du nom dans l'éditeur.
Le nom de fichier propose également « Année en cours » (`{date.annee}`),
« NOM-Prénom ou Raison sociale bénéficiaire » (`{beneficiaire.identite}`) et
« JJ-MM-AA » (`{date.jour}`). Les infobulles de date utilisent la date locale
configurée dans Django. La raison sociale complète est prioritaire ; si elle
est vide, le nom en majuscules et le prénom sont utilisés. Les espaces des
valeurs sont remplacés par des tirets, y compris les espaces insécables.
Le service `services.filename.resolve_filename` prépare cette résolution pour
la sortie NAS ; il n'écrit lui-même aucun fichier et ne crée aucun Document.
L'emplacement du dossier inclut son séparateur final : on peut écrire
`{dossier.emplacement}Work/`. Les anciens patrons avec un `/` explicite après
la variable restent acceptés. La configuration incomplète colore les champs
concernés et la bordure du bloc en rouge ; la mention de bas de bloc est en italique.
L'infobulle de destination affiche la racine NAS de l'environnement configuré,
sans accès au NAS et sans rendre le module accessible en production.
La résolution et l'écriture sont réalisées par `DocumentOutputService` après
validation complète du contexte. `RecordGenerationService` enregistre ensuite
le document et son historique (voir étape 9 ci-dessous).
En cas de doublon, un suffixe automatique `_2`, `_3`, etc. sera ajouté avant
l'extension. Aucun réglage distinct de collision ou de sous-dossier n'est prévu.

## Nettoyage

Depuis `autorisations/src`, en dev :

```powershell
python manage.py clean_document_previews
python manage.py clean_document_previews --max-age-hours 2
```

La commande supprime les dossiers de contexte inactifs depuis plus de deux heures,
avec contrôle du chemin et sans suivre de liens symboliques. Les contextes en
cours de conversion sont ignorés. Les conteneurs dossier/utilisateur vides sont
également retirés. Aucun SQL, NAS, profil LibreOffice utilisateur ou autre dossier
temporaire n'est nettoyé.

Pour automatiser sur la VM dev, programmer cette commande toutes les 30 minutes
dans cron ou un timer systemd. Exemple à adapter et à installer manuellement :

```cron
*/30 * * * * cd /chemin/projet/autorisations/src && DJANGO_ENV=dev /chemin/venv/bin/python manage.py clean_document_previews --max-age-hours 2
```

Aucune tâche système n'est installée automatiquement. Sous Windows, la même
commande peut être programmée dans le Planificateur de tâches avec le Python du
venv et le répertoire de travail `autorisations/src`.

## Vérifications

Les tests couvrent le remplacement du PDF, la suppression des DOCX intermédiaires,
la conservation de l'ancien aperçu après échec, le timeout et l'arrêt des processus,
l'absence de LibreOffice, le nettoyage, les accès non connectés et l'isolation des
utilisateurs. Le test de conversion réelle est activé explicitement :

```powershell
python -m tests tests.unit.admin.test_pdf_preview tests.unit.admin.test_generation_workflow tests.unit.admin.test_docx_renderer tests.unit.admin.test_generation_analyzer tests.unit.admin.test_generation_context tests.unit.admin.test_generation_validation tests.unit.admin.test_generation_catalogue tests.unit.admin.test_admin_schema_grouping tests.unit.back_office.test_documents
$env:AGIDA_TEST_LIBREOFFICE = '1'
python -m tests tests.integration.test_pdf_preview_libreoffice
```

Le parcours d'interface (iframe, valeurs conservées, action POST et désactivation
du bouton) est également testé dans Chrome à 540 et 1600 pixels :

```powershell
python -m tests tests.interface.test_generation_preview
```

## Étape 9 — Enregistrement et historique des générations

Exécuter **manuellement en BDD dev** `sql/generation_doc/0014_historique_generations.sql`
après les scripts précédents. Il vérifie la nature existante **Fichier généré**
(active, `est_acte=false`), ajoute le format `docx` si absent, crée la table
`generation.document_generation`, ses index et les droits du rôle applicatif dev.
Aucune migration Django et aucune exécution SQL automatique.

Le bouton « Générer le fichier » écrit le Word sur le NAS dev puis crée, dans
une transaction, `Document`, `DossierDocument` et `DocumentGeneration`.
Le nom réellement attribué est conservé, suffixe `_2`, `_3`, etc. compris.
`Document.emplacement` reste relatif à la racine NAS, avec un `/` final ;
`Document.titre` contient le nom complet, extension comprise.
La nature du Document est **Fichier généré**, quelle que soit la nature de
configuration du template. Un numéro explicitement réservé ou récupéré est
recopié ; la génération ne réserve pas elle-même de numéro et ne déclenche aucun
circuit de signature. Les documents déjà générés avant cette étape ne sont pas repris.

L'historique conserve le contexte final injecté (corrections connues et saisies
manuelles), l'auteur, la date, la référence du template et un snapshot de son
ID, nom, chemin et configuration. Les empreintes SHA-256 identifient exactement
le Word source analysé et le fichier rendu. Le snapshot est du JSON : dates en
ISO et décimaux en chaînes, booléens et listes préservés. Il ne constitue pas une
copie archivée du template Word. Il contient des données personnelles et n'est
pas exposé en clair dans le tableau d'historique.

En cas d'échec BDD, la transaction est annulée et seul le nouveau fichier créé
est supprimé. Si cette compensation échoue, le message signale qu'un fichier
peut subsister et les logs permettent de le retrouver. NAS et PostgreSQL ne
partagent pas de transaction distribuée : un arrêt brutal entre les deux reste
une limite de ce mécanisme.

Sous le formulaire, même sans template sélectionné, le tableau affiche les
50 dernières générations du dossier, toutes démarches et tous templates
confondus : date, nom historique du template, fichier, auteur et téléchargement.
Le téléchargement vérifie les droits sur le dossier, l'appartenance de la
génération et le confinement du fichier au NAS dev. Un template désactivé ou
supprimé n'empêche pas d'accéder aux fichiers historiques.

Les validations, aperçus PDF et téléchargements DOCX de test historiques ne
créent aucune ligne. L'actualisation après génération reste un GET et ne crée
pas de doublon. Les aperçus restent locaux et temporaires ; la purge est inchangée.

Tests isolés, sans BDD/NAS réels :
```powershell
python -m tests tests.unit.admin.test_generation_record tests.unit.admin.test_generation_workflow tests.unit.admin.test_generation_output tests.unit.admin.test_generation_dossier
```

# Back-office · Avis

La rubrique **Avis** comporte deux sous-menus : **Formulaires d’avis** et **Thématiques**. L’ancienne adresse `#avis` ouvre toujours les formulaires ; les adresses dédiées sont désormais `#avis/formulaires` et `#avis/thematiques`.

## Formulaires d’avis

Cette sous-rubrique permet de personnaliser trois formulaires :

- **Depuis un dossier · Consultation**, pour les nouvelles demandes et l’édition des brouillons ;
- **Nouvelle demande générique**, sans dossier initial et sans enregistrement en brouillon ;
- **Ajouter un avis existant · Hors application**, pour importer dans un dossier un avis déjà reçu en dehors d’AGIDA.

La recherche et le rattachement d’un avis **déjà présent dans AGIDA** ne sont pas concernés.

## Personnaliser les champs

Choisir le formulaire à modifier, puis ouvrir la fiche d’un champ. Les flèches permettent de changer son ordre d’affichage.

Chaque fiche propose le libellé, une aide au remplissage et, selon le champ, une valeur initiale. Les valeurs initiales ne remplacent pas une saisie personnalisée ou une valeur déjà enregistrée.

L’**aide au remplissage** est affichée dans une infobulle « i » à côté du libellé, au survol ou au focus clavier, dans l’aperçu et dans le formulaire utilisateur. L’aide du **numéro de l’avis CS importé** se modifie ici également.

Le **texte indicatif dans le champ (placeholder)** apparaît tant que la zone est vide, par exemple « Note libre pour le demandeur… ». Contrairement à la **valeur initiale**, il n’est pas envoyé ni enregistré comme contenu de la note.

Les autres réglages déterminent si le champ est affiché et s’il est obligatoire pour **enregistrer le brouillon** ou **envoyer**. Un champ peut être facultatif en brouillon et obligatoire à l’envoi. Le générique ne dispose pas d’action brouillon.

Pour **Ajouter un avis existant**, l’obligation concerne uniquement **l’enregistrement** : l’import ne crée pas de brouillon et n’envoie pas de demande. Les dates, la réponse reçue, le mode de contact, la note et les pièces jointes sont configurables. L’instructeur à l’origine de la demande reste obligatoire, comme la nature, l’expert et la thématique.

Par défaut, les champs **Numéro de l’avis CS importé** et **Publication au RAA** apparaissent uniquement pour le Conseil scientifique. Une référence externe vide laisse le numéro interne s’afficher. **À publier** laisse la publication en attente ; **Déjà publié** et **Publication non requise** la considèrent traitée. Ces informations restent réservées aux avis CS, même si leur affichage est personnalisé.

Les sélecteurs structurels (nature, expert, thématique et type de demande pour le générique) restent protégés : leurs libellés et leurs valeurs initiales sont personnalisables, mais leurs obligations et leurs conditions de sélection ne peuvent pas être retirées. Les formats de documents autorisés restent contrôlés par l’application.

Les conditions protégées des experts sont affichées dans leurs fiches : l’expert interne apparaît pour une **Consultation en interne**, l’expert externe pour une **Demande à une instance**.

La fiche **Thématique de l’avis** conserve les réglages de libellé, d’aide et de valeur initiale. La liste proposée est uniquement gérée dans **Avis → Thématiques** : il n’y a plus de liste indépendante par formulaire ou par cas conditionnel.

## Thématiques

Le catalogue utilise directement le référentiel `AvisThematique`, sans créer une deuxième table de répartition. Rechercher une thématique ou filtrer par rattachement, modifier son libellé ou son rattachement, puis cliquer sur **Enregistrer** sur sa ligne. Les autres lignes en cours de saisie sont conservées.

- **Une démarche** : la thématique est proposée pour cette démarche.
- **Toutes les démarches** : la thématique est commune à toutes les démarches. Ce choix utilise la valeur historique `Autre` dans le champ `demarche`.
- **Non rattachée** : la thématique reste dans le catalogue mais n’est plus proposée quand une démarche est définie.

**Exemple — Activités commerciales :** filtrer sur ce rattachement pour retrouver Artisanat, Camping, Gîtes, Hébergement, Restauration, etc. Modifier le rattachement d’une ligne change sa présence dans les listes. Les thématiques « Toutes les démarches », comme Autre, s’ajoutent à cette sélection.

Le bloc **Ajouter une thématique** permet de créer une entrée et de choisir son rattachement. Un nom déjà utilisé est refusé. Le champ existant autorise un seul rattachement par thématique, ou toutes les démarches ; il ne s’agit pas d’une sélection de plusieurs démarches.

La même répartition est appliquée à la demande depuis un dossier, à l’import d’un avis hors application et à la demande générique dès que son **Type de demande** est choisi. Elle est aussi appliquée dans l’aperçu et contrôlée côté serveur lors d’un enregistrement. Les changements sont visibles à la prochaine ouverture du formulaire.

Modifier un rattachement ne réécrit aucun avis existant et ne change pas les numéros. Renommer une thématique change en revanche son libellé partout où elle est affichée, y compris sur les avis déjà liés à cette entrée. Il n’y a pas de suppression de thématique dans cette interface.

Les anciennes listes personnalisées des formulaires ne sont plus utilisées. Les autres réglages de ces formulaires sont conservés.

## Définir les conditions

Un cas conditionnel comporte une ou plusieurs conditions : nature de l’avis, expert interne ou externe, reconnaissance du Conseil scientifique ou type de demande. Plusieurs conditions dans un même cas sont reliées par **ET**.

Les cas sont essayés dans leur ordre : le **premier correspondant** s’applique. Les réglages généraux servent si aucun cas ne correspond. Les flèches permettent de réordonner les cas.

Un **libellé dans ce cas** laissé vide reprend le libellé général du champ.
De même, un **texte indicatif dans le champ** laissé vide dans un cas reprend le texte indicatif général, dans l’aperçu comme dans le formulaire utilisateur.

Par exemple, le champ **Destinataire** est initialement masqué. Un cas le rend visible, avec la valeur initiale **CS**, si la nature est « Demande à une instance » et si l’expert est reconnu comme Conseil scientifique. Il reste facultatif en brouillon et obligatoire à l’envoi.

Pour cibler une autre instance, utiliser une condition **Expert externe est égal à** puis sélectionner son contact. La reconnaissance standard du CS repose actuellement sur sa raison sociale ou son organisation.

Un champ masqué ne peut pas être déclaré obligatoire. Le masquer ne supprime pas les documents déjà enregistrés sur un brouillon.

## Valeurs initiales et textes

Pour les listes, sélectionner une valeur existante. Pour les textes, les variables suivantes sont disponibles :

- `{numero_dossier}` : numéro du dossier, vide pour une demande générique ;
- `{numero_avis}` : numéro réservé de l’avis, vide pour un import d’avis existant ;
- `{type_demarche}` : démarche du dossier ou type de demande choisi.

Aucun fichier ne peut être prérempli automatiquement.

Pour l’import d’un avis, les dates initiales se choisissent dans un champ date/heure ; la réponse, le mode de contact et la publication au RAA utilisent leurs listes de valeurs autorisées.

## Aperçu et enregistrement

L’aperçu reprend la présentation du formulaire utilisateur : listes déroulantes, zones de texte, sélecteurs de fichiers et boutons. Les choix peuvent être simulés directement dans ses listes ; les champs et leurs valeurs initiales sont recalculés à partir des règles de gauche. Le choix **Champs requis pour** permet de visualiser les astérisques du brouillon ou de l’envoi.

Modifier une valeur initiale dans l’éditeur met immédiatement à jour l’aperçu, même si une autre valeur avait été simulée auparavant. Choisir une démarche dans le scénario de prévisualisation afin de vérifier la liste de thématiques correspondante.

Le **Scénario de prévisualisation**, replié par défaut, permet également de tester les conditions structurantes, dont la reconnaissance du CS. Les sélecteurs de fichiers et les boutons d’enregistrement ne sont que visuels : cet aperçu ne téléverse aucun fichier, ne crée aucun avis, ne réserve aucun numéro et n’envoie aucune notification.

Cliquer sur **Enregistrer ce formulaire** pour publier les réglages. Ils sont pris en compte à la prochaine ouverture du formulaire, puis vérifiés également côté serveur lors d’un enregistrement ou d’un envoi. Une page déjà ouverte peut donc être soumise à de nouvelles exigences si la configuration a changé entre-temps.

**Rétablir les réglages standards** restaure la configuration initiale dans l’éditeur ; il faut ensuite l’enregistrer. Cette action ne réécrit aucun avis existant et ne modifie pas les numéros réservés.

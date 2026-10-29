# Back-office · Circuit d’instruction · Types d’actes

La rubrique **Circuit d’instruction → Types d’actes** permet aux superutilisateurs de gérer les types d’actes proposés lors de la création d’un projet d’acte : par exemple arrêté, délibération ou avis.

Chaque type possède sa propre fiche. Les fiches sont affichées dans l’ordre des listes de choix de l’application. Les flèches permettent de modifier cet ordre ; un nouveau type est ajouté en dernière position.

Les réglages n’altèrent ni les numéros, ni les fichiers, ni les actes déjà existants. Ils s’appliquent aux nouveaux traitements après enregistrement.

## Créer ou modifier un type d’acte

Les champs obligatoires sont signalés par une étoile.

### Nom et disponibilité

- **Nom du type d’acte** : libellé présenté aux utilisateurs.
- **Actif** : un type actif est proposé pour les nouveaux projets. Un type inactif est retiré des nouveaux choix, mais les actes déjà créés restent accessibles et peuvent terminer leur circuit.

### Numérotation et nom de fichier

- **Numérotation** : automatique (compteur annuel AGIDA) ou manuelle (référence libre saisie par l’instructeur lors de la création du projet).
- **Préfixe du numéro** : facultatif, affiché devant le numéro automatique ou la référence manuelle, par exemple DIR-I- ou PF-. Sans préfixe, le numéro ou la référence est affiché tel quel.
- **Préfixe du nom de fichier** : préfixe utilisé dans le nom du fichier signé. Il peut être différent du préfixe affiché du numéro.

La fiche affiche un **prochain numéro estimé**. Ouvrir cette ligne pour voir le détail : le numéro associe le préfixe, l’année en cours et le dernier compteur de ce type d’acte augmenté de 1. Sans numéro attribué cette année, le compteur commence à 1000.

Cet aperçu ne réserve aucun numéro : il peut changer si un autre projet est créé avant le vôtre.

En mode **Manuelle**, il n’y a aucun compteur ni aperçu de prochain numéro. L’instructeur saisit une référence, par exemple `2025-018/PF`, dans chacun des formulaires de création d’un projet. Elle est conservée pendant les validations, la signature et l’envoi. Plusieurs dossiers peuvent utiliser la même référence sans être liés automatiquement. Pour indiquer qu’il s’agit du même acte, utiliser explicitement la reprise depuis un autre dossier.

Les `/` et `\` sont conservés dans la référence affichée, mais remplacés par des tirets dans le nom du fichier NAS. Les deux préfixes restent configurables. Une fois le type utilisé par un document, son mode de numérotation ne peut plus être changé ; créer un nouveau type si le fonctionnement évolue.

### Circuit et documents associés

- **Circuit de signature** : définit si l’acte suit le circuit Direction ou Conseil d’administration.
- **Rapport CA obligatoire** : lorsqu’il est activé, un projet de rapport CA puis un rapport CA signé sont requis avec l’acte. Les références documentaires « Projet Rapport CA » et « Rapport CA » doivent exister dans l’application.

### Publication au RAA

Le mode choisi détermine ce qui se produit après signature :

- **Dans AGIDA** : le dossier passe par l’étape « À publier au RAA » ;
- **Déjà réalisée hors AGIDA** : le dossier est classé directement et l’acte est marqué comme publié ;
- **Non requise** : le dossier est classé directement sans marquer l’acte comme publié.

### Dépôt sur Déclaration Manifestations

L’option **Ce type d’acte peut être déposé sur DM** autorise le dépôt du fichier sur Déclaration Manifestations lorsque le dossier DN est lié à un dossier DM. Elle ne décide pas si la réponse est favorable ou défavorable : cette décision reste celle du dossier.

## Conseils de gestion

- Désactiver un type devenu obsolète plutôt que le supprimer : les dossiers et documents historiques restent cohérents.
- Vérifier les deux préfixes avant de créer des projets avec un nouveau type.
- Configurer le circuit de signature, le besoin de rapport CA, la publication et le dépôt DM avant de rendre un nouveau type actif.
- Utiliser le prochain numéro estimé comme contrôle, jamais comme réservation.


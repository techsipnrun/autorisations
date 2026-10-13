# Back-office · Démarche

La rubrique **Démarche** permet de définir, pour chaque démarche Démarche Numérique, les informations utilisées par AGIDA et l’affichage de ses tableaux. Choisir une démarche dans le menu latéral ouvre sa fiche.

Les blocs sont repliés par défaut. Le bouton + ouvre le bloc et le bouton − le referme ; cette action ne modifie aucun réglage.

## Champs du formulaire DN

Ce bloc est un inventaire des champs récupérés depuis Démarche Numérique : nom, type et caractère obligatoire.

La recherche permet de retrouver un champ par son nom ou son type. Cocher **Afficher les identifiants DN** révèle l’identifiant technique du champ.

Pour une démarche Manifestations sportives, un second bloc **Champs du formulaire DM** présente les champs disponibles dans Déclaration Manifestations. Il permet notamment de choisir sans ambiguïté une source DN ou DM dans les configurations qui l’acceptent.

## Date prévisionnelle de l’activité

Ce bloc indique à AGIDA où trouver la date de début de l’activité. Ajouter les champs dans leur ordre de priorité : le premier champ contenant une date valide est utilisé ; si sa valeur est vide ou inexploitable, AGIDA essaie le suivant.

Pour les Manifestations sportives, les sources peuvent venir de Démarche Numérique ou de Déclaration Manifestations. Lorsqu’une source DM est choisie, elle n’est utilisable que si le dossier DN est lié à un dossier DM.

La date retenue alimente la date d’activité des dossiers, utilisée dans les tableaux, les cartes calendrier et les autres vues qui affichent **Début activité**. Une démarche peut ne pas avoir de source de date : la valeur reste alors vide.

Le délai et les deux couleurs règlent les repères visuels des dates :

- **activité proche** : date située dans le nombre de jours indiqué ;
- **activité passée** : date antérieure au jour courant.

Les dates des tableaux archivés ne reçoivent pas de couleur d’alerte.

## Personnalisation des tableaux

Pour chaque tableau disponible sur la démarche, ce bloc permet de :

- afficher ou masquer une colonne ;
- modifier son libellé affiché ;
- changer son ordre avec les flèches.

Le numéro affiché devant chaque colonne correspond à sa position réelle dans le tableau. Les changements portent sur les tableaux de la vue d’ensemble (dossiers en cours, archives et Mes dossiers). Pour les Manifestations sportives, les trois tableaux de Réception sont aussi configurables : dossiers DM, dossiers DN et dossiers complets.

Le libellé personnalisé ne change pas la donnée : renommer **Début activité** en **Début de la manifestation** conserve la même date et les mêmes couleurs. Une colonne sans libellé personnalisé utilise son intitulé standard.

## Génération des noms de dossiers

Cette configuration concerne uniquement les dossiers Démarche Numérique. Elle permet de proposer des noms plus lisibles sans écraser un nom saisi manuellement.

Une règle est composée d’éléments placés dans l’ordre : texte fixe, champ du formulaire DN, champ DM pour les Manifestations sportives, ou information déjà connue par AGIDA (numéro, date de dépôt, demandeur, bénéficiaire, etc.). AGIDA ajoute automatiquement un espace entre les éléments.

Les règles sont essayées par priorité. Une règle est retenue uniquement si toutes ses variables sont exploitables ; sinon AGIDA passe à la suivante. Si aucune règle ne convient, le nom standard est conservé.

Les transformations permettent par exemple d’utiliser des majuscules, une date formatée ou une correspondance personnalisée : une valeur telle que « Renouvellement de demande » peut être affichée comme « Renouvellement ». Pour une correspondance personnalisée, choisir le comportement souhaité si la valeur ne figure pas dans la liste des correspondances.

Le bloc propose trois usages :

- **Enregistrer les règles** : sauvegarde leur ordre, leur activation et leur composition ;
- **Tester sur un dossier DN** : montre quelle règle est retenue ou pourquoi une règle est ignorée, sans modifier le dossier ;
- **Appliquer aux dossiers existants** : recalcule les noms générés de tous les dossiers de la démarche, y compris archivés.

La priorité d’affichage d’un nom est toujours la suivante : nom saisi manuellement, puis nom provenant d’un dossier DM lié, puis nom généré, puis nom standard. Le recalcul ne remplace donc jamais un nom manuel ni un nom DM prioritaire.


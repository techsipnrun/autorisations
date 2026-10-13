# Back-office · Cartographie

La rubrique **Carto**, réservée aux superutilisateurs, centralise les réglages visuels des cartes d’AGIDA. Elle comporte deux sous-menus :

- **Catalogue** : gérer les fonds de carte et les couches partagées ;
- **Personnaliser les cartes** : choisir ce qui est proposé et visible sur chaque carte de l’application.

Les modifications enregistrées s’appliquent aux pages ouvertes après l’enregistrement.

## Catalogue

Le catalogue sépare les **fonds de carte** des **couches cartographiques**.

Le panneau **Aperçu** permet de vérifier une source avant enregistrement. Il contient volontairement des géométries fictives de pétitionnaire. Aucune couche n’est affichée au départ : sélectionner une couche permet de la prévisualiser sans modifier la visibilité enregistrée dans les cartes de l’application.

### Fonds de carte

Un fond est un service de tuiles accessible par URL. Son URL doit contenir les variables {z}, {x} et {y}. L’attribution du fournisseur est obligatoire : elle est affichée en bas de la carte conformément aux conditions du service.

Un seul fond doit être choisi comme visible par défaut dans une même carte. Les utilisateurs peuvent ensuite en sélectionner un autre si le contrôle des fonds est activé pour cette carte.

### Couches cartographiques

Une couche peut être fournie de deux manières :

- par une URL ou un chemin vers un fichier GeoJSON déjà disponible ;
- par l’import d’un fichier **GeoJSON**, **GPX** ou **KML**.

Les importations doivent utiliser des coordonnées géographiques WGS84 (longitude / latitude) et sont limitées à 5 Mo. GPX et KML sont convertis en GeoJSON avant l’aperçu puis lors de l’enregistrement. Cette conversion utilise la bibliothèque de lecture XML sécurisée defusedxml ; les entités XML et les ressources externes sont refusées.

Le fichier importé n’est pas conservé comme fichier joint : une fois la source enregistrée, seule sa version GeoJSON validée est conservée. Une erreur de format, de coordonnées ou de taille est affichée avant toute modification de la source existante.

Les formats pris en charge sont :

- **GeoJSON** : .geojson ou .json ;
- **GPX 1.0 / 1.1** : points, routes et traces ;
- **KML** : points, lignes, polygones, trous de polygones et MultiGeometry.

Les styles contenus dans un fichier KML sont ignorés : le style affiché est celui configuré dans AGIDA. Les fichiers Shapefile, KMZ, GeoTIFF, les liens réseau KML, les images superposées, les modèles 3D et les traces animées ne sont pas pris en charge.

### Style, informations et légende

Une couche peut recevoir une couleur, une couleur de remplissage, une épaisseur et une transparence. Les propriétés du GeoJSON sont proposées après lecture du fichier : elles peuvent servir à afficher un texte au clic ou au survol, ou à choisir une couleur selon une catégorie.

La propriété est une information attachée à chaque objet de la couche, par exemple un nom de secteur ou une description. Les textes affichés sur la carte sont toujours traités comme du texte simple.

Le réglage **Source active** rend la couche utilisable dans les cartes. Une couche inactive ne peut pas être chargée par les utilisateurs ; l’aperçu le signale clairement. Cocher la case puis actualiser l’aperçu permet de vérifier la couche avant de l’enregistrer.

La suppression d’une source est définitive. Elle doit d’abord être retirée de toutes les cartes où elle est disponible, y compris lorsqu’elle n’est pas visible par défaut.

## Personnaliser les cartes

Cette rubrique contient une fiche pour chaque contexte : pré-instruction DN, instruction DN, pré-instruction DM, instruction DM, Requête, Statistiques et Édition de géométrie.

Les sections **Fonds de carte** et **Couches cartographiques** sont repliées par défaut afin de faciliter la lecture des réglages. Le bouton **Actualiser l’aperçu** applique les valeurs en cours à la carte de droite, sans les enregistrer.

### Fonds et couches disponibles

Cocher **Disponible** rend une source proposée dans le contexte sélectionné. Cocher **Visible par défaut** l’affiche dès l’ouverture de cette carte.

Les flèches déterminent l’ordre d’affichage des couches : de l’arrière-plan vers le premier plan, tout en laissant les géométries du pétitionnaire au-dessus. Une source ajoutée au catalogue n’apparaît dans aucune carte tant qu’elle n’a pas été rendue disponible puis enregistrée dans le contexte voulu.

### Cadrage et géométries du pétitionnaire

Le cadrage initial définit le centre et le niveau de zoom à l’ouverture. Le recentrage adapte ensuite l’affichage lorsque la carte contient une géométrie de pétitionnaire.

La section dédiée permet de régler la couleur, le remplissage, l’épaisseur et la transparence des géométries dessinées ou transmises par le pétitionnaire. Ces réglages sont propres à chaque contexte de carte.

### Fonctionnalités de la carte

Les cases permettent d’activer ou non les contrôles pertinents : zoom, molette, choix des fonds, choix des couches, légende, impression et, lorsque le contexte le permet, outils de dessin, modification et suppression de géométries.

Les couches ajoutées ici sont visuelles : elles ne créent pas de filtre métier et ne modifient pas les calculs existants de cœur de parc, d’aire d’adhésion ou de secteurs.

## Bonnes pratiques

- Vérifier l’aperçu avant d’enregistrer une source ou une carte.
- Utiliser un nom affiché court et explicite : il apparaît dans les menus et les légendes de carte.
- Préférer une couche WGS84 légère à une couche volumineuse ou projetée.
- Pour une URL distante, vérifier qu’elle est accessible depuis le navigateur des utilisateurs et qu’elle autorise les requêtes CORS.
- Ne jamais saisir d’identifiant ou de jeton secret dans une URL publique.


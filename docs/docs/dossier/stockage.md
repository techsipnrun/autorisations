# Le stockage physique
Pour configurer l'accès au NAS, rendez-vous sur la page [Espace de stockage](../prerequis/espace-stockage.md).

---

## Organisation générale du stockage
Le NAS est structuré de façon logique pour permettre un accès rapide aux dossiers.

### 1. La racine 
À la racine de ```\\x-wing\autodev_data```, on retrouve un découpage par type de dossier.

```
/Activites_agricoles
/Activites_commerciales
/Aretes
/Documents_planification_urbanisme
/Manifestations_publiques
/Manifestations_sportives
/Missions_scientifiques
/PDV_et_son
/Survol_hélicoptere
/Travaux
```

On retrouve également un dossier `/Avis` qui regroupe l'ensemble des avis génériques (= les avis qui ne sont pas nécessairement liés à un dossier).

---

### 2. Deuxième niveau : Année de dépôt du dossier
Pour les types de dossier on retrouve ensuite un découpage par année de dépot.

Exemple pour `Suvol d'hélicoptère` :
```
Survol_hélicoptere/
│
├── 2023/
├── 2024/
├── 2025/
```

---

### 3. Troisième niveau : sous-type éventuel
Certaines démarches comme `Travaux` et `Missions scientifiques` peuvent encore être subdivisées. Ici, le nombre de sous dossiers correspond au nombre de formulaires.

Exemple pour `Travaux en 2025` :
```
/Travaux/2025/
│
├── Aire_adhesion
├── Non_soumis_urbanisme
├── Soumis_urbanisme
```

Exemple pour `Missions scientifiques en 2025` :
```
/Missions_scientifiques/2025/
│
├── Coeur_de_parc
├── Especes_protegees
```

---

### 4. Dernier niveau : Liste des dossiers
Le nommage des dossiers suit la règle suivante : `{Numéro de dossier}_{Identité du pétitionnaire}_{Date de réception du dossier}`

Exemple pour `Suvol d'hélicoptère en 2025` :
```
/Survol_hélicoptere/2025/
│
├── 27938012_MOUSTAID_Myriam_27-11/
├── 28073781_deal_reunion_04-12/
├── 28073373_CALU_Louis_04-12/
├── ...
```

---

## Structure interne d’un dossier

Chaque dossier possède toujours **la même organisation interne**, générée automatiquement par l’application.

Exemple :
```
/Survol_hélicoptere/2025/28073373_CALU_Louis_04-12/
│
├── Actes/
├── Annexes/
├── Avis/
├── Carto/
├── Work/
└── dossier-28073373.pdf
```

### Dossier *Actes/*
Contient **tous les actes signés** délivrés par le Parc (format PDF).

> Ce dossier est **en lecture seule** : il est alimenté exclusivement par l’application.

---

### Dossier *Annexes/*
Contient :

- les pièces jointes déposées par le pétitionnaire ;
- les PJ échangées via la messagerie.

> Ce dossier est **en lecture seule** : il est alimenté exclusivement par l’application.

---

### Dossier *Avis/*
Contient les **documents associés aux avis liés au dossier**.

Exemple :
```
/Survol_hélicoptere/2025/28073373_CALU_Louis_04-12/Avis/
│
├── calu_louis/
├── collin_gerard/
├── ...
```

Pour chaque dossier relatif à un avis on retrouvera :

- L'avis signé s'il existe.
- Un dossier `Annexes` qui contient l'ensemble des documents liés à l'avis (Rapport CS, Projet d'avis, Projet d'arrêté etc.).

> Ce dossier est **en lecture seule** : il est alimenté exclusivement par l’application.

---

### Dossier *Carto/*
Contient un **fichier unique `.geojson`**, représentant :

- La géométrie saisie par le pétitionnaire

> Ce dossier est **en lecture seule** : il est alimenté exclusivement par l’application.

---

### Dossier *Work/*
C'est le seul dossier **modifiable directement par les instructeurs**.
Il s’agit d’un **espace de travail personnel**, par exemple pour :

- stocker des documents  
- rédiger les projets d'avis  
- rédiger les projets d'actes

---

### Résumé PDF du dossier

À la racine du dossier se trouve un fichier automatiquement généré :

```
dossier-{Numéro de dossier}.pdf
```

Ce document est généré automatiquement par [Démarche Numérique](https://demarche.numerique.gouv.fr/).
On y retrouve l'identité du demandeur, les dates de réception/début d'instruction du dossier, le formulaire du pétitionnaire ou encore les échanges dans la messagerie. 

---

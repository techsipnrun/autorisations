# Ajouter un avis existant

## Avis existant sur l'application

---

<figure style="text-align: center;">
  <img src="../../images/dossier/formulaire/consultation/ajouter-avis-existant-sur-appli.png" alt="Lier un avis existant à un dossier" width="800">
  <figcaption><em>Figure 1 — Lier un avis existant à un dossier </em></figcaption>
</figure>

---

Si un un avis lié à un autre dossier ou avis générique concerne notre dossier, on peut alors l'associer. Pour cela, il faut d'abord retrouver l'avis en question à l'aide de la **recherche filtrée**.

Une fois trouvé, il suffit de cliquer sur « Associer au dossier ». **L'avis apparaîtra désormais dans l'onglet « Consultation »** de notre dossier. 

---


## Avis hors application

On laisse la possibilité d'ajouter un avis qui aurait été émis en dehors de l'application.

Les libellés, l’ordre, la visibilité, les valeurs initiales et les obligations de ce formulaire peuvent être personnalisés dans **Back-office → Avis → Ajouter un avis existant · Hors application**. La liste ci-dessous décrit les réglages standards. La recherche d’un avis déjà présent dans AGIDA reste indépendante de cette configuration.

Pour ce faire, vous devez dérouler le formulaire :


- **Nature de l'avis** : *Consultation en interne* ou *Demande à une instance*

- **Instructeur.rice à l'origine de la demande** : Choisir dans le menu déroulant

- **Thématique de l'avis** : Choisir dans le menu déroulant

- **Expert interne/externe** : Choisir dans le menu déroulant

- Pour un **avis du Conseil scientifique**, deux champs supplémentaires apparaissent :

    - **Numéro de l’avis CS importé** : référence facultative, par exemple `2026-42` ou `CS-2026-042`. Si elle est renseignée, elle est affichée dans les colonnes **N° Avis**. Sinon, le numéro attribué par AGIDA est affiché. Dans les deux cas, l’identifiant interne et les liens restent gérés automatiquement. La recherche par numéro accepte les deux références.
    - **Publication au RAA** : **À publier** conserve l’état non traité (`publie_au_raa` à `NULL`). **Déjà publié** et **Publication non requise** positionnent tous deux `publie_au_raa` à `True`, pour ne plus proposer l’avis à la publication. Ces deux derniers motifs ne sont donc pas distingués en base. L’apparition dans la liste de publication reste soumise aux critères habituels, notamment une réponse favorable ou favorable sous réserve.

- **Expert.e sollicité.e via** : Courrier papier, Mail, Téléphone, Autre

- **Réponse de l'avis** : Favorable ou Défavorable

- **Date de la demande d'avis** : Date à laquelle la demande d'avis à été émise

- **Date de la réponse de l'expert.e** : Date à laquelle l'expert.e a répondu

- **Note** : Facultatif. Visible uniquement par les autres collègues

- **Pièce(s) jointe(s) liée(s) à l'avis** : Facultatif. *Pensez à donner des noms intuitifs à vos fichiers*

---

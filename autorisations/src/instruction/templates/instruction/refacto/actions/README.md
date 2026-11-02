# Composants des changements d’étape

Le code technique de `ChangementEtape` détermine le fichier du bouton :
`instruction/{code}.html`, `preinstruction/{code}.html` ou `dm/{code}.html`.
Les règles `ActionsPossibles` et les contrôles serveur restent inchangés.

Pour les quatre actions d’archivage/annulation DN, le formulaire est partagé
entre instruction et pré-instruction dans `formulaires/{code}.html`.
`actions_interface.construire_menu()` le trouve automatiquement et les pages
l’insèrent hors du menu. Aucun enregistrement supplémentaire n’est nécessaire.

- Le bouton porte `data-ouvrir-formulaire="{{ action.code }}"`.
- La zone porte `data-action-form="{{ action.code }}"` et la classe `zone-complement`.
- `actions_dossier.js` ouvre la zone et ferme le menu ; il contrôle également
  les justificatifs portant `data-taille-max`.
- Un bouton d’archivage direct utilise `data-confirmer-action="Message de confirmation"`
  dans son formulaire POST existant.

La variable `interface` permet de conserver les différences entre les deux écrans.

Les autres changements d’étape conservent encore leurs formulaires et scripts
dans les pages d’origine. Les DM seuls ne chargent pas les formulaires DN.

Vérifications ciblées, depuis `autorisations/src` :

```console
python -m tests tests.unit.instruction.test_actions_interface tests.unit.instruction.test_formulaires_archivage tests.interface.test_menu_archivage
```

Ces tests vérifient notamment le branchement bouton/formulaire, les variantes
DN et DM lié, les confirmations et le comportement sur petit écran, sans BDD réelle.

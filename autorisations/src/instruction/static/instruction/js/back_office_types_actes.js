function positionnerAideTypeActe(aide) {
  const bulle = aide.querySelector('.back-office-acte-help-bubble');
  const repere = aide.getBoundingClientRect();
  const gauche = Math.max(12, Math.min(repere.left, window.innerWidth - bulle.offsetWidth - 12));
  const haut = repere.bottom + 8 + bulle.offsetHeight <= window.innerHeight
    ? repere.bottom + 8 : Math.max(12, repere.top - bulle.offsetHeight - 8);
  bulle.style.setProperty('--acte-help-left', `${gauche}px`);
  bulle.style.setProperty('--acte-help-top', `${haut}px`);
}
document.querySelectorAll('.back-office-acte-help').forEach(aide => {
  aide.addEventListener('mouseenter', () => positionnerAideTypeActe(aide));
  aide.addEventListener('focus', () => positionnerAideTypeActe(aide));
});
const repositionnerAidesTypesActes = () => document.querySelectorAll('.back-office-acte-help:hover, .back-office-acte-help:focus').forEach(positionnerAideTypeActe);
window.addEventListener('resize', repositionnerAidesTypesActes);
window.addEventListener('scroll', repositionnerAidesTypesActes, {passive: true, capture: true});

document.querySelectorAll('[data-type-acte-form]').forEach(form => {
  const apercu = () => {
    const manuel = form.elements.mode_numerotation.value === 'manuelle';
    form.querySelector('.back-office-acte-number-preview').hidden = manuel;
    form.querySelector('[data-type-acte-manual-help]').hidden = !manuel;
    const numero = form.dataset.nextNumber;
    form.querySelector('[data-type-acte-preview]').textContent = `Prochain numéro estimé : ${form.elements.prefixe_numero.value}${numero}`;
    form.querySelector('[data-type-acte-filename-preview]').textContent = `Exemple de fichier signé : ${form.elements.prefixe_nom_fichier.value}${numero}_JJ-MM.pdf`;
  };
  form.addEventListener('input', apercu);
  apercu();
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const bouton = form.querySelector('[type="submit"]');
    const statut = form.querySelector('[data-type-acte-status]');
    bouton.disabled = true;
    statut.textContent = 'Enregistrement en cours…';
    try {
      const reponse = await fetch(form.action, {method: 'POST', body: new FormData(form), headers: {'X-Requested-With': 'XMLHttpRequest'}});
      const resultat = await reponse.json();
      if (!reponse.ok || !resultat.success) {
        throw new Error(resultat.error || Object.values(resultat.errors || {}).flat().join(' ') || 'Enregistrement impossible.');
      }
      sessionStorage.setItem('type-acte-enregistre', '1');
      window.location.hash = 'circuit/types-actes';
      window.location.reload();
    } catch (erreur) {
      statut.textContent = erreur.message;
      statut.classList.add('is-error');
      bouton.disabled = false;
    }
  });
});
const listeTypesActes = document.querySelector('[data-type-acte-list]');
if (listeTypesActes) {
  const statutOrdre = document.querySelector('[data-type-acte-order-status]');
  const actualiserClassement = () => {
    const cartes = [...listeTypesActes.querySelectorAll('[data-type-acte-id]')];
    cartes.forEach((carte, index) => {
      carte.querySelector('[data-type-acte-rank]').textContent = index + 1;
      carte.querySelector('[data-type-acte-move="monter"]').disabled = index === 0;
      carte.querySelector('[data-type-acte-move="descendre"]').disabled = index === cartes.length - 1;
    });
  };
  actualiserClassement();
  listeTypesActes.querySelectorAll('[data-type-acte-move]').forEach(bouton => {
    bouton.addEventListener('click', async event => {
      event.preventDefault();
      event.stopPropagation();
      const carte = bouton.closest('[data-type-acte-id]');
      const direction = bouton.dataset.typeActeMove;
      listeTypesActes.querySelectorAll('[data-type-acte-move]').forEach(action => { action.disabled = true; });
      statutOrdre.textContent = 'Enregistrement du classement…';
      statutOrdre.classList.remove('is-error');
      try {
        const reponse = await fetch(carte.dataset.orderUrl, {
          method: 'POST',
          body: new URLSearchParams({direction, csrfmiddlewaretoken: carte.querySelector('[name="csrfmiddlewaretoken"]').value}),
          headers: {'X-Requested-With': 'XMLHttpRequest'},
        });
        const resultat = await reponse.json();
        if (!reponse.ok || !resultat.success) throw new Error(resultat.error || 'Classement non enregistré.');
        const cartes = new Map([...listeTypesActes.querySelectorAll('[data-type-acte-id]')].map(item => [Number(item.dataset.typeActeId), item]));
        if (!Array.isArray(resultat.ordre) || resultat.ordre.length !== cartes.size || resultat.ordre.some(id => !cartes.has(id))) {
          throw new Error('La liste a changé. Actualisez la page pour afficher le classement enregistré.');
        }
        resultat.ordre.forEach(id => listeTypesActes.append(cartes.get(id)));
        statutOrdre.textContent = 'Classement enregistré.';
      } catch (erreur) {
        statutOrdre.textContent = erreur.message;
        statutOrdre.classList.add('is-error');
      } finally {
        actualiserClassement();
      }
    });
  });
}
if (sessionStorage.getItem('type-acte-enregistre')) {
  sessionStorage.removeItem('type-acte-enregistre');
  const message = document.createElement('p');
  message.className = 'back-office-acte-success';
  message.setAttribute('role', 'status');
  message.textContent = 'Le type d’acte a été enregistré.';
  document.querySelector('[data-panel="types-actes"]').prepend(message);
}

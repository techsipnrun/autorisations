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
  const naming=form.querySelector('[data-act-filename]'),editor=naming.querySelector('[data-act-filename-editor]'),choices=naming.querySelector('[data-act-filename-choices]');
  const labels={'prefixe_fichier':'Préfixe du fichier','document.numero':'Numéro de l’acte','dossier.numero':'Numéro du dossier','date.jour_mois':'Jour-Mois','date.jour':'Jour-Mois-Année','date.annee':'Année','beneficiaire.identite':'Bénéficiaire'};
  const samples=()=>({'prefixe_fichier':form.elements.prefixe_nom_fichier?.value ?? form.dataset.prefix ?? '', 'document.numero':form.dataset.nextNumber,
    'dossier.numero':'31770683','date.jour_mois':naming.dataset.day,'date.jour':naming.dataset.date,'date.annee':naming.dataset.year,'beneficiaire.identite':'DUPONT-Jean'});
  const raw=()=>[...editor.childNodes].map(node=>node.dataset?.variable ? `{${node.dataset.variable}}` : node.textContent).join('').replaceAll('\u200b','').replace(/\.pdf$/i,'')+'.pdf';
  function sync(){form.elements.nom_fichier_signe.value=raw();choices.querySelectorAll('button').forEach(button=>{button.disabled=raw().includes(`{${button.dataset.variable}}`);});}
  function token(code){
    const chip=document.createElement('span');chip.className='act-filename-token';chip.contentEditable='false';chip.dataset.variable=code;
    const label=document.createElement('span');label.textContent=labels[code];
    const remove=document.createElement('button');remove.type='button';remove.textContent='×';remove.setAttribute('aria-label',`Retirer ${labels[code]}`);
    remove.addEventListener('click',()=>{chip.remove();sync();apercu();editor.focus();});chip.append(label,remove);return chip;
  }
  const pattern=form.elements.nom_fichier_signe.value.replace(/\.pdf$/i,'');let start=0;
  for(const match of pattern.matchAll(/\{([^{}]+)\}/g)){
    if(!Object.hasOwn(labels,match[1]))continue;
    editor.append(document.createTextNode(pattern.slice(start,match.index)),token(match[1]));start=match.index+match[0].length;
  }
  editor.append(document.createTextNode(pattern.slice(start)));
  for(const [code,label] of Object.entries(labels)){
    const wrapper=document.createElement('div'),button=document.createElement('button'),example=document.createElement('small');
    button.type='button';button.textContent=label;button.dataset.variable=code;example.dataset.example=code;
    button.addEventListener('mousedown',event=>event.preventDefault());
    button.addEventListener('click',()=>{
      if(raw().includes(`{${code}}`))return;
      const selection=window.getSelection();let range=selection.rangeCount ? selection.getRangeAt(0) : null;
      if(!range || !editor.contains(range.commonAncestorContainer)){range=document.createRange();range.selectNodeContents(editor);range.collapse(false);}
      const chip=token(code);range.deleteContents();range.insertNode(chip);range.setStartAfter(chip);range.collapse(true);selection.removeAllRanges();selection.addRange(range);
      sync();apercu();editor.focus();
    });wrapper.append(button,example);choices.append(wrapper);
  }
  editor.addEventListener('input',sync);
  const forbidden=/[\\/:*?"<>|\x00-\x1f]/;
  const nameError=naming.querySelector('[data-act-filename-error]');
  function rejectInvalid(text){
    const invalid=forbidden.test(text);
    nameError.hidden=!invalid;
    nameError.textContent=invalid ? 'Caractère interdit dans un nom de fichier : /, \\, :, *, ?, ", <, >, | ou caractère de contrôle.' : '';
    return invalid;
  }
  editor.addEventListener('beforeinput',event=>{if(event.data && rejectInvalid(event.data))event.preventDefault();});
  editor.addEventListener('keydown',event=>{if(event.key==='Enter')event.preventDefault();});
  editor.addEventListener('drop',event=>event.preventDefault());
  editor.addEventListener('paste',event=>{
    event.preventDefault();const selection=window.getSelection();if(!selection.rangeCount)return;
    const range=selection.getRangeAt(0);if(!editor.contains(range.commonAncestorContainer))return;
    const pasted=event.clipboardData.getData('text/plain');if(rejectInvalid(pasted))return;
    range.deleteContents();const text=document.createTextNode(pasted);range.insertNode(text);range.setStartAfter(text);range.collapse(true);sync();apercu();
  });
  sync();
  const apercu = () => {
    if(form.elements.mode_numerotation){
      const manuel = form.elements.mode_numerotation.value === 'manuelle';
      form.querySelector('.back-office-acte-number-preview').hidden = manuel;
      form.querySelector('[data-type-acte-manual-help]').hidden = !manuel;
      const numero = form.dataset.nextNumber;
      form.querySelector('[data-type-acte-preview]').textContent = `Prochain numéro estimé : ${form.elements.prefixe_numero.value}${numero}`;
    }
    const values=samples();
    naming.querySelectorAll('[data-example]').forEach(node=>{node.textContent=values[node.dataset.example] || '(vide)';});
    editor.querySelectorAll('[data-variable]').forEach(node=>{node.title=values[node.dataset.variable] || '(vide)';});
    const filename=raw().replace(/\{([^{}]+)\}/g,(match,code)=>Object.hasOwn(values,code) ? values[code].replace(/[\\/:*?"<>|\x00-\x1f]/g,'-') : match).replace(/\s+/g,'-');
    form.querySelector('[data-type-acte-filename-preview]').textContent = `Exemple de fichier signé : ${filename}`;
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

document.addEventListener('DOMContentLoaded', () => {
    const panel = document.querySelector('[data-documents-catalogue]');
    if (!panel) return;
    const liste = panel.querySelector('[data-documents-liste]');
    const fiche = panel.querySelector('[data-document-fiche]');
    const statut = panel.querySelector('[data-documents-status]');
    const rapport = panel.querySelector('[data-document-rapport]');
    const toolbar = panel.querySelector('[data-documents-toolbar]');
    const recherche = panel.querySelector('[data-documents-recherche]');
    const filtre = panel.querySelector('[data-documents-filtre]');
    const filtreDemarche = panel.querySelector('[data-documents-demarche]');
    const filtreStatut = panel.querySelector('[data-documents-statut]');
    const edition = panel.querySelector('[data-document-edition]');
    const editButton = panel.querySelector('[data-document-edit]');
    let optionsEdition = null;
    let creating = false;
    let chargement = false, selection = null, templates = [];
    function element(tag, text) {
        const node = document.createElement(tag);
        node.textContent = text;
        return node;
    }
    const variables = {'dossier.emplacement':'Emplacement du dossier', 'dossier.numero':'Numéro du dossier',
        'date.annee':'Année en cours', 'beneficiaire.identite':'NOM-Prénom ou Raison sociale bénéficiaire', 'date.jour':'JJ-MM-AA', 'document.numero':'Numéro du document'};
    const variableTitle = code => code==='date.annee' ? optionsEdition?.filename_date?.year || ''
        : code==='date.jour' ? optionsEdition?.filename_date?.day || ''
        : code==='beneficiaire.identite' ? 'La raison sociale est utilisée en priorité ; si elle est vide, le NOM-Prénom est utilisé. Les espaces sont remplacés par des tirets.' : '';
    function afficherPatron(cible, patron) {
        const value=patron.replaceAll('{num_doss}', '{dossier.numero}');
        cible.replaceChildren();
        let start=0;
        for(const match of value.matchAll(/\{([^{}]+)\}/g)) {
            const code=match[1];
            if(!Object.hasOwn(variables,code)) continue;
            cible.append(document.createTextNode(value.slice(start,match.index)));
            const token=element('span',variables[code]+(code==='dossier.emplacement' ? ' /' : ''));
            token.className='bo-document-token';token.dataset.variable=code;token.title=variableTitle(code);
            cible.append(token);
            start=match.index+match[0].length;
            // Le séparateur final est déjà visible dans la chip d'emplacement.
            if(code==='dossier.emplacement' && value[start]==='/') start++;
        }
        cible.append(document.createTextNode(value.slice(start)));
    }
    const tokenFields = [...edition.querySelectorAll('[data-token-field]')].map(container => {
        const name=container.dataset.tokenField, input=edition.elements[name];
        const editor=container.querySelector('[data-token-editor]'), choices=container.querySelector('[data-token-choices]');
        const allowed=name==='nom_fichier' ? ['dossier.numero', 'date.annee', 'beneficiaire.identite', 'date.jour', 'document.numero'] : ['dossier.emplacement','dossier.numero'];
        const canonical=value => value.replaceAll('{num_doss}', '{dossier.numero}');
        function raw() {
            return [...editor.childNodes].map(node => node.nodeType===Node.ELEMENT_NODE && node.dataset.variable
                ? `{${node.dataset.variable}}` : node.textContent).join('').replaceAll('\u200b','');
        }
        function sync() {
            const value=canonical(raw());
            input.value=name==='nom_fichier' ? value.replace(/\.docx$/i,'')+'.docx' : value;
            choices.querySelectorAll('button').forEach(button => {
                button.disabled=value.includes(`{${button.dataset.variable}}`);
            });
        }
        function chip(code) {
            const token=element('span','');token.className='bo-document-token';token.contentEditable='false';token.dataset.variable=code;
            token.title=variableTitle(code);
            const label=element('span',variables[code]);
            if(code==='dossier.emplacement') label.append(element('span',' /'));
            const remove=element('button','×');remove.type='button';remove.className='bo-document-token-remove';
            remove.setAttribute('aria-label',`Retirer ${variables[code]}`);
            remove.addEventListener('click',()=>{token.remove();sync();editor.focus();});
            token.append(label,remove);return token;
        }
        function load(value) {
            value=canonical(value || '');
            if(name==='nom_fichier') value=value.replace(/\.docx$/i,'');
            editor.replaceChildren();
            const pattern=/\{(dossier\.emplacement|dossier\.numero|date\.annee|date\.jour|beneficiaire\.identite|document\.numero)\}/g;
            let start=0;
            for(const match of value.matchAll(pattern)) {
                editor.append(document.createTextNode(value.slice(start,match.index)));
                editor.append(chip(match[1]));start=match.index+match[0].length;
            }
            editor.append(document.createTextNode(value.slice(start)));sync();
        }
        allowed.forEach(code => {
            const button=element('button',variables[code]);button.type='button';button.dataset.variable=code;
            button.className='bo-document-variable-choice';
            button.addEventListener('mousedown',event=>event.preventDefault());
            button.addEventListener('click',()=>{
                if(raw().includes(`{${code}}`)) return;
                const selection=window.getSelection();
                let range=selection.rangeCount ? selection.getRangeAt(0) : null;
                if(!range || !editor.contains(range.commonAncestorContainer)) {
                    range=document.createRange();range.selectNodeContents(editor);range.collapse(false);
                }
                const token=chip(code);range.deleteContents();range.insertNode(token);
                const space=document.createTextNode('');token.after(space);
                range.setStartAfter(token);range.collapse(true);selection.removeAllRanges();selection.addRange(range);
                sync();editor.focus();
            });
            choices.append(button);
        });
        editor.addEventListener('input',sync);
        editor.addEventListener('blur',event=>{if(!container.contains(event.relatedTarget)) load(input.value);});
        editor.addEventListener('keydown',event=>{if(event.key==='Enter') event.preventDefault();});
        editor.addEventListener('paste',event=>{
            event.preventDefault();
            const text=event.clipboardData.getData('text/plain').replace(/[\r\n]/g,'');
            const selection=window.getSelection();
            if(!selection.rangeCount) return;
            const range=selection.getRangeAt(0);range.deleteContents();
            const node=document.createTextNode(text);range.insertNode(node);range.setStartAfter(node);range.collapse(true);
            sync();
        });
        input.addEventListener('change',()=>load(input.value));
        function refreshTitles() {
            choices.querySelectorAll('button').forEach(button=>{button.title=variableTitle(button.dataset.variable);});
            editor.querySelectorAll('[data-variable]').forEach(token=>{token.title=variableTitle(token.dataset.variable);});
        }
        return {name,input,editor,load,sync,refreshTitles};
    });
    function configurationBadge(template) {
        return badge(template.configuration_complete ? 'Configuration complète' : 'Configuration incomplète',
            template.configuration_complete ? 'is-success' : 'is-warning');
    }
    function signaler(texte, erreur = false) {
        statut.textContent = texte;
        statut.classList.toggle('is-error', erreur);
    }
    function messageLocal(cible, texte, erreur = false) {
        cible.textContent = texte;
        cible.classList.toggle('is-error', erreur);
    }
    function effacerErreursChamps() {
        edition.querySelectorAll('[data-document-field-error]').forEach(node=>node.remove());
        edition.querySelectorAll('[aria-invalid]').forEach(node=>node.removeAttribute('aria-invalid'));
        edition.querySelectorAll('[aria-errormessage]').forEach(node=>node.removeAttribute('aria-errormessage'));
    }
    function erreurChamp(nom, texte) {
        const token=tokenFields.find(field=>field.name===nom);
        const target=token?.editor || (nom==='demarches' ? panel.querySelector('[data-document-demarches]').closest('fieldset') : edition.elements.namedItem(nom));
        if(!target || !target.setAttribute) return null;
        const error=element('small',texte);error.id=`document-field-error-${nom}`;error.dataset.documentFieldError='';error.className='bo-document-field-error';error.setAttribute('role','alert');
        target.setAttribute('aria-invalid','true');target.setAttribute('aria-errormessage',error.id);
        (target.closest('[data-token-field]') || target.closest('label') || target).append(error);
        return target;
    }
    function fermerEdition() {
        edition.hidden = true;
        panel.querySelector('[data-document-informations]').hidden = false;
        panel.querySelector('[data-document-configuration]').hidden = false;
        editButton.setAttribute('aria-expanded', 'false');
        panel.querySelector('[data-document-retour]').disabled = false;
    }
    function badge(texte, classe = '') {
        const node = element('span', texte);
        node.className = `bo-documents-badge ${classe}`;
        return node;
    }
    function dessinerListe() {
        liste.replaceChildren();
        const terme = recherche.value.trim().toLocaleLowerCase('fr');
        const visibles = templates.filter(t => (!filtre.value || t.actif === (filtre.value === 'actif'))
            && (!filtreDemarche.value || !t.demarche_ids.length || t.demarche_ids.some(id => String(id) === filtreDemarche.value))
            && (!filtreStatut.value || (filtreStatut.value==='valide' ? t.rapport?.valide===true : t.rapport?.valide===false))
            && `${t.nom} ${t.nature}`.toLocaleLowerCase('fr').includes(terme));
        panel.querySelector('[data-documents-compte]').textContent = `${visibles.length} / ${templates.length} templates`;
        for (const template of visibles) {
            const bouton = element('button', '');
            bouton.type = 'button';
            bouton.className = 'bo-documents-card';
            const infos = element('div', '');
            infos.append(element('strong', template.nom), element('small', [template.nature].filter(Boolean).join(' · ')));
            const etat = element('div', '');
            etat.className = 'bo-documents-card-status';
            etat.append(badge(template.actif ? 'Actif' : 'Inactif', template.actif ? 'is-success' : ''));
            etat.append(configurationBadge(template));
            etat.append(badge(template.rapport ? (template.rapport.valide ? 'Vérifié · valide' : 'À corriger') : 'Non vérifié', template.rapport ? (template.rapport.valide ? 'is-success' : 'is-error') : 'is-warning'));
            etat.append(element('span', '→'));
            bouton.append(infos, etat);
            bouton.addEventListener('click', () => ouvrir(template));
            liste.append(bouton);
        }
        if (!visibles.length) {
            const vide = element('p', templates.length ? 'Aucun template ne correspond à ces filtres.' : 'Aucun template. Ajoutez votre premier modèle dans Django Admin.');
            vide.className = 'bo-documents-empty';
            liste.append(vide);
        }
    }
    function afficherRapport(data) {
        rapport.replaceChildren();
        if (!data) {
            const vide = element('p', 'Le rapport de ce modèle est indisponible.');
            vide.className = 'bo-documents-empty';
            rapport.append(vide);
            return;
        }
        const resultat = element('div', '');
        resultat.className = `bo-documents-result ${data.valide ? '' : 'is-error'}`;
        resultat.append(element('h3', data.valide ? '✓ Modèle valide' : '✗ Template invalide'));
        resultat.append(element('p', data.syntaxe_valide ? '✓ Syntaxe docxtpl valide' : '✗ Syntaxe docxtpl non validée'));
        rapport.append(resultat);
        const compteurs = data.compteurs || {};
        const compte = element('ul', '');
        compte.className = 'bo-documents-metrics';
        for (const [texte, classe] of [[`${data.total || 0} Balises détectées`, ''], [`${compteurs.CONNUE || 0} CONNUES`, 'is-success'], [`${compteurs.A_RENSEIGNER || 0} A RENSEIGNER`, 'is-warning'], [`${compteurs.INCONNUE || 0} INCONNUE`, 'is-error']]) {
            const metric=element('li', texte); metric.className=classe; compte.append(metric);
        }
        rapport.append(compte);
        if (!data.analyse_complete) rapport.append(element('p', 'Analyse incomplète : la dernière liste synchronisée en base n’a pas été actualisée.'));
        if (data.erreurs.length) {
            const erreurs = element('ul', '');
            erreurs.className = 'bo-documents-errors';
            for (const erreur of data.erreurs) erreurs.append(element('li', erreur));
            rapport.append(erreurs);
        }
        const table = element('table', '');
        table.className = 'bo-documents-table';
        const head = element('thead', '');
        const entete = element('tr', '');
        entete.append(element('th', 'Balise'), element('th', 'Classement'));
        head.append(entete);
        table.append(head);
        const body = element('tbody', '');
        for (const balise of data.balises) {
            const ligne = element('tr', '');
            const classement = element('td', '');
            classement.append(badge(balise.statut.replaceAll('_', ' '), balise.statut === 'CONNUE' ? 'is-success' : balise.statut === 'INCONNUE' ? 'is-error' : 'is-warning'));
            ligne.append(element('td', balise.code), classement);
            if(balise.statut==='INCONNUE') {
                const configure=element('a','Configurer cette balise');
                configure.href=`#documents/balises/nouvelle?code=${encodeURIComponent(balise.code)}&template=${selection.id}`;
                configure.className='bo-balise-configurer';classement.append(configure);
            }
            body.append(ligne);
        }
        table.append(body);
        rapport.append(table);
    }
    function ouvrir(template, creation = false) {
        fermerEdition();
        creating = creation;
        editButton.hidden=creation;
        panel.querySelector('.bo-documents-controle').hidden=creation;
        selection = template;
        history.replaceState(null, '', `#documents/templates/${creation ? 'nouveau' : template.id}`);
        const download=panel.querySelector('[data-document-download]');
        download.hidden=!template.telechargement_url;
        if(template.telechargement_url) download.href=template.telechargement_url;
        else download.removeAttribute('href');
        toolbar.hidden = true;
        liste.hidden = true;
        fiche.hidden = false;
        panel.querySelector('[data-document-nom]').textContent = creation ? 'Nouveau template' : template.nom;
        panel.querySelector('[data-document-etat]').replaceChildren(badge(template.actif ? 'Actif' : 'Inactif', template.actif ? 'is-success' : ''));
        panel.querySelector('[data-document-etat]').append(configurationBadge(template));
        const configuration=panel.querySelector('[data-document-configuration]');
        messageLocal(configuration, template.configuration_complete ? '' : 'Configuration du template incomplète.');
        panel.querySelector('.bo-documents-identite').classList.toggle('is-incomplete', !template.configuration_complete);
        const infos = panel.querySelector('[data-document-informations]');
        infos.replaceChildren();
        for (const [label, valeur] of Object.entries({Nature: template.nature, 'Chemin sous Templates/': template.chemin_relatif, État: template.actif ? 'Actif' : 'Inactif', Démarches: template.demarches.join(', ') || 'Global — toutes les démarches', 'Destination du fichier généré': template.destination_relative || 'Non définie', 'Nom du fichier': template.nom_fichier || 'Non défini'})) {
            const key={Nature:'id_nature','Chemin sous Templates/':'chemin_relatif','Destination du fichier généré':'destination_relative','Nom du fichier':'nom_fichier'}[label];
            const invalid=key && (template.configuration_errors?.[key] || (key!=='id_nature' && (!valeur || valeur==='Non définie' || valeur==='Non défini')));
            const title=element('dt', label), value=element('dd', label==='Nature' && !valeur ? 'Non renseignée' : valeur);
            if((key==='destination_relative' || key==='nom_fichier') && template[key]) afficherPatron(value,template[key]);
            if(invalid) {title.classList.add('is-invalid');value.classList.add('is-invalid');}
            infos.append(title, value);
        }
        if(template.configuration_errors?.nom || !template.nom) panel.querySelector('[data-document-nom]').classList.add('is-invalid');
        else panel.querySelector('[data-document-nom]').classList.remove('is-invalid');
        afficherRapport(template.rapport);
        panel.querySelector('[data-document-nom]').focus({preventScroll:true});
    }
    function afficherListe() {
        fermerEdition();
        creating=false;
        selection=null;
        liste.hidden=false;fiche.hidden=true;toolbar.hidden=false;
        dessinerListe();
    }
    function restaurerDepuisUrl() {
        const route=window.location.hash.match(/^#documents\/templates(?:\/(nouveau|\d+))?$/);
        if(!route || panel.hidden) return;
        if(route[1]==='nouveau') {
            ouvrir({nom:'',code:'',chemin_relatif:'',destination_relative:'',nom_fichier:'',nature:'',id_nature:null,
                actif:true,demarches:[],demarche_ids:[],configuration_complete:false,configuration_errors:{},rapport:null},true);
            ouvrirEdition();return;
        }
        const template=route[1] && templates.find(item=>String(item.id)===route[1]);
        if(template) ouvrir(template);
        else {
            afficherListe();
            if(route[1]) {
                history.replaceState(null,'','#documents/templates');
                signaler('Ce template n’est plus disponible.',true);
            }
        }
    }
    async function charger() {
        if (panel.hidden || chargement) return;
        chargement = true;
        signaler('Analyse automatique de tous les templates…');
        editButton.disabled = true;
        panel.setAttribute('aria-busy', 'true');
        liste.replaceChildren();
        try {
            const response = await fetch(panel.dataset.documentsVerification, {method:'POST', credentials: 'same-origin', headers:{'X-CSRFToken':edition.querySelector('[name=csrfmiddlewaretoken]').value}});
            if (!response.headers.get('content-type')?.includes('application/json')) throw new Error('Session expirée. Rechargez la page.');
            const data = await response.json();
            if (!response.ok) throw new Error(data.erreur || 'Chargement impossible.');
            templates = data.templates;
            const optionsResponse = await fetch(panel.dataset.documentsOptions, {credentials:'same-origin'});
            if (!optionsResponse.headers.get('content-type')?.includes('application/json')) throw new Error('Session expirée. Rechargez la page.');
            const choices = await optionsResponse.json();
            if (!optionsResponse.ok) throw new Error(choices.erreur || 'Impossible de charger les démarches.');
            optionsEdition = choices;
            const selectedDemarche = filtreDemarche.value;
            const all = element('option', '---');all.value='';
            filtreDemarche.replaceChildren(all, ...choices.demarches.map(d => {
                const option = element('option', d.nom);option.value=d.id;return option;
            }));
            filtreDemarche.value = selectedDemarche;
            dessinerListe();
            signaler('');
            restaurerDepuisUrl();
        } catch (error) { signaler(error.message, true); }
        finally { chargement = false; editButton.disabled=false; panel.removeAttribute('aria-busy'); }
    }
    panel.querySelector('[data-document-retour]').addEventListener('click', () => {
        if(creating && !edition.hidden && !window.confirm('Voulez-vous abandonner la création de ce template ?')) return;
        history.replaceState(null,'','#documents/templates');
        afficherListe();
        signaler('');
        recherche.focus({preventScroll:true});
    });
    window.addEventListener('hashchange',()=>{if(!chargement) restaurerDepuisUrl();});
    recherche.addEventListener('input', dessinerListe);
    filtre.addEventListener('change', dessinerListe);
    filtreDemarche.addEventListener('change', dessinerListe);
    filtreStatut.addEventListener('change', dessinerListe);
    panel.querySelector('[data-document-new]').addEventListener('click',()=>{location.hash='documents/templates/nouveau';});
    async function ouvrirEdition() {
        if (!edition.hidden) { fermerEdition(); return; }
        editButton.disabled = true;
        try {
            effacerErreursChamps();
            if (!optionsEdition) {
                const response = await fetch(panel.dataset.documentsOptions, {credentials:'same-origin'});
                if (!response.headers.get('content-type')?.includes('application/json')) throw new Error('Session expirée. Rechargez la page.');
                const data = await response.json();
                if (!response.ok) throw new Error(data.erreur || 'Impossible de charger les choix.');
                optionsEdition = data;
            }
            const nasInfo=panel.querySelector('[data-document-nas-info]');
            const nasHint=`Depuis la racine NAS (${optionsEdition.nas_root || 'non configurée'})`;
            nasInfo.dataset.tooltip=nasHint;nasInfo.setAttribute('aria-label',nasHint);
            for (const nom of ['nom', 'chemin_relatif', 'destination_relative', 'nom_fichier']) edition.elements[nom].value = selection[nom] || '';
            tokenFields.forEach(field=>field.load(selection[field.name]));
            tokenFields.forEach(field=>field.refreshTitles());
            edition.elements.actif.checked = selection.actif;
            const emptyNature=element('option', '---');emptyNature.value='';
            edition.elements.id_nature.replaceChildren(emptyNature,...optionsEdition.natures.map(n => {
                const option = element('option', n.nom);option.value = n.id;return option;
            }));
            edition.elements.id_nature.value = selection.id_nature ?? '';
            const demarches = panel.querySelector('[data-document-demarches]');
            demarches.replaceChildren(...optionsEdition.demarches.map(d => {
                const label = element('label', '');label.className='bo-documents-checkbox';
                const input=document.createElement('input');input.type='checkbox';input.name='demarches';input.value=d.id;
                input.checked=(selection.demarche_ids || []).includes(d.id);
                label.append(input, element('span',d.nom));return label;
            }));
            messageLocal(panel.querySelector('[data-document-edition-status]'), '');
            edition.hidden = false;
            panel.querySelector('[data-document-informations]').hidden = true;
            panel.querySelector('[data-document-configuration]').hidden = true;
            editButton.setAttribute('aria-expanded','true');
            panel.querySelector('[data-document-retour]').disabled = !creating;
            edition.elements.nom.focus();
        } catch(error) { signaler(error.message, true); }
        finally { editButton.disabled = false; }
    }
    editButton.addEventListener('click',ouvrirEdition);
    panel.querySelector('[data-document-annuler]').addEventListener('click',()=>{
        if(creating) {history.replaceState(null,'','#documents/templates');afficherListe();}
        else fermerEdition();
    });
    edition.addEventListener('submit', async event => {
        event.preventDefault();
        const statutEdition=panel.querySelector('[data-document-edition-status]');
        effacerErreursChamps();
        messageLocal(statutEdition,'');
        tokenFields.forEach(field=>field.sync());
        for(const field of tokenFields) {
            const value=field.input.value;
            const tokens=[...value.matchAll(/\{([^{}]+)\}/g)].map(match=>match[1]);
            const literal=value.replace(/\{([^{}]+)\}/g,(token,code)=>Object.hasOwn(variables,code) ? 'value' : token);
            const invalid = !value.trim() || value.toLowerCase()==='.docx' || new Set(tokens).size!==tokens.length
                || /[{}<>:"\\|?*\x00-\x1f]/.test(literal)
                || (field.name==='destination_relative' && (value.startsWith('/') || value.replace(/\/$/,'').split('/').some(part=>!part || part==='.' || part==='..')))
                || (field.name==='nom_fichier' && (literal.includes('/') || tokens.includes('dossier.emplacement')));
            if(invalid) {
                erreurChamp(field.name,field.name==='destination_relative' ? 'Renseignez une destination relative valide, sans / initial ni remontée de dossier.' : 'Renseignez un nom de fichier valide, sans séparateur de dossier ni variable répétée.');
                field.editor.focus();return;
            }
        }
        const boutons=edition.querySelectorAll('button');
        boutons.forEach(b => { b.disabled=true; });editButton.disabled=true;
        messageLocal(statutEdition, 'Enregistrement…');
        try {
            const response=await fetch(creating ? panel.dataset.documentsCreate : selection.edition_url, {method:'POST', credentials:'same-origin', body:new FormData(edition)});
            if (!response.headers.get('content-type')?.includes('application/json')) throw new Error('Session expirée ou requête refusée. Rechargez la page.');
            const data=await response.json();
            if (!response.ok) {
                let first=null;const globalErrors=[];
                for(const [nom,erreurs] of Object.entries(data.fields || {})) {
                    const texte=erreurs.map(e=>e.message).join(' '),target=erreurChamp(nom,texte);
                    if(target) first ||= target;else globalErrors.push(texte);
                }
                if(first) {messageLocal(statutEdition,globalErrors.join(' '),!!globalErrors.length);first.focus();return;}
                throw new Error(globalErrors.join(' ') || data.erreur || 'Enregistrement impossible.');
            }
            if(creating) templates.push(data.template);
            else templates=templates.map(t=>t.id===data.template.id ? data.template : t);
            ouvrir(data.template);
            signaler('Informations enregistrées et modèle analysé.');
        } catch(error) { messageLocal(statutEdition,error.message,true); }
        finally { boutons.forEach(b=>{b.disabled=false;});tokenFields.forEach(field=>field.sync());editButton.disabled=false; }
    });
    let visible = !panel.hidden;
    new MutationObserver(() => {
        const maintenantVisible = !panel.hidden;
        if (maintenantVisible && !visible) charger();
        visible = maintenantVisible;
    }).observe(panel, {attributes: true, attributeFilter: ['hidden']});
    charger();
});

document.addEventListener('DOMContentLoaded',()=>{
    const panel=document.querySelector('[data-balises-catalogue]');if(!panel) return;
    const form=panel.querySelector('[data-balise-form]'),list=panel.querySelector('[data-balises-list]');
    const detail=panel.querySelector('[data-balise-detail]'),toolbar=panel.querySelector('[data-balises-toolbar]');
    const status=panel.querySelector('[data-balises-status]'),saveStatus=panel.querySelector('[data-balise-save-status]');
    const sources=panel.querySelector('[data-balise-sources]');
    const sourceFilter=panel.querySelector('[data-balises-source]'),demarcheFilter=panel.querySelector('[data-balises-demarche]');
    const templateFilter=panel.querySelector('[data-balises-template]');
    let data=null,loading=false,current=null,returnTemplate=null,routeVersion=0;
    const node=(tag,text='')=>{const element=document.createElement(tag);element.textContent=text;return element;};
    const message=(target,text,error=false)=>{target.textContent=text;target.classList.toggle('is-error',error);};
    async function api(url,options={}) {
        const response=await fetch(url,{credentials:'same-origin',...options});
        if(!response.headers.get('content-type')?.includes('application/json')) throw new Error('Session expirée. Rechargez la page.');
        const result=await response.json();
        if(!response.ok) throw new Error(Object.entries(result.fields || {}).map(([field,errors])=>`${field} : ${errors.map(e=>e.message).join(' ')}`).join(' ') || result.erreur || 'Requête impossible.');
        return result;
    }
    function options(select,rows,placeholder) {
        select.replaceChildren();const empty=node('option',placeholder);empty.value='';select.append(empty);
        rows.forEach(row=>{const option=node('option',row.nom);option.value=row.id ?? row.code;select.append(option);});
    }
    function templatesForDemarche() {
        return (data.templates || []).filter(t=>!demarcheFilter.value || !t.demarche_ids.length
            || t.demarche_ids.some(id=>String(id)===demarcheFilter.value));
    }
    function updateTemplateFilter() {
        const selected=templateFilter.value;
        options(templateFilter,templatesForDemarche(),'---');
        templateFilter.value=selected;
        panel.querySelector('[data-balises-template-label]').hidden=!demarcheFilter.value;
    }
    function drawList() {
        list.replaceChildren();const query=panel.querySelector('[data-balises-search]').value.toLocaleLowerCase('fr');
        const state=panel.querySelector('[data-balises-state]').value;
        const source=sourceFilter.value,demarche=demarcheFilter.value;
        const usedCodes=new Set(templatesForDemarche().filter(t=>!templateFilter.value || String(t.id)===templateFilter.value)
            .flatMap(t=>t.balise_codes));
        for(const item of data.balises.filter(b=>(!state || b.actif===(state==='actif'))
            && (!source || (b.source || (b.mode==='CONNUE' ? 'AGIDA' : 'MANUELLE'))===source)
            && (!demarche || usedCodes.has(b.code))
            && `${b.code} ${b.libelle}`.toLocaleLowerCase('fr').includes(query))) {
            const button=node('button');button.type='button';button.className='bo-documents-card';
            const identity=node('div');identity.append(node('strong',item.libelle),node('small',item.code));
            const state=node('span',!item.actif ? 'Inactive' : item.erreurs.length ? 'À configurer' : item.mode==='CONNUE' ? (item.source==='FORMULAIRE' ? 'Formulaire' : 'AGIDA') : 'À renseigner');
            state.className='bo-documents-badge '+(!item.actif || item.erreurs.length ? 'is-warning' : 'is-success');
            button.append(identity,state);button.addEventListener('click',()=>{location.hash=`documents/balises/${item.id}`;});list.append(button);
        }
        if(!list.children.length) list.append(node('p','Aucune balise ne correspond à la recherche.'));
    }
    function sourceVisibility() {
        panel.querySelector('[data-balise-property]').hidden=form.elements.source.value!=='AGIDA';
        form.elements.source_propriete.required=form.elements.source.value==='AGIDA';
        panel.querySelector('[data-balise-mappings]').hidden=form.elements.source.value!=='FORMULAIRE';
        panel.querySelector('[data-balise-item-label]').hidden=form.elements.type.value!=='LIST';
        form.elements.libelle_element.required=form.elements.type.value==='LIST';
    }
    async function addSource(value={}) {
        const row=node('div');row.className='bo-balise-source-row';
        const demarcheLabel=node('label','Démarche'),fieldLabel=node('label','Champ du formulaire');
        const demarche=node('select'),field=node('select'),remove=node('button','Retirer');remove.type='button';
        demarche.dataset.sourceDemarche='';field.dataset.sourceChamp='';
        options(demarche,data.demarches,'Choisir une démarche');options(field,[],'Choisir une démarche d’abord');
        demarcheLabel.append(demarche);fieldLabel.append(field);row.append(demarcheLabel,fieldLabel,remove);sources.append(row);
        remove.addEventListener('click',()=>row.remove());
        async function loadFields(selected='') {
            const id=demarche.value;
            options(field,[],'Chargement…');field.disabled=true;
            if(!id) {options(field,[],'Choisir une démarche d’abord');return;}
            try {
                const result=await api(`/back-office/documents/balises/champs/${id}/`);
                if(demarche.value!==id || !row.isConnected) return;
                options(field,result.champs.map(c=>({id:c.id,nom:`${c.nom} · ${c.type} (#${c.id})`})),'Choisir un champ');
                field.value=selected;field.disabled=false;
            } catch(error) {message(saveStatus,error.message,true);options(field,[],'Chargement impossible');}
        }
        demarche.addEventListener('change',()=>loadFields());
        if(value.id_demarche) {demarche.value=value.id_demarche;await loadFields(String(value.id_champ));}
    }
    async function route() {
        if(!data || panel.hidden) return;
        const match=location.hash.match(/^#documents\/balises(?:\/(nouvelle|\d+))?(?:\?(.*))?$/);if(!match) return;
        const version=++routeVersion;
        if(!match[1]) {detail.hidden=true;list.hidden=false;toolbar.hidden=false;drawList();return;}
        current=match[1]==='nouvelle' ? null : data.balises.find(item=>String(item.id)===match[1]);
        if(match[1]!=='nouvelle' && !current) {message(status,'Cette balise n’est plus disponible.',true);location.hash='documents/balises';return;}
        const params=new URLSearchParams(match[2] || '');returnTemplate=/^[1-9][0-9]*$/.test(params.get('template') || '') ? params.get('template') : null;
        panel.querySelector('[data-balise-back]').textContent=returnTemplate ? '← Revenir au template' : '← Toutes les balises';
        form.reset();list.hidden=true;toolbar.hidden=true;detail.hidden=false;message(saveStatus,'');
        panel.querySelector('[data-balise-title]').textContent=current ? current.libelle : 'Nouvelle balise';
        options(form.elements.source_propriete,data.proprietes,'Choisir une information');options(form.elements.type,data.types,'Choisir un type');
        for(const name of ['code','libelle','source','source_propriete','type','libelle_element','help_text']) form.elements[name].value=current?.[name] || '';
        form.elements.code.disabled=!!current;
        if(!current) {form.elements.code.value=params.get('code') || '';form.elements.source.value='MANUELLE';form.elements.type.value='TEXT';}
        for(const name of ['required','actif']) form.elements[name].checked=current ? current[name] : name!=='required';
        sources.replaceChildren();sourceVisibility();
        for(const source of current?.sources || []) {if(version!==routeVersion) return;await addSource(source);}
    }
    async function load() {
        if(loading || panel.hidden) return;loading=true;message(status,'Chargement du catalogue…');
        try {
            data=await api(panel.dataset.balisesCatalogue);
            const selected=demarcheFilter.value;
            options(demarcheFilter,data.demarches,'---');
            demarcheFilter.value=selected;
            updateTemplateFilter();
            message(status,'');await route();
        }
        catch(error) {message(status,error.message,true);} finally {loading=false;}
    }
    panel.querySelector('[data-balises-search]').addEventListener('input',drawList);
    panel.querySelector('[data-balises-state]').addEventListener('change',drawList);
    sourceFilter.addEventListener('change',drawList);
    demarcheFilter.addEventListener('change',()=>{templateFilter.value='';updateTemplateFilter();drawList();});
    templateFilter.addEventListener('change',drawList);
    panel.querySelector('[data-balise-new]').addEventListener('click',()=>{location.hash='documents/balises/nouvelle';});
    for(const selector of ['[data-balise-back]','[data-balise-cancel]']) panel.querySelector(selector).addEventListener('click',()=>{location.hash=returnTemplate ? `documents/templates/${returnTemplate}` : 'documents/balises';});
    form.elements.source.addEventListener('change',sourceVisibility);
    form.elements.type.addEventListener('change',()=>{
        if(form.elements.type.value==='LIST') form.elements.source.value='MANUELLE';
        sourceVisibility();
    });
    panel.querySelector('[data-balise-add-source]').addEventListener('click',()=>addSource());
    form.addEventListener('submit',async event=>{
        event.preventDefault();if(form.dataset.saving==='true') return;
        const payload=new FormData(form);payload.set('code',form.elements.code.value);
        const mappings=form.elements.source.value==='FORMULAIRE' ? [...sources.children].map(row=>({
            id_demarche:row.querySelector('[data-source-demarche]').value,id_champ:row.querySelector('[data-source-champ]').value})) : [];
        if(form.elements.source.value==='FORMULAIRE' && (!mappings.length || mappings.some(row=>!row.id_demarche || !row.id_champ))) {message(saveStatus,'Choisissez au moins une démarche et son champ de formulaire.',true);return;}
        payload.set('sources',JSON.stringify(mappings));
        const buttons=[...form.querySelectorAll('button')];buttons.forEach(button=>{button.disabled=true;});form.dataset.saving='true';message(saveStatus,'Enregistrement et réanalyse des templates…');
        try {
            const result=await api(current ? `/back-office/documents/balises/${current.id}/enregistrer/` : '/back-office/documents/balises/creer/',{method:'POST',body:payload});
            const index=data.balises.findIndex(item=>item.id===result.balise.id);if(index<0) data.balises.push(result.balise);else data.balises[index]=result.balise;
            history.replaceState(null,'',`#documents/balises/${result.balise.id}${returnTemplate ? '?template='+encodeURIComponent(returnTemplate) : ''}`);
            await route();message(saveStatus,['Balise enregistrée.',...(result.warnings || [])].join(' '));
        } catch(error) {message(saveStatus,error.message,true);}
        finally {form.dataset.saving='false';buttons.forEach(button=>{button.disabled=false;});}
    });
    window.addEventListener('hashchange',()=>{if(!panel.hidden) {if(data) route();else load();}});
    new MutationObserver(()=>{if(!panel.hidden) load();}).observe(panel,{attributes:true,attributeFilter:['hidden']});
    if(!panel.hidden) load();
});

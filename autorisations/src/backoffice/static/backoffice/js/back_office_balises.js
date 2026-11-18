document.addEventListener('DOMContentLoaded',()=>{
    const panel=document.querySelector('[data-balises-catalogue]');if(!panel) return;
    const form=panel.querySelector('[data-balise-form]'),list=panel.querySelector('[data-balises-list]');
    const detail=panel.querySelector('[data-balise-detail]'),toolbar=panel.querySelector('[data-balises-toolbar]');
    const status=panel.querySelector('[data-balises-status]'),saveStatus=panel.querySelector('[data-balise-save-status]');
    const sources=panel.querySelector('[data-balise-sources]');
    const saveButton=form.querySelector('button[type="submit"]');
    const propertyDescription=panel.querySelector('[data-balise-property-description]');
    function updateValidity() {
        for(const row of sources.children) {
            const field=row.querySelector('[data-source-champ]');
            const error=field.sourceFields?.find(item=>String(item.id)===field.value)?.erreurs_types?.[form.elements.type.value] || '';
            field.setCustomValidity(form.elements.source.value==='FORMULAIRE' ? error : '');
            const feedback=row.querySelector('[data-source-feedback]');
            feedback.textContent=error;feedback.hidden=!error;
        }
        propertyDescription.textContent=data?.proprietes.find(item=>item.code===form.elements.source_propriete.value)?.description || '';
        propertyDescription.hidden=!propertyDescription.textContent || form.elements.source.value!=='AGIDA';
        let valid=true;
        for(const field of form.querySelectorAll('input,select,textarea')) {
            const missing=!field.disabled && field.required && !field.value.trim();
            const invalid=!field.disabled && (missing || !field.validity.valid || (field.required && field.selectedOptions?.[0]?.disabled));
            field.classList.toggle('is-incomplete',invalid);
            field.setAttribute('aria-invalid',String(invalid));
            if(invalid) valid=false;
        }
        const mappingMissing=form.elements.source.value==='FORMULAIRE' && (!sources.children.length || [...sources.children].some(row=>
            !row.querySelector('[data-source-demarche]').value || !row.querySelector('[data-source-champ]').value || row.querySelector('[data-source-champ]').disabled));
        panel.querySelector('[data-balise-mappings]').classList.toggle('is-incomplete',mappingMissing);
        saveButton.disabled=!valid || mappingMissing || form.dataset.saving==='true';
    }
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
        const groups=new Map();
        if(rows.some(row=>row.categorie)) {
            for(const category of ['Année','Date','Dossier','Document','Pétitionnaire']) {
                if(!rows.some(row=>row.categorie===category)) continue;
                const group=document.createElement('optgroup');group.label=category;groups.set(category,group);select.append(group);
            }
        }
        rows.forEach(row=>{const option=node('option',row.nom);option.value=row.id ?? row.code;(groups.get(row.categorie) || select).append(option);});
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
        const usedTemplates=templatesForDemarche().filter(t=>!templateFilter.value || String(t.id)===templateFilter.value);
        for(const item of data.balises.filter(b=>(!state || b.actif===(state==='actif'))
            && (!source || (b.source || (b.mode==='CONNUE' ? 'AGIDA' : 'MANUELLE'))===source)
            && (!demarche || (b.id_template ? usedTemplates.some(t=>String(t.id)===String(b.id_template)) : usedCodes.has(b.code)))
            && `${b.code} ${b.libelle}`.toLocaleLowerCase('fr').includes(query))) {
            const button=node('button');button.type='button';button.className='bo-documents-card';
            button.classList.toggle('is-unconfigured',item.actif && item.erreurs.length>0);
            const identity=node('div');identity.append(node('strong',item.libelle),node('small',item.code),node('small',item.id_template ? `Template : ${item.template_nom || item.id_template}` : item.source==='AGIDA' ? 'AGIDA · Globale' : 'Sans template · À rattacher'));
            const state=node('span',!item.actif ? 'Inactive' : item.erreurs.length ? 'À configurer' : item.mode==='CONNUE' ? (item.source==='FORMULAIRE' ? 'Formulaire' : 'AGIDA') : 'À renseigner');
            state.className='bo-documents-badge '+(!item.actif || item.erreurs.length ? 'is-warning' : 'is-success');
            button.append(identity,state);button.addEventListener('click',()=>{location.hash=`documents/balises/${item.id}`;});list.append(button);
        }
        if(!list.children.length) list.append(node('p','Aucune balise ne correspond à la recherche.'));
    }
    function sourceVisibility() {
        const global=form.elements.source.value==='AGIDA';
        panel.querySelector('[data-balise-template]').hidden=global;
        form.elements.id_template.disabled=global;form.elements.id_template.required=!global;
        panel.querySelector('[data-balise-property]').hidden=form.elements.source.value!=='AGIDA';
        form.elements.source_propriete.required=form.elements.source.value==='AGIDA';
        panel.querySelector('[data-balise-mappings]').hidden=form.elements.source.value!=='FORMULAIRE';
        panel.querySelector('[data-balise-item-label]').hidden=form.elements.type.value!=='LIST';
        form.elements.libelle_element.required=form.elements.type.value==='LIST';
        for(const option of form.elements.source_propriete.options) {
            const used=data.balises.find(item=>item.id!==current?.id && (item.source==='AGIDA' || (!item.source && item.mode==='CONNUE')) && (item.source_propriete || item.code)===option.value);
            option.disabled=!!option.value && !!used;
            option.title=used ? `Déjà utilisée par la balise « ${used.libelle} » (${used.code}).` : '';
        }
        updateValidity();
    }
    function fieldPicker(select) {
        const wrapper=node('span');wrapper.className='bo-balise-field-picker';
        const trigger=node('button');trigger.type='button';trigger.className='bo-balise-field-trigger';
        trigger.setAttribute('aria-haspopup','listbox');trigger.setAttribute('aria-expanded','false');
        const popup=node('span');popup.className='bo-balise-field-options';popup.hidden=true;popup.setAttribute('role','listbox');
        select.classList.add('bo-balise-field-native');
        select.tabIndex=-1;
        wrapper.append(select,trigger,popup);
        const close=()=>{popup.hidden=true;trigger.setAttribute('aria-expanded','false');};
        function position() {
            const rect=trigger.getBoundingClientRect(),width=Math.min(Math.max(rect.width,400),window.innerWidth-24);
            popup.style.width=`${width}px`;
            popup.style.left=`${Math.max(12,Math.min(rect.left,window.innerWidth-width-12))}px`;
            const below=window.innerHeight-rect.bottom-12,above=rect.top-12;
            const height=Math.min(320,Math.max(below,above));
            popup.style.maxHeight=`${Math.max(0,height)}px`;
            popup.style.top=`${below>=Math.min(200,height) ? rect.bottom+4 : Math.max(12,rect.top-Math.min(popup.scrollHeight,height)-4)}px`;
        }
        function sync() {
            trigger.textContent=select.selectedOptions[0]?.textContent || 'Choisir un champ';
            trigger.disabled=select.disabled;trigger.classList.toggle('is-placeholder',!select.value);
            trigger.setAttribute('aria-label',`Champ du formulaire : ${trigger.textContent}`);
            popup.replaceChildren();
            for(const option of select.options) {
                if(!option.value) continue;
                const item=node('button',option.textContent);item.type='button';item.setAttribute('role','option');
                item.setAttribute('aria-selected',String(option.selected));item.disabled=option.disabled;
                item.addEventListener('click',()=>{select.value=option.value;select.dispatchEvent(new Event('change',{bubbles:true}));close();trigger.focus();});
                popup.append(item);
            }
            if(select.disabled) close();
            if(!popup.hidden) position();
        }
        trigger.addEventListener('click',()=>{if(!popup.hidden) {close();return;} sync();popup.hidden=false;trigger.setAttribute('aria-expanded','true');position();(popup.querySelector('[aria-selected="true"]') || popup.querySelector('button'))?.focus();});
        wrapper.addEventListener('keydown',event=>{
            if(event.key==='Escape') {close();trigger.focus();event.preventDefault();}
            if(event.key==='Tab') close();
            if(!popup.hidden && ['ArrowDown','ArrowUp','Home','End'].includes(event.key)) {
                event.preventDefault();const items=[...popup.querySelectorAll('button:not(:disabled)')];
                const index=items.indexOf(document.activeElement);
                items[event.key==='Home' ? 0 : event.key==='End' ? items.length-1 : (index+(event.key==='ArrowDown' ? 1 : -1)+items.length)%items.length]?.focus();
            }
        });
        wrapper.addEventListener('focusout',event=>{if(!wrapper.contains(event.relatedTarget)) close();});
        window.addEventListener('resize',close);
        window.addEventListener('scroll',event=>{if(!popup.contains(event.target)) close();},{capture:true,passive:true});
        new MutationObserver(sync).observe(select,{childList:true,subtree:true,attributes:true});
        select.addEventListener('change',sync);sync();return wrapper;
    }
    async function addSource(value={}) {
        const row=node('div');row.className='bo-balise-source-row';
        const demarcheLabel=node('label','Démarche'),fieldLabel=node('label','Champ du formulaire');
        const demarche=node('select'),field=node('select'),remove=node('button','Retirer');remove.type='button';
        remove.dataset.sourceRemove='';
        demarche.dataset.sourceDemarche='';field.dataset.sourceChamp='';
        options(demarche,availableDemarches(),'Choisir une démarche');options(field,[],'Choisir une démarche d’abord');
        demarche.disabled=availableDemarches().length===1;
        remove.hidden=demarche.disabled;
        const feedback=node('small');feedback.dataset.sourceFeedback='';feedback.className='is-error';feedback.setAttribute('role','status');feedback.hidden=true;
        demarcheLabel.append(demarche);fieldLabel.append(fieldPicker(field),feedback);row.append(demarcheLabel,fieldLabel,remove);sources.append(row);
        remove.addEventListener('click',()=>{row.remove();refreshMappingScope();});
        updateValidity();
        async function loadFields(selected='') {
            const id=demarche.value;
            options(field,[],'Chargement…');field.disabled=true;
            field.sourceFields=[];
            updateValidity();
            if(!id) {options(field,[],'Choisir une démarche d’abord');updateValidity();return;}
            try {
                const result=await api(`/back-office/documents/balises/champs/${id}/`);
                if(demarche.value!==id || !row.isConnected) return;
                field.sourceFields=result.champs;
                options(field,result.champs.map(c=>({id:c.id,nom:`${c.nom} · ${c.type} (#${c.id})`})),'Choisir un champ');
                field.value=selected;field.disabled=false;
            } catch(error) {message(saveStatus,error.message,true);options(field,[],'Chargement impossible');}
            finally {updateValidity();}
        }
        demarche.addEventListener('change',()=>loadFields());
        if(value.id_demarche) {demarche.value=value.id_demarche;await loadFields(String(value.id_champ));}
    }
    function availableDemarches() {
        const template=(data.templates || []).find(item=>String(item.id)===form.elements.id_template.value);
        if(!template) return [];
        return data.demarches.filter(item=>!template.demarche_ids.length || template.demarche_ids.some(id=>String(id)===String(item.id)));
    }
    async function refreshMappingScope() {
        const allowed=availableDemarches();
        const add=panel.querySelector('[data-balise-add-source]');
        add.hidden=allowed.length<=1;
        add.disabled=allowed.length<=1 || sources.children.length>=allowed.length;
        for(const row of [...sources.children]) {
            const select=row.querySelector('[data-source-demarche]'),previous=select.value;
            options(select,allowed,'Choisir une démarche');
            select.value=allowed.some(item=>String(item.id)===previous) ? previous : (allowed.length===1 ? String(allowed[0].id) : '');
            select.disabled=allowed.length===1;
            row.querySelector('[data-source-remove]').hidden=allowed.length===1;
            if(select.value!==previous) select.dispatchEvent(new Event('change'));
        }
        if(form.elements.source.value==='FORMULAIRE' && allowed.length===1 && !sources.children.length) {
            await addSource({id_demarche:allowed[0].id});
            if(sources.firstElementChild) {
                sources.firstElementChild.querySelector('[data-source-demarche]').disabled=true;
                sources.firstElementChild.querySelector('[data-source-remove]').hidden=true;
            }
        }
        add.disabled=allowed.length<=1 || sources.children.length>=allowed.length;
        updateValidity();
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
        panel.querySelector('[data-balise-delete]').hidden=!current;
        const impact=panel.querySelector('[data-balise-impact]');impact.replaceChildren();
        const usages=current ? (data.templates || []).filter(template=>(!current.id_template || String(template.id)===String(current.id_template)) && (template.balise_codes || []).includes(current.code)) : [];
        impact.hidden=!current;
        if(current && !usages.length) impact.append(node('strong','Cette balise n’est utilisée par aucun template.'));
        if(usages.length) {
            impact.append(node('strong',`Cette balise est utilisée par ${usages.length} template${usages.length>1 ? 's' : ''}. Toute modification s’y appliquera.`));
            const details=node('details'),summary=node('summary',usages.length>1 ? 'Voir les templates concernés' : 'Voir le template concerné'),list=node('ul');
            usages.forEach(template=>{const row=node('li'),link=node('a',template.nom);link.href=`#documents/templates/${template.id}`;row.append(link);list.append(row);});
            details.append(summary,list);impact.append(details);
        }
        options(form.elements.source_propriete,data.proprietes,'Choisir une information');options(form.elements.type,data.types,'Choisir un type');
        for(const name of ['code','libelle','source','source_propriete','type','libelle_element','help_text']) form.elements[name].value=current?.[name] || '';
        form.elements.code.disabled=!!current;
        options(form.elements.id_template,data.templates || [],'Choisir un template');
        form.elements.id_template.value=current?.id_template || returnTemplate || '';
        if(!current) {form.elements.code.value=params.get('code') || '';form.elements.source.value='MANUELLE';form.elements.type.value='';}
        form.elements.actif.checked=current ? current.actif : true;
        sources.replaceChildren();sourceVisibility();
        for(const source of current?.sources || []) {if(version!==routeVersion) return;await addSource(source);}
        await refreshMappingScope();
        updateValidity();
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
    form.elements.source.addEventListener('change',()=>{sourceVisibility();refreshMappingScope();});
    form.elements.id_template.addEventListener('change',refreshMappingScope);
    form.elements.type.addEventListener('change',()=>{
        if(form.elements.type.value==='LIST') form.elements.source.value='MANUELLE';
        sourceVisibility();
    });
    panel.querySelector('[data-balise-add-source]').addEventListener('click',async()=>{await addSource();await refreshMappingScope();});
    form.addEventListener('input',updateValidity);
    panel.querySelector('[data-balise-delete]').addEventListener('click',async()=>{
        if(!current || form.dataset.saving==='true') return;
        const count=(data.templates || []).filter(template=>(!current.id_template || String(template.id)===String(current.id_template)) && template.balise_codes.includes(current.code)).length;
        const warning=count ? `La balise « ${current.code} » est utilisée par ${count} template${count>1 ? 's' : ''}. Sa suppression rendra ${count>1 ? 'ces templates invalides : il faudra les corriger' : 'ce template invalide : il faudra le corriger'}.` : `La balise « ${current.code} » n’est utilisée par aucun template.`;
        if(!window.confirm(`${warning}\n\nConfirmer la suppression ?`)) return;
        form.dataset.saving='true';const buttons=[...form.querySelectorAll('button')];buttons.forEach(button=>{button.disabled=true;});
        try {
            const payload=new FormData();payload.set('csrfmiddlewaretoken',form.querySelector('[name=csrfmiddlewaretoken]').value);
            await api(`/back-office/documents/balises/${current.id}/supprimer/`,{method:'POST',body:payload});
            data.balises=data.balises.filter(item=>item.id!==current.id);
            location.hash='documents/balises';message(status,'Balise supprimée.');
        } catch(error) {message(saveStatus,error.message,true);}
        finally {form.dataset.saving='false';buttons.forEach(button=>{button.disabled=false;});updateValidity();}
    });
    form.addEventListener('change',updateValidity);
    form.addEventListener('submit',async event=>{
        event.preventDefault();if(form.dataset.saving==='true') return;
        updateValidity();if(saveButton.disabled) return;
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
        finally {form.dataset.saving='false';buttons.forEach(button=>{button.disabled=false;});updateValidity();}
    });
    window.addEventListener('hashchange',()=>{if(!panel.hidden) {if(data) route();else load();}});
    new MutationObserver(()=>{if(!panel.hidden) load();}).observe(panel,{attributes:true,attributeFilter:['hidden']});
    if(!panel.hidden) load();
});

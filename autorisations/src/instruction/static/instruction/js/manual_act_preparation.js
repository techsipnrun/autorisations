(() => {
    const block=document.querySelector('[data-manual-act]');
    if(!block) return;
    const get=name=>block.querySelector(`[data-preparation-${name}]`);
    const nature=get('nature'),dialog=get('dialog'),choice=get('choice');
    let data={natures:[],preparation:null},busy=false,key=crypto.randomUUID();
    const originals=new WeakMap();
    const help=block.querySelector('.manual-act-info'),bubble=help?.querySelector('[role=tooltip]');
    function positionHelp() {
        if(!bubble) return;
        const rect=help.getBoundingClientRect();
        bubble.style.left=Math.max(16,Math.min(rect.left,innerWidth-bubble.offsetWidth-16))+'px';
        bubble.style.top=Math.max(16,Math.min(rect.bottom+8,innerHeight-bubble.offsetHeight-16))+'px';
    }
    help?.addEventListener('mouseenter',positionHelp);help?.addEventListener('focus',positionHelp);
    window.addEventListener('resize',positionHelp);window.addEventListener('scroll',positionHelp,true);
    const forms=[...new Set([...document.querySelectorAll('[name=piece_jointe_work]')].map(input=>input.closest('form')).filter(Boolean))];
    async function api(body,query='',fullscreen=false) {
        if(busy) return null;
        busy=true;get('loading').hidden=fullscreen;if(fullscreen) get('progress').showModal();get('error').hidden=true;block.setAttribute('aria-busy','true');
        block.querySelectorAll('button,select').forEach(control=>{control.dataset.preparationDisabled=String(control.disabled);control.disabled=true;});
        try {
            const response=await fetch(block.dataset.url+query,{method:body ? 'POST':'GET',body,
                credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(20000)});
            const result=await response.json();
            if(!response.ok) throw new Error(result.error || 'Préparation indisponible.');
            return result;
        } catch(error) {get('error').textContent=error.message || 'Préparation indisponible.';get('error').hidden=false;return null;}
        finally {get('progress').close();busy=false;get('loading').hidden=true;block.removeAttribute('aria-busy');block.querySelectorAll('button,select').forEach(control=>{control.disabled=control.dataset.preparationDisabled==='true';delete control.dataset.preparationDisabled;});}
    }
    function applyPreparation(form,select) {
        const preparation=data.preparation;
        const matches=preparation && select.value===String(preparation.nature_id);
        form.querySelectorAll('[data-manual-preparation-field]').forEach(input=>input.remove());
        let summary=form.querySelector('[data-manual-preparation-summary]');
        if(!summary) {summary=document.createElement('p');summary.dataset.manualPreparationSummary='';summary.className='manual-preparation-summary';}
        const picker=select.nextElementSibling?.classList.contains('act-nature-picker') ? select.nextElementSibling : select;
        picker.after(summary);
        summary.hidden=!matches;
        if(matches) {
            form.dataset.manualPreparation=preparation.id;
            form.dataset.manualPreparationNumber=preparation.numero;
            form.dataset.manualPreparationDisplay=preparation.display;
            const input=document.createElement('input');input.type='hidden';input.name='manual_preparation';input.value=preparation.id;input.dataset.manualPreparationField='';form.append(input);
            const number=document.createElement('strong');number.textContent=preparation.display;
            summary.replaceChildren(document.createTextNode('Numéro réservé à utiliser : '),number);
            const checkbox=form.querySelector('[name=projet_acte_identique]');
            if(checkbox) checkbox.checked=false;
        } else {
            delete form.dataset.manualPreparation;delete form.dataset.manualPreparationNumber;delete form.dataset.manualPreparationDisplay;
        }
        document.dispatchEvent(new CustomEvent('manual-act-preparation-updated',{detail:Boolean(preparation)}));
    }
    function syncForms() {
        for(const form of forms) {
            const select=form.querySelector('select[name=nature_document]');
            if(!select) continue;
            if(!originals.has(form)) {
                originals.set(form,{value:select.value,disabled:select.disabled});
                select.addEventListener('change',()=>applyPreparation(form,select),{capture:true});
            }
            const preparation=data.preparation;
            const previous=form.dataset.reservedPreparationId;
            if(preparation) {
                form.dataset.reservedPreparationId=preparation.id;
                form.dataset.reservedPreparationNature=String(preparation.nature_id);
                form.dataset.reservedPreparationNumber=preparation.numero;
                if(previous!==preparation.id) select.value=String(preparation.nature_id);
            } else {
                delete form.dataset.reservedPreparationId;delete form.dataset.reservedPreparationNature;delete form.dataset.reservedPreparationNumber;
                if(previous) select.value=originals.get(form).value;
            }
            select.disabled=originals.get(form).disabled;
            applyPreparation(form,select);
            select.dispatchEvent(new Event('change',{bubbles:true}));
        }
    }
    function render(result) {
        data=result;
        const previous=nature.value;
        nature.replaceChildren(new Option('Sélectionner une nature',''));
        data.natures.forEach(item=>nature.add(new Option(item.label,item.id)));
        nature.value=data.preparation ? String(data.preparation.nature_id):previous;
        get('config').hidden=Boolean(data.preparation);get('current').hidden=!data.preparation;
        if(data.preparation) {
            get('label').textContent=`Numéro à utiliser pour « ${data.preparation.nature} » :`;
            get('number').textContent=data.preparation.display;
            get('used').textContent=data.preparation.origin==='RECUPERE' && data.preparation.dossiers.length
                ? data.preparation.dossiers.every(id=>String(id)===block.dataset.dossier)
                    ? `Ce numéro est déjà utilisé pour un autre acte de nature « ${data.preparation.nature} » sur ce dossier.`
                    : `Ce numéro est également utilisé pour les dossiers : ${data.preparation.dossiers.join(', ')}.`:'';
        }
        updateNature();syncForms();
        document.dispatchEvent(new CustomEvent('manual-act-preparation-updated',{detail:Boolean(data.preparation)}));
    }
    function updateNature() {
        const item=data.natures.find(item=>String(item.id)===nature.value);
        get('options').hidden=!item?.can_generate;
        get('number-options').hidden=!item || Boolean(item.can_generate);
        const numberHelp=block.querySelector('#manual-act-number-help > span:last-child');
        if(numberHelp) numberHelp.textContent=item && !item.automatic
            ? 'Saisir à la main : Saisissez vous-même le numéro'
            : 'Générer un nouveau : obtenir un nouveau numéro unique pour le futur acte.';
        if(item){get('generate').href=item.url;get('reserve').hidden=!item.automatic;get('reserve').disabled=!item.automatic;get('enter').hidden=item.automatic;get('reserve').title=item.automatic ? '' : 'Nature à référence libre : récupérez un numéro existant.';}
    }
    function body(action) {
        const fields=new FormData();fields.set('csrfmiddlewaretoken',block.querySelector('[name=csrfmiddlewaretoken]').value);
        fields.set('action',action);fields.set('confirmed','1');fields.set('nature',nature.value);fields.set('request_key',key);
        return fields;
    }
    async function select(action,source,manual) {
        const fields=body(action);if(manual!==undefined) fields.set('numero',manual);if(source) fields.set('source',source);
        const result=await api(fields);
        if(result){key=crypto.randomUUID();render(result);dialog.close();get('entry-dialog').close();}
    }
    get('generate').addEventListener('click',event=>{
        if(event.button!==0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
        if(busy){event.preventDefault();return;}get('progress').showModal();
    });
    window.addEventListener('pageshow',()=>get('progress').close());
    nature.addEventListener('change',updateNature);
    get('manual').onclick=()=>{get('options').hidden=true;get('number-options').hidden=false;};
    get('enter').onclick=()=>{get('entry').value='';get('entry-confirm').disabled=true;get('entry-dialog').showModal();get('entry').focus();};
    get('entry').oninput=()=>{get('entry-confirm').disabled=!get('entry').value.trim() || /[\\:*?"<>|\x00-\x1f]/.test(get('entry').value);};
    get('entry-confirm').onclick=()=>{if(!get('entry-confirm').disabled && confirm('Utiliser cette référence pour le projet d’acte ?')) select('manual',null,get('entry').value.trim());};
    get('entry').onkeydown=event=>{if(event.key==='Enter'){event.preventDefault();get('entry-confirm').click();}};
    get('entry-cancel').onclick=()=>get('entry-dialog').close();
    get('reserve').onclick=()=>{if(confirm('Générer un nouveau numéro pour cette nature ? Le numéro sera réservé même si vous ne terminez pas le projet.')) select('reserve');};
    get('cancel').onclick=async()=>{
        if(!data.preparation || !confirm('Annuler cette réservation ? Aucun document ne sera supprimé et le numéro généré ne sera pas réattribué.')) return;
        const fields=body('cancel');fields.set('preparation',data.preparation.id);
        const result=await api(fields);if(result){nature.value='';key=crypto.randomUUID();render(result);}
    };
    get('copy').onclick=async()=>{try{await navigator.clipboard.writeText(data.preparation.display);}catch{get('error').textContent='Copie impossible. Sélectionnez le numéro pour le copier.';get('error').hidden=false;}};
    get('recover').onclick=async()=>{
        const result=await api(null,'?nature='+encodeURIComponent(nature.value),true);if(!result) return;
        choice.replaceChildren(new Option('Sélectionner un numéro',''));
        result.choices.forEach(item=>choice.add(new Option(`${item.display} (Dossier ${item.dossier})`,item.key)));
        get('description').textContent=`Seuls les numéros des actes et projets d’acte de nature « ${data.natures.find(item=>String(item.id)===nature.value)?.label} » existants pour ce dossier ou ses dossiers liés sont proposés ici.`;
        get('empty').hidden=result.choices.length>0;get('confirm').disabled=true;dialog.showModal();
    };
    choice.onchange=()=>{get('confirm').disabled=!choice.value;};
    get('confirm').onclick=()=>{if(choice.value && confirm('Récupérer ce numéro pour votre projet d’acte ?')) select('recover',choice.value);};
    get('close').onclick=()=>dialog.close();
    api().then(result=>{if(result) render(result);});
})();

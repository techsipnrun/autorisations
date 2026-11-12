(() => {
    const form=document.querySelector('#generation-form');
    if(!form?.dataset.draftKey) return;
    const key='agida:generation-draft:'+form.dataset.draftKey;
    const fields=()=>[...form.querySelectorAll('.known-information input,.known-information select,.known-information textarea,.manual-fields input,.manual-fields select,.manual-fields textarea')]
        .filter(input=>input.name.startsWith('balise_') || input.name.startsWith('known-balise_') || input.name==='edit_known');
    let timer;
    function save() {
        clearTimeout(timer);
        const values={};
        fields().forEach(input=>{
            (values[input.name]??=[]).push({value:input.value,checked:input.checked,
                selected:input.multiple ? [...input.selectedOptions].map(option=>option.value) : null});
        });
        try {localStorage.setItem(key,JSON.stringify(values));return true;}
        catch {return false;}
    }
    let draft;
    try {draft=JSON.parse(localStorage.getItem(key));} catch {draft=null;}
    if(draft && typeof draft==='object') {
        for(const group of form.querySelectorAll('[data-repeated-text]')) {
            const input=group.querySelector('input');
            const count=Math.min(100,draft[input?.name]?.length || 1);
            while(group.querySelectorAll('[data-repeated-rows] input').length<count) group.querySelector('[data-add-row]').click();
            while(group.querySelectorAll('[data-repeated-rows] input').length>count) group.querySelector('[data-repeated-rows]').lastElementChild.querySelector('[data-remove-row]').click();
        }
        const indexes={};
        fields().forEach(input=>{
            const item=draft[input.name]?.[indexes[input.name] || 0];
            indexes[input.name]=(indexes[input.name] || 0)+1;
            if(!item || typeof item.value!=='string') return;
            input.value=item.value;
            if(input.multiple && Array.isArray(item.selected)) [...input.options].forEach(option=>{option.selected=item.selected.includes(option.value);});
            if(['checkbox','radio'].includes(input.type)) input.checked=Boolean(item.checked);
        });
        if(form.querySelector('[name=edit_known]')?.value==='1') {
            form.querySelector('#known-editor').hidden=false;
            form.querySelector('#known-editor fieldset').disabled=false;
            form.querySelector('#known-display').hidden=true;
            form.querySelector('.edit-known')?.setAttribute('aria-expanded','true');
        }
        form.dispatchEvent(new Event('change',{bubbles:true}));
    }
    const schedule=()=>{clearTimeout(timer);timer=setTimeout(save,250);};
    form.addEventListener('input',schedule);
    form.addEventListener('change',schedule);
    form.addEventListener('click',schedule);
    window.addEventListener('pagehide',save);
    document.addEventListener('visibilitychange',()=>{if(document.hidden) save();});
    // A successfully saved draft makes navigation safe; retain the existing
    // warning if storage is unavailable rather than silently losing changes.
    window.saveDocumentGenerationDraft=save;
})();

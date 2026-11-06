document.addEventListener('DOMContentLoaded',()=>{
    const control=document.querySelector('[data-document-number]'),filename=document.querySelector('[data-output-filename]');
    const filenameValues=JSON.parse(document.getElementById('output-filename-values')?.textContent || '{}');
    let refreshNumberChip=()=>{};
    if(filename) {
        const editor=filename.querySelector('[data-output-editor]'),input=filename.querySelector('[name=output_filename]');
        const raw=()=>[...editor.childNodes].map(node=>node.dataset?.variable ? `{${node.dataset.variable}}` : node.textContent).join('').replaceAll('\u200b','').replace(/\.docx$/i,'')+'.docx';
        const sync=()=>{input.value=raw();input.dispatchEvent(new Event('input',{bubbles:true}));};
        function chip(code) {
            const info=filenameValues[code] || {label:code,value:'À compléter',pending:true};
            const node=document.createElement('span');node.className='output-variable';node.dataset.variable=code;node.contentEditable='false';
            node.classList.toggle('is-pending',info.pending);
            const label=document.createElement('span');label.dataset.variableLabel='';label.textContent=info.value;label.title=info.label;
            node.title=info.label;node.append(label);return node;
        }
        function textPart(value) {
            const node=document.createElement('span');node.contentEditable='true';node.className='output-filename-text';
            node.setAttribute('role','textbox');node.setAttribute('aria-label','Texte du nom de fichier');node.textContent=value;return node;
        }
        const value=input.value.replace(/\.docx$/i,'');let start=0;
        for(const match of value.matchAll(/\{([^{}]+)\}/g)) {editor.append(textPart(value.slice(start,match.index)),chip(match[1]));start=match.index+match[0].length;}
        editor.append(textPart(value.slice(start)));
        editor.addEventListener('beforeinput',event=>{
            const selection=window.getSelection();
            if(selection.rangeCount && !selection.isCollapsed && [...editor.querySelectorAll('[data-variable]')].some(node=>selection.getRangeAt(0).intersectsNode(node))) event.preventDefault();
        });
        editor.addEventListener('drop',event=>event.preventDefault());
        editor.addEventListener('cut',event=>{
            const selection=window.getSelection();
            if(selection.rangeCount && [...editor.querySelectorAll('[data-variable]')].some(node=>selection.getRangeAt(0).intersectsNode(node))) event.preventDefault();
        });
        editor.addEventListener('input',sync);
        editor.addEventListener('keydown',event=>{if(event.key==='Enter') event.preventDefault();});
        editor.addEventListener('paste',event=>{
            event.preventDefault();const text=event.clipboardData.getData('text/plain').replace(/[\r\n]/g,'');
            const selection=window.getSelection();if(!selection.rangeCount) return;
            const range=selection.getRangeAt(0);if([...editor.querySelectorAll('[data-variable]')].some(node=>range.intersectsNode(node))) return;
            if(!event.target.closest('.output-filename-text')) return;
            range.deleteContents();const node=document.createTextNode(text);range.insertNode(node);range.setStartAfter(node);range.collapse(true);sync();
        });
        refreshNumberChip=numero=>editor.querySelectorAll('[data-variable="document.numero"]').forEach(node=>{
            node.querySelector('[data-variable-label]').textContent=numero;node.classList.remove('is-pending');
        });
    }
    if(!control) return;
    const dialog=control.querySelector('[data-number-dialog]'),choice=control.querySelector('[data-number-choice]'),message=control.querySelector('[data-number-message]');
    const confirm=control.querySelector('[data-number-confirm]');let busy=false;
    const actions=control.querySelector('.number-actions'),toggle=control.querySelector('[data-number-toggle]');
    toggle.addEventListener('click',()=>{actions.hidden=!actions.hidden;toggle.setAttribute('aria-expanded',String(!actions.hidden));});
    const progress=document.querySelector('[data-generation-progress]');
    const loading=show=>{if(!progress) return;if(show && !progress.open) progress.showModal();else if(!show && progress.open) progress.close();};
    // Custom options allow italic metadata, which native option elements cannot render reliably.
    const picker=document.createElement('div');picker.className='number-picker';
    const pickerButton=document.createElement('button');pickerButton.type='button';pickerButton.className='number-picker-trigger';pickerButton.setAttribute('aria-expanded','false');
    const options=document.createElement('div');options.className='number-picker-options';options.hidden=true;options.setAttribute('role','group');options.setAttribute('aria-label','Numéros disponibles');
    choice.after(picker);picker.append(pickerButton,options);choice.hidden=true;
    const pickerLabel=()=>{pickerButton.replaceChildren();const selected=choice.selectedOptions[0];pickerButton.append(document.createTextNode(selected?.dataset.numero || 'Sélectionner un numéro'));if(selected?.dataset.detail){const detail=document.createElement('em');detail.textContent=` (${selected.dataset.detail})`;pickerButton.append(detail);}};
    pickerLabel();pickerButton.addEventListener('click',()=>{options.hidden=!options.hidden;pickerButton.setAttribute('aria-expanded',String(!options.hidden));});
    picker.addEventListener('keydown',event=>{if(event.key==='Escape' && !options.hidden){event.preventDefault();event.stopPropagation();options.hidden=true;pickerButton.setAttribute('aria-expanded','false');pickerButton.focus();}});
    document.addEventListener('click',event=>{if(!picker.contains(event.target)){options.hidden=true;pickerButton.setAttribute('aria-expanded','false');}});
    async function api(url,data) {
        const response=await fetch(url,{credentials:'same-origin',...(data ? {method:'POST',body:data,headers:{'X-CSRFToken':control.querySelector('[name=csrfmiddlewaretoken]').value}} : {})});
        if(!response.headers.get('content-type')?.includes('application/json')) throw new Error('Session expirée ou accès refusé.');
        const result=await response.json();if(!response.ok) throw new Error(result.error || 'Action impossible.');return result;
    }
    async function select(action,source='') {
        if(busy) return;
        const text=action==='reserve' ? 'Réserver un nouveau numéro unique ?' : `Récupérer ${choice.selectedOptions[0].textContent} pour ce document ?`;
        if(!window.confirm(text)) return;
        busy=true;control.querySelectorAll('button').forEach(button=>{button.disabled=true;});message.textContent='Attribution du numéro…';
        try {
            const data=new FormData();data.set('action',action);data.set('choice',source);data.set('request_key',control.querySelector('[data-number-request]').value);
            const result=await api(control.dataset.selectUrl,data);
            const selected=control.querySelector('[name=number_selection]');selected.value=result.selection;selected.dispatchEvent(new Event('input',{bubbles:true}));
            control.querySelector('[data-number-request]').value=result.request_key;control.querySelector('[data-number-value]').textContent=result.numero;
            control.querySelector('[data-number-value]').classList.remove('is-unassigned');toggle.hidden=false;actions.hidden=true;toggle.setAttribute('aria-expanded','false');refreshNumberChip(result.numero);
            control.querySelector('.number-format-example').hidden=true;
            message.textContent='';dialog.close();
        } catch(error) {message.textContent=error.message;dialog.close();}
        finally {busy=false;control.querySelectorAll('button').forEach(button=>{button.disabled=false;});confirm.disabled=!choice.value;}
    }
    control.querySelector('[data-number-reserve]').addEventListener('click',()=>select('reserve'));
    control.querySelector('[data-number-recover]').addEventListener('click',async()=>{
        if(busy) return;busy=true;message.textContent='';loading(true);
        try {
            const result=await api(control.dataset.choicesUrl);choice.replaceChildren();
            const empty=document.createElement('option');empty.value='';empty.textContent='Sélectionner un numéro';choice.append(empty);
            options.replaceChildren();
            result.choices.forEach(item=>{
                const detail=`${item.nature || 'Document'} - Dossier ${item.dossier}`;
                const option=document.createElement('option');option.value=item.key;option.dataset.numero=item.numero;option.dataset.detail=detail;option.textContent=`${item.numero} (${detail})`;choice.append(option);
                const button=document.createElement('button');button.type='button';button.append(document.createTextNode(item.numero+' '));const meta=document.createElement('em');meta.textContent=`(${detail})`;button.append(meta);
                button.addEventListener('click',()=>{choice.value=item.key;choice.dispatchEvent(new Event('change'));options.hidden=true;pickerButton.setAttribute('aria-expanded','false');pickerButton.focus();});options.append(button);
            });
            pickerLabel();options.hidden=true;pickerButton.setAttribute('aria-expanded','false');
            confirm.disabled=true;message.textContent=result.choices.length ? '' : 'Aucun numéro de même nature trouvé pour les dossiers accessibles.';loading(false);dialog.showModal();
        } catch(error) {message.textContent=error.message;}
        finally {busy=false;loading(false);}
    });
    choice.addEventListener('change',()=>{confirm.disabled=!choice.value;pickerLabel();});
    confirm.addEventListener('click',()=>{if(choice.value) select('recover',choice.value);});
    control.querySelector('[data-number-cancel]').addEventListener('click',()=>{if(!busy) dialog.close();});
    dialog.addEventListener('cancel',event=>{if(busy) event.preventDefault();});
});

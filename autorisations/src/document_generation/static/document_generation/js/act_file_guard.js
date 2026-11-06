document.addEventListener('DOMContentLoaded', () => {
    const config=document.querySelector('[data-act-history-guard]');
    if(!config) return;
    const badge=document.querySelector('[data-act-repair-count]');
    const forms=[...new Set([...document.querySelectorAll('input[name="piece_jointe_work"]')].map(input=>input.closest('form')).filter(Boolean))];
    const guards=forms.map(form=>{
        const fieldset=document.createElement('fieldset');fieldset.className='act-history-guard-fields';
        while(form.firstChild) fieldset.append(form.firstChild);
        const notice=document.createElement('div');notice.className='act-history-guard-notice';notice.setAttribute('role','status');
        const message=document.createElement('p');
        const repair=document.createElement('a');repair.href=config.dataset.repairUrl;repair.textContent='Réparer les fichiers générés';
        notice.append(message,repair);form.append(notice,fieldset);
        const guard={form,fieldset,notice,message,blocked:true,historyBlocked:true};
        form.addEventListener('submit',event=>{if(guard.blocked){event.preventDefault();event.stopImmediatePropagation();}},true);
        return guard;
    });
    let recognized=[];
    guards.forEach(guard=>{
        const selection=guard.form.querySelector('[name="piece_jointe_work"]');
        const nature=guard.form.querySelector('[name="nature_document"]');
        const box=selection.closest('.projet_acte_pj');
        if(!box || !nature) return;
        box.classList.add('generated-act-selection-layout');
        const info=document.createElement('p');info.className='generated-act-provenance';info.hidden=true;info.setAttribute('role','status');box.append(info);
        const replacement=document.createElement('label');replacement.className='generated-act-replacement';replacement.hidden=true;
        const consent=document.createElement('input');consent.type='checkbox';
        const consentText=document.createElement('span');replacement.append(consent,consentText);box.append(replacement);
        const replaceId=document.createElement('input');replaceId.type='hidden';replaceId.name='generated_act_replace_id';box.append(replaceId);
        let replacementKey='';
        const shared=guard.form.querySelector('.projet-acte-identique-option');
        const saved=new Map(),buttons=new Map();
        guard.updateProvenance=()=>{
            const selected=recognized.filter(item=>item.filename.toLocaleLowerCase()===selection.value.toLocaleLowerCase());
            const ready=Boolean(selection.value && nature.value);
            const mismatch=ready && selected.length>0 && (selected.length!==1 || String(selected[0].nature_id)!==nature.value);
            const match=ready && selected.length===1 && !mismatch;
            const previous=match ? recognized.filter(item=>item.active && item.document_id!==selected[0].document_id && String(item.nature_id)===nature.value && item.numero===selected[0].numero) : [];
            const key=match && previous.length===1 ? `${selected[0].document_id}:${previous[0].document_id}` : '';
            if(key!==replacementKey){consent.checked=false;replacementKey=key;}
            replacement.hidden=!key || !previous[0]?.replaceable;
            consentText.textContent=key ? `Remplacer « ${previous[0].filename} » par cette version en conservant le même numéro. L’ancien fichier et son historique seront conservés.` : '';
            replaceId.value=key && consent.checked && previous[0].replaceable ? String(previous[0].document_id) : '';
            const replacementBlocked=previous.length>0 && (previous.length!==1 || !previous[0].replaceable || !consent.checked);
            info.hidden=!match && !mismatch;
            info.classList.toggle('is-mismatch',mismatch);
            info.textContent=mismatch ? `Ce fichier a été généré pour une autre nature (${selected[0].nature || 'nature différente'}). Choisissez la même nature ou un autre fichier.` : match ? selected[0].description : '';
            if(match && previous.length && !previous[0].replaceable) {info.hidden=false;info.textContent='Le projet précédent est encore dans le circuit ou a été diffusé. Son remplacement est bloqué.';info.classList.add('is-mismatch');}
            guard.blocked=guard.historyBlocked || mismatch || replacementBlocked;
            guard.form.querySelectorAll('button[type="submit"],button.btn-envoyer-complement').forEach(button=>{
                if((mismatch || replacementBlocked) && !buttons.has(button)) buttons.set(button,button.disabled);
                if(mismatch || replacementBlocked) button.disabled=true;
                else if(buttons.has(button)){button.disabled=buttons.get(button);buttons.delete(button);}
            });
            if(shared) {
                shared.hidden=match;
                shared.querySelectorAll('input,select,textarea,button').forEach(input=>{
                    if(match) {
                        if(!saved.has(input)) saved.set(input,{disabled:input.disabled,required:input.required});
                        input.disabled=true;input.required=false;
                    } else if(saved.has(input)) {
                        const previous=saved.get(input);input.disabled=previous.disabled;input.required=previous.required;saved.delete(input);
                    }
                });
            }
        };
        guard.form.addEventListener('click',()=>queueMicrotask(guard.updateProvenance));
        guard.form.addEventListener('change',guard.updateProvenance);
    });
    function show(blocked,message) {
        guards.forEach(guard=>{
            guard.historyBlocked=blocked;guard.blocked=blocked;guard.fieldset.disabled=blocked;guard.fieldset.hidden=blocked;guard.notice.hidden=!blocked;guard.message.textContent=message;
            guard.updateProvenance?.();
        });
    }
    let pending=false;
    async function refresh() {
        if(pending) return;
        pending=true;show(true,'Vérification des fichiers générés en cours…');
        const abort=new AbortController(),timeout=setTimeout(()=>abort.abort(),20000);
        try {
            const response=await fetch(config.dataset.statusUrl,{credentials:'same-origin',cache:'no-store',signal:abort.signal});
            if(!response.ok) throw new Error('Vérification indisponible');
            const result=await response.json();
            if(typeof result.missing!=='number' || typeof result.unknown!=='number' || typeof result.blocked!=='boolean') throw new Error('Réponse invalide');
            recognized=result.recognized_files || [];
            guards.forEach(guard=>guard.updateProvenance?.());
            badge.hidden=!result.missing && !result.unknown;
            badge.textContent=result.missing || '!';
            badge.title=result.missing ? `${result.missing} fichier(s) généré(s) à réparer` : 'Vérification des fichiers générés impossible';
            badge.setAttribute('aria-label',badge.title);
            show(result.blocked,result.unknown
                ? 'Vérification des fichiers générés impossible. Vérifiez l’accès au NAS puis actualisez la page.'
                : 'Des fichiers générés sont introuvables. Retrouvez-les ou supprimez-les de l’historique avant de sélectionner un projet d’acte.');
        } catch(error) {
            badge.hidden=false;badge.textContent='!';badge.title='Vérification des fichiers générés impossible';badge.setAttribute('aria-label',badge.title);
            show(true,'Vérification des fichiers générés impossible. Vérifiez l’accès au NAS et à l’historique, puis actualisez la page.');
        } finally {clearTimeout(timeout);pending=false;}
    }
    refresh();
    window.addEventListener('pageshow',event=>{if(event.persisted) refresh();});
});

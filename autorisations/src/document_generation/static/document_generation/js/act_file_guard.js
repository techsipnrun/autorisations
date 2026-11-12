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
    let recognized=[],reportFiles=[],historyReady=false;
    const numberHelp=document.createElement('div');
    numberHelp.className='prepared-number-help';numberHelp.id='prepared-number-help';numberHelp.setAttribute('role','tooltip');numberHelp.hidden=true;document.body.append(numberHelp);
    let helpTarget=null;
    function showNumberHelp(event) {
        const button=event.target.closest?.('[data-blocked-nature]');
        if(!button?.dataset.numberHelp) {numberHelp.hidden=true;helpTarget=null;return;}
        helpTarget=button;numberHelp.textContent=button.dataset.numberHelp;numberHelp.hidden=false;
        const rect=button.getBoundingClientRect();
        const menu=button.closest('.act-nature-options')?.getBoundingClientRect() || rect;
        const beside=menu.right+12+numberHelp.offsetWidth<=innerWidth-8;
        numberHelp.style.left=(beside ? menu.right+12 : Math.max(8,Math.min(rect.left,innerWidth-numberHelp.offsetWidth-8)))+'px';
        numberHelp.style.top=Math.max(8,Math.min(beside ? rect.top : rect.bottom+6,innerHeight-numberHelp.offsetHeight-8))+'px';
    }
    document.addEventListener('pointerover',showNumberHelp);
    document.addEventListener('focusin',showNumberHelp);
    document.addEventListener('focusout',()=>{numberHelp.hidden=true;});
    document.addEventListener('pointerout',event=>{if(helpTarget && !helpTarget.contains(event.relatedTarget)){numberHelp.hidden=true;helpTarget=null;}});
    window.addEventListener('resize',()=>{numberHelp.hidden=true;});
    window.addEventListener('scroll',()=>{numberHelp.hidden=true;},true);
    const naturePickers=new Map();
    forms.forEach((form,index)=>{
        const select=form.querySelector('select[name="nature_document"]');
        if(!select) return;
        const picker=document.createElement('div');picker.className='act-nature-picker';
        const trigger=document.createElement('button');trigger.type='button';trigger.className='act-nature-trigger';
        trigger.setAttribute('aria-haspopup','listbox');trigger.setAttribute('aria-expanded','false');
        const list=document.createElement('div');list.className='act-nature-options';list.id=`act-nature-options-${index}`;list.hidden=true;list.setAttribute('role','listbox');list.setAttribute('aria-label','Nature du projet d’acte');
        trigger.setAttribute('aria-controls',list.id);
        select.classList.add('act-nature-native');select.tabIndex=-1;select.setAttribute('aria-hidden','true');
        select.after(picker);picker.append(trigger,list);
        function close(){list.hidden=true;trigger.setAttribute('aria-expanded','false');numberHelp.hidden=true;}
        function render(){
            trigger.textContent=select.selectedOptions[0]?.textContent.trim() || 'Choisir une nature';trigger.disabled=select.disabled;
            list.replaceChildren();
            for(const option of select.options) {
                if(!option.value) continue;
                const item=document.createElement('button');item.type='button';item.className='act-nature-option';item.textContent=option.textContent.trim();
                item.setAttribute('role','option');item.setAttribute('aria-selected',String(select.value===option.value));item.setAttribute('aria-disabled',String(option.disabled));
                if(option.disabled && option.dataset.numberHelp) {item.dataset.blockedNature='';item.dataset.numberHelp=option.dataset.numberHelp;item.setAttribute('aria-describedby',numberHelp.id);}
                item.addEventListener('click',()=>{if(option.disabled)return;select.value=option.value;select.dispatchEvent(new Event('change',{bubbles:true}));render();close();trigger.focus();});
                list.append(item);
            }
            if(select.disabled) close();
        }
        trigger.addEventListener('click',()=>{list.hidden=!list.hidden;trigger.setAttribute('aria-expanded',String(!list.hidden));});
        picker.addEventListener('keydown',event=>{
            if(event.key==='Escape'){event.preventDefault();close();trigger.focus();}
            if(event.key==='ArrowDown' || event.key==='ArrowUp') {
                event.preventDefault();list.hidden=false;trigger.setAttribute('aria-expanded','true');
                const items=[...list.children],current=items.indexOf(document.activeElement);
                items[(current+(event.key==='ArrowDown'?1:items.length-1)+items.length)%items.length]?.focus();
            }
        });
        document.addEventListener('click',event=>{if(!picker.contains(event.target))close();});
        select.addEventListener('change',render);
        select.addEventListener('invalid',event=>{event.preventDefault();trigger.focus();list.hidden=false;trigger.setAttribute('aria-expanded','true');});
        new MutationObserver(render).observe(select,{attributes:true,attributeFilter:['disabled']});
        naturePickers.set(select,render);
    });
    function updateNumberActions() {
        const reason="Pour sélectionner cette nature, vous devez d’abord disposer d’un numéro. Vous pouvez soit le réserver dans « Préparer un projet d’acte » (circuit manuel), soit l’obtenir en générant un fichier.";
        forms.forEach(form=>{
            const select=form.querySelector('select[name="nature_document"]');
            if(!select) return;
            for(const option of select.options) {
                if(!option.value) continue;
                const prepared=form.dataset.reservedPreparationNumber && form.dataset.reservedPreparationNature===option.value;
                const generated=historyReady && recognized.some(item=>item.numero && String(item.nature_id)===option.value);
                const unavailable=!prepared && !generated;
                if(!Object.hasOwn(option.dataset,'numberOriginalDisabled')) option.dataset.numberOriginalDisabled=String(option.disabled);
                option.disabled=unavailable || option.dataset.numberOriginalDisabled==='true';
                option.removeAttribute('title');
                option.dataset.numberHelp=unavailable ? reason : '';
            }
            delete select.dataset.numberHelp;select.removeAttribute('aria-describedby');
            naturePickers.get(select)?.();
        });
        const available=forms.some(form=>[...(form.querySelector('select[name="nature_document"]')?.options || [])].some(option=>option.value && !option.disabled));
        document.querySelectorAll('[data-requires-numbered-nature]').forEach(button=>{
            if(button.hasAttribute('data-no-draft-advice')) {
                button.disabled=true;button.dataset.blockedNature='';
                button.dataset.numberHelp='Aucun avis au statut « Brouillon » à faire valider pour ce dossier.';
                button.removeAttribute('title');button.setAttribute('aria-describedby',numberHelp.id);
                return;
            }
            button.disabled=!available;
            if(available) {delete button.dataset.blockedNature;delete button.dataset.numberHelp;button.removeAttribute('aria-describedby');}
            else {button.dataset.blockedNature='';button.dataset.numberHelp='Pour continuer, vous devez d’abord disposer d’un numéro. Vous pouvez soit le réserver dans « Préparer un projet d’acte » (circuit manuel), soit l’obtenir en générant un fichier.';button.setAttribute('aria-describedby',numberHelp.id);}
        });
        numberHelp.hidden=true;
    }
    document.addEventListener('manual-act-preparation-updated',()=>updateNumberActions());
    updateNumberActions();
    guards.forEach(guard=>{
        const selection=guard.form.querySelector('[name="piece_jointe_work"]');
        const nature=guard.form.querySelector('[name="nature_document"]');
        const box=selection.closest('.projet_acte_pj');
        if(!box || !nature) return;
        box.classList.add('generated-act-selection-layout');
        const info=document.createElement('p');info.className='generated-act-provenance';info.hidden=true;info.setAttribute('role','status');box.append(info);
        const alignProvenance=()=>{
            const list=box.querySelector('.liste-work-files'),files=box.querySelector('.selection-fichier-work');
            if(!list || !files || info.hidden) return;
            const beside=info.getBoundingClientRect().left>=files.getBoundingClientRect().right;
            const margin=beside ? Math.max(0,list.getBoundingClientRect().top-files.getBoundingClientRect().top+parseFloat(getComputedStyle(files).marginTop || 0)) : 0;
            info.style.marginTop=`${margin}px`;
        };
        new ResizeObserver(alignProvenance).observe(box);
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
            const manualReminder=ready && !selected.length && Boolean(guard.form.dataset.manualPreparationNumber);
            const wrongPreparedNumber=Boolean(match && guard.form.dataset.manualPreparationNumber && selected[0].numero!==guard.form.dataset.manualPreparationNumber);
            const previous=match ? recognized.filter(item=>item.active && item.document_id!==selected[0].document_id && String(item.nature_id)===nature.value && item.numero===selected[0].numero) : [];
            const key=match && previous.length===1 ? `${selected[0].document_id}:${previous[0].document_id}` : '';
            if(key!==replacementKey){consent.checked=false;replacementKey=key;}
            replacement.hidden=!key || !previous[0]?.replaceable;
            consentText.textContent=key ? `Remplacer « ${previous[0].filename} » par cette version en conservant le même numéro. L’ancien fichier et son historique seront conservés.` : '';
            replaceId.value=key && consent.checked && previous[0].replaceable ? String(previous[0].document_id) : '';
            const replacementBlocked=previous.length>0 && (previous.length!==1 || !previous[0].replaceable || !consent.checked);
            info.hidden=!match && !mismatch && !manualReminder;
            info.classList.toggle('is-manual-reminder',manualReminder);
            info.classList.toggle('is-mismatch',mismatch || wrongPreparedNumber);
            const provenance=selected[0]?.author && selected[0]?.date ? ` par ${selected[0].author} le ${selected[0].date}` : '';
            const modelNature=selected[0]?.nature || 'nature différente';
            const modelArticle=/^[aeiouyàâéèêëîïôùûüœ]/i.test(modelNature) ? 'd’' : 'de ';
            info.textContent=mismatch ? `Ce fichier a été généré à partir d’un modèle ${modelArticle}${modelNature}${provenance}. La nature du fichier généré doit correspondre à la nature de l’acte sélectionnée plus haut dans le formulaire.` : match ? selected[0].description : '';
            if(wrongPreparedNumber) info.textContent='Ce fichier généré ne porte pas le numéro réservé. Choisissez le bon projet ou annulez la réservation du numéro.';
            if(manualReminder) {
                const number=document.createElement('strong');
                number.textContent=guard.form.dataset.manualPreparationDisplay || guard.form.dataset.manualPreparationNumber;
                info.replaceChildren(document.createTextNode('Avez-vous bien pensé à insérer le numéro '),number,document.createTextNode(' dans votre projet d’acte ?'));
            }
            requestAnimationFrame(alignProvenance);
            if(match && previous.length && !previous[0].replaceable) {info.hidden=false;info.textContent='Le projet précédent est encore dans le circuit ou a été diffusé. Son remplacement est bloqué.';info.classList.add('is-mismatch');}
            const report=guard.form.querySelector('[name="piece_jointe_rapport_ca_work"]');
            report?.closest('.projet_rapport_ca_pj')?.querySelectorAll('.liste-work-files button').forEach(button=>{
                const wrong=reportFiles.some(item=>item.filename.toLocaleLowerCase()===button.textContent.trim().toLocaleLowerCase() && !item.is_report);
                if(wrong){button.disabled=true;button.dataset.reportNatureDisabled='true';button.title='Ce fichier généré n’est pas de nature Rapport CA.';}
                else if(button.dataset.reportNatureDisabled){button.disabled=false;delete button.dataset.reportNatureDisabled;button.removeAttribute('title');}
            });
            const wrongReport=Boolean(report?.value && reportFiles.some(item=>item.filename.toLocaleLowerCase()===report.value.toLocaleLowerCase() && !item.is_report));
            let reportInfo=guard.form.querySelector('[data-report-nature-error]');
            if(report && !reportInfo){reportInfo=document.createElement('p');reportInfo.dataset.reportNatureError='';reportInfo.className='generated-act-provenance is-mismatch';reportInfo.setAttribute('role','alert');report.closest('.projet_rapport_ca_pj').append(reportInfo);}
            if(reportInfo){reportInfo.hidden=!wrongReport;reportInfo.textContent='Ce fichier a été généré pour une autre nature. Choisissez un fichier généré à partir d’un modèle de nature Rapport CA, ou un rapport rédigé manuellement.';}
            guard.blocked=guard.historyBlocked || mismatch || replacementBlocked || wrongReport || wrongPreparedNumber;
            guard.form.querySelectorAll('button[type="submit"],button.btn-envoyer-complement').forEach(button=>{
                if((mismatch || replacementBlocked || wrongReport || wrongPreparedNumber) && !buttons.has(button)) buttons.set(button,button.disabled);
                if(mismatch || replacementBlocked || wrongReport || wrongPreparedNumber) button.disabled=true;
                else if(buttons.has(button)){button.disabled=buttons.get(button);buttons.delete(button);}
            });
            if(shared) {
                const manual=Boolean(guard.form.dataset.manualPreparation);
                const hideShared=!ready || match || mismatch || manual;
                shared.hidden=hideShared;
                shared.querySelectorAll('input,select,textarea,button').forEach(input=>{
                    if(hideShared) {
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
            historyReady=!result.blocked;
            updateNumberActions();
            reportFiles=result.generated_report_files || [];
            guards.forEach(guard=>guard.updateProvenance?.());
            badge.hidden=!result.missing && !result.unknown;
            badge.textContent=result.missing || '!';
            badge.title=result.missing ? `${result.missing} fichier(s) généré(s) à réparer` : 'Vérification des fichiers générés impossible';
            badge.setAttribute('aria-label',badge.title);
            show(result.blocked,result.unknown
                ? 'Vérification des fichiers générés impossible. Vérifiez l’accès au NAS puis actualisez la page.'
                : 'Des fichiers générés sont introuvables. Retrouvez-les ou supprimez-les de l’historique avant de sélectionner un projet d’acte.');
        } catch(error) {
            historyReady=false;updateNumberActions();
            badge.hidden=false;badge.textContent='!';badge.title='Vérification des fichiers générés impossible';badge.setAttribute('aria-label',badge.title);
            show(true,'Vérification des fichiers générés impossible. Vérifiez l’accès au NAS et à l’historique, puis actualisez la page.');
        } finally {clearTimeout(timeout);pending=false;}
    }
    refresh();
    window.addEventListener('pageshow',event=>{if(event.persisted) refresh();});
});

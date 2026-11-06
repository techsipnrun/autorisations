document.addEventListener('DOMContentLoaded', () => {
    const panel=document.querySelector('[data-generation-history]');if(!panel) return;
    const dialog=panel.querySelector('[data-history-dialog]'),form=panel.querySelector('[data-history-relink-form]');
    const choice=form.elements.file,message=panel.querySelector('[data-history-message]'),dialogMessage=panel.querySelector('[data-dialog-message]');
    let currentRow=null,busy=false;
    const syncSubmit=()=>{form.querySelector('[type=submit]').disabled=busy || choice.disabled || !choice.value;};
    const folderLabel=panel.querySelector('[data-history-folder-label]');
    choice.addEventListener('change',()=>{
        syncSubmit();
        if(choice.value) folderLabel.textContent=`Fichiers du dossier ${JSON.parse(choice.value).destination}`;
    });
    const csrf=form.querySelector('[name=csrfmiddlewaretoken]').value;
    async function api(url, data) {
        const response=await fetch(url,{credentials:'same-origin',...(data ? {method:'POST',headers:{'X-CSRFToken':csrf},body:data} : {})});
        if(!response.headers.get('content-type')?.includes('application/json')) throw new Error('Session expirée ou accès refusé. Rechargez la page.');
        const result=await response.json();if(!response.ok) throw new Error(result.error || 'Action impossible.');return result;
    }
    function state(row,value) {
        const needsRepair=value==='missing' && row.dataset.numberedGeneration==='true';
        row.classList.toggle('history-numbered-repair',needsRepair);
        const repair=row.querySelector('[data-numbered-repair]');if(repair) repair.hidden=!needsRepair;
        const target=row.querySelector('[data-file-state]');
        const labels={found:'Fichier trouvé',missing:'Fichier introuvable',unknown:'Vérification impossible : NAS ou emplacement inaccessible'};
        target.className=`history-file-state is-${value}`;target.setAttribute('aria-label',labels[value]);target.title=labels[value];
        target.innerHTML=value==='found' ? '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" aria-hidden="true"><path d="m5 12 4 4L19 6"/></svg>'
            : value==='missing' ? '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" aria-hidden="true"><path d="m6 6 12 12M6 18 18 6"/></svg>' : '—';
        row.querySelector('[data-missing-actions]').hidden=value!=='missing';
        row.querySelector('a[download]').hidden=value==='missing';
    }
    async function check() {
        try {
            const result=await api(panel.dataset.statusUrl);
            const states=new Map(result.files.map(item=>[String(item.id),item.state]));
            panel.querySelectorAll('[data-generation-id]').forEach(row=>state(row,states.get(row.dataset.generationId) || 'unknown'));
        } catch(error) {
            panel.querySelectorAll('[data-generation-id]').forEach(row=>state(row,'unknown'));message.textContent=error.message;
        }
    }
    panel.addEventListener('click',async event=>{
        const remove=event.target.closest('[data-remove-history]'),find=event.target.closest('[data-find-file]');
        if((!remove && !find) || busy) return;
        const row=event.target.closest('[data-generation-id]');message.textContent='';
        if(remove) {
            if(!window.confirm('Supprimer cette génération de fichier de l’historique ?')) return;
            busy=true;remove.disabled=true;
            try {
                const result=await api(row.dataset.removeUrl,new FormData());row.remove();message.textContent=result.message;
                if(!panel.querySelector('[data-generation-id]')) panel.remove();
            } catch(error) {message.textContent=error.message;await check();}
            finally {busy=false;remove.disabled=false;}
        } else {
            folderLabel.textContent=`Fichiers du dossier ${row.querySelector('[data-history-destination]').textContent}`;
            currentRow=row;choice.replaceChildren();choice.disabled=true;
            form.querySelector('[type=submit]').disabled=true;dialogMessage.textContent='Recherche des fichiers…';dialog.showModal();
            try {
                const result=await api(row.dataset.choicesUrl);
                if(currentRow!==row || !dialog.open) return;
                const empty=document.createElement('option');empty.value='';empty.textContent='Sélectionner un fichier';choice.append(empty);
                const errors=[];
                for(const folder of result.folders) {
                    for(const filename of folder.files) {
                        const option=document.createElement('option');option.value=JSON.stringify({destination:folder.destination,filename});option.textContent=filename;choice.append(option);
                    }
                    if(folder.error) errors.push(`${folder.destination} : ${folder.error}`);
                }
                choice.disabled=false;syncSubmit();
                dialogMessage.textContent=[choice.options.length<2 ? 'Aucun fichier Word disponible.' : '',...errors].filter(Boolean).join(' ');
            } catch(error) {dialogMessage.textContent=error.message;}
        }
    });
    panel.querySelector('[data-history-cancel]').addEventListener('click',()=>{if(!busy) dialog.close();});
    dialog.addEventListener('cancel',event=>{if(busy) event.preventDefault();});
    form.addEventListener('submit',async event=>{
        event.preventDefault();if(busy || !choice.value) return;
        const selected=JSON.parse(choice.value),data=new FormData();data.set('filename',selected.filename);data.set('destination',selected.destination);
        if(!window.confirm(`Associer le fichier « ${selected.filename} » à cette génération ? `)) return;
        busy=true;choice.disabled=true;form.querySelectorAll('button').forEach(button=>{button.disabled=true;});dialogMessage.textContent='Vérification et association…';
        try {
            const result=await api(currentRow.dataset.relinkUrl,data);
            currentRow.querySelector('[data-history-filename]').textContent=result.filename;
            currentRow.querySelector('[data-history-destination]').textContent=result.destination;
            const download=currentRow.querySelector('a[download]');download.title=`Télécharger ${result.filename}`;download.setAttribute('aria-label',download.title);
            state(currentRow,'found');message.textContent=result.message;dialog.close();
        } catch(error) {dialogMessage.textContent=error.message;}
        finally {busy=false;choice.disabled=false;form.querySelectorAll('button').forEach(button=>{button.disabled=false;});syncSubmit();}
    });
    check();
});

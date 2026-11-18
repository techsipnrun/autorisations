(() => {
    const workspace=document.querySelector('.generation-workspace');
    if(!workspace?.querySelector('.docx-preview-panel')) return;
    const handle=document.createElement('div');
    handle.className='generation-splitter';handle.tabIndex=0;
    handle.setAttribute('role','separator');handle.setAttribute('aria-orientation','vertical');
    handle.setAttribute('aria-label','Répartir la largeur entre le formulaire et l’aperçu');
    handle.setAttribute('aria-valuemin','25');handle.setAttribute('aria-valuemax','75');
    workspace.append(handle);
    let ratio=50,dragging=false;
    function update(value=ratio) {
        ratio=Math.max(25,Math.min(75,value));
        workspace.style.setProperty('--generation-left',`${ratio}fr`);
        workspace.style.setProperty('--generation-right',`${100-ratio}fr`);
        const gap=parseFloat(getComputedStyle(workspace).columnGap) || 0;
        handle.style.left=`${(workspace.clientWidth-gap)*ratio/100+gap/2}px`;
        handle.setAttribute('aria-valuenow',String(Math.round(ratio)));
        handle.setAttribute('aria-valuetext',`Formulaire ${Math.round(ratio)} %, aperçu ${100-Math.round(ratio)} %`);
    }
    function move(event) {
        const rect=workspace.getBoundingClientRect(),gap=parseFloat(getComputedStyle(workspace).columnGap) || 0;
        update((event.clientX-rect.left-gap/2)/(rect.width-gap)*100);
    }
    handle.addEventListener('pointerdown',event=>{
        if(event.button!==0) return;
        event.preventDefault();dragging=true;handle.setPointerCapture(event.pointerId);
        workspace.classList.add('is-resizing');move(event);
    });
    handle.addEventListener('pointermove',event=>{if(dragging) move(event);});
    const stop=()=>{dragging=false;workspace.classList.remove('is-resizing');};
    handle.addEventListener('pointerup',stop);handle.addEventListener('pointercancel',stop);handle.addEventListener('lostpointercapture',stop);
    handle.addEventListener('dblclick',()=>update(50));
    handle.addEventListener('keydown',event=>{
        const values={ArrowLeft:ratio-2,ArrowRight:ratio+2,Home:25,End:75};
        if(event.key in values) {event.preventDefault();update(values[event.key]);}
    });
    new ResizeObserver(()=>update()).observe(workspace);
    update();
})();

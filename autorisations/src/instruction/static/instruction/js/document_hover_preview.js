document.addEventListener("DOMContentLoaded", () => {
    let activeContainer = null;
    const script=document.querySelector('script[data-docx-url][data-jszip-url]');
    let wordLibraries;
    function loadScript(url) {
        return new Promise((resolve,reject)=>{
            if(!url) {reject(new Error('Bibliothèque d’aperçu indisponible.'));return;}
            const asset=document.createElement('script');asset.src=url;
            asset.onload=resolve;asset.onerror=()=>{asset.remove();reject(new Error('Chargement de l’aperçu Word impossible.'));};
            document.head.append(asset);
        });
    }
    function loadWordLibraries() {
        if(window.docx?.renderAsync && window.JSZip) return Promise.resolve();
        if(!wordLibraries) wordLibraries=(window.JSZip ? Promise.resolve() : loadScript(script?.dataset.jszipUrl))
            .then(()=>window.docx?.renderAsync ? undefined : loadScript(script?.dataset.docxUrl))
            .catch(error=>{wordLibraries=null;throw error;});
        return wordLibraries;
    }
    async function renderWord(url,popover) {
        const [response]=await Promise.all([fetch(url,{credentials:'same-origin',signal:AbortSignal.timeout(20000)}),loadWordLibraries()]);
        if(!response.ok) throw new Error(`HTTP ${response.status}`);
        const blob=await response.blob();
        const frame=document.createElement('iframe');frame.className='document-apercu-contenu';frame.title='Aperçu Word';
        frame.setAttribute('sandbox','allow-same-origin');
        const ready=new Promise(resolve=>frame.addEventListener('load',resolve,{once:true}));
        frame.srcdoc=`<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data: blob:; font-src data: blob:; style-src 'unsafe-inline'"><style>body{margin:0;background:#edf0ee} .docx-wrapper{padding:12px!important}</style></head><body><div id="word"></div></body></html>`;
        popover.replaceChildren(frame);
        await ready;
        const host=frame.contentDocument.getElementById('word');
        await window.docx.renderAsync(blob,host,null,{useBase64URL:true,renderAltChunks:false,ignoreLastRenderedPageBreak:false});
        await frame.contentDocument.fonts.ready;
        const fit=()=>{
            const width=Math.max(0,...[...host.querySelectorAll('section.docx')].map(page=>page.offsetWidth))+24;
            if(width>24) {host.style.width=width+'px';host.style.zoom=String(Math.min(1,frame.contentDocument.documentElement.clientWidth/width));}
        };
        new ResizeObserver(fit).observe(frame);fit();
    }

    const closePreview = (container) => {
        if (!container) return;
        container.classList.remove("is-preview-open");
        container.querySelector(".document-apercu-trigger")?.setAttribute("aria-expanded", "false");
        delete container.dataset.apercuOuvertParClic;
        if (activeContainer === container) activeContainer = null;
    };

    const positionPreview = (trigger, popover, bridge) => {
        const margin = 12;
        const navbar = document.querySelector(".navigation_header");
        const topLimit = Math.max(margin, (navbar?.getBoundingClientRect().bottom || 0) + margin);
        const availableHeight = Math.max(0, window.innerHeight - topLimit - margin);
        const previewHeight = Math.min(650, window.innerHeight * 0.7, availableHeight);

        popover.style.height = `${previewHeight}px`;
        popover.style.maxHeight = `${availableHeight}px`;

        const triggerRect = trigger.getBoundingClientRect();
        const popoverRect = popover.getBoundingClientRect();

        let left = triggerRect.right + margin;
        if (left + popoverRect.width > window.innerWidth - margin) {
            left = triggerRect.left - popoverRect.width - margin;
        }

        left = Math.max(margin, Math.min(left, window.innerWidth - popoverRect.width - margin));

        let top = triggerRect.top + triggerRect.height / 2 - popoverRect.height / 2;
        top = Math.max(topLimit, Math.min(top, window.innerHeight - popoverRect.height - margin));

        popover.style.left = `${left}px`;
        popover.style.top = `${top}px`;

        if (bridge) {
            const popoverLeft = left;
            const popoverRight = left + popoverRect.width;
            const previewIsRight = popoverLeft >= triggerRect.right;
            const bridgeLeft = previewIsRight ? triggerRect.right : popoverRight;
            const bridgeRight = previewIsRight ? popoverLeft : triggerRect.left;

            bridge.style.left = `${bridgeLeft}px`;
            bridge.style.top = `${triggerRect.top - 10}px`;
            bridge.style.width = `${Math.max(0, bridgeRight - bridgeLeft)}px`;
            bridge.style.height = `${triggerRect.height + 20}px`;
        }
    };

    const triggersInitialises = new WeakSet();

    const initialiserApercuDocument = (trigger) => {
        if (!trigger || triggersInitialises.has(trigger)) return;
        triggersInitialises.add(trigger);

        const container = trigger.closest(".document-avec-apercu");
        const popover = container?.querySelector(".document-apercu-popover");
        const bridge = container?.querySelector(".document-apercu-pont");
        const correctionButton = container?.querySelector(".remplacer-acte-toggle");
        let previewLoaded = false;
        let previewLoading = false;
        let closeTimeout = null;

        const cancelScheduledClose = () => {
            if (!closeTimeout) return;
            clearTimeout(closeTimeout);
            closeTimeout = null;
        };

        const scheduleClose = () => {
            cancelScheduledClose();
            closeTimeout = setTimeout(() => {
                const sourisDansLeScope = (
                    container.matches(":hover")
                    || bridge?.matches(":hover")
                    || popover.matches(":hover")
                );

                if (!sourisDansLeScope) closePreview(container);
            }, 250);
        };

        const loadPreview = async () => {
            if (previewLoaded || previewLoading || !popover) return;
            previewLoading=true;

            const previewUrl = trigger.dataset.previewUrl;
            const previewType = trigger.dataset.previewType;
            let previewElement;

            try {
                if(previewType === 'docx') {
                    await renderWord(previewUrl,popover);
                    previewLoaded=true;
                    return;
                }
                if (previewType === "pdf") {
                    const response = await fetch(previewUrl, {
                        credentials: "same-origin",
                        cache: "no-store"
                    });

                    if (!response.ok) throw new Error(`HTTP ${response.status}`);

                    const pdfBlob = await response.blob();
                    previewElement = document.createElement("embed");
                    previewElement.src = URL.createObjectURL(pdfBlob);
                    previewElement.type = "application/pdf";
                    previewElement.title = "Aperçu PDF";
                } else {
                    previewElement = document.createElement("img");
                    // Réduire les grandes images sans agrandir les petites.
                    previewElement.style.objectFit = "scale-down";
                    previewElement.src = previewUrl;
                    previewElement.alt = "Aperçu du document";
                }

                previewElement.className = "document-apercu-contenu";
                popover.replaceChildren(previewElement);
                previewLoaded = true;
            } catch (error) {
                const message = document.createElement("span");
                message.className = "document-apercu-erreur";
                message.textContent = "L’aperçu ne peut pas être chargé.";
                popover.replaceChildren(message);
                console.error("Erreur de chargement de l’aperçu :", error);
            } finally {
                previewLoading=false;
            }
        };

        const openPreview = () => {
            if (!container || !popover) return;
            cancelScheduledClose();

            if (activeContainer && activeContainer !== container) {
                closePreview(activeContainer);
            }

            activeContainer = container;
            container.classList.add("is-preview-open");
            trigger.setAttribute("aria-expanded", "true");
            loadPreview();
            requestAnimationFrame(() => {
                requestAnimationFrame(() => positionPreview(trigger, popover, bridge));
            });
        };

        trigger.addEventListener("click", () => {
            if (
                container.classList.contains("is-preview-open")
                && container.dataset.apercuOuvertParClic === "true"
            ) {
                closePreview(container);
                return;
            }

            container.dataset.apercuOuvertParClic = "true";
            openPreview();
        });

        const closeFromCorrection = () => {
            closePreview(container);
        };
        correctionButton?.addEventListener("mouseenter", closeFromCorrection);
        correctionButton?.addEventListener("focus", closeFromCorrection);

        container.addEventListener("mouseenter", cancelScheduledClose);
        container.addEventListener("mouseleave", scheduleClose);
        bridge?.addEventListener("mouseenter", cancelScheduledClose);
        bridge?.addEventListener("mouseleave", scheduleClose);
        popover.addEventListener("mouseenter", cancelScheduledClose);
        popover.addEventListener("mouseleave", scheduleClose);
        container.addEventListener("focusout", (event) => {
            if (!container.contains(event.relatedTarget)) scheduleClose();
        });
    };

    window.initialiserApercuDocument = initialiserApercuDocument;
    window.fermerApercuDocument = () => closePreview(activeContainer);
    document.querySelectorAll(".document-apercu-trigger").forEach(initialiserApercuDocument);

    window.addEventListener("resize", () => {
        if (!activeContainer) return;
        const trigger = activeContainer.querySelector(".document-apercu-trigger");
        const popover = activeContainer.querySelector(".document-apercu-popover");
        const bridge = activeContainer.querySelector(".document-apercu-pont");
        if (trigger && popover) positionPreview(trigger, popover, bridge);
    });

    window.addEventListener("scroll", () => {
        if (!activeContainer) return;
        const trigger = activeContainer.querySelector(".document-apercu-trigger");
        const popover = activeContainer.querySelector(".document-apercu-popover");
        const bridge = activeContainer.querySelector(".document-apercu-pont");
        if (trigger && popover) positionPreview(trigger, popover, bridge);
    }, { passive: true });

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") closePreview(activeContainer);
    });
});

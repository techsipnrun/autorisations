(() => {
    const panel = document.querySelector('[data-docx-preview]');
    const form = document.getElementById('generation-form');
    if (!panel || !form) return;
    let libraries;
    let viewer;
    const toolbar = document.createElement('div');
    toolbar.className = 'docx-preview-toolbar';
    toolbar.hidden = true;
    toolbar.setAttribute('role', 'group');
    toolbar.setAttribute('aria-label', 'Navigation et zoom de l’aperçu Word');
    const icon = paths => `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true">${paths}</svg>`;
    const rotateIcon = icon('<path d="M3 10a9 9 0 1 1 2 8M3 4v6h6"/><path d="m10 10 5-2 3 7-5 2z"/>');
    const printIcon = icon('<path d="M7 8V3h10v5M7 17H4V9h16v8h-3"/><path d="M7 14h10v7H7zM16 11h1"/>');
    toolbar.innerHTML = `<div class="docx-page-controls">
        <button type="button" data-docx-previous title="Page précédente" aria-label="Page précédente">${icon('<path d="m14 6-6 6 6 6"/>')}</button>
        <input type="number" data-docx-page min="1" value="1" aria-label="Numéro de page">
        <span data-docx-total></span>
        <button type="button" data-docx-next title="Page suivante" aria-label="Page suivante">${icon('<path d="m10 6 6 6-6 6"/>')}</button>
        </div><div class="docx-zoom-controls">
        <button type="button" data-docx-minus title="Réduire le zoom" aria-label="Réduire le zoom">−</button>
        <label class="docx-zoom-value"><input type="text" inputmode="decimal" data-docx-zoom value="100" aria-label="Zoom en pourcentage" title="Zoom de 25 à 200 %"><span>%</span></label>
        <button type="button" data-docx-plus title="Augmenter le zoom" aria-label="Augmenter le zoom">+</button>
        </div><div class="docx-view-actions">
        <button type="button" data-docx-rotate title="Pivoter vers la gauche" aria-label="Pivoter vers la gauche">${rotateIcon}</button>
        <button type="button" data-docx-download title="Télécharger cet aperçu en PDF" aria-label="Télécharger le PDF">${icon('<path d="M12 3v12m-5-5 5 5 5-5M5 16v5h14v-5"/>')}</button>
        <button type="button" data-docx-print title="Imprimer" aria-label="Imprimer">${printIcon}</button>
        <div class="docx-options">
        <button type="button" data-docx-options aria-label="Options de l’aperçu" title="Options" aria-expanded="false" aria-controls="docx-options-menu">${icon('<circle cx="12" cy="5" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="12" cy="19" r="1"/>')}</button>
        <div id="docx-options-menu" class="docx-options-menu" hidden>
        <button type="button" data-docx-fit>Ajuster la largeur</button>
        <button type="button" data-docx-fit-page>Ajuster la page</button>
        <button type="button" data-docx-two-pages aria-pressed="false">Vue sur 2 pages</button>
        </div></div></div>`;
    panel.insertBefore(toolbar, panel.querySelector('.docx-preview-viewport') || panel.querySelector('[data-docx-preview-content]'));
    const pageInput = toolbar.querySelector('[data-docx-page]');
    const zoomInput = toolbar.querySelector('[data-docx-zoom]');
    const downloadButton = toolbar.querySelector('[data-docx-download]');
    let exporting = false, exportLibraries;
    downloadButton.onclick = async () => {
        if (!viewer || running || exporting) return;
        exporting = true;
        downloadButton.disabled = true;
        const source = viewer;
        const errorBox = panel.querySelector('[data-docx-preview-error]');
        const label = loader.querySelector('span');
        const previousLabel = label?.textContent;
        loader.hidden = false;
        panel.setAttribute('aria-busy', 'true');
        errorBox.hidden = true;
        try {
            if (!window.html2canvas || !window.jspdf?.jsPDF) {
                if (!exportLibraries) exportLibraries = Promise.all([
                    loadScript(panel.dataset.canvasUrl), loadScript(panel.dataset.pdfLibraryUrl),
                ]).catch(error => { exportLibraries = null; throw error; });
                await exportLibraries;
            }
            let pdf;
            for (let index = 0; index < source.pages.length; index++) {
                if (label) label.textContent = `Export PDF : page ${index + 1} / ${source.pages.length}`;
                const {width, height} = source.sizes[index];
                const canvas = await window.html2canvas(source.pages[index], {
                    backgroundColor: '#fff', logging: false,
                    scale: Math.min(2, Math.sqrt(8000000 / (width * height))),
                    width, height, scrollX: 0, scrollY: 0,
                    onclone: doc => {
                        doc.body.style.zoom = '1';
                        const wrapper = doc.querySelector('.docx-wrapper');
                        wrapper.style.cssText = 'display:block;width:max-content;padding:0;margin:0;zoom:1;background:white';
                        doc.querySelectorAll('.docx-view-sheet').forEach((sheet, i) => {
                            sheet.style.cssText = `width:${source.sizes[i].width}px;height:${source.sizes[i].height}px;margin:0;position:relative;`;
                            const page = sheet.querySelector('section.docx');
                            page.style.transform = 'none'; page.style.boxShadow = 'none';
                        });
                    },
                });
                try {
                    const format = [width * .75, height * .75];
                    const orientation = width > height ? 'landscape' : 'portrait';
                    if (!pdf) pdf = new window.jspdf.jsPDF({unit: 'pt', format, orientation, compress: true});
                    else pdf.addPage(format, orientation);
                    pdf.addImage(canvas, 'PNG', 0, 0, format[0], format[1], undefined, 'FAST');
                } finally { canvas.width = 0; canvas.height = 0; }
                // Laisser le navigateur afficher la progression entre les pages.
                await new Promise(resolve => setTimeout(resolve, 0));
            }
            pdf.save(panel.dataset.pdfFilename || 'apercu.pdf');
        } catch (error) {
            errorBox.textContent = 'Impossible de télécharger l’aperçu en PDF. Réessayez.';
            errorBox.hidden = false;
        } finally {
            exporting = false;
            downloadButton.disabled = false;
            loader.hidden = true;
            if (label) label.textContent = previousLabel;
            panel.removeAttribute('aria-busy');
            if (pending || snapshot() !== lastRendered) {
                pending = false;
                clearTimeout(timer);
                timer = setTimeout(renderPreview, 650);
            }
        }
    };
    const options = toolbar.querySelector('.docx-options-menu');
    const optionsButton = toolbar.querySelector('[data-docx-options]');
    function closeOptions() { options.hidden = true; optionsButton.setAttribute('aria-expanded', 'false'); }
    optionsButton.onclick = () => {
        options.hidden = !options.hidden;
        optionsButton.setAttribute('aria-expanded', String(!options.hidden));
        if (!options.hidden) options.querySelector('button').focus();
    };
    document.addEventListener('pointerdown', event => { if (!event.target.closest('.docx-options')) closeOptions(); });
    toolbar.addEventListener('keydown', event => {
        if (event.key === 'Escape') { closeOptions(); optionsButton.focus(); }
    });
    options.addEventListener('focusout', event => { if (!options.contains(event.relatedTarget) && event.relatedTarget !== optionsButton) closeOptions(); });
    function spreadRect(index) {
        const first = viewer.twoPages ? index - index % 2 : index;
        const left = viewer.sheets[first].getBoundingClientRect();
        const right = viewer.twoPages && viewer.sheets[first + 1] ? viewer.sheets[first + 1].getBoundingClientRect() : left;
        return {left: left.left, top: left.top, width: right.right - left.left, height: Math.max(left.height, right.height)};
    }
    function layoutWidth() {
        const widths = viewer.sheets.map(sheet => parseFloat(sheet.style.width));
        if (!viewer.twoPages) return Math.max(...widths);
        return Math.max(...widths.filter((_, index) => index % 2 === 0)) + Math.max(0, ...widths.filter((_, index) => index % 2 === 1)) + 24;
    }
    function goToPage(number) {
        if (!viewer) return;
        let index = Math.max(0, Math.min(viewer.pages.length - 1, Math.round(Number(number) || 1) - 1));
        if (viewer.twoPages) index -= index % 2;
        const win = viewer.frame.contentWindow;
        const rect = spreadRect(index);
        win.scrollTo({top: rect.top + win.scrollY - 16,
            left: Math.max(0, rect.left + win.scrollX + (rect.width - viewer.frame.contentDocument.documentElement.clientWidth) / 2)});
        updatePage();
    }
    function updatePage() {
        if (!viewer) return;
        let index = 0;
        viewer.sheets.forEach((page, i) => {
            if (viewer.twoPages && i % 2) return;
            if (page.getBoundingClientRect().top <= viewer.frame.clientHeight / 3) index = i;
        });
        viewer.page = index + 1;
        if (document.activeElement !== pageInput) pageInput.value = viewer.page;
        toolbar.querySelector('[data-docx-previous]').disabled = index === 0;
        toolbar.querySelector('[data-docx-next]').disabled = index + (viewer.twoPages ? 2 : 1) >= viewer.pages.length;
    }
    function setZoom(value, fit = false) {
        if (!viewer) return;
        const page = viewer.page;
        viewer.fit = fit;
        viewer.zoom = Math.max(.25, Math.min(2, value));
        const doc = viewer.frame.contentDocument;
        const wrapper = doc.querySelector('.docx-wrapper');
        // Zoomer le contenu, sans réduire la largeur de référence du viewport.
        wrapper.style.zoom = viewer.zoom;
        wrapper.style.width = `${Math.max(doc.documentElement.clientWidth / viewer.zoom, layoutWidth() + 32)}px`;
        zoomInput.value = Math.round(viewer.zoom * 100);
        toolbar.querySelector('[data-docx-minus]').disabled = viewer.zoom <= .25;
        toolbar.querySelector('[data-docx-plus]').disabled = viewer.zoom >= 2;
        toolbar.querySelector('[data-docx-fit]').setAttribute('aria-pressed', String(fit === 'width'));
        toolbar.querySelector('[data-docx-fit-page]').setAttribute('aria-pressed', String(fit === 'page'));
        goToPage(page);
    }
    function fitWidth() {
        if (!viewer) return;
        const width = layoutWidth();
        setZoom((viewer.frame.clientWidth - 48) / width, 'width');
    }
    function fitPage() {
        if (!viewer) return;
        const sheet = spreadRect(viewer.page - 1);
        setZoom(Math.min((viewer.frame.clientWidth - 48) / (sheet.width / viewer.zoom),
            (viewer.frame.clientHeight - 48) / (sheet.height / viewer.zoom)), 'page');
    }
    function rotateLeft() {
        if (!viewer) return;
        const page = viewer.page;
        viewer.rotation = (viewer.rotation + 270) % 360;
        viewer.pages.forEach((element, i) => {
            const {width, height} = viewer.sizes[i];
            const swap = viewer.rotation % 180 !== 0;
            const sheet = viewer.sheets[i];
            sheet.style.width = `${swap ? height : width}px`;
            sheet.style.height = `${swap ? width : height}px`;
            const translation = {0: '0px,0px', 90: `${height}px,0px`, 180: `${width}px,${height}px`, 270: `0px,${width}px`}[viewer.rotation];
            element.style.transformOrigin = 'top left';
            element.style.transform = `translate(${translation}) rotate(${viewer.rotation}deg)`;
        });
        if (viewer.fit === 'width') fitWidth();
        else if (viewer.fit === 'page') fitPage();
        goToPage(page);
    }
    function printDocument() {
        if (!viewer) return;
        closeOptions();
        try { viewer.frame.contentWindow.focus(); viewer.frame.contentWindow.print(); }
        catch { panel.querySelector('[data-docx-preview-error]').textContent = 'Impossible d’ouvrir l’impression. Vérifiez les autorisations de votre navigateur.'; panel.querySelector('[data-docx-preview-error]').hidden = false; }
    }
    toolbar.querySelector('[data-docx-previous]').onclick = () => goToPage(viewer.page - (viewer.twoPages ? 2 : 1));
    toolbar.querySelector('[data-docx-next]').onclick = () => goToPage(viewer.page + (viewer.twoPages ? 2 : 1));
    pageInput.addEventListener('change', () => { goToPage(pageInput.value); pageInput.value = viewer.page; });
    pageInput.addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); pageInput.blur(); } });
    toolbar.querySelector('[data-docx-minus]').onclick = () => setZoom(viewer.zoom - .1);
    toolbar.querySelector('[data-docx-plus]').onclick = () => setZoom(viewer.zoom + .1);
    function applyManualZoom() {
        if (!viewer) return;
        const value = zoomInput.value.trim().replace(/%$/, '').replace(',', '.');
        if (value && Number.isFinite(Number(value))) setZoom(Number(value) / 100);
        else zoomInput.value = Math.round(viewer.zoom * 100);
    }
    zoomInput.addEventListener('change', applyManualZoom);
    zoomInput.addEventListener('blur', applyManualZoom);
    zoomInput.addEventListener('keydown', event => {
        if (event.key === 'Enter') { event.preventDefault(); zoomInput.blur(); }
        if (event.key === 'Escape') { zoomInput.value = Math.round(viewer.zoom * 100); zoomInput.blur(); }
    });
    toolbar.querySelector('[data-docx-fit]').onclick = () => { fitWidth(); closeOptions(); };
    toolbar.querySelector('[data-docx-fit-page]').onclick = () => { fitPage(); closeOptions(); };
    toolbar.querySelector('[data-docx-two-pages]').onclick = () => {
        if (!viewer) return;
        viewer.twoPages = !viewer.twoPages;
        const wrapper = viewer.frame.contentDocument.querySelector('.docx-wrapper');
        wrapper.style.display = viewer.twoPages ? 'grid' : 'flex';
        wrapper.style.gridTemplateColumns = 'max-content max-content';
        wrapper.style.justifyContent = viewer.twoPages ? 'center' : '';
        wrapper.style.alignItems = viewer.twoPages ? 'start' : 'center';
        wrapper.style.gap = viewer.twoPages ? '24px' : '';
        viewer.sheets.forEach(sheet => { sheet.style.margin = viewer.twoPages ? '0' : '0 auto 24px'; });
        toolbar.querySelector('[data-docx-two-pages]').setAttribute('aria-pressed', String(viewer.twoPages));
        fitWidth(); closeOptions();
    };
    toolbar.querySelector('[data-docx-rotate]').onclick = rotateLeft;
    toolbar.querySelector('[data-docx-print]').onclick = printDocument;
    new ResizeObserver(() => { if (viewer?.fit === 'width') fitWidth(); else if (viewer?.fit === 'page') fitPage(); }).observe(panel);
    function attachViewer(frame) {
        const pages = [...frame.contentDocument.querySelectorAll('.docx-wrapper > section.docx')];
        if (!pages.length) throw new Error('Aucune page détectée dans cet aperçu Word.');
        viewer?.frame.contentWindow.removeEventListener('scroll', updatePage);
        const sizes = pages.map(page => ({width: page.offsetWidth, height: page.offsetHeight}));
        const sheets = pages.map((page, i) => {
            const sheet = frame.contentDocument.createElement('div');
            sheet.className = 'docx-view-sheet';
            sheet.style.cssText = `position:relative;width:${sizes[i].width}px;height:${sizes[i].height}px;margin:0 auto 24px;flex-shrink:0;`;
            page.before(sheet); sheet.append(page);
            page.style.margin = '0';
            // Le style blanc du fournisseur ne cible que les enfants directs
            // du wrapper ; nos supports de rotation ajoutent un niveau.
            page.style.backgroundColor = '#fff';
            page.style.boxShadow = '0 1px 6px #0003';
            return sheet;
        });
        viewer = {frame, pages, sheets, sizes, page: 1, zoom: 1, fit: 'width', rotation: 0, twoPages: false};
        toolbar.querySelector('[data-docx-two-pages]').setAttribute('aria-pressed', 'false');
        const wrapper = frame.contentDocument.querySelector('.docx-wrapper');
        wrapper.style.background = '#edf0ee';
        wrapper.style.boxSizing = 'border-box';
        const printStyle = frame.contentDocument.createElement('style');
        printStyle.textContent = '@page {margin:0} @media print { html,body{zoom:1!important;background:white!important;margin:0!important} .docx-wrapper{zoom:1!important;width:auto!important;padding:0!important;background:white!important;display:block!important} .docx-view-sheet{width:auto!important;height:auto!important;margin:0!important;break-after:page} .docx-view-sheet:last-child{break-after:auto} .docx-view-sheet>section.docx{transform:none!important;box-shadow:none!important;margin:0!important;break-after:auto!important} }';
        frame.contentDocument.head.append(printStyle);
        pageInput.max = pages.length;
        pageInput.style.width = `${Math.max(1, String(pages.length).length) + 1}ch`;
        pageInput.value = 1;
        toolbar.querySelector('[data-docx-total]').textContent = `/ ${pages.length}`;
        toolbar.hidden = false;
        frame.contentWindow.addEventListener('scroll', updatePage, {passive: true});
        closeOptions();
        fitWidth();
    }
    function loadScript(url) {
        return new Promise((resolve, reject) => {
            const script = document.createElement('script');
            const timeout = setTimeout(() => { script.remove(); reject(new Error('Le chargement de la bibliothèque a expiré. Réessayez.')); }, 20000);
            script.src = url;
            script.onload = () => { clearTimeout(timeout); resolve(); };
            script.onerror = () => { clearTimeout(timeout); script.remove(); reject(new Error('Impossible de charger la bibliothèque d’aperçu Word.')); };
            document.head.append(script);
        });
    }
    function loadLibraries() {
        if (window.JSZip && window.docx?.renderAsync) return Promise.resolve();
        if (!libraries) libraries = loadScript(panel.dataset.jszipUrl)
            .then(() => loadScript(panel.dataset.rendererUrl))
            .catch(error => { libraries = null; throw error; });
        return libraries;
    }
    let timer, active, running = false, pending = false, version = 0;
    let observed = '', lastRendered = '', changedAt = 0;
    const loader = panel.querySelector('[data-docx-preview-loading]');
    function snapshot() {
        return JSON.stringify([...new FormData(form)].filter(([name]) =>
            name.startsWith('balise_') || name.startsWith('known-balise_') || ['edit_known', 'number_selection'].includes(name)));
    }
    function schedule() {
        const signature = snapshot();
        if (signature === observed) return;
        observed = signature; changedAt = Date.now(); version++;
        clearTimeout(timer); active?.abort();
        if (signature !== lastRendered) timer = setTimeout(renderPreview, 650);
        else panel.querySelector('[data-docx-preview-status]').textContent = '';
    }
    async function renderPreview() {
        if (form.getAttribute('aria-busy') === 'true') return;
        if (running || exporting) { pending = true; return; }
        const signature = snapshot();
        if (signature === lastRendered) return;
        running = true; pending = false;
        downloadButton.disabled = true;
        const currentVersion = version;
        active = new AbortController();
        const timeout = setTimeout(() => active?.abort('timeout'), 60000);
        const content = panel.querySelector('[data-docx-preview-content]');
        const status = panel.querySelector('[data-docx-preview-status]');
        const errorBox = panel.querySelector('[data-docx-preview-error]');
        const data = new FormData(form);
        data.set('action', 'preview_docx');
        let frame;
        panel.setAttribute('aria-busy', 'true');
        loader.hidden = false;
        errorBox.hidden = true;
        try {
            const [response] = await Promise.all([
                // Les contrôles name="action" masquent la propriété form.action.
                fetch(form.getAttribute('action') || location.href, {method: 'POST', body: data, credentials: 'same-origin', cache: 'no-store', signal: active.signal}),
                loadLibraries(),
            ]);
            if (!response.ok) {
                const result = await response.json().catch(() => ({}));
                throw new Error(result.error || 'Impossible de préparer l’aperçu Word. Vérifiez vos informations et votre connexion.');
            }
            if (!response.headers.get('Content-Type')?.includes('application/json')) {
                throw new Error('Votre session a peut-être expiré. Rechargez la page.');
            }
            const result = await response.json();
            if (currentVersion !== version) return;
            if (typeof result.docx !== 'string') throw new Error('Aperçu Word indisponible.');
            const bytes = Uint8Array.from(atob(result.docx), char => char.charCodeAt(0));
            const blob = new Blob([bytes], {type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'});
            const missingBox = panel.querySelector('[data-docx-preview-missing]');
            const list = missingBox.querySelector('ul');
            list.replaceChildren();
            for (const item of result.missing || []) {
                const row = document.createElement('li');
                const label = document.createElement('strong'); label.textContent = item.label;
                row.append(label);
                list.append(row);
            }
            missingBox.hidden = !list.children.length;
            panel.classList.toggle('has-missing-values', Boolean(list.children.length));
            frame = document.createElement('iframe');
            frame.title = 'Aperçu Word du document';
            frame.className = 'document-preview docx-preview-frame';
            // Aucun script ni accès réseau dans le document rendu.
            frame.setAttribute('sandbox', 'allow-same-origin allow-modals');
            const ready = new Promise(resolve => { frame.onload = resolve; });
            frame.srcdoc = '<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data: blob:; font-src data: blob:; style-src \'unsafe-inline\'"><style>body{margin:0;background:#edf0ee} .docx-wrapper{padding:16px!important}</style></head><body></body></html>';
            // Garder le dernier aperçu si le nouveau rendu échoue.
            frame.style.visibility = 'hidden';
            frame.style.position = 'absolute';
            content.append(frame);
            await ready;
            await window.docx.renderAsync(blob, frame.contentDocument.body, null, {
                useBase64URL: true, renderAltChunks: false, ignoreLastRenderedPageBreak: false,
            });
            await frame.contentDocument.fonts.ready;
            if (currentVersion !== version) { frame.remove(); return; }
            attachViewer(frame);
            // Déplacer/réinsérer une iframe réinitialise son document.
            [...content.children].filter(child => child !== frame).forEach(child => child.remove());
            frame.style.visibility = '';
            frame.style.position = '';
            lastRendered = signature;
            status.textContent = '';
        } catch (error) {
            if (frame?.style.visibility === 'hidden') frame.remove();
            if (currentVersion !== version || (active.signal.aborted && active.signal.reason !== 'timeout')) return;
            errorBox.textContent = active.signal.reason === 'timeout' ? 'Le chargement de l’aperçu a expiré. Réessayez.' : (error.message || 'Impossible d’afficher l’aperçu Word.');
            errorBox.hidden = false;
        } finally {
            clearTimeout(timeout);
            if (frame?.style.visibility === 'hidden') frame.remove();
            loader.hidden = true;
            panel.removeAttribute('aria-busy');
            running = false;
            downloadButton.disabled = false;
            if (pending || currentVersion !== version) {
                pending = false;
                clearTimeout(timer);
                if (snapshot() !== lastRendered)
                    timer = setTimeout(renderPreview, Math.max(0, 650 - (Date.now() - changedAt)));
            }
        }
    }
    form.addEventListener('generation-validity', schedule);
    form.addEventListener('input', schedule);
    form.addEventListener('change', schedule);
    window.addEventListener('pagehide', () => { clearTimeout(timer); active?.abort(); });
    schedule();
})();

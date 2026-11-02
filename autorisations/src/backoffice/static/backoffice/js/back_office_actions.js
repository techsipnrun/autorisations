/* Configuration des ensembles d'actions ; aucune exécution métier depuis ce panneau. */
(() => {
    'use strict';
    const root = document.querySelector('[data-actions-office]');
    if (!root) return;
    const $ = selector => root.querySelector(selector);
    const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char]));
    let data = null, loading = false, circuit = 'dn', editing = null, draftOrders = {}, saving = false, dirtyEditor = false, previousStage = '';
    let previousOverflow = '', testVersion = 0, suggestionVersion = 0, suggestionTimer, suggestions = [], resolvedNumber = '';
    const stage = $('[data-actions-etape]');
    const editor = $('[data-actions-editor]');
    const testForm = $('[data-actions-test-form]');
    const scopeKeys = ['id_etape_id', 'present_sur_dn', 'id_demarche_id', 'id_groupe_instructeur_id', 'coeur_de_parc', 'type_manif_sportive'];
    const fieldNames = {id_etape_id: 'Étape', id_demarche_id: 'Démarche', id_groupe_instructeur_id: 'Groupe instructeur',
        present_sur_dn: 'Présence sur DN', coeur_de_parc: 'Cœur de parc', type_manif_sportive: 'Type de dossier sportif'};
    const niveaux = () => data.profils[circuit].niveaux;
    const definition = code => niveaux().find(level => level.code === code);
    const selected = (value, current) => String(value ?? '') === String(current ?? '') ? ' selected' : '';
    const options = (items, current, blank) => `<option value="">${esc(blank)}</option>` + items.map(item => `<option value="${item.id}"${selected(item.id, current)}>${esc(item.nom)}</option>`).join('');
    const name = (items, id, fallback) => items.find(item => item.id === id)?.nom || fallback;

    function status(message, error = false, target = $('[data-actions-status]')) {
        target.textContent = message;
        target.classList.toggle('is-error', error);
    }
    async function api(url, payload) {
        const headers = {Accept: 'application/json'};
        if (payload) {
            headers['Content-Type'] = 'application/json';
            headers['X-CSRFToken'] = document.querySelector('[name=csrfmiddlewaretoken]')?.value || decodeURIComponent(document.cookie.split('; ').find(cookie => cookie.startsWith('csrftoken='))?.split('=')[1] || '');
        }
        const response = await fetch(url, {method: payload ? 'POST' : 'GET', credentials: 'same-origin', headers,
            ...(payload ? {body: JSON.stringify(payload)} : {})});
        let result;
        if (!response.headers.get('content-type')?.includes('application/json')) throw new Error('Réponse inattendue. Vérifiez votre session et reconnectez-vous si nécessaire.');
        try { result = await response.json(); } catch (_) { throw new Error('La réponse du serveur est illisible.'); }
        if (!response.ok || !result.success) throw new Error(result.error || 'La requête n’a pas abouti.');
        return result;
    }
    async function load() {
        if (loading || saving) return;
        loading = true;
        status('Chargement des configurations…');
        try {
            data = await api(root.dataset.catalogueUrl);
            draftOrders = structuredClone(data.ordres);
            updateStageOptions();
            testForm.elements.etape_fictive.innerHTML = options(data.etapes, '', '— Choisir un dossier —');
            renderConfigurations(); renderPriorities(); renderTest();
            status(data.priorites_installees ? '' : 'La table des priorités n’est pas encore installée. Les dossiers continuent d’utiliser l’ordre standard ; l’enregistrement des priorités sera disponible après votre SQL.');
        } catch (error) { status(error.message, true); }
        finally { loading = false; }
    }
    function updateStageOptions() {
        stage.innerHTML = options(data.etapes, stage.value, '— Choisir une étape —');
        if (circuit === 'dm') {
            for (const item of data.etapes) {
                const option = Array.from(stage.options).find(option => option.value === String(item.id));
                option.disabled = !item.disponible_dm;
                if (option.disabled) option.title = 'Aucune règle « Dossier DM » et étape non marquée comme archivage.';
            }
            if (stage.selectedOptions[0]?.disabled) stage.value = '';
        }
        previousStage = stage.value;
    }
    function actionChips(ids) {
        return `<div class="bo-actions-chips">${ids.map(id => `<span class="bo-actions-chip">${esc(name(data.actions, id, `Action n° ${id}`))}</span>`).join('')}</div>`;
    }
    function describe(scope) {
        const parts = [name(data.demarches, scope.id_demarche_id, 'Toutes les démarches'), name(data.groupes, scope.id_groupe_instructeur_id, 'Tous les groupes'), scope.present_sur_dn ? 'Présent sur DN' : 'Absent de DN'];
        if (scope.type_manif_sportive && circuit !== 'dm') parts.push(scope.type_manif_sportive);
        if (scope.coeur_de_parc !== null) parts.push(scope.coeur_de_parc ? 'En cœur de parc' : 'Hors cœur de parc');
        return parts.join(' · ');
    }
    function renderConfigurations() {
        $('[data-actions-ajouter]').disabled = !stage.value;
        const container = $('[data-actions-configurations]');
        if (!stage.value) { container.innerHTML = '<p class="bo-actions-empty">Choisissez une étape pour examiner ses configurations.</p>'; return; }
        const configurations = data.configurations.filter(config => config.scope.id_etape_id === Number(stage.value) && (Object.hasOwn(config.niveaux, circuit) || !Object.keys(config.niveaux).length));
        const codes = [...data.ordres[circuit], null];
        container.innerHTML = codes.map((code, index) => {
            const configs = configurations.filter(config => (config.niveaux[circuit] ?? null) === code);
            if (!configs.length && code === null) return '';
            return `<section class="bo-actions-level"><h2><span class="bo-actions-rank">${code ? index + 1 : '!'}</span>${esc(code ? definition(code).nom : 'Combinaisons non prises en charge')}</h2>` +
                (configs.length ? `<div class="bo-actions-cards">${configs.map(config => `<article class="bo-actions-card"><h3>${esc(describe(config.scope))}</h3>${actionChips(config.actions)}
                    ${config.actions.some(id => { const item = data.actions.find(action => action.id === id); return !item || availability(item, config.scope.id_etape_id); }) ? '<p class="bo-actions-alerte">Certaines actions enregistrées ne sont pas disponibles à cette étape pour ce circuit. Elles restent conservées ; ouvrez la configuration pour les examiner.</p>' : ''}
                    ${code ? `<button type="button" data-actions-modifier="${data.configurations.indexOf(config)}">Modifier</button>` : '<p class="bo-actions-warning">Cette combinaison ne correspond à aucun niveau du circuit. Elle n’a pas été modifiée.</p>'}</article>`).join('')}</div>` : '<p class="bo-actions-empty">Aucune configuration enregistrée pour ce niveau à cette étape.</p>') + '</section>';
        }).join('');
    }
    function renderPriorities() {
        renderCommonCriteria();
        $('[data-actions-priorites]').innerHTML = draftOrders[circuit].map((code, index, array) => `<div class="bo-actions-priority"><span class="bo-actions-rank">${index + 1}</span><div class="bo-actions-priority-description"><strong>${esc(definition(code).nom)}</strong>${definition(code).champs.length ? `<small>Critères spécifiques obligatoires : ${definition(code).champs.map(key => esc(fieldNames[key])).join(' · ')}</small>` : '<small>Aucun critère spécifique : configuration générale.</small>'}</div>
            <button type="button" data-actions-move="${index}" data-direction="-1" aria-label="Monter ${esc(definition(code).nom)}" ${index === 0 ? 'disabled' : ''}>↑</button>
            <button type="button" data-actions-move="${index}" data-direction="1" aria-label="Descendre ${esc(definition(code).nom)}" ${index === array.length - 1 ? 'disabled' : ''}>↓</button></div>`).join('');
        $('[data-actions-enregistrer-priorites]').disabled = !data.priorites_installees;
    }
    function renderCommonCriteria() {
        const notice = $('[data-actions-common]');
        notice.hidden = !['configurations', 'priorites'].some(tab => $(`[data-actions-tab="${tab}"]`).getAttribute('aria-pressed') === 'true');
        notice.textContent = `Critères communs obligatoires : Étape · Présence sur DN${circuit === 'dm' ? ' (Non) · Démarche (manifestations sportives)' : ''}`;
    }
    function availability(item, etape) {
        if (!item.disponibles?.[circuit]?.includes(Number(etape))) return 'Aucun composant d’action n’est implémenté sur l’écran de cette étape.';
        return '';
    }
    function renderConfigurationActions(config) {
        return data.actions.map(item => {
            const checked = config?.actions.includes(item.id);
            const reason = availability(item, config?.scope.id_etape_id || stage.value);
            return `<label data-action-label class="${reason ? 'is-unavailable' : ''}"><input type="checkbox" name="action" value="${item.id}" ${checked ? 'checked' : ''} ${reason && !checked ? 'disabled' : ''} ${reason ? 'data-action-unavailable' : ''}>
                <span>${esc(item.nom)}${reason ? `<small>${esc(reason)}${checked ? ' Déjà configurée : vous pouvez la décocher pour la retirer.' : ''}</small>` : ''}</span></label>`;
        }).join('');
    }
    function scopeDetails(scope, resultCircuit, configuration = false) {
        const rows = [
            ['Étape', name(data.etapes, scope.id_etape_id, 'Étape inconnue')],
            ['Démarche', name(data.demarches, scope.id_demarche_id, configuration ? 'Toutes les démarches' : 'Non renseignée')],
        ];
        if (resultCircuit !== 'dm') rows.push(['Groupe instructeur', name(data.groupes, scope.id_groupe_instructeur_id, configuration ? 'Tous les groupes' : 'Aucun groupe affecté')]);
        rows.push(['Présence sur DN', scope.present_sur_dn ? 'Oui' : 'Non']);
        if (resultCircuit !== 'dn') {
            rows.push(['Type de dossier', scope.type_manif_sportive || (configuration ? 'Tous les types' : 'Non renseigné')]);
            rows.push(['Cœur de parc', scope.coeur_de_parc === null ? (configuration ? 'Sans précision' : 'Non renseigné') : scope.coeur_de_parc ? 'Oui' : 'Non']);
        }
        return `<dl class="bo-actions-context">${rows.map(([label, value]) => `<dt>${esc(label)}</dt><dd>${esc(value)}</dd>`).join('')}</dl>`;
    }
    function selectField(key, value, {required = false, blank = '---', items, allowNone = false} = {}) {
        let content;
        if (key === 'present_sur_dn') content = `<option value="true"${selected(true, value)}>Présent sur DN</option><option value="false"${selected(false, value)}>Absent de DN</option>`;
        else if (key === 'coeur_de_parc') content = `<option value="">${esc(blank)}</option>${allowNone ? '<option value="__aucun__">Non renseigné</option>' : ''}<option value="true"${selected(true, value)}>En cœur de parc</option><option value="false"${selected(false, value)}>Hors cœur de parc</option>`;
        else if (key === 'type_manif_sportive') {
            const types = circuit === 'dm' ? ['Dossier DM'] : ['Dossier DN', 'Dossier complet'];
            content = `<option value="">${esc(blank)}</option>${types.map(type => `<option${selected(type, value)}>${esc(type)}</option>`).join('')}`;
        } else {
            const choices = items || (key === 'id_etape_id' ? data.etapes : key === 'id_groupe_instructeur_id' ? data.groupes : data.demarches.filter(item => item.sportif === (circuit !== 'dn')));
            content = options(choices, value, blank);
            if (allowNone && key === 'id_groupe_instructeur_id') content += '<option value="__aucun__">Aucun groupe instructeur</option>';
        }
        return `<label><span class="bo-actions-field-caption">${esc(fieldNames[key])}<span class="bo-actions-field-required"${required ? '' : ' hidden'}> *</span></span><select name="${key}" ${required ? 'required' : ''}>${content}</select></label>`;
    }
    function readScope(form) {
        const result = {};
        scopeKeys.forEach(key => {
            const value = form.elements[key]?.value ?? '';
            result[key] = value === '' || value === '__aucun__' ? null : ['present_sur_dn', 'coeur_de_parc'].includes(key) ? value === 'true' : key.endsWith('_id') ? Number(value) : value;
        });
        return result;
    }
    function blankScope() {
        return {id_etape_id: Number(stage.value), id_demarche_id: null, id_groupe_instructeur_id: null,
            present_sur_dn: circuit !== 'dm', coeur_de_parc: null, type_manif_sportive: null};
    }
    function closeEditor() {
        if (editor.open) { editor.close(); document.body.style.overflow = previousOverflow; }
        editing = null; dirtyEditor = false; editor.hidden = true; editor.replaceChildren();
    }
    function requestCloseEditor() {
        if (saving || !dirtyEditor || confirm('Abandonner les modifications non enregistrées ?')) closeEditor();
    }
    function positionEditor() {
        const main = root.closest('.back-office-content');
        const left = Math.max(0, main?.getBoundingClientRect().left || 0);
        editor.style.setProperty('--actions-modal-left', `${Math.min(left, innerWidth - 1)}px`);
    }
    function lockConfigurationFields(form) {
        form.elements.id_etape_id.disabled = true;
        form.elements.id_demarche_id.disabled = circuit === 'dm';
        form.elements.type_manif_sportive.disabled = circuit === 'dm';
        if (circuit === 'dm') {
            form.elements.type_manif_sportive.title = 'Type imposé par le circuit « Dossiers DM seuls ».';
            form.elements.id_demarche_id.title = 'Démarche manifestations sportives imposée par ce circuit.';
            if (form.elements.id_demarche_id.required) {
                form.elements.id_demarche_id.value = data.demarches.find(item => item.sportif)?.id ?? '';
            }
        }
    }
    function openEditor(config = null) {
        if (dirtyEditor && !confirm('Abandonner les modifications de la configuration en cours ?')) return;
        dirtyEditor = false;
        editing = config;
        const scope = config ? {...config.scope} : blankScope();
        const level = config?.niveaux[circuit] || data.ordres[circuit][0];
        editor.innerHTML = `<section class="bo-actions-modal-card"><header class="bo-actions-modal-heading"><h2 id="bo-actions-editor-title">${config ? 'Modifier la configuration' : 'Ajouter une configuration'}</h2><button type="button" class="bo-actions-modal-close" data-actions-fermer aria-label="Fermer la fenêtre">×</button></header><form data-actions-edit-form>
            <div class="bo-actions-grid"><label><span>Niveau de configuration <span class="bo-actions-field-required">*</span></span><select name="niveau" required>${niveaux().map(item => `<option value="${item.code}"${selected(item.code, level)}>${esc(item.nom)}</option>`).join('')}</select></label>
            ${scopeKeys.map(key => selectField(key, scope[key], {required: key === 'id_etape_id'})).join('')}</div>
            <p class="bo-actions-help" data-actions-scope-help></p>
            <h3>Actions proposées</h3>
            <p class="bo-actions-help">Sélectionnez le jeu complet d’actions de ce contexte, pas seulement ses exceptions. Vous utilisez ici les actions métier existantes ; leurs formulaires et leurs droits restent inchangés.</p>
            <label>Rechercher une action<input type="search" data-actions-recherche placeholder="Filtrer les actions…"></label>
            <div class="bo-actions-checks">${renderConfigurationActions(config)}</div>
            <p data-actions-editor-status role="status"></p><div class="bo-actions-toolbar"><button type="button" data-actions-annuler>Annuler</button>
            ${config ? '<button type="button" class="bo-actions-danger" data-actions-supprimer>Supprimer cette configuration</button>' : ''}
            <button type="submit" class="bo-actions-primary">Enregistrer la configuration</button></div></form></section>`;
        const form = $('[data-actions-edit-form]');
        function updateFields() {
            const fields = definition(form.elements.niveau.value).champs;
            scopeKeys.forEach(key => {
                const input = form.elements[key];
                const permitted = key === 'id_etape_id' || key === 'present_sur_dn' || fields.includes(key);
                input.closest('label').hidden = !permitted;
                input.required = key === 'id_etape_id' || key === 'present_sur_dn' || fields.includes(key);
                input.closest('label').querySelector('.bo-actions-field-required').hidden = !input.required;
                if (!permitted) input.value = '';
            });
            if (circuit === 'dm') { form.elements.present_sur_dn.value = 'false'; form.elements.present_sur_dn.closest('label').hidden = true; }
            if (fields.includes('type_manif_sportive') && circuit === 'dm') form.elements.type_manif_sportive.value = 'Dossier DM';
            lockConfigurationFields(form);
            $('[data-actions-scope-help]').textContent = circuit === 'dm' && form.elements.niveau.value === 'general'
                ? 'Configuration générale réservée aux dossiers DM seuls : le type « Dossier DM » est renseigné automatiquement.'
                : fields.length ? 'Les critères masqués sont laissés sans précision, comme prévu par ce niveau.' : 'Configuration générale : elle peut être utilisée par plusieurs circuits DN. Vérifiez les dossiers concernés avant de modifier.';
        }
        form.elements.niveau.addEventListener('change', updateFields);
        form.elements.id_etape_id.title = 'Étape sélectionnée dans « Étape à examiner ».';
        updateFields(); editor.hidden = false;
        positionEditor();
        if (!editor.open) { previousOverflow = document.body.style.overflow; editor.showModal(); document.body.style.overflow = 'hidden'; }
        form.elements.niveau.focus({preventScroll: true});
    }
    function renderTest() {
        const prior = testForm.querySelector('[data-actions-test-fictif]');
        const scope = {id_etape_id: Number(stage.value) || null, id_demarche_id: circuit === 'dn' ? null : data.demarches.find(item => item.sportif)?.id,
            id_groupe_instructeur_id: null, present_sur_dn: circuit !== 'dm', coeur_de_parc: null, type_manif_sportive: circuit === 'dm' ? 'Dossier DM' : circuit === 'sportif' ? 'Dossier DN' : null};
        prior.innerHTML = scopeKeys.map(key => selectField(key, scope[key], {required: true, blank: '— Choisir —', allowNone: true})).join('');
        if (circuit === 'dn') ['coeur_de_parc', 'type_manif_sportive'].forEach(key => { testForm.elements[key].closest('label').hidden = true; });
        if (circuit === 'dm') ['present_sur_dn', 'id_groupe_instructeur_id', 'type_manif_sportive'].forEach(key => { testForm.elements[key].closest('label').hidden = true; });
        clearSuggestions(); testForm.elements.numero.value = ''; testForm.elements.etape_fictive.value = '';
        updateTestMode();
    }
    function resetResult() {
        testVersion++;
        const result = $('[data-actions-resultat]');
        result.classList.remove('is-error');
        result.innerHTML = '<p class="bo-actions-empty">Aucun dossier ne sera modifié. Lancez le test pour examiner la sélection.</p>';
    }
    function updateTestMode() {
        const existing = testForm.elements.mode.value === 'dossier';
        $('[data-actions-test-dossier]').hidden = !existing;
        $('[data-actions-test-fictif]').hidden = existing;
        testForm.elements.numero.required = existing;
        testForm.elements.etape_fictive.required = existing;
        testForm.querySelectorAll('[data-actions-test-fictif] select').forEach(input => {
            input.required = !existing && !input.closest('label').hidden;
        });
        resetResult();
    }
    function clearSuggestions() {
        clearTimeout(suggestionTimer); suggestionVersion++;
        suggestions = []; resolvedNumber = '';
        $('#bo-actions-dossiers').replaceChildren();
        status('', false, $('[data-actions-dossier-status]'));
    }
    function applySuggestion(query) {
        const dossier = suggestions.find(item => item.numero === query);
        if (!dossier) return false;
        if (resolvedNumber !== query) {
            const select = testForm.elements.etape_fictive;
            if (![...select.options].some(option => option.value === String(dossier.etape))) select.add(new Option(dossier.etape_nom, dossier.etape));
            select.value = String(dossier.etape);
            resolvedNumber = query;
        }
        status(`Étape actuelle : ${dossier.etape_nom}`, false, $('[data-actions-dossier-status]'));
        return true;
    }
    function suggestDossiers() {
        const query = testForm.elements.numero.value.trim();
        clearTimeout(suggestionTimer);
        const version = ++suggestionVersion;
        resetResult();
        if (applySuggestion(query)) return;
        resolvedNumber = ''; testForm.elements.etape_fictive.value = '';
        if (!/^\d{1,15}$/.test(query)) { clearSuggestions(); return; }
        status('Recherche du dossier…', false, $('[data-actions-dossier-status]'));
        const selectedCircuit = circuit;
        suggestionTimer = setTimeout(async () => {
            try {
                const url = new URL(root.dataset.dossiersUrl, location.href);
                url.searchParams.set('circuit', selectedCircuit); url.searchParams.set('q', query);
                const result = await api(url);
                if (version !== suggestionVersion || circuit !== selectedCircuit) return;
                suggestions = result.dossiers;
                $('#bo-actions-dossiers').innerHTML = suggestions.map(item => `<option value="${esc(item.numero)}">${esc([item.nom, item.etape_nom].filter(Boolean).join(' · '))}</option>`).join('');
                if (!applySuggestion(query)) status(suggestions.length ? 'Sélectionnez un numéro proposé pour récupérer son étape.' : 'Aucun dossier trouvé dans ce circuit.', false, $('[data-actions-dossier-status]'));
            } catch (error) {
                if (version === suggestionVersion) status(error.message, true, $('[data-actions-dossier-status]'));
            }
        }, 180);
    }
    root.addEventListener('click', async event => {
        const button = event.target.closest('button');
        if (!button) return;
        if (button.hasAttribute('data-actions-fermer')) { requestCloseEditor(); return; }
        if (saving) return;
        if (!data) return;
        if (button.dataset.actionsTab) {
            root.querySelectorAll('[data-actions-tab]').forEach(item => item.setAttribute('aria-pressed', String(item === button)));
            root.querySelectorAll('[data-actions-page]').forEach(page => { page.hidden = page.dataset.actionsPage !== button.dataset.actionsTab; });
            renderCommonCriteria();
        }
        if (button.hasAttribute('data-actions-ajouter')) openEditor();
        if (button.hasAttribute('data-actions-modifier')) openEditor(data.configurations[Number(button.dataset.actionsModifier)]);
        if (button.hasAttribute('data-actions-annuler')) requestCloseEditor();
        if (button.hasAttribute('data-actions-move')) {
            const index = Number(button.dataset.actionsMove), target = index + Number(button.dataset.direction);
            const order = draftOrders[circuit];
            [order[index], order[target]] = [order[target], order[index]];
            renderPriorities(); status('Ordre modifié localement. Cliquez sur « Enregistrer les priorités » pour l’appliquer.');
        }
        if (button.hasAttribute('data-actions-standard')) { draftOrders[circuit] = niveaux().map(item => item.code); renderPriorities(); status('Ordre standard préparé. Enregistrez pour l’appliquer.'); }
        if (button.hasAttribute('data-actions-enregistrer-priorites')) {
            if (!confirm('Appliquer cet ordre de priorité à tous les dossiers de ce circuit ? Les niveaux généraux placés en premier peuvent masquer les configurations spécifiques.')) return;
            saving = true; button.disabled = true;
            try { await api(root.dataset.prioritesUrl, {circuit, ordre: draftOrders[circuit], original: data.ordres[circuit]}); saving = false; await load(); status('Priorités enregistrées.'); }
            catch (error) { status(error.message, true); }
            finally { saving = false; button.disabled = false; }
        }
        if (button.hasAttribute('data-actions-supprimer')) {
            if (confirm('Supprimer toutes les actions de cette configuration ? Un niveau de priorité inférieur pourra alors devenir applicable.')) await saveConfiguration(true);
        }
    });
    async function saveConfiguration(remove = false) {
        const form = $('[data-actions-edit-form]');
        if (!remove && !form.reportValidity()) return;
        const payload = {circuit, scope: readScope(form), original: editing ? {scope: editing.scope, signature: editing.signature} : null,
            actions: [...form.querySelectorAll('[name=action]:checked')].map(input => Number(input.value)), supprimer: remove};
        if (remove) payload.scope = editing.scope;
        saving = true;
        form.querySelectorAll('input,select,button').forEach(control => { control.disabled = true; });
        const message = $('[data-actions-editor-status]'); status('Enregistrement…', false, message);
        try {
            await api(root.dataset.configurationUrl, payload);
            stage.value = String(payload.scope.id_etape_id); closeEditor(); saving = false; await load();
            status(remove ? 'Configuration supprimée.' : 'Configuration enregistrée. Les formulaires et les permissions n’ont pas changé.');
        } catch (error) { status(error.message, true, editor.open ? message : $('[data-actions-status]')); }
        finally { saving = false; form.querySelectorAll('input,select,button').forEach(control => { control.disabled = control.hasAttribute('data-action-unavailable') && !control.checked; }); lockConfigurationFields(form); }
    }
    root.addEventListener('submit', async event => {
        if (event.target.matches('[data-actions-edit-form]')) { event.preventDefault(); if (!saving) await saveConfiguration(); }
        if (!event.target.matches('[data-actions-test-form]')) return;
        event.preventDefault();
        if (saving) return;
        const payload = {circuit};
        if (testForm.elements.mode.value === 'dossier') { payload.numero = testForm.elements.numero.value; payload.etape_fictive = Number(testForm.elements.etape_fictive.value) || null; }
        else payload.contexte = readScope(testForm);
        const button = testForm.querySelector('[type=submit]'); button.disabled = true;
        const version = ++testVersion;
        try {
            const result = await api(root.dataset.testerUrl, payload);
            if (version !== testVersion) return;
            const win = result.niveau_retenu;
            $('[data-actions-resultat]').classList.remove('is-error');
            const statuses = {retenue: 'Retenu : premier niveau contenant des règles', ecartee: 'Écarté : un niveau précédent est retenu', absente: 'Aucune règle correspondante', inapplicable: 'Inapplicable : un critère nécessaire n’est pas renseigné'};
            $('[data-actions-resultat]').innerHTML = `<div class="bo-actions-card"><h2>${win ? `Configuration retenue — Priorité ${win.priorite} · ${esc(win.nom)}` : 'Aucune configuration retenue'}</h2>
                <section class="bo-actions-result-section" data-actions-tested-context><h3>${payload.numero ? `Contexte testé · dossier n° ${esc(payload.numero)}` : 'Contexte fictif testé'}</h3>
                <p class="bo-actions-help"><strong>Circuit :</strong> ${esc(data.profils[result.circuit].nom)}</p>${scopeDetails(result.contexte, result.circuit)}</section>
                ${win && result.configuration_retenue ? `<section class="bo-actions-result-section" data-actions-retained-configuration><h3>Critères de la configuration retenue</h3>${scopeDetails(result.configuration_retenue, result.circuit, true)}</section>` : ''}
                <section class="bo-actions-result-section"><h3>Actions proposées</h3>
                <div class="bo-actions-chips">${result.actions.map(label => `<span class="bo-actions-chip">${esc(label)}</span>`).join('') || 'Aucune action proposée par les règles.'}</div></section></div>` +
                (result.actions_incompatibles?.length ? `<section class="bo-actions-warning"><h3>Actions sélectionnées par les règles, mais non disponibles</h3>${result.actions_incompatibles.map(item => `<p><strong>${esc(item.nom)}</strong> : ${esc(item.raison)}</p>`).join('')}</section>` : '') +
                result.niveaux.map(item => `<article class="bo-actions-trace ${item.statut === 'retenue' ? 'is-winner' : ''}"><strong>${item.priorite}. ${esc(item.nom)}</strong><p>${esc(statuses[item.statut])}</p>
                    <div class="bo-actions-chips">${item.actions.map(label => `<span class="bo-actions-chip">${esc(label)}</span>`).join('')}</div></article>`).join('');
        } catch (error) { if (version === testVersion) status(error.message, true, $('[data-actions-resultat]')); }
        finally { button.disabled = false; }
    });
    root.addEventListener('input', event => {
        if (event.target.closest('[data-actions-edit-form]') && !event.target.hasAttribute('data-actions-recherche')) dirtyEditor = true;
        if (!event.target.hasAttribute('data-actions-recherche')) return;
        const query = event.target.value.toLocaleLowerCase('fr');
        editor.querySelectorAll('[data-action-label]').forEach(label => { label.hidden = !label.textContent.toLocaleLowerCase('fr').includes(query); });
    });
    editor.addEventListener('change', event => { dirtyEditor = true; if (event.target.hasAttribute('data-action-unavailable') && !event.target.checked) event.target.disabled = true; });
    editor.addEventListener('cancel', event => { event.preventDefault(); requestCloseEditor(); });
    editor.addEventListener('click', event => { if (event.target === editor) requestCloseEditor(); });
    window.addEventListener('resize', positionEditor);
    stage.addEventListener('change', () => {
        if (dirtyEditor && !confirm('Changer d’étape et abandonner les modifications non enregistrées ?')) { stage.value = previousStage; return; }
        closeEditor(); previousStage = stage.value; if (data) renderConfigurations();
    });
    $('[data-actions-circuit]').addEventListener('change', event => {
        if (dirtyEditor && !confirm('Changer de circuit et abandonner les modifications non enregistrées ?')) { event.target.value = circuit; return; }
        closeEditor(); circuit = event.target.value;
        if (data) { updateStageOptions(); renderConfigurations(); renderPriorities(); renderTest(); }
    });
    testForm.elements.mode.addEventListener('change', updateTestMode);
    testForm.elements.numero.addEventListener('input', suggestDossiers);
    testForm.elements.numero.addEventListener('change', suggestDossiers);
    window.addEventListener('beforeunload', event => {
        const dirtyPriorities = data && Object.keys(draftOrders).some(code => JSON.stringify(draftOrders[code]) !== JSON.stringify(data.ordres[code]));
        if (!saving && (dirtyEditor || dirtyPriorities)) { event.preventDefault(); event.returnValue = ''; }
    });
    const panel = root.closest('[data-panel]');
    const observer = new MutationObserver(() => { if (!panel.hidden && !data && !loading) load(); });
    observer.observe(panel, {attributes: true, attributeFilter: ['hidden']});
    if (!panel.hidden) load();
})();

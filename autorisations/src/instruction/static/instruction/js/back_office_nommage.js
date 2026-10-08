(() => {
    'use strict';

    document.querySelectorAll('[data-nommage]').forEach(form => {
        const config = JSON.parse(document.getElementById(form.dataset.configId).textContent);
        let rules = config.regles.map(rule => ({
            ...rule,
            elements: rule.elements.map(element => ({...element, _customExpanded: false})),
            _expanded: false,
        }));
        let dirty = false;
        let busy = false;
        let autocompleteTimer = null;
        let autocompleteController = null;
        const list = form.querySelector('[data-nommage-rules]');
        const status = form.querySelector('[data-nommage-status]');
        const result = form.querySelector('[data-nommage-result]');
        const recalculate = form.querySelector('[data-nommage-recalculate]');
        const saveFeedback = form.querySelector('[data-nommage-save-feedback]');
        const numberInput = form.querySelector('[data-nommage-number]');
        const numberSuggestions = form.querySelector('[data-nommage-numbers]');
        const fields = new Map(config.champs.map(field => [field.id, field]));
        const fieldsDm = new Map((config.champs_dm || []).map(field => [field.name, field]));
        const savedRules = new WeakMap();
        const ruleCards = new Map();
        let savedPayload;
        const info = form.closest('.back-office-nommage-block')?.querySelector('.bo-nommage-info');
        if (info) {
            info.addEventListener('click', event => event.preventDefault());
            info.addEventListener('keydown', event => {
                if (event.key === 'Enter' || event.key === ' ') event.preventDefault();
            });
        }

        function node(tag, className, text) {
            const element = document.createElement(tag);
            if (className) element.className = className;
            if (text !== undefined) element.textContent = text;
            return element;
        }

        function button(text, title, action, disabled = false) {
            const element = node('button', '', text);
            element.type = 'button';
            element.title = title;
            element.setAttribute('aria-label', title);
            element.disabled = disabled;
            element.addEventListener('click', action);
            return element;
        }

        function duplicateIcon() {
            const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
            svg.setAttribute('viewBox', '3 3 17 19');
            svg.setAttribute('aria-hidden', 'true');
            const back = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
            back.setAttribute('x', '8');
            back.setAttribute('y', '4');
            back.setAttribute('width', '11');
            back.setAttribute('height', '13');
            back.setAttribute('rx', '2');
            const front = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
            front.setAttribute('x', '4');
            front.setAttribute('y', '8');
            front.setAttribute('width', '11');
            front.setAttribute('height', '13');
            front.setAttribute('rx', '2');
            svg.append(back, front);
            return svg;
        }

        function removeIcon() {
            const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
            svg.setAttribute('viewBox', '0 0 24 24');
            svg.setAttribute('aria-hidden', 'true');
            const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
            path.setAttribute('d', 'M3 3l18 18M21 3L3 21');
            svg.append(path);
            return svg;
        }

        function editIcon() {
            const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
            svg.setAttribute('viewBox', '0 0 24 24');
            svg.setAttribute('aria-hidden', 'true');
            const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
            path.setAttribute('d', 'M15 5l4 4M4 20l5-1L20 8a2.8 2.8 0 0 0-4-4L5 15z');
            svg.append(path);
            return svg;
        }

        function rememberSavedRules() {
            rules.forEach((rule, index) => {
                savedRules.set(rule, JSON.stringify({ordre: index, ...serializeRule(rule)}));
            });
            savedPayload = JSON.stringify(payload());
        }

        function updateRuleStates() {
            rules.forEach((rule, index) => {
                const card = ruleCards.get(rule);
                if (!card) return;
                const modified = savedRules.get(rule) !== JSON.stringify({ordre: index, ...serializeRule(rule)});
                card.classList.toggle('is-unsaved', modified);
                card.querySelector('.bo-nommage-rule-unsaved').hidden = !modified;
            });
        }

        function changed() {
            dirty = JSON.stringify(payload()) !== savedPayload;
            recalculate.disabled = dirty;
            saveFeedback.textContent = '';
            saveFeedback.classList.remove('is-error');
            result.hidden = true;
            updateRuleStates();
        }

        function labelOf(element) {
            const label = element.type === 'champ_dn'
                ? fields.get(element.id_champ)?.nom || 'Champ à sélectionner'
                : element.type === 'champ_dm'
                    ? `DM · ${fieldsDm.get(element.champ_dm)?.nom || 'Champ à sélectionner'}`
                    : config.attributs[element.attribut] || 'Variable à sélectionner';
            return label + (element.transformation !== 'aucune' ? ` (${config.transformations[element.transformation]})` : '');
        }

        function pattern(rule, container) {
            container.replaceChildren();
            if (!rule.elements.length) {
                container.append(node('span', '', 'Ajoutez du texte ou une variable pour composer le nom.'));
                return;
            }
            rule.elements.forEach((element, index) => {
                if (index) container.append(document.createTextNode(' '));
                const source = element.type === 'champ_dn' ? 'Champ du formulaire DN'
                    : element.type === 'champ_dm' ? 'Champ du formulaire DM'
                        : element.type === 'attribut' ? 'Information AGIDA / BDD' : null;
                const token = node(
                    'span',
                    element.type === 'texte' ? 'bo-nommage-fixed'
                        : element.type === 'champ_dn' ? 'bo-nommage-token bo-nommage-token--dn'
                            : element.type === 'champ_dm' ? 'bo-nommage-token bo-nommage-token--dm'
                                : 'bo-nommage-token bo-nommage-token--bdd',
                    element.type === 'texte' ? element.texte.trim() || '…' : labelOf(element),
                );
                if (source) {
                    token.title = source;
                    token.setAttribute('aria-label', `${source} : ${labelOf(element)}`);
                }
                container.append(token);
            });
        }

        function renderPreservingScroll() {
            const scrollX = window.scrollX;
            const scrollY = window.scrollY;
            render();
            window.requestAnimationFrame(() => window.scrollTo(scrollX, scrollY));
        }

        function move(array, index, delta) {
            [array[index], array[index + delta]] = [array[index + delta], array[index]];
            changed();
            renderPreservingScroll();
        }

        function makeVariableSelect(element, onChange) {
            const select = node('select');
            select.setAttribute('aria-label', 'Source de la variable');
            const placeholder = node('option', '', 'Choisir une variable…');
            placeholder.value = '';
            select.append(placeholder);

            const attrs = node('optgroup');
            attrs.label = 'Info BDD';
            Object.entries(config.attributs).forEach(([key, label]) => {
                const option = node('option', '', label);
                option.value = `attribut:${key}`;
                attrs.append(option);
            });

            const fieldsGroup = node('optgroup');
            fieldsGroup.label = 'Champs du formulaire DN';
            config.champs.forEach(field => {
                const name = field.nom.length > 85 ? `${field.nom.slice(0, 82)}…` : field.nom;
                const option = node('option', '', `${name} (${field.type})`);
                option.title = field.nom;
                option.value = `champ:${field.id}`;
                fieldsGroup.append(option);
            });
            select.append(attrs, fieldsGroup);
            if (fieldsDm.size) {
                const fieldsDmGroup = node('optgroup');
                fieldsDmGroup.label = 'Champs Déclaration Manifestations (DM)';
                fieldsDm.forEach(field => {
                    const option = node('option', '', `${field.nom} (${field.type})`);
                    option.value = `champ_dm:${field.name}`;
                    fieldsDmGroup.append(option);
                });
                select.append(fieldsDmGroup);
            }
            select.value = element.type === 'champ_dn'
                ? `champ:${element.id_champ}`
                : element.type === 'champ_dm' ? `champ_dm:${element.champ_dm}`
                : element.attribut ? `attribut:${element.attribut}` : '';
            select.addEventListener('change', () => {
                if (select.value.startsWith('champ:')) {
                    element.type = 'champ_dn';
                    element.id_champ = Number(select.value.slice(6));
                    delete element.attribut;
                    delete element.champ_dm;
                } else if (select.value.startsWith('champ_dm:')) {
                    element.type = 'champ_dm';
                    element.champ_dm = select.value.slice(9);
                    delete element.id_champ;
                    delete element.attribut;
                } else {
                    element.type = 'attribut';
                    element.attribut = select.value.slice(9);
                    delete element.id_champ;
                    delete element.champ_dm;
                }
                changed();
                onChange();
            });
            return select;
        }

        function makeCustomTransformEditor(element, onChange) {
            const custom = element.configuration_transformation;
            const editor = node('div', 'bo-nommage-custom-transform');
            editor.append(node('p', 'bo-nommage-custom-help',
                'Remplacez certaines valeurs par un texte plus parlant. La comparaison ignore la casse et les espaces superflus. Pour un booléen, utilisez Oui ou Non.'));
            custom.correspondances.forEach((correspondance, index) => {
                const row = node('div', 'bo-nommage-custom-row');
                const sourceLabel = node('label', '', 'Si la valeur est');
                const source = node('input');
                source.type = 'text';
                source.maxLength = 1000;
                source.value = correspondance.valeur;
                source.placeholder = 'Ex. Renouvellement de demande';
                source.addEventListener('input', () => {
                    correspondance.valeur = source.value;
                    changed();
                    onChange();
                });
                sourceLabel.append(source);
                const targetLabel = node('label', '', 'Utiliser dans le nom');
                const target = node('input');
                target.type = 'text';
                target.maxLength = 1000;
                target.value = correspondance.texte;
                target.placeholder = 'Ex. Renouvellement';
                target.addEventListener('input', () => {
                    correspondance.texte = target.value;
                    changed();
                    onChange();
                });
                targetLabel.append(target);
                row.append(sourceLabel, node('span', 'bo-nommage-custom-arrow', '→'), targetLabel,
                    button('×', 'Retirer cette correspondance', () => {
                        custom.correspondances.splice(index, 1);
                        changed();
                        renderPreservingScroll();
                    }));
                editor.append(row);
            });
            const add = button('+ Correspondance', 'Ajouter une correspondance', () => {
                custom.correspondances.push({valeur: '', texte: ''});
                changed();
                renderPreservingScroll();
            }, custom.correspondances.length >= 100);
            const fallbackLabel = node('label', 'bo-nommage-custom-fallback', 'Si aucune valeur ne correspond');
            const fallback = node('select');
            Object.entries({conserver: 'Conserver la valeur d’origine', ignorer_regle: 'Passer à la règle suivante'}).forEach(([key, label]) => {
                const option = node('option', '', label);
                option.value = key;
                fallback.append(option);
            });
            fallback.value = custom.sans_correspondance;
            fallback.addEventListener('change', () => {
                custom.sans_correspondance = fallback.value;
                changed();
            });
            fallbackLabel.append(fallback);
            editor.append(add, fallbackLabel, node('p', 'bo-nommage-custom-help',
                'Un texte de remplacement vide omet cet élément du nom. Un champ absent ou vide fait toujours passer à la règle suivante.'));
            return editor;
        }

        function render() {
            list.replaceChildren();
            ruleCards.clear();
            form.querySelector('[data-nommage-empty]').hidden = rules.length > 0;

            rules.forEach((rule, index) => {
                const card = node('section', 'bo-nommage-rule');
                const heading = node('div', 'bo-nommage-rule-heading');
                const priority = node('span', 'bo-nommage-priority', `Priorité ${index + 1}`);
                const ruleName = rule._expanded
                    ? node('input', 'bo-nommage-rule-name-input')
                    : node('span', 'bo-nommage-rule-name', rule.libelle || 'Règle sans nom');
                if (rule._expanded) {
                    ruleName.type = 'text';
                    ruleName.value = rule.libelle;
                    ruleName.maxLength = 150;
                    ruleName.placeholder = 'Nom de la règle (facultatif)';
                    ruleName.setAttribute('aria-label', `Libellé de la règle ${index + 1}`);
                    ruleName.addEventListener('input', () => {
                        rule.libelle = ruleName.value;
                        changed();
                    });
                }
                const active = node('label', 'bo-nommage-active');
                const checkbox = node('input');
                checkbox.type = 'checkbox';
                checkbox.checked = rule.actif;
                checkbox.addEventListener('change', () => {
                    rule.actif = checkbox.checked;
                    changed();
                    card.classList.toggle('is-disabled', !rule.actif);
                });
                active.append(checkbox, node('span', '', 'Active'));

                const priorityControls = node('div', 'bo-nommage-order bo-nommage-rule-order');
                priorityControls.append(
                    button('↑', 'Monter la règle', () => move(rules, index, -1), index === 0),
                    button('↓', 'Descendre la règle', () => move(rules, index, 1), index === rules.length - 1),
                );
                const toggle = button(
                    rule._expanded ? '−' : '',
                    rule._expanded ? 'Réduire le détail de la règle' : 'Modifier cette règle',
                    () => {
                        rule._expanded = !rule._expanded;
                        renderPreservingScroll();
                    },
                );
                toggle.classList.add('back-office-collapse-icon', 'bo-nommage-rule-toggle');
                toggle.setAttribute('aria-expanded', String(rule._expanded));
                if (!rule._expanded) toggle.append(editIcon());
                const ruleActions = node('div', 'bo-nommage-rule-actions');
                ruleActions.hidden = !rule._expanded;
                const duplicate = button('', 'Dupliquer la règle', () => {
                    const copy = JSON.parse(JSON.stringify(rule));
                    copy._expanded = true;
                    copy.elements.forEach(element => { element._customExpanded = false; });
                    rules.splice(index + 1, 0, copy);
                    changed();
                    renderPreservingScroll();
                });
                const removeRule = button('', 'Supprimer la règle complète', () => {
                    if (!window.confirm(`Supprimer définitivement la règle « ${rule.libelle || `Priorité ${index + 1}`} » ?`)) return;
                    rules.splice(index, 1);
                    changed();
                    renderPreservingScroll();
                });
                duplicate.append(duplicateIcon());
                removeRule.append(removeIcon());
                duplicate.classList.add('bo-nommage-rule-icon');
                removeRule.classList.add('bo-nommage-rule-icon', 'bo-nommage-delete-rule');
                ruleActions.append(duplicate, removeRule);
                heading.append(priority, ruleName, active, priorityControls, ruleActions, toggle);

                const compositionLabel = node('p', 'bo-nommage-composition-label', 'Composition du nom');
                const composition = node('div', 'bo-nommage-composition');
                pattern(rule, composition);

                const detail = node('div', 'bo-nommage-rule-detail');
                detail.hidden = !rule._expanded;

                const elements = node('div', 'bo-nommage-elements');
                rule.elements.forEach((element, elementIndex) => {
                    const row = node('div', 'bo-nommage-element');
                    row.append(node('span', 'bo-nommage-element-kind', element.type === 'texte' ? 'Texte fixe' : 'Variable'));
                    if (element.type === 'texte') {
                        const input = node('input');
                        input.type = 'text';
                        input.value = element.texte;
                        input.maxLength = 1000;
                        input.placeholder = 'Ex. « à » ou « - »';
                        input.setAttribute('aria-label', 'Texte fixe');
                        input.addEventListener('input', () => {
                            element.texte = input.value;
                            changed();
                            pattern(rule, composition);
                        });
                        row.append(input);
                    } else {
                        const sourceField = node('label', 'bo-nommage-variable-field bo-nommage-source-field');
                        // Le libellé reste affiché même sans valeur : le sélecteur reste ainsi
                        // aligné avec celui de la transformation.
                        const sourceCaption = node('span', '', 'Source de la variable');
                        sourceField.append(sourceCaption, makeVariableSelect(element, () => {
                            pattern(rule, composition);
                        }));
                        row.append(sourceField);
                        const transformField = node('div', 'bo-nommage-variable-field bo-nommage-transform-field');
                        const transformLabel = node('label', '', 'Transformation');
                        const select = node('select', 'bo-nommage-transform');
                        select.setAttribute('aria-label', 'Transformation');
                        Object.entries(config.transformations).forEach(([value, label]) => {
                            const option = node('option', '', label);
                            option.value = value;
                            select.append(option);
                        });
                        select.value = element.transformation;
                        select.addEventListener('change', () => {
                            element.transformation = select.value;
                            // Une transformation que l'on vient de choisir doit pouvoir être
                            // paramétrée immédiatement. Les règles déjà enregistrées, elles,
                            // restent repliées lors de leur rendu initial.
                            element._customExpanded = select.value === 'personnalisee';
                            if (select.value === 'personnalisee' && !element.configuration_transformation?.correspondances) {
                                element.configuration_transformation = {
                                    correspondances: [{valeur: '', texte: ''}], sans_correspondance: 'conserver',
                                };
                            }
                            changed();
                            renderPreservingScroll();
                        });
                        transformLabel.append(select);
                        transformField.append(transformLabel);
                        if (element.transformation === 'personnalisee') {
                            const customToggle = button(
                                element._customExpanded ? 'Réduire la transformation' : 'Modifier la transformation',
                                element._customExpanded ? 'Réduire la transformation personnalisée' : 'Modifier la transformation personnalisée',
                                () => {
                                    element._customExpanded = !element._customExpanded;
                                    renderPreservingScroll();
                                },
                            );
                            customToggle.classList.add('bo-nommage-custom-toggle');
                            customToggle.setAttribute('aria-expanded', String(Boolean(element._customExpanded)));
                            transformField.append(customToggle);
                        }
                        row.append(transformField);
                    }
                    const order = node('div', 'bo-nommage-order');
                    order.append(
                        button('↑', 'Monter cet élément', () => move(rule.elements, elementIndex, -1), elementIndex === 0),
                        button('↓', 'Descendre cet élément', () => move(rule.elements, elementIndex, 1), elementIndex === rule.elements.length - 1),
                        button('×', 'Retirer cet élément', () => {
                            rule.elements.splice(elementIndex, 1);
                            changed();
                            renderPreservingScroll();
                        }),
                    );
                    row.append(order);
                    elements.append(row);
                    if (element.type !== 'texte' && element.transformation === 'personnalisee') {
                        const customEditor = makeCustomTransformEditor(element, () => pattern(rule, composition));
                        customEditor.hidden = !element._customExpanded;
                        elements.append(customEditor);
                    }
                });

                const add = node('div', 'bo-nommage-add-elements');
                add.append(
                    button('+ Texte fixe', 'Ajouter un texte fixe', () => {
                        rule.elements.push({type: 'texte', texte: '', transformation: 'aucune'});
                        changed();
                        renderPreservingScroll();
                    }),
                    button('+ Variable', 'Ajouter une variable', () => {
                        rule.elements.push({type: 'attribut', attribut: '', transformation: 'aucune'});
                        changed();
                        renderPreservingScroll();
                    }),
                );
                detail.append(elements, add);
                card.classList.toggle('is-disabled', !rule.actif);
                const unsaved = node('p', 'bo-nommage-rule-unsaved', 'Modifications à enregistrer');
                unsaved.setAttribute('role', 'status');
                card.append(heading, compositionLabel, composition, detail, unsaved);
                ruleCards.set(rule, card);
                list.append(card);
            });
            updateRuleStates();
        }

        function serializeRule(rule) {
            return {
                libelle: rule.libelle,
                actif: rule.actif,
                elements: rule.elements.map(element => ({
                    type: element.type,
                    texte: element.texte,
                    id_champ: element.id_champ,
                    champ_dm: element.champ_dm,
                    attribut: element.attribut,
                    transformation: element.transformation,
                    configuration_transformation: element.transformation === 'personnalisee'
                        ? element.configuration_transformation : {},
                })),
            };
        }

        function payload() {
            return {regles: rules.map(serializeRule)};
        }

        async function request(url, data, loading, feedback = status) {
            if (busy) return null;
            busy = true;
            const controls = [...form.querySelectorAll('button, input, select')];
            const disabled = controls.map(control => control.disabled);
            controls.forEach(control => { control.disabled = true; });
            form.setAttribute('aria-busy', 'true');
            const loader = form.querySelector('[data-nommage-loader]');
            loader.hidden = false;
            feedback.textContent = loading;
            feedback.classList.remove('is-error');
            try {
                const response = await fetch(url, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': form.querySelector('[name=csrfmiddlewaretoken]').value,
                    },
                    body: JSON.stringify(data),
                });
                const type = response.headers.get('content-type') || '';
                if (response.redirected || !type.includes('application/json')) {
                    throw new Error('La requête n’a pas abouti. Vérifiez votre connexion et votre session.');
                }
                const value = await response.json();
                if (!response.ok) throw new Error(value.error || 'L’opération n’a pas pu être effectuée.');
                return value;
            } catch (error) {
                feedback.textContent = error.message;
                feedback.classList.add('is-error');
                return null;
            } finally {
                busy = false;
                controls.forEach((control, index) => { control.disabled = disabled[index]; });
                loader.hidden = true;
                form.removeAttribute('aria-busy');
            }
        }

        async function updateNumberSuggestions() {
            const query = numberInput.value.trim();
            numberSuggestions.replaceChildren();
            if (!/^\d+$/.test(query)) return;
            if (autocompleteController) autocompleteController.abort();
            autocompleteController = new AbortController();
            try {
                const response = await fetch(
                    `${form.dataset.numbersUrl}?q=${encodeURIComponent(query)}`,
                    {headers: {'Accept': 'application/json'}, signal: autocompleteController.signal},
                );
                if (!response.ok || numberInput.value.trim() !== query) return;
                const value = await response.json();
                value.numeros.forEach(numero => {
                    const option = node('option');
                    option.value = numero;
                    numberSuggestions.append(option);
                });
            } catch (error) {
                if (error.name !== 'AbortError') numberSuggestions.replaceChildren();
            }
        }

        numberInput.addEventListener('input', () => {
            window.clearTimeout(autocompleteTimer);
            autocompleteTimer = window.setTimeout(updateNumberSuggestions, 180);
        });

        form.querySelector('[data-nommage-add]').addEventListener('click', () => {
            rules.push({libelle: '', actif: true, elements: [], _expanded: true});
            changed();
            renderPreservingScroll();
        });

        form.addEventListener('submit', async event => {
            event.preventDefault();
            const value = await request(form.dataset.saveUrl, payload(), 'Enregistrement des règles…', saveFeedback);
            if (value) {
                dirty = false;
                recalculate.disabled = false;
                rememberSavedRules();
                rules.forEach(rule => {
                    rule._expanded = false;
                    rule.elements.forEach(element => { element._customExpanded = false; });
                });
                renderPreservingScroll();
                saveFeedback.textContent = 'Règles enregistrées.';
            }
        });

        form.querySelector('[data-nommage-preview]').addEventListener('click', async () => {
            result.hidden = true;
            const value = await request(
                form.dataset.previewUrl,
                {...payload(), numero: numberInput.value},
                'Calcul de l’aperçu…',
            );
            if (!value) return;
            result.replaceChildren(node('p', '', 'Nom généré'), node('strong', '', value.nom_genere || 'Aucune règle complète : le nom standard sera utilisé.'));
            if (value.nom_manuel) result.append(node('p', '', 'Un nom manuel ou DM reste prioritaire à l’affichage.'));
            result.append(node('p', '', `Nom affiché : ${value.nom_affiche}`));
            value.details.forEach(detail => {
                const missing = detail.manquants?.length ? ` — valeur absente ou inexploitable : ${detail.manquants.join(', ')}` : '';
                const detailNode = node(
                    'p',
                    `bo-nommage-detail ${detail.statut === 'retenue' ? 'is-selected' : detail.statut === 'ignorée' ? 'is-skipped' : ''}`,
                    `Priorité ${detail.ordre}${detail.libelle ? ` · ${detail.libelle}` : ''} : ${detail.statut}${missing}`,
                );
                result.append(detailNode);
            });
            result.hidden = false;
            status.textContent = 'Aperçu calculé, sans modifier le dossier.';
        });

        recalculate.addEventListener('click', async () => {
            if (dirty || !window.confirm('Recalculer les noms de tous les dossiers DN de cette démarche, archives comprises ? Les noms manuels et DM prioritaires seront conservés.')) return;
            const value = await request(form.dataset.recalculateUrl, {}, 'Recalcul des noms, archives comprises…');
            if (value) {
                status.textContent = `${value.total} dossier(s) examiné(s), ${value.modifies} nom(s) généré(s) mis à jour. ${value.noms_prioritaires} nom(s) manuel(s) ou DM restent prioritaires.`;
            }
        });

        rememberSavedRules();
        render();
    });
})();

/* Même contrat déclaratif que instruction/utils/avis_formulaires.py. */
window.AvisFormulaires = (() => {
    function correspond(condition, etat) {
        const valeur = String(etat[condition.champ] || "");
        if (condition.operateur === "vide") return !valeur;
        if (condition.operateur === "renseigne") return Boolean(valeur);
        if (condition.operateur === "dans") return condition.valeur.includes(valeur);
        return valeur === String(condition.valeur);
    }
    function evaluer(champs, etat, variables = {}) {
        return champs.map(champ => {
            const cas = champ.regles.find(cas => cas.conditions.every(condition => correspond(condition, etat)));
            const effectif = {...champ, ...cas};
            effectif.libelle = cas?.libelle?.trim() || champ.libelle;
            effectif.placeholder = cas?.placeholder?.trim() ? cas.placeholder : champ.placeholder;
            effectif.defaut = effectif.defaut.replace(/\{\{|\}\}|\{(numero_dossier|numero_avis|type_demarche)\}/g,
                (mot, cle) => cle ? String(variables[cle] || "") : mot === "{{" ? "{" : "}");
            return effectif;
        });
    }
    let compteurAides = 0;
    function aide(label, texte) {
        let titre = label.parentElement;
        if (!texte && !titre.classList.contains("avis-field-heading")) return;
        if (!titre.classList.contains("avis-field-heading")) {
            titre = document.createElement("span");titre.className = "avis-field-heading";
            label.before(titre);titre.append(label);
        }
        let info = titre.querySelector(".avis-field-help");
        if (!texte) {info?.remove();return;}
        if (!info) {
            info = document.createElement("span");info.className = "avis-field-help";
            const bouton = document.createElement("button");bouton.type = "button";bouton.textContent = "i";
            bouton.setAttribute("aria-label", "Aide au remplissage");
            const bulle = document.createElement("span");bulle.className = "avis-field-help-bubble";
            bulle.id = `avis-aide-${++compteurAides}`;bulle.setAttribute("role", "tooltip");
            bouton.setAttribute("aria-describedby", bulle.id);info.append(bouton, bulle);titre.append(info);
            const positionner = () => {
                const rect = bouton.getBoundingClientRect();
                // Mesurer la largeur naturelle avant de la replacer près du bouton.
                bulle.style.left = "16px";
                const largeur = bulle.getBoundingClientRect().width;
                bulle.style.left = `${Math.max(16, Math.min(rect.left, innerWidth - largeur - 16))}px`;
                bulle.style.top = `${rect.bottom + 8}px`;
                if (bulle.getBoundingClientRect().bottom > innerHeight - 16) bulle.style.top = `${Math.max(16, rect.top - bulle.offsetHeight - 8)}px`;
            };
            info.addEventListener("mouseenter", positionner);bouton.addEventListener("focus", positionner);
        }
        info.querySelector(".avis-field-help-bubble").textContent = texte;
    }
    function initialiser(form) {
        const script = document.getElementById("avis-formulaire-configuration");
        if (!script) return null;
        const configuration = JSON.parse(script.textContent);
        if (!configuration?.champs) return null;
        const controles = new Map();
        const automatiques = new Map();
        const themes = form.querySelector("#thematique");
        const optionsThemes = themes ? Array.from(themes.options, option => option.cloneNode(true)) : [];
        const premier = form.querySelector(".attribut_avis");
        const repere = document.createElement("span");repere.hidden = true;
        premier.before(repere);
        configuration.champs.forEach(champ => {
            const input = form.querySelector(`#${champ.code}`);
            if (!input) return;
            const bloc = input.closest(".attribut_avis");
            const label = bloc.querySelector(".avis-reponse-label, label");
            controles.set(champ.code, {input, bloc, label, verrouille: input.disabled && champ.code === "nature"});
            form.insertBefore(bloc, repere);
        });
        let effectifs = [];
        function actualiser() {
            const nature = form.querySelector("#nature");
            const natureType = nature.selectedOptions[0]?.dataset.natureType || "";
            const externe = form.querySelector("#expert_externe");
            const interne = form.querySelector("#expert_interne");
            if (natureType !== "instance") externe.value = "";
            if (natureType !== "interne") interne.value = "";
            const codeExpert = natureType === "instance" ? "expert_externe" : natureType === "interne" ? "expert_interne" : null;
            const expert = codeExpert && controles.get(codeExpert)?.input;
            const defautExpert = configuration.champs.find(c => c.code === codeExpert)?.defaut;
            if (expert && !expert.value && defautExpert) expert.value = defautExpert;
            const demarche = form.querySelector("#demarche");
            const etat = {nature_type: natureType, expert_externe: externe.value, expert_interne: interne.value,
                expert_cs: externe.selectedOptions[0]?.dataset.estCs === "true" ? "true" : "false", demarche: demarche?.value || configuration.variables.demarche || ""};
            const variables = {...configuration.variables};
            if (demarche?.value) variables.type_demarche = demarche.selectedOptions[0].textContent.trim();
            effectifs = evaluer(configuration.champs, etat, variables);
            effectifs.forEach(champ => {
                const controle = controles.get(champ.code);
                if (!controle) return;
                const {input, bloc, label, verrouille} = controle;
                bloc.hidden = !champ.visible;
                bloc.style.display = champ.visible ? "flex" : "none";
                bloc.querySelectorAll("input, select, textarea").forEach(el => {
                    el.disabled = !champ.visible || (el === input && verrouille);
                    el.required = false;
                });
                label.textContent = champ.libelle + " :";
                if (champ.code === "thematique") {
                    const autorises = configuration.thematiques_par_demarche?.[etat.demarche];
                    const valeur = input.value;
                    input.replaceChildren(...optionsThemes.filter(option => !option.value || !autorises || autorises.includes(option.value)).map(option => option.cloneNode(true)));
                    input.value = valeur;
                }
                if (["textarea", "text"].includes(input.type)) input.placeholder = champ.placeholder || "";
                const radios = input.querySelectorAll('input[type="radio"]');
                const valeur = radios.length ? input.querySelector('input:checked')?.value || "" : input.value;
                if (champ.visible && input.type !== "file" && (!valeur.trim() || valeur === automatiques.get(champ.code))) {
                    if (radios.length) radios.forEach(radio => {radio.checked = radio.value === champ.defaut;});
                    else input.value = champ.defaut;
                    automatiques.set(champ.code, champ.defaut);
                }
                aide(label, champ.aide);
            });
            const actions = form.querySelector(".avis-form-actions, .div-btn-confirmer-envoi");
            if (actions) actions.hidden = !["interne", "instance"].includes(natureType);
            obligations("envoi");
        }
        function obligations(action) {
            effectifs.forEach(champ => {
                const controle = controles.get(champ.code);
                if (!controle) return;
                const {input, label} = controle;
                const requis = champ.visible && champ[action === "brouillon" ? "requis_brouillon" : "requis_envoi"];
                const dejaJoint = input.dataset.exists === "true" || (champ.code === "pj_lie_avis" && form.querySelector("[data-pj-enregistrees] [data-pj-controle]"));
                const radios = input.querySelectorAll('input[type="radio"]');
                if (radios.length) radios.forEach(radio => {radio.required = Boolean(requis);});
                else input.required = Boolean(requis && !(input.type === "file" && dejaJoint));
                label.textContent = champ.libelle + (requis ? "* :" : " :");
            });
        }
        ["nature", "expert_externe", "expert_interne", "demarche"].forEach(code => form.querySelector(`#${code}`)?.addEventListener("change", actualiser));
        // Les valeurs structurelles initiales peuvent être choisies dans le back-office.
        configuration.champs.filter(c => ["nature", "demarche", "thematique"].includes(c.code)).forEach(champ => {
            const controle = controles.get(champ.code);
            if (controle && !controle.input.value && champ.defaut) controle.input.value = champ.defaut;
        });
        actualiser();
        return {actualiser, obligations};
    }
    return {evaluer, initialiser, aide};
})();

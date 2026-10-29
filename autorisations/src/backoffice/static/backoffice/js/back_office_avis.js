document.addEventListener("DOMContentLoaded", () => {
    const racine = document.querySelector("[data-avis-configuration]");
    if (!racine) return;
    const contexte = racine.querySelector("[data-avis-contexte]");
    const liste = racine.querySelector("[data-avis-champs]");
    const message = racine.querySelector("[data-avis-message]");
    const simulation = racine.querySelector("[data-avis-simulation]");
    const urlFormulaire = () => racine.dataset[{dossier: "urlDossier", generique: "urlGenerique", existant: "urlExistant"}[contexteCharge]];
    let donnees, champs, charge = false, sale = false, enCours = false, contexteCharge = "dossier";
    let modeApercu = "envoi";
    const etat = {nature_type: "", expert_cs: "false", expert_externe: "", expert_interne: "", demarche: ""};
    const sources = {nature_type: "Nature de l’avis", expert_externe: "Expert externe", expert_interne: "Expert interne", expert_cs: "Expert reconnu Conseil scientifique", demarche: "Type de demande"};
    function element(tag, texte, classe) {
        const el = document.createElement(tag); if (texte !== undefined) el.textContent = texte;
        if (classe) el.className = classe;return el;
    }
    function bouton(texte, action, titre) {
        const el = element("button", texte);el.type = "button";if (titre) el.title = titre;
        el.addEventListener("click", event => {event.preventDefault();event.stopPropagation();action();});return el;
    }
    function signaler(texte, erreur = false) {message.textContent = texte;message.className = erreur ? "is-error" : "is-success";}
    async function lireReponse(reponse) {
        if (reponse.redirected || [401, 403].includes(reponse.status)) {
            throw new Error("Votre session a expiré ou l’accès est refusé. Vos réglages restent présents à l’écran ; reconnectez-vous dans un autre onglet, puis réessayez.");
        }
        const contenu = await reponse.text();
        try {return JSON.parse(contenu);}
        catch {
            throw new Error(`Le serveur a renvoyé une réponse inattendue (HTTP ${reponse.status}). Consultez les logs serveur. Vos réglages restent présents à l’écran.`);
        }
    }
    function modifier() {sale = true;racine.classList.add("is-dirty");signaler("Modifications à enregistrer.");apercu();}
    function choix(items, valeur, changer, multiple = false) {
        const select = document.createElement("select");select.multiple = multiple;
        if (!multiple) select.append(new Option("— Aucun —", ""));
        items.forEach(item => {const option = new Option(item.libelle, item.valeur);option.selected = multiple ? valeur.includes(item.valeur) : valeur === item.valeur;select.append(option);});
        select.addEventListener("change", () => changer(multiple ? Array.from(select.selectedOptions, o => o.value) : select.value));
        return select;
    }
    function texte(obj, cle, titre, multiligne = false) {
        const label = element("label", titre, "bo-avis-text");
        const input = document.createElement(multiligne ? "textarea" : "input");input.value = obj[cle] || "";
        input.addEventListener("input", () => {obj[cle] = input.value;modifier();});label.append(input);return label;
    }
    function coche(obj, cle, titre, disabled = false) {
        const label = element("label", titre);const input = document.createElement("input");input.type = "checkbox";input.checked = obj[cle];input.disabled = disabled;
        input.addEventListener("change", () => {obj[cle] = input.checked;modifier();});label.prepend(input);return label;
    }
    function valeurInitiale(obj, code, valeur) {
        obj.defaut = valeur;
        // Une modification de configuration prime sur une ancienne simulation.
        if (code === "nature") {etat.nature_type = "";etat.expert_externe = "";etat.expert_interne = "";etat.expert_cs = "false";}
        else delete etat[code];
        simulation.querySelectorAll("[data-preview-source]").forEach(select => {select.value = etat[select.dataset.previewSource] || "";});
        modifier();
    }
    function reglages(obj, code, bloque = false) {
        const bloc = document.createElement("div");const checks = element("div", undefined, "bo-avis-checks");
        checks.append(coche(obj, "visible", "Afficher", bloque));
        if (contexteCharge === "dossier") checks.append(coche(obj, "requis_brouillon", "Obligatoire en brouillon", bloque));
        checks.append(coche(obj, "requis_envoi", contexteCharge === "existant" ? "Obligatoire à l’enregistrement" : "Obligatoire à l’envoi", bloque));bloc.append(checks);
        if (!code.startsWith("pj_")) {
            if (donnees.choix[code]) {
                const label = element("label", "Valeur initiale", "bo-avis-text");
                label.append(choix(donnees.choix[code], obj.defaut, valeur => valeurInitiale(obj, code, valeur)));bloc.append(label);
            } else if (["date_demande_avis", "date_reponse_avis"].includes(code)) {
                const label = element("label", "Valeur initiale", "bo-avis-text");
                const input = document.createElement("input");input.type = "datetime-local";input.value = obj.defaut || "";
                input.addEventListener("change", () => {obj.defaut = input.value;modifier();});label.append(input);bloc.append(label);
            } else bloc.append(texte(obj, "defaut", "Valeur initiale", true));
        }
        if (["note_demandeur", "formulation_avis", "numero_avis_externe"].includes(code)) bloc.append(texte(obj, "placeholder", "Texte indicatif dans le champ (placeholder)"));
        return bloc;
    }
    function lienCatalogue() {
        const lien = element("a", undefined, "bo-avis-catalogue-link");lien.href = "#avis/thematiques";
        const icone = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        icone.setAttribute("viewBox", "0 0 24 24");icone.setAttribute("aria-hidden", "true");icone.setAttribute("focusable", "false");
        const chemin = document.createElementNS("http://www.w3.org/2000/svg", "path");
        chemin.setAttribute("d", "M9 6h11M9 12h11M9 18h11M4 6h.01M4 12h.01M4 18h.01");icone.append(chemin);
        const textes = element("span", undefined, "bo-avis-catalogue-link-text");
        textes.append(element("strong", "Gérer les thématiques"), element("small", "Répartition par démarche"));
        const fleche = element("span", "→", "bo-avis-catalogue-link-arrow");fleche.setAttribute("aria-hidden", "true");
        lien.append(icone, textes, fleche);return lien;
    }
    function afficherCondition(cas, condition) {
        const ligne = element("div", undefined, "bo-avis-condition");
        ligne.append(choix(Object.entries(sources).map(([valeur, libelle]) => ({valeur, libelle})), condition.champ, valeur => {
            condition.champ = valeur;condition.valeur = condition.operateur === "dans" ? [] : "";modifier();dessiner();
        }));
        ligne.append(choix([{valeur: "egal", libelle: "est égal à"}, {valeur: "dans", libelle: "fait partie de"}, {valeur: "renseigne", libelle: "est renseigné"}, {valeur: "vide", libelle: "est vide"}], condition.operateur, valeur => {
            condition.operateur = valeur;condition.valeur = valeur === "dans" ? [] : "";modifier();dessiner();
        }));
        if (["egal", "dans"].includes(condition.operateur)) {
            ligne.append(choix(donnees.choix[condition.champ] || [], condition.valeur, valeur => {condition.valeur = valeur;modifier();}, condition.operateur === "dans"));
        }
        ligne.append(bouton("×", () => {cas.conditions.splice(cas.conditions.indexOf(condition), 1);modifier();dessiner();}, "Retirer cette condition"));return ligne;
    }
    function deplacer(tableau, index, direction) {
        const cible = index + direction;if (cible < 0 || cible >= tableau.length) return;
        [tableau[index], tableau[cible]] = [tableau[cible], tableau[index]];modifier();dessiner();
    }
    function dessiner() {
        const position = {left: scrollX, top: scrollY, behavior: "instant"};
        const actif = document.activeElement;
        const carteActive = actif?.closest("[data-code]");
        const indexActif = carteActive && actif.matches("input, select, textarea")
            ? Array.from(carteActive.querySelectorAll("input, select, textarea")).indexOf(actif) : -1;
        const ouverts = new Set(Array.from(liste.querySelectorAll("details[open]"), d => d.dataset.code));
        const fragment = document.createDocumentFragment();
        champs.forEach((champ, index) => {
            const bloque = donnees.structurels.includes(champ.code);
            const carte = element("details", undefined, "bo-avis-field");carte.dataset.code = champ.code;carte.open = ouverts.has(champ.code);
            const heading = element("summary");heading.append(element("span", index + 1, "bo-avis-rank"), element("strong", champ.libelle));
            heading.append(bouton("↑", () => deplacer(champs, index, -1), "Monter le champ"), bouton("↓", () => deplacer(champs, index, 1), "Descendre le champ"));carte.append(heading);
            const corps = element("div", undefined, "bo-avis-field-body");
            corps.append(texte(champ, "libelle", "Libellé"), texte(champ, "aide", "Aide au remplissage", true));
            if (bloque) corps.append(element("p", "Champ structurel : les obligations et conditions de sélection sont protégées.", "bo-avis-lock"));
            corps.append(reglages(champ, champ.code, bloque));
            if (champ.code === "thematique") corps.append(lienCatalogue());
            if (bloque && champ.code !== "thematique" && champ.regles.length) {
                const conditions = element("div", undefined, "bo-avis-protected-conditions");
                champ.regles.forEach(cas => {
                    const resume = cas.conditions.map(c => `${sources[c.champ]} : ${(donnees.choix[c.champ] || []).find(o => o.valeur === c.valeur)?.libelle || c.valeur}`).join(" ET ");
                    conditions.append(element("p", `Affiché et obligatoire si ${resume}.`));
                });corps.append(conditions);
            }
            if (!bloque || champ.code === "thematique") {
                champ.regles.forEach((cas, indice) => {
                    const fieldset = element("fieldset", undefined, "bo-avis-case");fieldset.append(element("legend", `Cas ${indice + 1} · si toutes les conditions correspondent`));
                    cas.conditions.forEach(condition => fieldset.append(afficherCondition(cas, condition)));
                    fieldset.append(bouton("+ Condition (ET)", () => {cas.conditions.push({champ: "nature_type", operateur: "egal", valeur: "instance"});modifier();dessiner();}));
                    fieldset.append(reglages(cas, champ.code, bloque));
                    fieldset.append(texte(cas, "libelle", "Libellé dans ce cas"));
                    const actions = element("div", undefined, "bo-avis-rule-actions");
                    actions.append(bouton("↑", () => deplacer(champ.regles, indice, -1), "Monter ce cas"), bouton("↓", () => deplacer(champ.regles, indice, 1), "Descendre ce cas"),
                        bouton("Supprimer ce cas", () => {champ.regles.splice(indice, 1);modifier();dessiner();}));fieldset.append(actions);corps.append(fieldset);
                });
                const ajouterCas = bouton("+ Cas conditionnel", () => {
                    champ.regles.push({conditions: [{champ: "nature_type", operateur: "egal", valeur: "instance"}], visible: true,
                        requis_brouillon: bloque ? champ.requis_brouillon : false, requis_envoi: bloque ? champ.requis_envoi : false, defaut: "", libelle: ""});modifier();dessiner();
                });ajouterCas.className = "bo-avis-add-case";corps.append(ajouterCas);
            }
            carte.append(corps);fragment.append(carte);
        });
        // Remplacer en une fois : vider la liste avant de la reconstruire réduisait
        // momentanément la page et ramenait le navigateur en haut.
        liste.replaceChildren(fragment);
        apercu();
        if (indexActif >= 0) {
            liste.querySelector(`[data-code="${carteActive.dataset.code}"]`)?.querySelectorAll("input, select, textarea")[indexActif]?.focus({preventScroll: true});
        }
        window.scrollTo(position);
    }
    function apercu() {
        if (!champs) return;
        const position = {left: scrollX, top: scrollY, behavior: "instant"};
        const sortie = racine.querySelector("[data-avis-apercu]");
        const variables = {numero_dossier: "12345678", numero_avis: "EXEMPLE", type_demarche: "Exemple de démarche"};
        const effectif = {...etat};
        // Reproduire les sélections initiales sans modifier la configuration.
        const initial = code => champs.find(c => c.code === code)?.defaut || "";
        if (!effectif.nature_type && initial("nature")) {
            effectif.nature_type = donnees.choix.nature?.find(c => c.valeur === initial("nature"))?.nature_type || "";
        }
        if (!effectif.demarche) effectif.demarche = initial("demarche");
        const demarche = donnees.choix.demarche?.find(c => c.valeur === effectif.demarche);
        if (demarche) variables.type_demarche = demarche.libelle;
        if (effectif.nature_type !== "instance") {effectif.expert_externe = "";effectif.expert_cs = "false";}
        if (effectif.nature_type !== "interne") effectif.expert_interne = "";
        const codeExpert = effectif.nature_type === "instance" ? "expert_externe" : "expert_interne";
        if (effectif.nature_type && !effectif[codeExpert]) effectif[codeExpert] = initial(codeExpert);
        if (!etat.expert_externe && effectif.expert_externe) {
            effectif.expert_cs = donnees.choix.expert_externe?.find(c => c.valeur === effectif.expert_externe)?.est_cs ? "true" : "false";
        }
        const formulaire = element("div", undefined, "bo-avis-preview-user-form");
        formulaire.append(element("h3", contexteCharge === "existant" ? "Ajouter un avis existant au dossier" : contexteCharge === "dossier" ? "Nouvelle demande d’avis n° EXEMPLE" : "Nouvelle demande d’avis générique EXEMPLE"));
        function selectionner(code, valeur) {
            if (code === "nature") {
                etat.nature_type = donnees.choix.nature?.find(c => c.valeur === valeur)?.nature_type || "";
                etat.expert_externe = "";etat.expert_interne = "";etat.expert_cs = "false";
            } else {
                etat[code] = valeur;
                if (code === "expert_externe") etat.expert_cs = donnees.choix.expert_externe?.find(c => c.valeur === valeur)?.est_cs ? "true" : "false";
            }
            simulation.querySelectorAll("[data-preview-source]").forEach(select => {select.value = etat[select.dataset.previewSource] || "";});
            apercu();
        }
        window.AvisFormulaires.evaluer(champs, effectif, variables).filter(c => c.visible).forEach(champ => {
            const ligne = element("div", undefined, "bo-avis-preview-field");ligne.dataset.previewCode = champ.code;
            const requis = champ[modeApercu === "brouillon" ? "requis_brouillon" : "requis_envoi"];
            const id = `bo-avis-preview-${champ.code}`;
            const label = element("label", champ.libelle + (requis ? "* :" : " :"));label.htmlFor = id;ligne.append(label);
            window.AvisFormulaires.aide(label, champ.aide);
            let controle;
            if (champ.code.startsWith("pj_")) {
                controle = element("div", undefined, "bo-avis-preview-file");
                const fichier = element("button", champ.code === "pj_lie_avis" ? "Choisir des fichiers" : "Choisir un fichier");
                fichier.type = "button";fichier.disabled = true;fichier.id = id;
                controle.append(fichier, element("span", "Aucun fichier sélectionné"));
            } else if (champ.code === "reponse") {
                controle = element("div", undefined, "bo-avis-preview-radios");controle.id = id;
                donnees.choix.reponse.forEach(item => {
                    const labelRadio = element("label", item.libelle);const radio = document.createElement("input");
                    radio.type = "radio";radio.name = "bo-avis-reponse";radio.value = item.valeur;
                    radio.checked = (effectif.reponse || champ.defaut) === item.valeur;
                    radio.addEventListener("change", () => {etat.reponse = radio.value;});
                    labelRadio.prepend(radio);controle.append(labelRadio);
                });
            } else if (donnees.choix[champ.code]) {
                let valeur = effectif[champ.code] || champ.defaut;
                if (champ.code === "nature") valeur = donnees.choix.nature.find(c => c.nature_type === effectif.nature_type)?.valeur || "";
                let items = donnees.choix[champ.code];
                if (champ.code === "thematique") {
                    const autorises = donnees.thematiques_par_demarche?.[effectif.demarche];
                    if (autorises) items = items.filter(item => autorises.includes(item.valeur));
                }
                controle = choix(items, valeur, valeur => selectionner(champ.code, valeur));controle.id = id;
            } else if (["date_demande_avis", "date_reponse_avis", "numero_avis_externe"].includes(champ.code)) {
                controle = document.createElement("input");controle.type = champ.code === "numero_avis_externe" ? "text" : "datetime-local";
                controle.id = id;controle.value = champ.defaut;controle.readOnly = true;
                controle.placeholder = champ.placeholder || "";
            } else {
                controle = document.createElement("textarea");controle.id = id;controle.rows = champ.code === "formulation_avis" ? 3 : 2;
                controle.value = champ.defaut;controle.readOnly = true;controle.placeholder = champ.placeholder || "";
                ligne.classList.add("bo-avis-preview-textarea");
            }
            ligne.append(controle);
            if (champ.code === "pj_demande_avis") ligne.append(element("small", "N’oubliez pas d’insérer le numéro de l’avis EXEMPLE dans le document.", "bo-avis-preview-reminder"));
            formulaire.append(ligne);
        });
        if (["interne", "instance"].includes(effectif.nature_type)) {
            const actions = element("div", undefined, "bo-avis-preview-actions");
            if (contexteCharge === "dossier") {
                const brouillon = element("button", "Enregistrer le brouillon", "bo-avis-preview-draft");brouillon.type = "button";brouillon.disabled = true;actions.append(brouillon);
            }
            const envoyer = element("button", contexteCharge === "existant" ? "Ajouter l’avis au dossier" : contexteCharge === "dossier" ? "Envoyer" : "Envoyer la demande");envoyer.type = "button";envoyer.disabled = true;actions.append(envoyer);
            formulaire.append(actions);
        }
        sortie.replaceChildren(formulaire);
        window.scrollTo(position);
    }
    async function charger() {
        if (enCours) return;
        enCours = true;contexte.disabled = true;signaler("Chargement…");
        const precedent = contexteCharge;contexteCharge = contexte.value;
        try {
            const reponse = await fetch(urlFormulaire(), {credentials: "same-origin"});
            if (!reponse.ok) throw new Error("Impossible de charger les réglages. Vérifiez votre session et l’installation des tables.");
            donnees = await lireReponse(reponse);champs = donnees.champs;charge = true;sale = false;racine.classList.remove("is-dirty");
            simulation.replaceChildren();
            Object.entries(sources).forEach(([code, libelle]) => {
                const label = element("label", libelle);
                const select = choix(donnees.choix[code] || [], etat[code], valeur => {etat[code] = valeur;apercu();});select.dataset.previewSource = code;
                label.append(select);simulation.append(label);
            });
            const mode = racine.querySelector("[data-avis-preview-mode]");mode.replaceChildren();modeApercu = "envoi";
            if (contexteCharge === "dossier") {
                const label = element("label", "Champs requis pour", "bo-avis-preview-mode");
                label.append(choix([{valeur: "envoi", libelle: "L’envoi"}, {valeur: "brouillon", libelle: "Le brouillon"}], modeApercu, valeur => {modeApercu = valeur || "envoi";apercu();}));mode.append(label);
            }
            racine.querySelector(".bo-avis-workspace").hidden = false;racine.querySelector("[data-avis-restaurer]").disabled = false;
            dessiner();signaler("");
        } catch (erreur) {contexteCharge = precedent;contexte.value = precedent;signaler(erreur.message, true);}
        finally {enCours = false;contexte.disabled = false;}
    }
    racine.querySelector("[data-avis-enregistrer]").addEventListener("click", async event => {
        if (enCours) return;enCours = true;event.currentTarget.disabled = true;contexte.disabled = true;signaler("Enregistrement…");
        try {
            const reponse = await fetch(urlFormulaire(), {
                method: "POST", credentials: "same-origin", headers: {"Content-Type": "application/json", "X-CSRFToken": racine.querySelector("[name=csrfmiddlewaretoken]").value}, body: JSON.stringify({champs}),
            });
            const resultat = await lireReponse(reponse);if (!reponse.ok || !resultat.success) throw new Error(resultat.error || "Enregistrement impossible.");
            sale = false;racine.classList.remove("is-dirty");signaler("Formulaire enregistré. Les nouveaux réglages seront utilisés à la prochaine ouverture du formulaire.");
        } catch (erreur) {signaler(erreur.message || "La requête n’a pas abouti. Vos réglages restent présents à l’écran.", true);}
        finally {enCours = false;racine.querySelector("[data-avis-enregistrer]").disabled = false;contexte.disabled = false;}
    });
    contexte.addEventListener("change", () => {
        if (sale && !confirm("Changer de formulaire sans enregistrer les modifications ?")) {contexte.value = contexteCharge;return;}
        charger();
    });
    racine.querySelector("[data-avis-restaurer]").addEventListener("click", () => {
        if (!enCours && confirm("Rétablir les réglages standards ? Il faudra ensuite les enregistrer.")) {champs = structuredClone(donnees.standards);modifier();dessiner();}
    });
    window.addEventListener("beforeunload", event => {if (sale) {event.preventDefault();event.returnValue = "";}});
    let catalogueModifie = false;
    const ouvrir = async () => {
        if (!["#avis", "#avis/formulaires"].includes(location.hash) || enCours) return;
        if (!charge) {charger();return;}
        if (!catalogueModifie) return;
        enCours = true;
        try {
            const reponse = await fetch(urlFormulaire(), {credentials: "same-origin"});
            if (!reponse.ok) throw new Error("Impossible d’actualiser le catalogue des thématiques.");
            const actualisees = await lireReponse(reponse);
            donnees.choix = actualisees.choix;donnees.thematiques_par_demarche = actualisees.thematiques_par_demarche;
            catalogueModifie = false;dessiner();
        } catch (erreur) {signaler(erreur.message, true);}
        finally {enCours = false;}
    };
    window.addEventListener("avis-thematiques-modifiees", () => {catalogueModifie = true;});
    window.addEventListener("hashchange", ouvrir);ouvrir();
});

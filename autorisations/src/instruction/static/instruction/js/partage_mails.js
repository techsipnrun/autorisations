// -------------------- Form Envoi de l'acte final par mail ---------------------

document.addEventListener("DOMContentLoaded", () => {

    document.querySelectorAll(".copie_par_mail").forEach((wrap) => {
        const form = wrap.closest("form");
        if (!form) return;

        const radios = wrap.querySelectorAll('input[name="partager_par_mail_choice"]');
        const hidden = wrap.querySelector(".partager_par_mail_hidden");
        const bloc   = form.querySelector(".formulaire-partage-mails");

        const select = form.querySelector(".emails_copie");
        const search = form.querySelector(".search-contacts");
        const chips  = form.querySelector(".selected-chips");
        const addBtn = form.querySelector(".add-email-btn");

        const container = form.querySelector(".nouveaux-contacts-container");
        const tmpl = form.querySelector(".nouveau-contact-template");
        const erreurValidation = form.querySelector(".mail-validation-erreur");

        if (!radios.length || !hidden || !bloc || !select || !search || !chips || !addBtn || !container || !tmpl) return;

        function majPartage() {
            // IMPORTANT : chercher le checked DANS CE FORM uniquement
            const checked = form.querySelector('input[name="partager_par_mail_choice"]:checked');
            const val = checked ? checked.value : "non";
            hidden.value = val;

            if (val === "oui") {
                bloc.classList.add("show");
                form.querySelector(".annexes-mail-input")?.dispatchEvent(new CustomEvent("verifier-volume"));
            } else {
                bloc.classList.remove("show");
                if (select) Array.from(select.options).forEach(o => o.selected = false);
                if (chips) chips.innerHTML = "";
                if (erreurValidation) erreurValidation.hidden = true;
            }
        }

        radios.forEach(r => r.addEventListener("change", majPartage));
        majPartage();

    // const radios = document.querySelectorAll('input[name="partager_par_mail_choice"]');
    // const hidden = document.getElementById("partager_par_mail");
    // const bloc = document.getElementById("formulaire-partage-mails");
    // const select = document.getElementById('emails_copie');
    // const search = document.getElementById('search-contacts');
    // const chips  = document.getElementById('selected-chips');
    // const addBtn = document.getElementById('add-email-btn');

    // if (!select || !search || !chips) return;

    // // ----- Toggle Oui/Non -----
    // function majPartage() {
    //     const val = document.querySelector('input[name="partager_par_mail_choice"]:checked')?.value || "non";
    //     hidden.value = val;
    //     if (val === "oui") {
    //         bloc.classList.add("show");
    //     } else {
    //         bloc.classList.remove("show");
    //         Array.from(select.options).forEach(o => o.selected = false);
    //     }
    // }
    // radios.forEach(r => r.addEventListener("change", majPartage));
    // majPartage();

        // ----- Données -----
        const originalOptions = [...select.options].map(opt => ({
            value: opt.value,
            text:  opt.text,
            nom:   (opt.dataset.nom   || '').toLowerCase(),
            email: (opt.dataset.email || '').toLowerCase(),
            emailRaw: opt.dataset.email || opt.value
        }));

        let selectedValues = new Set();
        let manualEmails   = new Set();

        // ----- Helpers -----
        const rebuildOptions = (list) => {
            const scrollTop = select.scrollTop;
            select.innerHTML = '';
            list.forEach(item => {
                const o = document.createElement('option');
                o.value = item.value;
                o.text  = item.text;
                o.dataset.nom   = item.nom;
                o.dataset.email = item.emailRaw;
                o.selected = selectedValues.has(item.value);
                select.appendChild(o);
            });
            select.scrollTop = scrollTop;
        };

        const createChip = (email, onRemove, source) => {
            const chip = document.createElement("span");
            chip.className = "chip";
            chip.dataset.email = email.toLowerCase();
            chip.dataset.source = source || "unknown";
            chip.textContent = email;

            const btn = document.createElement("button");
            btn.type = "button";
            btn.textContent = "×";
            btn.addEventListener("click", onRemove);
            chip.appendChild(btn);

            const hiddenInput = document.createElement("input");
            hiddenInput.type = "hidden";
            hiddenInput.name = "emails_copie[]";
            hiddenInput.value = email;
            chip.appendChild(hiddenInput);

            return chip;
        };

        function renderChips() {
            chips.innerHTML = '';

            // ⚠️ Désélectionner toutes les options d'abord
            Array.from(select.options).forEach(o => o.selected = false);

            // 1. depuis le select
            selectedValues.forEach(val => {
                const opt = originalOptions.find(o => o.value === val);
                if (!opt) return;
                const chip = createChip(opt.emailRaw, () => {
                    selectedValues.delete(val);
                    renderChips();
                }, "select");
                chips.appendChild(chip);
            });

            // 2. manuels
            manualEmails.forEach(email => {
                const chip = createChip(email, () => {
                    // a) enlever de manualEmails
                    manualEmails.delete(email);

                    // b) supprimer le form caché correspondant (sinon email_contact[] part au POST)
                    const emailLower = email.toLowerCase();

                    container.querySelectorAll(".nouveau-contact-form").forEach(f => {
                        const emailAff = (f.querySelector('input[name="email_affiche"]')?.value || "").toLowerCase();
                        if (emailAff === emailLower) {
                            f.remove();
                        }
                    });

                    // c) refresh chips
                    renderChips();
                }, "manual");

                chips.appendChild(chip);
            });
        }

        // ----- Events -----
        select.addEventListener("change", () => {
            [...select.selectedOptions].forEach(opt => selectedValues.add(opt.value));
            renderChips();
        });

        search.addEventListener('input', () => {
            const q = search.value.trim().toLowerCase();
            if (!q) {
                rebuildOptions(originalOptions);
                addBtn.style.display = "none";
                return;
            }
            const filtered = originalOptions.filter(o =>
                o.text.toLowerCase().includes(q) || o.nom.includes(q) || o.email.includes(q)
            );
            rebuildOptions(filtered);
            addBtn.style.display = filtered.length === 0 ? "inline-block" : "none";
        });

            // Bouton + → insère seulement le formulaire
        addBtn.addEventListener("click", () => {
            const email = search.value.trim();
            const regex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
            if (!regex.test(email)) {
                alert("Adresse email invalide : " + email);
                return;
            }
            // if (document.querySelector(`.chip[data-email="${email.toLowerCase()}"]`)) {
            //     return; // doublon
            // }
            if (chips.querySelector(`.chip[data-email="${email.toLowerCase()}"]`)) {
                return; // doublon (dans CE formulaire uniquement)
            }

            // Clone le template
            const clone = tmpl.content.cloneNode(true);
            clone.querySelector("input[name='email_contact[]']").value = email;
            clone.querySelector("input[name='email_affiche']").value = email;

            // ✅ IMPORTANT : empêcher l'envoi au submit tant que pas validé
            const formEl = clone.querySelector(".nouveau-contact-form");
            formEl.dataset.pending = "1";

            // On retire les "name" (sauf email_affiche) mais on laisse éditable !
            formEl.querySelectorAll("input, select, textarea").forEach(el => {
                if (el.name === "email_affiche") return; // reste disabled dans le template
                if (el.name) {
                    el.dataset.name = el.name; // sauvegarde
                    el.removeAttribute("name"); // ne sera PAS envoyé au submit
                }
            });

            container.appendChild(clone);

            search.value = "";
            addBtn.style.display = "none";
        });

        // ----- Délégation boutons "Ajouter ce contact" / "Annuler" -----
        form.addEventListener("click", function (e) {
            if (e.target.classList.contains("btn-ajout-contact")) {
                const form = e.target.closest(".nouveau-contact-form");
                if (!form) return;

                const email = form.querySelector("input[name='email_affiche']").value;
                // const nom = form.querySelector("input[name='nom_contact[]']").value.trim();
                // const prenom = form.querySelector("input[name='prenom_contact[]']").value.trim();
                const nom = (form.querySelector("input[data-name='nom_contact[]']")?.value || "").trim();
                const prenom = (form.querySelector("input[data-name='prenom_contact[]']")?.value || "").trim();

                // ⚠️ Vérification Nom/Prénom
                if (!prenom || !nom) {
                    if (!confirm("Vous n'avez pas saisi de Nom ou de Prénom. Continuer ?")) return;
                }

                // Ajoute dans manualEmails et affiche la chip
                form.querySelectorAll("input, select, textarea").forEach(el => {
                    if (el.dataset.name) {
                        el.name = el.dataset.name;
                        delete el.dataset.name;
                    }
                });
                form.dataset.pending = "0";
                manualEmails.add(email);
                renderChips();

                // Garde le form pour le POST (mais caché)
                // document.getElementById("nouveaux-contacts-container").appendChild(form);
                form.style.display = "none";

                search.value = "";
                search.focus();
            }

            if (e.target.classList.contains("btn-annuler-ajout-contact")) {
                const form = e.target.closest(".nouveau-contact-form");
                if (form) form.remove();
            }
        });

        // ----- Init -----
        rebuildOptions(originalOptions);
        renderChips();

        form.addEventListener("submit", (event) => {
            const partageActif = form.querySelector(
                'input[name="partager_par_mail_choice"]:checked'
            )?.value === "oui";
            if (!partageActif) return;

            const destinataires = chips.querySelectorAll('input[name="emails_copie[]"]');
            if (!destinataires.length) {
                event.preventDefault();
                if (erreurValidation) {
                    erreurValidation.textContent = "Ajoutez au moins un destinataire pour partager l’acte par mail.";
                    erreurValidation.hidden = false;
                }
                search.focus();
                return;
            }

            if (erreurValidation) erreurValidation.hidden = true;

            const inputAnnexesMail = form.querySelector(".annexes-mail-input");
            if (inputAnnexesMail?.dataset.volumeValide === "non") {
                event.preventDefault();
                inputAnnexesMail.focus();
            }
        });
    });

    document.querySelectorAll(".annexes-piece-jointe-input").forEach((input) => {
        const liste = input.closest(".pieces-jointes-composeur")?.querySelector(".annexes-mail-liste");
        if (!liste) return;

        let fichiers = [];
        const estInputMail = input.classList.contains("annexes-mail-input");
        const estInputAnnexesDs = input.classList.contains("annexes-ds-input");
        const indicateurVolumeDs = input.closest(".partage-annexes-ds")?.querySelector(".annexes-ds-volume");
        const moduleMail = input.closest(".module-partage-mail");
        const indicateurVolume = input.closest(".pieces-jointes-composeur")?.querySelector(".mail-pj-volume");
        const tailleActe = Number.parseInt(moduleMail?.dataset.tailleActe || "", 10);
        const tailleMaxMailMo = Number.parseInt(moduleMail?.dataset.tailleMaxMailMo || "10", 10);
        const tailleMaxMail = tailleMaxMailMo * 1024 * 1024;

        const calculerTailleMailEstimee = (listeFichiers) => {
            if (!estInputMail || !Number.isFinite(tailleActe)) return null;
            const tailleAnnexes = listeFichiers.reduce((total, fichier) => total + fichier.size, 0);
            return Math.trunc((tailleActe + tailleAnnexes) * 4 / 3) + 512 * 1024;
        };

        const afficherVolumeMail = (listeFichiers) => {
            if (!estInputMail) return true;
            const tailleEstimee = calculerTailleMailEstimee(listeFichiers);
            const estValide = tailleEstimee === null || tailleEstimee <= tailleMaxMail;
            input.dataset.volumeValide = estValide ? "oui" : "non";

            if (indicateurVolume) {
                indicateurVolume.classList.toggle("est-invalide", !estValide);
                if (tailleEstimee === null) {
                    indicateurVolume.textContent = "Le volume total sera vérifié avant l’envoi.";
                } else {
                    const tailleMo = (tailleEstimee / (1024 * 1024)).toFixed(2).replace(".", ",");
                    indicateurVolume.textContent = estValide
                        ? `Volume total estimé du mail : ${tailleMo} Mo sur ${tailleMaxMailMo} Mo.`
                        : `Volume total estimé du mail : ${tailleMo} Mo sur ${tailleMaxMailMo} Mo. Retirez une ou plusieurs annexes.`;
                }
            }
            return estValide;
        };

        const afficherVolumeAnnexesDs = (listeFichiers) => {
            if (!estInputAnnexesDs || !indicateurVolumeDs) return;
            const tailleTotale = listeFichiers.reduce(
                (total, fichier) => total + fichier.size,
                0
            );
            indicateurVolumeDs.hidden = listeFichiers.length === 0;
            indicateurVolumeDs.textContent = `Volume total : ${(
                tailleTotale / (1024 * 1024)
            ).toFixed(2).replace(".", ",")} Mo sur 10 Mo.`;
        };

        const synchroniserInput = () => {
            const transfert = new DataTransfer();
            fichiers.forEach((fichier) => transfert.items.add(fichier));
            input.files = transfert.files;
            afficherVolumeMail(fichiers);
            afficherVolumeAnnexesDs(fichiers);
            if (input.classList.contains("annexes-ds-input")) {
                document.dispatchEvent(new CustomEvent("annexes-ds-modifiees"));
            }
        };

        const afficherFichiers = () => {
            liste.innerHTML = "";
            fichiers.forEach((fichier, index) => {
                const url = URL.createObjectURL(fichier);
                const ligne = document.createElement("div");
                ligne.className = "annexe-mail-row";

                const nom = document.createElement("a");
                nom.href = url;
                nom.target = "_blank";
                nom.rel = "noopener noreferrer";
                nom.textContent = fichier.name;
                nom.title = "Visualiser l’annexe";

                const infos = document.createElement("span");
                infos.className = "annexe-mail-infos";
                const taille = document.createElement("span");
                taille.className = "annexe-mail-taille";
                const tailleMo = fichier.size / (1024 * 1024);
                taille.textContent = tailleMo >= 0.1
                    ? `(${tailleMo.toFixed(2).replace(".", ",")} Mo)`
                    : `(${Math.max(1, Math.ceil(fichier.size / 1024))} Ko)`;
                infos.append(nom, taille);

                const telecharger = document.createElement("a");
                telecharger.href = url;
                telecharger.download = fichier.name;
                telecharger.className = "annexe-mail-action";
                telecharger.title = "Télécharger l’annexe";
                telecharger.setAttribute("aria-label", `Télécharger ${fichier.name}`);
                const iconeTelechargement = document.createElement("img");
                iconeTelechargement.src = input.dataset.downloadIcon;
                iconeTelechargement.alt = "";
                telecharger.appendChild(iconeTelechargement);

                const extension = fichier.name.split(".").pop()?.toLowerCase() || "";
                const estPdf = fichier.type === "application/pdf" || extension === "pdf";
                const extensionsImage = new Set(["png", "jpg", "jpeg", "gif", "webp", "svg", "bmp"]);
                const estImage = fichier.type.startsWith("image/") || extensionsImage.has(extension);

                let apercuContainer = null;
                if (estPdf || estImage) {
                    apercuContainer = document.createElement("span");
                    apercuContainer.className = "document-avec-apercu";

                    const apercu = document.createElement("button");
                    apercu.type = "button";
                    apercu.className = "annexe-mail-action document-apercu-trigger";
                    apercu.dataset.previewUrl = url;
                    apercu.dataset.previewType = estPdf ? "pdf" : "image";
                    apercu.title = "Visualiser l’annexe";
                    apercu.setAttribute("aria-label", `Visualiser ${fichier.name}`);

                    const iconeApercu = document.createElement("img");
                    iconeApercu.src = input.dataset.previewIcon;
                    iconeApercu.alt = "";
                    apercu.appendChild(iconeApercu);

                    const pont = document.createElement("span");
                    pont.className = "document-apercu-pont";
                    pont.setAttribute("aria-hidden", "true");

                    const popover = document.createElement("span");
                    popover.className = "document-apercu-popover";
                    popover.setAttribute("role", "tooltip");
                    const chargement = document.createElement("span");
                    chargement.className = "document-apercu-chargement";
                    chargement.textContent = "Chargement de l’aperçu…";
                    popover.appendChild(chargement);

                    apercuContainer.append(apercu, pont, popover);
                }

                const retirer = document.createElement("button");
                retirer.type = "button";
                retirer.className = "annexe-mail-retirer";
                retirer.title = "Retirer cette annexe";
                retirer.setAttribute("aria-label", `Retirer ${fichier.name}`);
                retirer.textContent = "×";
                retirer.addEventListener("click", () => {
                    URL.revokeObjectURL(url);
                    fichiers.splice(index, 1);
                    synchroniserInput();
                    afficherFichiers();
                });

                ligne.append(infos, telecharger);
                if (apercuContainer) ligne.appendChild(apercuContainer);
                ligne.appendChild(retirer);
                liste.appendChild(ligne);

                if (apercuContainer && window.initialiserApercuDocument) {
                    window.initialiserApercuDocument(
                        apercuContainer.querySelector(".document-apercu-trigger")
                    );
                }
            });
        };

        const ajouterFichiers = (nouveauxFichiers) => {
            const fichierTropLourd = nouveauxFichiers.find((fichier) => fichier.size > 10 * 1024 * 1024);
            if (fichierTropLourd) {
                alert(`La pièce jointe « ${fichierTropLourd.name} » dépasse la taille maximale de 10 Mo.`);
                input.value = "";
                synchroniserInput();
                return false;
            }

            const fichiersCandidats = [...fichiers];
            nouveauxFichiers.forEach((nouveauFichier) => {
                const dejaPresent = fichiersCandidats.some((fichier) => (
                    fichier.name === nouveauFichier.name
                    && fichier.size === nouveauFichier.size
                    && fichier.lastModified === nouveauFichier.lastModified
                ));
                if (!dejaPresent) fichiersCandidats.push(nouveauFichier);
            });

            if (estInputAnnexesDs) {
                const tailleTotale = fichiersCandidats.reduce(
                    (total, fichier) => total + fichier.size,
                    0
                );
                if (tailleTotale > 10 * 1024 * 1024) {
                    alert(
                        "La taille totale des annexes dépasse la limite autorisée de 10 Mo. "
                        + "Retirez une ou plusieurs annexes."
                    );
                    input.value = "";
                    synchroniserInput();
                    return false;
                }
            }

            if (!afficherVolumeMail(fichiersCandidats)) {
                alert(
                    `L’acte et les annexes dépassent la taille totale autorisée pour un mail `
                    + `(${tailleMaxMailMo} Mo, encodage compris). Retirez une ou plusieurs annexes.`
                );
                input.value = "";
                synchroniserInput();
                return false;
            }

            fichiers = fichiersCandidats;
            synchroniserInput();
            afficherFichiers();
            return true;
        };

        input.addEventListener("change", () => {
            ajouterFichiers(Array.from(input.files));
        });

        input.addEventListener("ajouter-fichiers", (event) => {
            ajouterFichiers(Array.from(event.detail?.fichiers || []));
        });
        input.addEventListener("verifier-volume", () => afficherVolumeMail(fichiers));
        afficherVolumeMail(fichiers);
        afficherVolumeAnnexesDs(fichiers);
    });

    document.querySelectorAll("form").forEach((form) => {
        const zoneAnnexesDs = form.querySelector(".zone-annexes-ds");
        const inputAnnexesDs = form.querySelector(".annexes-ds-input");
        if (!zoneAnnexesDs || !inputAnnexesDs) return;

        const radiosAnnexesDs = form.querySelectorAll('input[name="transmettre_annexes_ds"]');
        radiosAnnexesDs.forEach((radio) => {
            radio.addEventListener("change", () => {
                const transmettre = form.querySelector(
                    'input[name="transmettre_annexes_ds"]:checked'
                )?.value === "oui";
                zoneAnnexesDs.hidden = !transmettre;
            });
        });

        const inputAnnexesMail = form.querySelector(".annexes-mail-input");
        const reprendreAnnexesDs = form.querySelector(".mail-reprendre-annexes-ds");
        const actualiserRaccourciAnnexesDs = () => {
            if (reprendreAnnexesDs) {
                reprendreAnnexesDs.hidden = !(inputAnnexesDs.files?.length > 0);
            }
        };

        document.addEventListener("annexes-ds-modifiees", actualiserRaccourciAnnexesDs);
        reprendreAnnexesDs?.addEventListener("click", () => {
            if (!inputAnnexesMail || !inputAnnexesDs.files?.length) return;
            inputAnnexesMail.dispatchEvent(new CustomEvent("ajouter-fichiers", {
                detail: { fichiers: Array.from(inputAnnexesDs.files) }
            }));
        });
        actualiserRaccourciAnnexesDs();
    });

    const ajusterTextarea = (textarea) => {
        textarea.style.height = "auto";
        textarea.style.height = `${Math.max(textarea.scrollHeight + 4, 128)}px`;
    };

    document.querySelectorAll(".form-acceptation-textarea").forEach((textarea) => {
        ajusterTextarea(textarea);
        textarea.addEventListener("input", () => ajusterTextarea(textarea));
    });

    const formulaireAcceptation = document.getElementById("formulaire-acceptation");
    if (formulaireAcceptation) {
        new MutationObserver(() => {
            if (!formulaireAcceptation.classList.contains("show")) return;
            formulaireAcceptation.querySelectorAll(".form-acceptation-textarea").forEach(ajusterTextarea);
        }).observe(formulaireAcceptation, { attributes: true, attributeFilter: ["class"] });
    }
});

document.addEventListener("DOMContentLoaded", () => {
    const TAILLE_MAX_FICHIER = 20 * 1024 * 1024;
    const TAILLE_MAX_TOTAL = 100 * 1024 * 1024;

    const formaterTaille = (taille) => taille < 1024 * 1024
        ? `${Math.ceil(taille / 1024)} Ko`
        : `${(taille / (1024 * 1024)).toFixed(1).replace(".", ",")} Mo`;

    document.querySelectorAll(".infos-docs").forEach((blocDocuments) => {
        const formulaire = blocDocuments.querySelector(".documents-zip-form");
        if (!formulaire) return;

        const boutonZip = formulaire.querySelector(".btn-mode-zip");
        const boutonCompresser = formulaire.querySelector(".btn-telecharger-zip");
        const boutonAnnuler = formulaire.querySelector(".btn-annuler-zip");
        const zoneExterne = blocDocuments.querySelector(".documents-zip-externes");
        const zoneDepot = zoneExterne?.querySelector(".documents-zip-depot");
        const inputFichiers = zoneExterne?.querySelector(".documents-zip-fichier-input");
        const listeFichiers = zoneExterne?.querySelector(".documents-zip-externes-liste");
        const lignesDocuments = Array.from(blocDocuments.querySelectorAll("[data-zip-document]"));
        let fichiersExternes = [];
        let prochainId = 1;

        const nombreSelectionne = () => {
            const internes = lignesDocuments.filter((ligne) => ligne.querySelector(":scope > .document-zip-checkbox")?.checked).length;
            return internes + fichiersExternes.filter((entree) => entree.checked).length;
        };

        const actualiserCompteur = () => {
            const nombre = nombreSelectionne();
            boutonCompresser.textContent = `Compresser (${nombre} fichier${nombre > 1 ? "s" : ""})`;
        };

        const actualiserInputFichiers = (selectionSeulement = false) => {
            if (!inputFichiers || typeof DataTransfer === "undefined") return;
            const transfert = new DataTransfer();
            fichiersExternes
                .filter((entree) => !selectionSeulement || entree.checked)
                .forEach((entree) => transfert.items.add(entree.file));
            inputFichiers.files = transfert.files;
        };

        const afficherFichiersExternes = () => {
            if (!listeFichiers) return;
            listeFichiers.replaceChildren();
            fichiersExternes.forEach((entree) => {
                const ligne = document.createElement("li");
                ligne.className = "document-zip-externe-item";

                const caseACocher = document.createElement("input");
                caseACocher.type = "checkbox";
                caseACocher.checked = entree.checked;
                caseACocher.className = "document-zip-checkbox";
                caseACocher.setAttribute("aria-label", `Inclure ${entree.file.name} dans le ZIP`);
                caseACocher.addEventListener("change", () => {
                    entree.checked = caseACocher.checked;
                    actualiserCompteur();
                });

                const nom = document.createElement("span");
                nom.className = "document-zip-externe-nom";
                nom.textContent = entree.file.name;
                nom.title = entree.file.name;

                const taille = document.createElement("span");
                taille.className = "document-zip-externe-taille";
                taille.textContent = formaterTaille(entree.file.size);

                const retirer = document.createElement("button");
                retirer.type = "button";
                retirer.className = "document-zip-externe-retirer";
                retirer.textContent = "×";
                retirer.title = `Retirer ${entree.file.name}`;
                retirer.setAttribute("aria-label", `Retirer ${entree.file.name}`);
                retirer.addEventListener("click", () => {
                    fichiersExternes = fichiersExternes.filter((fichier) => fichier.id !== entree.id);
                    actualiserInputFichiers();
                    afficherFichiersExternes();
                    actualiserCompteur();
                });

                ligne.append(caseACocher, nom, taille, retirer);
                listeFichiers.appendChild(ligne);
            });
        };

        const ajouterFichiers = (fichiers) => {
            const nouveaux = Array.from(fichiers);
            const tropVolumineux = nouveaux.find((fichier) => fichier.size > TAILLE_MAX_FICHIER);
            if (tropVolumineux) {
                window.alert(`${tropVolumineux.name} dépasse la limite de 20 Mo par fichier.`);
                return;
            }
            const tailleActuelle = fichiersExternes.reduce((total, entree) => total + entree.file.size, 0);
            const tailleAjoutee = nouveaux.reduce((total, fichier) => total + fichier.size, 0);
            if (tailleActuelle + tailleAjoutee > TAILLE_MAX_TOTAL) {
                window.alert("La taille totale des fichiers externes ne peut pas dépasser 100 Mo.");
                return;
            }
            nouveaux.forEach((file) => fichiersExternes.push({ id: prochainId++, file, checked: true }));
            actualiserInputFichiers();
            afficherFichiersExternes();
            actualiserCompteur();
        };

        const quitterSelection = () => {
            blocDocuments.classList.remove("zip-selection-active");
            blocDocuments.querySelectorAll(".document-zip-checkbox").forEach((caseACocher) => caseACocher.remove());
            formulaire.querySelectorAll('input[name="documents"]').forEach((input) => input.remove());
            fichiersExternes = [];
            actualiserInputFichiers();
            afficherFichiersExternes();
            zoneExterne.hidden = true;
            boutonZip.hidden = false;
            boutonCompresser.hidden = true;
            boutonAnnuler.hidden = true;
        };

        boutonZip.addEventListener("click", () => {
            blocDocuments.classList.add("zip-selection-active");
            lignesDocuments.forEach((ligne) => {
                if (ligne.querySelector(":scope > .document-zip-checkbox")) return;
                const caseACocher = document.createElement("input");
                caseACocher.type = "checkbox";
                caseACocher.checked = true;
                caseACocher.className = "document-zip-checkbox";
                caseACocher.setAttribute("aria-label", "Inclure ce document dans le ZIP");
                caseACocher.addEventListener("change", actualiserCompteur);
                ligne.prepend(caseACocher);
            });
            zoneExterne.hidden = false;
            boutonZip.hidden = true;
            boutonCompresser.hidden = false;
            boutonAnnuler.hidden = false;
            actualiserCompteur();
        });

        boutonAnnuler.addEventListener("click", quitterSelection);
        zoneDepot?.addEventListener("click", () => inputFichiers.click());
        inputFichiers?.addEventListener("change", () => ajouterFichiers(inputFichiers.files));

        ["dragenter", "dragover"].forEach((typeEvenement) => zoneDepot?.addEventListener(typeEvenement, (event) => {
            event.preventDefault();
            zoneDepot.classList.add("is-drag-over");
        }));
        ["dragleave", "drop"].forEach((typeEvenement) => zoneDepot?.addEventListener(typeEvenement, (event) => {
            event.preventDefault();
            zoneDepot.classList.remove("is-drag-over");
        }));
        zoneDepot?.addEventListener("drop", (event) => ajouterFichiers(event.dataTransfer.files));

        formulaire.addEventListener("submit", (event) => {
            formulaire.querySelectorAll('input[name="documents"]').forEach((input) => input.remove());
            const selectionInterne = lignesDocuments.filter((ligne) => ligne.querySelector(":scope > .document-zip-checkbox")?.checked);
            if (!selectionInterne.length && !fichiersExternes.some((entree) => entree.checked)) {
                event.preventDefault();
                window.alert("Sélectionnez au moins un document à compresser.");
                return;
            }
            selectionInterne.forEach((ligne) => {
                const input = document.createElement("input");
                input.type = "hidden";
                input.name = "documents";
                input.value = ligne.dataset.zipDocument;
                formulaire.appendChild(input);
            });
            actualiserInputFichiers(true);
        });
    });
});

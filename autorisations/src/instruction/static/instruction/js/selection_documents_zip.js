document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".infos-docs").forEach((blocDocuments) => {
        const formulaire = blocDocuments.querySelector(".documents-zip-form");
        if (!formulaire) return;

        const boutonZip = formulaire.querySelector(".btn-mode-zip");
        const boutonCompresser = formulaire.querySelector(".btn-telecharger-zip");
        const boutonAnnuler = formulaire.querySelector(".btn-annuler-zip");
        const lignesDocuments = Array.from(
            blocDocuments.querySelectorAll("[data-zip-document]")
        );

        const quitterSelection = () => {
            blocDocuments.classList.remove("zip-selection-active");
            blocDocuments.querySelectorAll(".document-zip-checkbox").forEach((caseACocher) => {
                caseACocher.remove();
            });
            formulaire.querySelectorAll('input[name="documents"]').forEach((input) => input.remove());
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
                ligne.prepend(caseACocher);
            });
            boutonZip.hidden = true;
            boutonCompresser.hidden = false;
            boutonAnnuler.hidden = false;
        });

        boutonAnnuler.addEventListener("click", quitterSelection);

        formulaire.addEventListener("submit", (event) => {
            formulaire.querySelectorAll('input[name="documents"]').forEach((input) => input.remove());
            const selection = lignesDocuments.filter((ligne) => (
                ligne.querySelector(":scope > .document-zip-checkbox")?.checked
            ));

            if (!selection.length) {
                event.preventDefault();
                window.alert("Sélectionnez au moins un document à compresser.");
                return;
            }

            selection.forEach((ligne) => {
                const input = document.createElement("input");
                input.type = "hidden";
                input.name = "documents";
                input.value = ligne.dataset.zipDocument;
                formulaire.appendChild(input);
            });
        });
    });
});

// Regroupe le code JS mutualisable pour preinstruction_dossier.html et instruction_dosier.html


// ---------------------------------------------------------------------------
// --------------------- Menu déroulant Etape dossier ------------------------
// ---------------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", function () {
    const toggleBtn = document.getElementById("etapeMenuToggle");
    const menuContent = document.getElementById("etapeMenuContent");

    if (!toggleBtn || !menuContent) return;

    const dropdownWrapper = toggleBtn.closest(".etat-badge-menu-dropdown");
    if (!dropdownWrapper) return;
    
    toggleBtn.addEventListener("click", function (e) {
        e.stopPropagation();

        const isOpen = !dropdownWrapper.classList.contains("open");

        if (isOpen) {
            menuContent.classList.add("show");
            dropdownWrapper.classList.add("open");

            // Appliquer la hauteur comme margin-bottom
            const hauteur = menuContent.scrollHeight;
            dropdownWrapper.style.marginBottom = `${hauteur}px`;
        } else {
            menuContent.classList.remove("show");
            dropdownWrapper.classList.remove("open");
            dropdownWrapper.style.marginBottom = "";
        }
    });

    document.addEventListener("click", function (e) {
        if (!dropdownWrapper.contains(e.target)) {
            menuContent.classList.remove("show");
            dropdownWrapper.classList.remove("open");
            dropdownWrapper.style.marginBottom = "";
        }
    });
});



// ---------------------------------------------------------------------------
// ------- POP UP de validation du changement de groupe instructeur ----------
// ---------------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", function() {
    const select = document.getElementById("select-changer-groupe");
    const form = document.getElementById("form-changer-groupe");

    if (!select || !form) return;

    select.addEventListener("change", function() {
        const selectedOption = select.options[select.selectedIndex].text;
        const confirmed = confirm("Voulez-vous vraiment affecter ce dossier au groupe : « " + selectedOption + " » ?");

        if (confirmed) {
            form.submit();
        } else {
            // Réinitialise le select sur le placeholder
            select.selectedIndex = 0;
        }
    });
});



// ------------------------------------------------------------------------------
// --------------------------- Bouton actualiser --------------------------------
// ------------------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", function () {
    const refreshForm = document.querySelector(".refresh-doss form");
    const refreshButton = document.querySelector(".refresh-button");

    if (!refreshForm || !refreshButton) return;

    refreshForm.addEventListener("submit", function () {
        const icon = refreshButton.dataset.icon;

        refreshButton.disabled = true;
        refreshButton.innerHTML = `
            <img src="${icon}" class="refresh-icon" />
            Traitement en cours...
        `;
    });
});



// ------------------------------------------------------------------
// --------------------------- NOTES --------------------------------
// ------------------------------------------------------------------

// Pop up confirmer suppression annexe
function confirmerSuppressionAnnexe(bouton) {
    const ok = confirm("Êtes-vous sûr de vouloir supprimer définitivement cette annexe du dossier ?");
    if (ok) {
        bouton.closest("form").submit();
    }
}


function copierPath(button, path) {
    if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(path)
            .then(() => afficherFeedbackCopie(button))
            .catch(err => fallbackCopie(button, path, err));
    } else {
        fallbackCopie(button, path);
    }
}

function afficherFeedbackCopie(button) {
    const feedback = button.nextElementSibling;
    if (!feedback) return;

    feedback.classList.add("show");
    setTimeout(() => {
        feedback.classList.remove("show");
    }, 2000);
}

function fallbackCopie(button, path, originalError = null) {
    try {
        const textarea = document.createElement("textarea");
        textarea.value = path;
        textarea.setAttribute("readonly", "");
        textarea.style.position = "fixed";
        textarea.style.left = "-9999px";
        document.body.appendChild(textarea);

        textarea.select();
        textarea.setSelectionRange(0, textarea.value.length);

        const ok = document.execCommand("copy");
        document.body.removeChild(textarea);

        if (ok) {
            afficherFeedbackCopie(button);
        } else {
            throw new Error("Copie impossible");
        }
    } catch (err) {
        alert(
            "Erreur lors de la copie du chemin."
            + (originalError ? "\nCause initiale : " + originalError : "")
        );
    }
}


// Sauvegarde automatique brouillon note
document.addEventListener("DOMContentLoaded", function () {

    const textarea = document.getElementById("nouvelle-note-textarea");
    if (!textarea) return;

    const userEmail = textarea.dataset.user;
    const dossierId = textarea.dataset.dossier;

    if (!userEmail || !dossierId) return;

    const storageKey = `note_temp_${userEmail}_${dossierId}`;

    // restauration
    const saved = localStorage.getItem(storageKey);
    if (saved !== null) { textarea.value = saved; }

    // sauvegarde
    textarea.addEventListener("input", function () { localStorage.setItem(storageKey, textarea.value); });

    // suppression après envoi
    const form = textarea.closest("form");
    if (form) {
        form.addEventListener("submit", function () { localStorage.removeItem(storageKey); });
    }
});



// ------------------------------------------------------------------
// --------------------- Nom du dossier éditable --------------------
// ------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", function () {
    const bloc = document.getElementById("nomDossierBloc");
    if (!bloc) return;

    const btnEdit = document.getElementById("btnEditNom");
    const btnValidate = document.getElementById("btnValidateNom");
    const texte = document.getElementById("nomDossierTexte");
    const input = document.getElementById("nomDossierInput");

    if (!btnEdit || !btnValidate || !texte || !input) return;

    const saveUrl = bloc.dataset.saveUrl;
    if (!saveUrl) return;

    function getCookie(name) {
        const value = `; ${document.cookie}`;
        const parts = value.split(`; ${name}=`);
        if (parts.length === 2) return parts.pop().split(";").shift();
        return "";
    }

    const csrfToken = getCookie("csrftoken");
    let oldValue = input.value || "";

    function enterEditMode() {
        oldValue = input.value || texte.textContent.trim() || "";
        bloc.classList.add("is-editing");
        input.focus();
        input.select();
    }

    function exitEditMode(reset = true) {
        if (reset) input.value = oldValue;
        bloc.classList.remove("is-editing");
    }

    async function save() {
        const newValue = (input.value || "").trim();

        if (!newValue) {
            exitEditMode(true);
            return;
        }

        try {
            const resp = await fetch(saveUrl, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": csrfToken,
                    "X-Requested-With": "XMLHttpRequest",
                },
                body: JSON.stringify({
                    nom_dossier_plus_parlant: newValue
                }),
            });

            if (!resp.ok) {
                throw new Error("HTTP " + resp.status);
            }

            const data = await resp.json();

            texte.textContent = data.nom_dossier_plus_parlant;
            input.value = data.nom_dossier_plus_parlant;

            exitEditMode(false);
        } catch (e) {
            console.error(e);
            exitEditMode(true);
            alert("Impossible d'enregistrer le nom du dossier.");
        }
    }

    btnEdit.addEventListener("click", function (e) {
        e.stopPropagation();
        enterEditMode();
    });

    btnValidate.addEventListener("click", function (e) {
        e.stopPropagation();
        save();
    });

    input.addEventListener("keydown", function (e) {
        if (e.key === "Enter") {
            e.preventDefault();
            save();
        } else if (e.key === "Escape") {
            e.preventDefault();
            exitEditMode(true);
        }
    });

    document.addEventListener("mousedown", function (e) {
        if (!bloc.classList.contains("is-editing")) return;
        if (!bloc.contains(e.target)) {
            exitEditMode(true);
        }
    });
});



// ------------------------------------------------------------------
// -------- Annulation ou écrasement document en cas de doublon -----
// ------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", function () {
    const input = document.getElementById("file-upload");
    if (!input) return;

    const form = input.closest("form");
    if (!form) return;

    const script = document.getElementById("emplacements-existants");
    if (!script) return;

    const dossierEmplacement = input.dataset.dossier;
    if (!dossierEmplacement) {
        console.warn("data-dossier manquant sur #file-upload");
        return;
    }

    let emplacements = [];
    try {
        emplacements = JSON.parse(script.textContent);
    } catch (e) {
        console.error("Erreur parsing emplacements-existants :", e);
        return;
    }

    input.addEventListener("change", function () {
        const fichier = input.files[0];
        if (!fichier) return;

        const emplacement = `${dossierEmplacement}Annexes/${fichier.name}`;

        if (emplacements.includes(emplacement)) {
            const confirmReplace = confirm(
                `Un fichier nommé "${fichier.name}" existe déjà. Voulez-vous le remplacer ?`
            );

            if (!confirmReplace) {
                input.value = "";
                return;
            }
        }

        form.submit();
    });
});


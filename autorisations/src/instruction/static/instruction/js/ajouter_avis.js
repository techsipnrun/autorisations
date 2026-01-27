document.addEventListener("DOMContentLoaded", function () {
    const form = document.getElementById("form-avis");

    // Champs principaux
    const nature       = document.getElementById("nature");
    const thematique   = document.getElementById("thematique");
    const modeContact  = document.getElementById("mode_contact");
    const formulation  = document.getElementById("formulation_avis");

    // Experts
    const blocInterne  = document.getElementById("bloc_expert_interne");
    const blocExterne  = document.getElementById("bloc_expert_externe");
    const expertInterne = document.getElementById("expert_interne");
    const expertExterne = document.getElementById("expert_externe");

    // Pièces jointes
    const blocAutresPJ = document.getElementById("bloc_autres_pj_avis");
    const blocPJ_demandeAvis = document.getElementById("bloc_pj_demande_avis");
    const blocPJ_rapportCS   = document.getElementById("bloc_pj_rapport_cs");
    const blocPJ_projetActe  = document.getElementById("bloc_pj_projet_acte");
    const pjDemandeAvis = document.getElementById("pj_demande_avis");
    const pjProjetActe  = document.getElementById("pj_projet_acte");

    // ---- Masquer / afficher selon la nature ----
    function toggleExperts() {
        [blocInterne, blocExterne, blocPJ_demandeAvis, blocPJ_rapportCS, blocPJ_projetActe, blocAutresPJ]
            .forEach(b => b.style.display = "none");

        const selected = nature.options[nature.selectedIndex]?.text.trim();

        if (selected === "Consultation en interne") {
            blocInterne.style.display = "flex";
            blocPJ_demandeAvis.style.display = "flex";
            blocAutresPJ.style.display = "flex";
        } 
        else if (selected === "Demande à une instance") {
            blocExterne.style.display = "flex";
            // expertExterne.required = true;
            blocPJ_demandeAvis.style.display = "flex";
            blocAutresPJ.style.display = "flex";
            blocPJ_rapportCS.style.display = "flex";
            blocPJ_projetActe.style.display = "flex";
        }
    }

    nature.addEventListener("change", toggleExperts);
    toggleExperts(); // au chargement


    // Mettre un astérisque au champ 'Joindre la demande d'avis (Word)'
    const labelPJDemandeAvis = document.getElementById("label_pj_demande_avis");
    function toggleAsteriskPJDemandeAvis() {
        const selected = nature.options[nature.selectedIndex]?.text.trim();

        if (selected === "Consultation en interne") {
            // pas d’astérisque
            labelPJDemandeAvis.textContent = "Joindre la demande d'avis (Word)";
        } else {
            // astérisque
            labelPJDemandeAvis.textContent = "Joindre la demande d'avis (Word)*";
        }
    }

    nature.addEventListener("change", toggleAsteriskPJDemandeAvis);
    toggleAsteriskPJDemandeAvis(); // au chargement





    // ########################
    // Formulation de l'avis
    // ########################
    function mettreDefaultFormulationSiVide() {
        // Ne jamais écraser un texte déjà écrit (avis existant ou saisi par l'utilisateur)

        // if (formulation.value.trim() !== "") return;

        const selected = nature.options[nature.selectedIndex]?.text.trim();
        console.log({selected})
        if (!selected || selected === "Consultation en interne") {
            formulation.value = `Bonjour,

Je vous consulte sur ce dossier car [saisir la raison].

Merci d’avance pour votre retour.`;
        } else if (selected === "Demande à une instance") {
            formulation.value = "Bonjour, vous trouverez ci-joint la demande d'avis associée au dossier.";
        } else {
            formulation.value = "";
        }
    }

    // Déclenche le changement lorsqu'on sélectionne la nature
    nature.addEventListener("change", mettreDefaultFormulationSiVide);

    // Appel au chargement
    mettreDefaultFormulationSiVide();



    // ---- Gestion des required selon bouton ----
    function resetRequired() {
        [nature, thematique, modeContact, formulation,
         expertInterne, expertExterne, pjDemandeAvis, pjProjetActe].forEach(el => {
            if (el) el.required = false;
        });
    }

    function setRequired(buttonType) {
        resetRequired();

        // toujours obligatoires
        nature.required = true;
        thematique.required = true;
        modeContact.required = true;

        const selected = nature.options[nature.selectedIndex]?.text.trim();

        if (selected === "Consultation en interne") {
            expertInterne.required = true;
        }

        if (selected === "Demande à une instance") {
        expertExterne.required = true;

        if (buttonType === "confirmer") {
            if (pjDemandeAvis.dataset.exists !== "true") {
                pjDemandeAvis.required = true;
            }
            if (pjProjetActe.dataset.exists !== "true") {
                pjProjetActe.required = true;
            }
        }
    }

        if (buttonType === "confirmer") {
            formulation.required = true;     
        }
    }

    function handleSubmit(e, buttonType) {
        e.preventDefault();
        setRequired(buttonType);

        if (!form.checkValidity()) {
            form.reportValidity();
            return;
        }

         // 💬 Confirmation avant envoi pour les boutons "confirmer"
        if (buttonType === "confirmer") {
            const ok = confirm("Voulez-vous vraiment envoyer la demande d'avis ?");
            if (!ok) return; // annule l'envoi si l'utilisateur clique sur Annuler
        }

        const action = e.target.getAttribute("formaction") || form.getAttribute("action");
        form.setAttribute("action", action);
        form.submit();
    }

    // ---- Boutons ----
    document.querySelector(".main-btn").addEventListener("click", e => handleSubmit(e, "confirmer"));
    document.querySelector(".btn-confirmer-envoi").addEventListener("click", e => handleSubmit(e, "confirmer"));
    document.querySelector(".btn-brouillon").addEventListener("click", e => handleSubmit(e, "brouillon"));

    // ---- Menu déroulant ----
    document.querySelectorAll(".btn-dropdown .toggle-btn").forEach(btn => {
        btn.addEventListener("click", e => {
            e.stopPropagation();
            const parent = btn.closest(".btn-dropdown");
            document.querySelectorAll(".btn-dropdown.show").forEach(open => {
                if (open !== parent) open.classList.remove("show");
            });
            parent.classList.toggle("show");
        });
    });

    document.addEventListener("click", e => {
        document.querySelectorAll(".btn-dropdown.show").forEach(open => {
            if (!open.contains(e.target)) open.classList.remove("show");
        });
    });
});

// ---- Fonctions utilitaires ----
// function copierChemin(chemin) {
//     navigator.clipboard.writeText(chemin)
//         .then(() => alert("Chemin copié dans le presse-papiers :\n" + chemin))
//         .catch(err => alert("Impossible de copier le chemin : " + err));
// }

function copierChemin(chemin) {
    if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(chemin)
            .then(() => alert("Chemin copié dans le presse-papiers :\n" + chemin))
            .catch(err => alert("Erreur de copie : " + err));
    } else {
        // Fallback : création d’un input caché
        const input = document.createElement("textarea");
        input.value = chemin;
        document.body.appendChild(input);
        input.select();
        try {
            document.execCommand("copy");
            alert("Chemin copié dans le presse-papiers :\n" + chemin);
        } catch (err) {
            alert("Impossible de copier le chemin : " + err);
        }
        document.body.removeChild(input);
    }
}

function supprimerDoc(avisId, champ) {
    if (!confirm("Supprimer ce document ?")) return;
    fetch(`/avis/${avisId}/supprimer-doc/${champ}/`, {
        method: "POST",
        headers: { "X-CSRFToken": "{{ csrf_token }}" }
    })
    .then(resp => resp.ok ? location.reload() : alert("Erreur suppression : " + resp.status))
    .catch(err => alert("Erreur réseau : " + err));
}





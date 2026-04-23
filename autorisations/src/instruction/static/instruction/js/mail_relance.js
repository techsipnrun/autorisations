
function afficherFormulaireRelanceDemandeur() {
    const formulaire = document.getElementById("formulaire-relance-demandeur");

    if (formulaire.classList.contains("show")) {
        formulaire.classList.remove("show");
    } else {
        formulaire.classList.add("show");
    }
}

function emailRelanceExiste(email) {
    const emails = document.querySelectorAll('#selected-chips-relance .chip');
    return Array.from(emails).some(chip =>
        (chip.dataset.email || "").toLowerCase() === email.toLowerCase()
    );
}

function ajouterEmailRelance() {
    const input = document.getElementById("nouvel-email-relance");
    const container = document.getElementById("selected-chips-relance");
    const hiddenContainer = document.getElementById("hidden-emails-relance");

    if (!input) return;

    const email = (input.value || "").trim();
    if (!email) return;

    const emailValide = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
    if (!emailValide) {
        alert("Veuillez saisir une adresse email valide.");
        return;
    }

    if (emailRelanceExiste(email)) {
        input.value = "";
        return;
    }

    const chip = document.createElement("span");
    chip.className = "chip";
    chip.dataset.email = email;
    chip.innerHTML = `
        ${email}
        <button type="button" onclick="retirerEmailRelance(this)">×</button>
    `;
    container.appendChild(chip);

    const hidden = document.createElement("input");
    hidden.type = "hidden";
    hidden.name = "emails[]";
    hidden.value = email;
    hidden.className = "hidden-email-relance";
    hiddenContainer.appendChild(hidden);

    input.value = "";
    toggleBoutonAjoutEmailRelance();
}

function retirerEmailRelance(button) {
    const chip = button.closest(".chip");
    if (!chip) return;

    const email = chip.dataset.email;
    chip.remove();

    const hiddenInputs = document.querySelectorAll('.hidden-email-relance');
    hiddenInputs.forEach(input => {
        if ((input.value || "").toLowerCase() === (email || "").toLowerCase()) {
            input.remove();
        }
    });
}

function toggleBoutonAjoutEmailRelance() {
    const input = document.getElementById("nouvel-email-relance");
    const btn = document.getElementById("add-email-relance-btn");
    if (!input || !btn) return;

    btn.style.display = input.value.trim() ? "inline-flex" : "none";
}

function confirmerRelanceDemandeur(button) {
    const form = document.querySelector(".form-relance-demandeur");
    if (!form) return;

    const dests = form.querySelectorAll('input[name="emails[]"]');
    if (!dests.length) {
        alert("Veuillez renseigner au moins un destinataire.");
        return;
    }

    if (!form.checkValidity()) {
        form.reportValidity();
        return;
    }

    const confirmation = confirm("Confirmez-vous l'envoi de ce mail de relance ?");
    if (!confirmation) return;

    const boutons = form.querySelectorAll('button, input[type="submit"]');
    boutons.forEach(btn => btn.disabled = true);

    if (button) {
        button.innerText = "Envoi en cours...";
    }

    form.submit();
}

document.addEventListener("DOMContentLoaded", function () {
    const input = document.getElementById("nouvel-email-relance");
    if (input) {
        input.addEventListener("input", toggleBoutonAjoutEmailRelance);

        input.addEventListener("keydown", function (e) {
            if (e.key === "Enter") {
                e.preventDefault();
                ajouterEmailRelance();
            }
        });
    }

    toggleBoutonAjoutEmailRelance();
});


function fermerFormulaireRelanceDemandeur() {
    const formulaire = document.getElementById("formulaire-relance-demandeur");
    if (formulaire) {
        formulaire.classList.remove("show");
    }
}

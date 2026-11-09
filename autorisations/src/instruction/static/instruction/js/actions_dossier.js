// Contrôleur commun aux composants d'archivage DN et à leurs formulaires.
document.addEventListener("click", function (event) {
    const bouton = event.target.closest("[data-ouvrir-formulaire], [data-confirmer-action]");
    if (!bouton) return;
    masquerToutesZonesComplementaires();
    if (bouton.hasAttribute("data-ouvrir-formulaire")) {
        const zone = Array.from(document.querySelectorAll("[data-action-form]"))
            .find(element => element.dataset.actionForm === bouton.dataset.ouvrirFormulaire);
        if (zone) zone.classList.add("show");
    } else if (window.confirm(bouton.dataset.confirmerAction)) {
        // Archivage direct : mêmes champs POST et même soumission qu'auparavant.
        bouton.closest("form").requestSubmit();
    }
    fermerMenuEtape();
});

// Tous les changements d'étape partagent le même écran d'attente, une fois
// les validations et confirmations terminées. requestSubmit() préserve aussi
// les contrôles métier branchés sur l'événement submit.
const etapesEnCours = new WeakSet();
document.addEventListener("submit", function (event) {
    const form = event.target;
    if (!form.matches(".zone-envoyer-pour-validation form, #etapeMenuContent form") || event.defaultPrevented) return;
    if (etapesEnCours.has(form)) { event.preventDefault(); return; }
    const attente = document.getElementById("envoi-acte-attente");
    if (!attente) return;
    etapesEnCours.add(form);
    const titre = document.getElementById("attente-action-titre");
    const detail = document.getElementById("attente-action-detail");
    if (titre) titre.textContent = "Changement d’étape en cours…";
    if (detail) detail.textContent = "Veuillez patienter pendant le traitement du dossier.";
    attente.hidden = false;
});
window.addEventListener("pageshow", function (event) {
    if (!event.persisted) return;
    document.querySelectorAll(".zone-envoyer-pour-validation form, #etapeMenuContent form").forEach(form => etapesEnCours.delete(form));
    const attente = document.getElementById("envoi-acte-attente");
    if (attente) attente.hidden = true;
});

// Les justificatifs conservent la limite de 10 Mo contrôlée aussi par le serveur.
document.addEventListener("change", function (event) {
    const input = event.target;
    if (!input.matches("[data-action-form] input[type='file'][data-taille-max]")) return;
    const fichier = input.files[0];
    const message = fichier && fichier.size > Number(input.dataset.tailleMax)
        ? "Le justificatif dépasse la taille maximale autorisée de 10 Mo." : "";
    input.setCustomValidity(message);
    if (message) input.reportValidity();
});

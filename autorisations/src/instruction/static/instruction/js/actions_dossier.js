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
        bouton.closest("form").submit();
    }
    fermerMenuEtape();
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

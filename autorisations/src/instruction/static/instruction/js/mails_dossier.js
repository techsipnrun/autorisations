document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-mails-dossier]").forEach((blocMails) => {
        const bouton = blocMails.querySelector("[data-toggle-mails]");
        if (!bouton) {
            return;
        }

        const libelle = bouton.querySelector("[data-toggle-mails-libelle]");
        const nombreMailsMasques = bouton.dataset.nombreMailsMasques;

        bouton.addEventListener("click", () => {
            const estDeplie = blocMails.classList.toggle("mails-dossier--deplie");
            bouton.setAttribute("aria-expanded", String(estDeplie));
            libelle.textContent = estDeplie
                ? "Masquer les mails supplémentaires"
                : `Afficher les ${nombreMailsMasques} autres mails`;
        });
    });
});

document.addEventListener("DOMContentLoaded", async () => {
    const warning = document.getElementById("dn-api-unavailable-warning");
    const statusUrl = warning?.dataset.statusUrl;
    if (!warning || !statusUrl) return;

    try {
        const response = await fetch(statusUrl, {
            credentials: "same-origin",
            headers: { "X-Requested-With": "XMLHttpRequest" },
        });
        if (!response.ok) return;

        const status = await response.json();
        warning.hidden = !status.indisponible;
    } catch (_) {
        // On conserve l'état rendu par le serveur si le contrôle lui-même échoue.
    }
});

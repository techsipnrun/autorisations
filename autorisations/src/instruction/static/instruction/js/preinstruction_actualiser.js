document.addEventListener("DOMContentLoaded", function () {
    const bouton = document.getElementById("btn-actualiser");
    const message = document.getElementById("message-actualisation");

    if (!bouton) return;

    // Lire l'heure de la dernière actualisation
    const saved = localStorage.getItem("derniere_actualisation");
    const savedTimestamp = localStorage.getItem("derniere_actualisation_timestamp");

    const now = new Date();
    const nowTimestamp = now.getTime();

    if (saved && savedTimestamp) {
        const delta = nowTimestamp - parseInt(savedTimestamp);
        const minutes = Math.floor(delta / 60000);

        if (minutes >= 15) {
            message.textContent = `⏳ Aucune actualisation depuis plus de 15 minutes… actualisation automatique.`;
            lancerActualisation();
        } else {
            message.textContent = `✅ Dernière actualisation à ${saved}`;
        }
    } else {
        const jj = now.getDate().toString().padStart(2, '0');
        const mm = (now.getMonth() + 1).toString().padStart(2, '0');
        const yyyy = now.getFullYear();
        message.textContent = `ℹ️ Aucune actualisation encore réalisée (en ce jour : ${jj}/${mm}/${yyyy})`;
    }

    bouton.addEventListener("click", function (e) {
        e.preventDefault();
        lancerActualisation();
    });

    function lancerActualisation() {
        const url = bouton.dataset.url;
        const csrf = bouton.dataset.csrf;

        bouton.disabled = true;
        message.textContent = "⏳ Actualisation en cours...";

        fetch(url, {
            method: "POST",
            headers: {
                "X-CSRFToken": csrf,
                "Content-Type": "application/json"
            }
        })
        .then(response => response.json())
        .then(data => {
            const checkInterval = setInterval(() => {
                fetch("/etat-actualisation/")
                    .then(response => response.json())
                    .then(result => {
                        if (result.en_cours === false) {
                            clearInterval(checkInterval);

                            const now = new Date();
                            const hh = now.getHours().toString().padStart(2, '0');
                            const mm = now.getMinutes().toString().padStart(2, '0');
                            const heureFinale = `${hh}h${mm}`;

                            localStorage.setItem("derniere_actualisation", heureFinale);
                            localStorage.setItem("derniere_actualisation_timestamp", now.getTime().toString());

                            message.textContent = `✅ Dernière actualisation à ${heureFinale}`;
                            bouton.disabled = false;

                            // Rechargement automatique de la page
                            setTimeout(() => {
                                location.reload();
                            }, 100);  // laisse le temps au navigateur d'afficher le message
                            
                        }
                    });
            }, 5000);
        })
        .catch(error => {
            console.error("Erreur AJAX :", error);
            message.textContent = "❌ Échec de l'actualisation.";
            bouton.disabled = false;
        });
    }
});


// Mise à jour automatique dans les autres onglets via localStorage
window.addEventListener("storage", function (e) {
    if (e.key === "derniere_actualisation") {
        const nouvelleHeure = e.newValue;
        if (nouvelleHeure) {
            message.textContent = `✅ Dernière actualisation à ${nouvelleHeure}`;
        }
    }
});

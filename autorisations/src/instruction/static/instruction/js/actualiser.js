document.addEventListener("DOMContentLoaded", function () {
    const bouton = document.getElementById("btn-actualiser");
    const message = document.getElementById("message-actualisation");
    if (!bouton) return;

    const urlEtat = "/etat-actualisation/"; // lit SynchronisationEtat en BDD
    let pollTimer = null;

    // --- helpers ---
    function setBouton(disabled, texte) {
        bouton.disabled = !!disabled;
        if (texte) message.textContent = texte;
    }
    function lireEtatBDD() {
        return fetch(urlEtat).then(r => r.json());
    }
    function afficherDerniereHeure() {
        const saved = localStorage.getItem("derniere_actualisation");
        const savedTs = localStorage.getItem("derniere_actualisation_timestamp");
        if (saved && savedTs) {
            message.textContent = `✅ Dernière actualisation à ${saved}`;
        } else {
            message.textContent = `ℹ️ Aucune actualisation encore réalisée`;
        }
    }
    function peutEtreLancerAuto() {
        // Ne s’appuie que sur localStorage pour la décision d’auto-lancement
        const saved = localStorage.getItem("derniere_actualisation");
        const savedTs = localStorage.getItem("derniere_actualisation_timestamp");
        if (saved && savedTs) {
            const minutes = Math.floor((Date.now() - parseInt(savedTs, 10)) / 60000);
            if (minutes >= 240) {
                lancerActualisation(); // va re-vérifier la BDD et désactiver le bouton
                return true;
            } else {
                message.textContent = `✅ Dernière actualisation à ${saved}`;
                return false;
            }
        } else {
            message.textContent = `ℹ️ Aucune actualisation encore réalisée`;
            return false;
        }
    }
    function demarrerPolling() {
        if (pollTimer) return;
        pollTimer = setInterval(() => {
            lireEtatBDD()
                .then(({ en_cours }) => {
                    if (!en_cours) {
                        arreterPolling();

                        const now = new Date();
                        const hh = now.getHours().toString().padStart(2, '0');
                        const mm = now.getMinutes().toString().padStart(2, '0');
                        const heureFinale = `${hh}h${mm}`;

                        localStorage.setItem("derniere_actualisation", heureFinale);
                        localStorage.setItem("derniere_actualisation_timestamp", now.getTime().toString());

                        setBouton(false, `✅ Dernière actualisation à ${heureFinale}`);

                        // Recharger pour refléter les nouvelles données
                        setTimeout(() => location.reload(), 100);
                    } else {
                        setBouton(true, "⏳ Actualisation en cours...");
                    }
                })
                .catch(() => {
                    // problème réseau -> ne pas réactiver le bouton
                    console.warn("Impossible de lire l'état de synchro.");
                });
        }, 5000);
    }
    function arreterPolling() {
        if (pollTimer) {
            clearInterval(pollTimer);
            pollTimer = null;
        }
    }

    // --- Au chargement : source de vérité = BDD ---
    lireEtatBDD()
        .then(({ en_cours }) => {
            if (en_cours) {
                setBouton(true, "⏳ Actualisation déjà en cours...");
                demarrerPolling();
            } else {
                // Pas en cours : décider si on auto-lance (si > 240 min) ou juste afficher l'heure
                setBouton(false);
                const autoLance = peutEtreLancerAuto();
                if (!autoLance) {
                    // rien à faire de plus
                }
            }
        })
        .catch(() => {
            // si on ne peut pas vérifier, on n’auto-lance pas à l’aveugle
            setBouton(false, "⚠️ Impossible de vérifier l'état.");
            afficherDerniereHeure();
        });

    // --- Clic utilisateur ---
    bouton.addEventListener("click", function (e) {
        e.preventDefault();
        lancerActualisation();
    });

    function lancerActualisation() {
        const url = bouton.dataset.url;
        const csrf = bouton.dataset.csrf;

        setBouton(true, "⏳ Actualisation en cours...");

        fetch(url, {
            method: "POST",
            headers: {
                "X-CSRFToken": csrf,
                "Content-Type": "application/json"
            }
        })
        .then(r => r.json())
        .then(() => {
            demarrerPolling();
        })
        .catch(err => {
            console.error("Erreur lors du lancement d'actualisation :", err);
            setBouton(false, "❌ Échec de l'actualisation.");
        });
    }

    // --- Si l’onglet redevient visible, re-vérifier immédiatement la BDD ---
    document.addEventListener("visibilitychange", () => {
        if (document.visibilityState === "visible") {
            lireEtatBDD()
                .then(({ en_cours }) => {
                    if (en_cours) {
                        setBouton(true, "⏳ Actualisation en cours...");
                        demarrerPolling();
                    } else {
                        arreterPolling();
                        setBouton(false);
                        // On peut relancer auto si > 240 min (ex: onglet ouvert depuis longtemps)
                        peutEtreLancerAuto();
                    }
                })
                .catch(() => {/* noop */});
        }
    });

    // --- Synchronisation visuelle inter-onglets (affichage uniquement) ---
    window.addEventListener("storage", function (e) {
        if (e.key === "derniere_actualisation") {
            const nouvelleHeure = e.newValue;
            if (nouvelleHeure) {
                message.textContent = `✅ Dernière actualisation à ${nouvelleHeure}`;
                // ne touche pas au disabled !
            }
        }
    });
});

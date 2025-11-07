document.addEventListener("DOMContentLoaded", function () {
    const bouton = document.getElementById("btn-actualiser");
    const message = document.getElementById("message-actualisation");

    if (!bouton) return;

    const urlEtat = "/etat-actualisation/";
    let pollTimer = null;

    // --- helpers ---
    function setBouton(disabled, texte) {
        bouton.disabled = !!disabled;
        if (texte) message.textContent = texte;
    }

    function lireEtatBDD() {
        return fetch(urlEtat).then(r => r.json());
    }

    // Affichage basé uniquement sur l’état retourné par le backend
    function afficherDerniereHeure() {
        lireEtatBDD()
            .then(({ date_maj, dernier_statut, date_derniere_tentative }) => {

                if (!date_maj) {
                    message.textContent = "Aucune actualisation encore réalisée";
                    return;
                }

                const date = new Date(date_maj);
                const date_affichage = `${date.getHours().toString().padStart(2, '0')}h${date.getMinutes().toString().padStart(2, '0')}`;

                if (dernier_statut === "erreur") {

                    if (date_derniere_tentative) {
                        message.textContent = `Échec de la dernière synchronisation à (${formatDate(date_derniere_tentative)})`;
                    }

                    else {
                        message.textContent = `Échec de la dernière synchronisation (${date_affichage})`;
                    }
                } 
                
                else {
                    message.textContent = `Dernière synchronisation : ${date_affichage}`;
                }


            })
            .catch(() => {
                message.textContent = `⚠️ Impossible de récupérer la dernière actualisation.`;
            });
    }

    // Décision d’auto-lancement basée uniquement sur date_maj de la BDD
    function peutEtreLancerAuto() {
        return lireEtatBDD()
            .then(({ date_maj, en_cours }) => {
                if (en_cours) return false;

                if (!date_maj) {
                    message.textContent = `Dernière synchronisation : Aucune actualisation encore réalisée`;
                    return false;
                }

                const [hh, mm] = date_maj.split("h").map(Number);
                const date = new Date(date_maj);
                const minutesDepuis = Math.floor((Date.now() - date.getTime()) / 60000);

                console.log("minutesDepuis =", minutesDepuis);
                const date_affichage = `${date.getHours().toString().padStart(2, '0')}h${date.getMinutes().toString().padStart(2, '0')}`;
                
                // Si dernière synchro date depuis + de 4h
                if (minutesDepuis >= 240) {
                    lancerActualisation();
                    return true;
                } else {
                    // message.textContent = `Dernière synchronisation : ${date_maj}`;
                    message.textContent = `Dernière synchronisation : ${date_affichage}`;
                    return false;
                }
            })
            .catch(() => {
                message.textContent = `⚠️ Erreur lors de la vérification de l'état.`;
                return false;
            });
    }

    function demarrerPolling() {
        if (pollTimer) return;
        pollTimer = setInterval(() => {
            lireEtatBDD()
                .then(({ en_cours, date_maj, dernier_statut }) => {
                    if (!en_cours) {
                        arreterPolling();
                        const date = new Date(date_maj);
                        const date_affichage = `${date.getHours().toString().padStart(2, '0')}h${date.getMinutes().toString().padStart(2, '0')}`;
                        setBouton(false, `Dernière synchronisation : ${date_affichage}`);
                        setTimeout(() => location.reload(), 100);
                    } else {
                        setBouton(true, "⏳ Actualisation en cours...");
                    }
                })
                .catch(() => {
                    console.warn("Impossible de lire l'état de synchro.");
                });
        }, 10000);
    }

    function arreterPolling() {
        if (pollTimer) {
            clearInterval(pollTimer);
            pollTimer = null;
        }
    }

    // --- Chargement initial ---
    lireEtatBDD()
        .then(({ en_cours, date_maj, dernier_statut }) => {
            if (en_cours) {
                setBouton(true, "⏳ Actualisation déjà en cours...");
                demarrerPolling();
            } else {
                setBouton(false);
                if (!date_maj) {
                    message.textContent = "Dernière synchronisation : Aucune actualisation encore réalisée";
                } else {
                    
                    const date = new Date(date_maj);
                    const date_affichage = `${date.getHours().toString().padStart(2, '0')}h${date.getMinutes().toString().padStart(2, '0')}`;
                    message.textContent = `Dernière synchronisation : ${date_affichage}`;

                    peutEtreLancerAuto();
                }
            }
        })
        .catch(() => {
            setBouton(false, "⚠️ Impossible de vérifier l'état.");
            afficherDerniereHeure();
        });

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

    // --- Re-check si onglet devient actif ---
    document.addEventListener("visibilitychange", () => {
        if (document.visibilityState === "visible") {
            lireEtatBDD()
                .then(({ en_cours, date_maj, dernier_statut }) => {
                    if (en_cours) {
                        setBouton(true, "⏳ Actualisation en cours...");
                        demarrerPolling();
                    } else {
                        arreterPolling();
                        const date = new Date(date_maj);
                        const date_affichage = `${date.getHours().toString().padStart(2, '0')}h${date.getMinutes().toString().padStart(2, '0')}`;
                        setBouton(false, `Dernière synchronisation : ${date_affichage}`);

                        peutEtreLancerAuto();
                    }
                })
                .catch(() => { /* noop */ });
        }
    });

});

document.addEventListener("DOMContentLoaded", function () {
    const bouton = document.getElementById("btn-actualiser");
    const message = document.getElementById("message-actualisation");
    if (!bouton) return;

    const urlEtat = "/etat-actualisation/";
    let pollTimer = null;

    // --- helpers ---
    function setBouton(disabled, texte) {
        bouton.disabled = !!disabled;
        if (texte) message.innerHTML = texte;
    }

    function lireEtatBDD() {
        return fetch(urlEtat).then(r => r.json());
    }

    // Convertit une date ISO ou SQL en timestamp
    function toMs(s) {
        if (!s) return null;
        const str = s.includes("T") ? s : s.replace(" ", "T");
        const t = Date.parse(str);
        return Number.isNaN(t) ? null : t;
    }

    // 🕓 Format abrégé : ven. 08/11 à 15h19
    function formatDateAbregee(s) {
        const t = toMs(s);
        if (t === null) return null;
        const d = new Date(t);

        const jours = ["dim.", "lun.", "mar.", "mer.", "jeu.", "ven.", "sam."];
        const jourNom = jours[d.getDay()];
        const jour = String(d.getDate()).padStart(2, "0");
        const mois = String(d.getMonth() + 1).padStart(2, "0");
        const heure = String(d.getHours()).padStart(2, "0");
        const minute = String(d.getMinutes()).padStart(2, "0");

        return `${jourNom} ${jour}/${mois} à ${heure}h${minute}`;
    }

    // --- affichage principal ---
    function afficherDerniereHeure() {
        lireEtatBDD()
            .then(({ en_cours, date_maj, date_derniere_tentative, dernier_statut }) => {
                // Si synchro en cours → message et bouton désactivé
                if (en_cours) {
                    setBouton(true, "⏳ Actualisation déjà en cours...");
                    return;
                }

                const tMaj = toMs(date_maj);
                const tTent = toMs(date_derniere_tentative);
                const hMaj = formatDateAbregee(date_maj);
                const hTent = formatDateAbregee(date_derniere_tentative);

                if (tMaj === null && tTent === null) {
                    setBouton(false, "Aucune actualisation encore réalisée");
                    return;
                }

                // 🔹 Priorité au statut "erreur"
                if (dernier_statut === "erreur") {
                    if (tMaj !== null && tTent !== null && tTent >= tMaj) {
                        setBouton(false, `🟢 Dernière synchronisation : ${hMaj}<br>🔴 Dernière tentative échouée : ${hTent}`);
                    } else if (tMaj === null && tTent !== null) {
                        setBouton(false, `🔴 Dernière synchronisation échouée : ${hTent}`);
                    } else {
                        setBouton(false, `🔴 Dernière tentative échouée`);
                    }
                    return;
                }

                // 🔹 Succès
                if (tMaj !== null) {
                    const prefix = (dernier_statut === "ok") ? "🟢 " : "";
                    setBouton(false, `${prefix}Dernière synchronisation : ${hMaj}`);
                    return;
                }

                setBouton(false, "⚠️ Aucune synchronisation disponible.");
            })
            .catch(() => {
                setBouton(false, "⚠️ Impossible de récupérer la dernière actualisation.");
            });
    }


async function lancerActualisation() {
    const url = bouton.dataset.url;
    const csrf = bouton.dataset.csrf;

    setBouton(true, "⏳ Lancement de la synchronisation...");

    try {
        const resp = await fetch(url, {
            method: "POST",
            headers: {
                "X-CSRFToken": csrf,
                "Content-Type": "application/json"
            }
        });

        if (!resp.ok) {
            throw new Error(`Erreur HTTP ${resp.status}`);
        }

        const data = await resp.json();

        if (data.status === "already_running") {
            setBouton(true, "⏳ Synchronisation déjà en cours...");
        } else {
            setBouton(true, "⏳ Synchronisation en cours...");
        }

        // 🌀 On démarre le polling
        demarrerPolling();
        return true;

    } catch (err) {
        console.error("Erreur lors du lancement d'actualisation :", err);
        setBouton(false, "❌ Échec de l'actualisation.");
        return false;
    }
}


    // --- auto-lancement si >2h, basé sur la DERNIÈRE TENTATIVE ---
function peutEtreLancerAuto() {
    return lireEtatBDD()
        .then(({ en_cours, date_derniere_tentative, date_maj, dernier_statut }) => {

            // 🚫 Si synchro en cours → on ne lance pas
            if (en_cours) return false;

            // On prend la dernière tentative si elle existe,
            // sinon on se rabat sur la dernière synchro réussie
            const refDate = date_derniere_tentative || date_maj;
            if (!refDate) return false;

            const t = Date.parse(refDate.includes("T") ? refDate : refDate.replace(" ", "T"));
            if (Number.isNaN(t)) return false;

            const minutesDepuis = Math.floor((Date.now() - t) / 60000);

            // 🕓 Si plus de 2 heures depuis la dernière tentative → on relance
            if (minutesDepuis >= 120) {
                lancerActualisation();
                return true;
            }

            return false;
        })
        .catch(() => false);
}


    // --- polling ---
    function demarrerPolling() {
        if (pollTimer) return;
        pollTimer = setInterval(() => {
            lireEtatBDD()
                .then(({ en_cours }) => {
                    if (!en_cours) {
                        // 🔒 On garde le bouton désactivé tant qu'on ne recharge pas
                        arreterPolling();
                        setBouton(true, "Actualisation terminée, rafraîchissement...");
                        setTimeout(() => location.reload(), 1000);
                    } else {
                        setBouton(true, "⏳ Actualisation en cours...");
                    }
                })
                .catch(() => console.warn("Impossible de lire l'état de synchro."));
        }, 10000);
    }

    function arreterPolling() {
        if (pollTimer) {
            clearInterval(pollTimer);
            pollTimer = null;
        }
    }

    // --- initialisation au chargement ---
    lireEtatBDD()
        .then(({ en_cours, dernier_statut }) => {
            if (en_cours) {
                // 🔒 Garde-fou si synchro déjà active (même ouverte ailleurs)
                setBouton(true, "⏳ Actualisation déjà en cours...");
                demarrerPolling();
            } else {
                setBouton(false);
                afficherDerniereHeure();
                if (dernier_statut !== "erreur") {
                    peutEtreLancerAuto();
                }
            }
        })
        .catch(() => {
            setBouton(false, "⚠️ Impossible de vérifier l'état.");
        });

    // --- lancer une actualisation manuelle ---
    bouton.addEventListener("click", async function (e) {
        e.preventDefault();

        // 🔒 Empêche les doubles clics immédiats
        if (bouton.disabled) return;

        setBouton(true, "⏳ Vérification de l'état...");

        try {
            const etat = await lireEtatBDD();

            // Si une synchro est déjà en cours → on bloque
            if (etat.en_cours) {
                setBouton(true, "⏳ Synchronisation déjà en cours...");
                return;
            }

            // 🔸 Lancement sécurisé
            const url = bouton.dataset.url;
            const csrf = bouton.dataset.csrf;

            setBouton(true, "⏳ Lancement de la synchronisation...");
            const resp = await fetch(url, {
                method: "POST",
                headers: {
                    "X-CSRFToken": csrf,
                    "Content-Type": "application/json"
                }
            });

            if (!resp.ok) throw new Error("Erreur réseau");
            const data = await resp.json();

            if (data.status === "already_running") {
                setBouton(true, "⏳ Synchronisation déjà en cours...");
                return;
            }

            // 🌀 Synchro lancée avec succès → on démarre le polling
            setBouton(true, "⏳ Synchronisation en cours...");
            demarrerPolling();

        } catch (err) {
            console.error("Erreur lors du lancement :", err);
            setBouton(false, "❌ Échec du lancement de l'actualisation.");
        }
    });


    // --- recheck quand on revient sur l'onglet ---
    document.addEventListener("visibilitychange", () => {
        if (document.visibilityState === "visible") {
            lireEtatBDD()
                .then(({ en_cours, dernier_statut }) => {
                    if (en_cours) {
                        setBouton(true, "⏳ Actualisation en cours...");
                        demarrerPolling();
                    } else {
                        arreterPolling();
                        afficherDerniereHeure();
                        if (dernier_statut !== "erreur") {
                            peutEtreLancerAuto();
                        }
                    }
                })
                .catch(() => { /* noop */ });
        }
    });
});

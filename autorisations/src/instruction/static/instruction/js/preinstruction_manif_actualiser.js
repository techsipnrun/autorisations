document.addEventListener("DOMContentLoaded", function () {
    const form = document.querySelector(".refresh-doss-manif form");
    const button = document.getElementById("btn-sync-manif");
    const statusEl = document.getElementById("sync-manif-status");

    if (!form || !button || !statusEl) return;

    const etatUrl = form.dataset.etatUrl;
    const icon = button.dataset.icon;
    const csrf = form.querySelector("[name=csrfmiddlewaretoken]")?.value;

    let pollTimer = null;

    function setBouton(disabled, texteBouton) {
        button.disabled = !!disabled;
        button.innerHTML = `
            <img src="${icon}" alt="Synchroniser" class="refresh-icon">
            ${texteBouton || "Actualiser les dossiers Manifestations sportives"}
        `;
    }

    function setStatus(type, html) {
        statusEl.className = `sync-inline-status ${type || ""}`;
        statusEl.innerHTML = html || "";
    }

    function lireEtatBDD() {
        return fetch(etatUrl, {
            headers: { "X-Requested-With": "XMLHttpRequest" },
            credentials: "same-origin",
        }).then(r => r.json());
    }

    function toMs(s) {
        if (!s) return null;
        const str = s.includes("T") ? s : s.replace(" ", "T");
        const t = Date.parse(str);
        return Number.isNaN(t) ? null : t;
    }

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

    function afficherEtat(data) {
        const {
            en_cours,
            statut,
            date,
            message,
            synchro_globale_en_cours
        } = data;

        // garde-fou principal : synchro globale
        if (synchro_globale_en_cours) {
            setBouton(true, "Traitement indisponible");
            setStatus("warning", "🟠 Synchronisation globale en cours");
            return;
        }

        if (en_cours || statut === "running") {
            setBouton(true, "Traitement en cours...");
            setStatus("running", "🟠 Synchronisation en cours...");
            return;
        }

        setBouton(false, "Actualiser les dossiers Manifestations sportives");

        if (statut === "error") {
            if (date) {
                setStatus(
                    "error",
                    `🔴 Dernière tentative échouée : ${formatDateAbregee(date)}${message ? ` — ${message}` : ""}`
                );
            } else {
                setStatus(
                    "error",
                    `🔴 Dernière synchronisation en erreur${message ? ` — ${message}` : ""}`
                );
            }
            return;
        }

        if (statut === "success") {
            if (date) {
                setStatus("success", `🟢 Dernière synchronisation : ${formatDateAbregee(date)}`);
            } else {
                setStatus("success", "🟢 Dernière synchronisation réussie");
            }
            return;
        }

        setStatus("", "Aucune synchronisation encore réalisée");
    }

    function arreterPolling() {
        if (pollTimer) {
            clearInterval(pollTimer);
            pollTimer = null;
        }
    }

    function demarrerPolling() {
        if (pollTimer) return;

        pollTimer = setInterval(() => {
            lireEtatBDD()
                .then((data) => {
                    afficherEtat(data);

                    if (!data.en_cours && data.statut !== "running") {
                        arreterPolling();
                    }
                })
                .catch(() => {
                    setBouton(false, "Actualiser les dossiers Manifestations sportives");
                    setStatus("error", "⚠️ Impossible de récupérer l’état de synchronisation.");
                    arreterPolling();
                });
        }, 5000);
    }

    async function lancerActualisation() {
        setBouton(true, "Vérification de l'état...");
        setStatus("running", "🟠 Vérification en cours...");

        try {
            // 1. relire l’état juste avant lancement
            const etat = await lireEtatBDD();

            if (etat.synchro_globale_en_cours) {
                afficherEtat(etat);
                return false;
            }

            if (etat.en_cours || etat.statut === "running") {
                setBouton(true, "Traitement en cours...");
                setStatus("running", "🟠 Synchronisation déjà en cours...");
                demarrerPolling();
                return false;
            }

            // 2. lancer la synchro
            setBouton(true, "Lancement...");
            setStatus("running", "🟠 Lancement de la synchronisation...");

            const resp = await fetch(form.action, {
                method: "POST",
                headers: {
                    "X-CSRFToken": csrf,
                    "X-Requested-With": "XMLHttpRequest",
                    "Content-Type": "application/json",
                },
                credentials: "same-origin",
            });

            const data = await resp.json();

            if (!resp.ok) {
                if (data.status === "blocked_global") {
                    setBouton(true, "Traitement indisponible");
                    setStatus("warning", `🟠 ${data.message || "Synchronisation globale en cours"}`);
                    return false;
                }

                if (data.status === "already_running") {
                    setBouton(true, "Traitement en cours...");
                    setStatus("running", `🟠 ${data.message || "Synchronisation déjà en cours..."}`);
                    demarrerPolling();
                    return false;
                }

                throw new Error(data.message || `Erreur HTTP ${resp.status}`);
            }

            if (data.status === "blocked_global") {
                setBouton(true, "Traitement indisponible");
                setStatus("warning", `🟠 ${data.message || "Synchronisation globale en cours"}`);
                return false;
            }

            if (data.status === "already_running") {
                setBouton(true, "Traitement en cours...");
                setStatus("running", `🟠 ${data.message || "Synchronisation déjà en cours..."}`);
                demarrerPolling();
                return false;
            }

            setBouton(true, "Traitement en cours...");
            setStatus("running", "🟠 Synchronisation en cours...");
            demarrerPolling();
            return true;

        } catch (err) {
            console.error("Erreur lors du lancement :", err);
            setBouton(false, "Actualiser les dossiers Manifestations sportives");
            setStatus(
                "error",
                "🔴 Échec du lancement de la synchronisation — Vous pouvez en informer le support technique."
            );
            return false;
        }
    }

    // état initial
    lireEtatBDD()
        .then((data) => {
            afficherEtat(data);
            if (data.en_cours || data.statut === "running") {
                demarrerPolling();
            }
        })
        .catch(() => {
            setBouton(false, "Actualiser les dossiers Manifestations sportives");
            setStatus("error", "⚠️ Impossible de vérifier l’état de la synchronisation.");
        });

    // lancement manuel
    form.addEventListener("submit", function (e) {
        e.preventDefault();
        e.stopPropagation();

        if (button.disabled) return;

        lancerActualisation();
        return false;
    });

    // si on revient sur l’onglet
    document.addEventListener("visibilitychange", () => {
        if (document.visibilityState === "visible") {
            lireEtatBDD()
                .then((data) => {
                    afficherEtat(data);
                    if (data.en_cours || data.statut === "running") {
                        demarrerPolling();
                    } else {
                        arreterPolling();
                    }
                })
                .catch(() => {});
        }
    });
});
document.addEventListener("DOMContentLoaded", () => {
    const form = document.getElementById("form-avis");
    if (!form) return;
    const nature = form.querySelector("#nature");
    const interne = form.querySelector("#expert_interne");
    const externe = form.querySelector("#expert_externe");
    const destinataire = form.querySelector("#destinataire");
    const formulation = form.querySelector("#formulation_avis");
    let texteAuto = null;
    let enCours = false;

    function afficher(id, visible) {
        const bloc = form.querySelector("#" + id);
        bloc.hidden = !visible;
        bloc.style.display = visible ? "flex" : "none";
        bloc.querySelectorAll("input, select, textarea").forEach(champ => {
            champ.disabled = !visible;
            champ.required = false;
        });
    }
    function actualiser() {
        const type = nature.selectedOptions[0]?.textContent.trim();
        const consultation = type === "Consultation en interne";
        const instance = type === "Demande à une instance";
        afficher("bloc_expert_interne", consultation);
        afficher("bloc_expert_externe", instance);
        if (!consultation) interne.value = "";
        if (!instance) externe.value = "";
        const estCS = instance && externe.selectedOptions[0]?.dataset.estCs === "true";
        afficher("bloc_destinataire_cs", estCS);
        if (estCS && !destinataire.value) destinataire.value = "CS";
        if (!estCS) destinataire.value = "";
        afficher("bloc_pj_demande_avis", instance);
        afficher("bloc_pj_rapport_cs", instance);
        afficher("bloc_pj_projet_acte", instance);
        afficher("bloc_pj_avis", consultation || instance);
        afficher("bloc_note_avis", consultation || instance);
        afficher("bloc_formulation_avis", consultation || instance);
        form.querySelector(".div-btn-confirmer-envoi").hidden = !(consultation || instance);
        form.querySelector("#label_pj_lie_avis").textContent = consultation
            ? "Pièces jointes à transmettre :" : "Autres pièce(s) jointe(s) liée(s) à l'avis :";
        interne.required = consultation;
        externe.required = instance;
        destinataire.required = estCS;
        form.querySelector("#pj_demande_avis").required = instance;
        form.querySelector("#pj_projet_acte").required = instance;
        formulation.required = consultation || instance;
        if (!formulation.value.trim() || formulation.value === texteAuto) {
            texteAuto = consultation ? "Bonjour,\n\nJe vous consulte car [saisir la raison].\n\nMerci d’avance pour votre retour."
                : instance ? "Bonjour, vous trouverez ci-joint la demande d'avis." : "";
            formulation.value = texteAuto;
        }
    }
    nature.addEventListener("change", actualiser);
    externe.addEventListener("change", actualiser);
    actualiser();
    form.addEventListener("submit", event => {
        if (enCours) { event.preventDefault(); return; }
        enCours = true;
        form.querySelector("button[type=submit]").disabled = true;
    });
    window.addEventListener("pageshow", event => {
        if (!event.persisted) return;
        enCours = false;
        form.querySelector("button[type=submit]").disabled = false;
    });
});

document.addEventListener("DOMContentLoaded", () => {
    const form = document.getElementById("form-avis");
    if (!form || !window.AvisFormulaires?.initialiser(form)) return;
    let enCours = false;

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

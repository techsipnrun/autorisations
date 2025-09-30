document.addEventListener("DOMContentLoaded", function () {
    const typeAvis = document.getElementById("type_avis");
    const blocDansAppli = document.querySelector(".form_avis_dans_appli");
    const blocHorsAppli = document.querySelector(".form_avis_hors_appli");

    const nature = document.getElementById("nature");
    const blocInterne = document.getElementById("bloc_expert_interne");
    const blocExterne = document.getElementById("bloc_expert_externe");
    const expertInterne = document.getElementById("expert_interne");
    const expertExterne = document.getElementById("expert_externe");

    // ---- Affiche/masque les grands blocs selon type_avis ----
    function toggleFormAvis() {
        blocDansAppli.style.display = "none";
        blocHorsAppli.style.display = "none";

        if (typeAvis.value === "avis_sur_application") {
            blocDansAppli.style.display = "block";
        } else if (typeAvis.value === "avis_hors_application") {
            blocHorsAppli.style.display = "block";
            toggleExperts(); // ajuste experts en même temps
        }
    }

    // ---- Affiche/masque experts selon nature ----
    function toggleExperts() {
        if (!nature) return;

        blocInterne.style.display = "none";
        blocExterne.style.display = "none";

        // reset required
        expertInterne.removeAttribute("required");
        expertExterne.removeAttribute("required");

        const selectedText = nature.options[nature.selectedIndex]?.text.trim();

        if (selectedText === "Consultation en interne") {
            blocInterne.style.display = "block";
            expertInterne.setAttribute("required", "required");
        } else if (selectedText === "Demande à une instance") {
            blocExterne.style.display = "block";
            expertExterne.setAttribute("required", "required");
        }
    }

    // Events
    typeAvis.addEventListener("change", toggleFormAvis);
    if (nature) {
        nature.addEventListener("change", toggleExperts);
    }

    // Init au chargement
    toggleFormAvis();
});

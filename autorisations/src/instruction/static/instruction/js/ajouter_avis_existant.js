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




document.addEventListener("DOMContentLoaded", function () {
    // Si recherche soumise, forcer l'affichage du bloc "avis sur application"
    if (window.location.search.includes("numero=") ||
        window.location.search.includes("expert=") ||
        window.location.search.includes("demandeur=") ||
        window.location.search.includes("date_demande=") ||
        window.location.search.includes("date_reponse=") ||
        window.location.search.includes("favorable=") ||
        window.location.search.includes("thematique=") ||
        window.location.search.includes("nature=") ||
        window.location.search.includes("deja_lie=")) {
        
        const typeAvis = document.getElementById("type_avis");
        if (typeAvis) {
            typeAvis.value = "avis_sur_application"; // force le select
            typeAvis.dispatchEvent(new Event("change")); // simule un changement
        }
    }

    // Affichage gris --> noir si champ selectionné
    // document.querySelectorAll(".select-filtre").forEach(sel => {
    //     function updateColor() {
    //         if (sel.value === "") {
    //             sel.style.color = "#aaa";
    //         } else {
    //             sel.style.color = "#000";
    //         }
    //     }
    //     sel.addEventListener("change", updateColor);
    //     updateColor(); // init au chargement
    // });
});

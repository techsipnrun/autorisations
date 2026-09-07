document.addEventListener("DOMContentLoaded", function () {
    const form = document.getElementById("form-avis");

    // Champs principaux
    const nature       = document.getElementById("nature");
    const thematique   = document.getElementById("thematique");
    const demarche     = document.getElementById("demarche");
    const formulation  = document.getElementById("formulation_avis");

    // Experts
    const blocInterne  = document.getElementById("bloc_expert_interne");
    const blocExterne  = document.getElementById("bloc_expert_externe");
    const expertInterne = document.getElementById("expert_interne");
    const expertExterne = document.getElementById("expert_externe");
    const blocDestinataireCS = document.getElementById("bloc_destinataire_cs");
    const destinataire = document.getElementById("destinataire");

    function toggleDestinataireCS() {
        const natureSelectionnee = nature.options[nature.selectedIndex]?.text.trim();
        const visible = natureSelectionnee === "Demande à une instance"
            && expertExterne?.selectedOptions[0]?.dataset.estCs === "true";
        blocDestinataireCS.hidden = !visible;
        blocDestinataireCS.style.display = visible ? "flex" : "none";
        destinataire.required = visible;
        if (!visible) {
            destinataire.value = "";
        }
    }

    expertExterne.addEventListener("change", toggleDestinataireCS);
    toggleDestinataireCS();

    // Pièces jointes
    const blocPJ_demandeAvis = document.getElementById("bloc_pj_demande_avis");
    const blocPJ_rapportCS   = document.getElementById("bloc_pj_rapport_cs");

    const blocPJ_projetActe  = document.getElementById("bloc_pj_projet_acte");
    const blocPJ_avis  = document.getElementById("bloc_pj_avis");

    const pjRapportInstance = document.getElementById("pj_rapport_cs");
    const pjDemandeAvis = document.getElementById("pj_demande_avis");
    const pjProjetActe  = document.getElementById("pj_projet_acte");
    const labelPJDemandeAvis = document.getElementById("label_pj_demande_avis");


    nature.addEventListener("change", toggleExperts);
    toggleExperts(); // au chargement

    // ---- Masquer / afficher selon la nature ----
    function toggleExperts() {


        console.log("appel de la fonction toggleExperts")
        setRequired()

        console.table({
            blocInterne,
            blocExterne,
            blocPJ_demandeAvis,
            blocPJ_avis,
            blocPJ_projetActe
        });

        [blocInterne, blocExterne, blocPJ_demandeAvis, blocPJ_avis, blocPJ_projetActe]
        .filter(Boolean)
        .forEach(b => b.style.display = "none");


        


        const selected = nature.options[nature.selectedIndex]?.text.trim();
        labelPJDemandeAvis.textContent = selected === "Demande à une instance"
            ? "Joindre le projet d'avis de l'instance (Word)* :"
            : "Joindre le projet d'avis de l'instance (Word) :";

        if (selected === "Consultation en interne") {
            expertExterne.value = "";
            blocInterne.style.display = "flex";
            blocPJ_demandeAvis.style.display = "flex";
            blocPJ_avis.style.display = "flex";
        } 
        else if (selected === "Demande à une instance") {
            expertInterne.value = "";
            blocExterne.style.display = "flex";
            blocPJ_demandeAvis.style.display = "flex";
            blocPJ_rapportCS.style.display = "flex";
            blocPJ_projetActe.style.display = "flex";
            blocPJ_avis.style.display = "flex";
        }
        toggleDestinataireCS();
    }


    // ########################
    // Formulation de l'avis
    // ########################
    function mettreDefaultFormulationSiVide() {
        // Ne jamais écraser un texte déjà écrit (avis existant ou saisi par l'utilisateur)

        // if (formulation.value.trim() !== "") return;

        const selected = nature.options[nature.selectedIndex]?.text.trim();
        console.log({selected})
        if (!selected || selected === "Consultation en interne") {
            formulation.value = `Bonjour,

Je vous consulte car [saisir la raison].

Merci d’avance pour votre retour.`;

        } else if (selected === "Demande à une instance") {
            formulation.value = "Bonjour, vous trouverez ci-joint la demande d'avis.";
        } else {
            formulation.value = "";
        }
    }

    // Déclenche le changement lorsqu'on sélectionne la nature
    nature.addEventListener("change", mettreDefaultFormulationSiVide);

    // Appel au chargement
    mettreDefaultFormulationSiVide();




   
    function setRequired() {

        // Reset des required
        [expertInterne, expertExterne, destinataire, pjDemandeAvis, pjProjetActe, pjRapportInstance].forEach(el => {
            if (el) el.required = false;
        });

        // toujours obligatoires
        nature.required = true;
        thematique.required = true;
        demarche.required = true;

        const selected = nature.options[nature.selectedIndex]?.text.trim();

        if (selected === "Consultation en interne") {
            expertInterne.required = true;
        }

        if (selected === "Demande à une instance") {
            expertExterne.required = true;
            destinataire.required = expertExterne?.selectedOptions[0]?.dataset.estCs === "true";
            pjDemandeAvis.required = true;
            // pjProjetActe.required = true;
        }
    }
});

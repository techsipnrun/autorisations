// -------------------- Form Envoi de l'acte final par mail ---------------------

document.addEventListener("DOMContentLoaded", () => {
    const radios = document.querySelectorAll('input[name="partager_par_mail_choice"]');
    const hidden = document.getElementById("partager_par_mail");
    const bloc = document.getElementById("formulaire-partage-mails");
    const select = document.getElementById('emails_copie');
    const search = document.getElementById('search-contacts');
    const chips  = document.getElementById('selected-chips');
    const addBtn = document.getElementById('add-email-btn');

    if (!select || !search || !chips) return;

    // ----- Toggle Oui/Non -----
    function majPartage() {
        const val = document.querySelector('input[name="partager_par_mail_choice"]:checked')?.value || "non";
        hidden.value = val;
        if (val === "oui") {
            bloc.classList.add("show");
        } else {
            bloc.classList.remove("show");
            Array.from(select.options).forEach(o => o.selected = false);
        }
    }
    radios.forEach(r => r.addEventListener("change", majPartage));
    majPartage();

    // ----- Données -----
    const originalOptions = [...select.options].map(opt => ({
        value: opt.value,
        text:  opt.text,
        nom:   (opt.dataset.nom   || '').toLowerCase(),
        email: (opt.dataset.email || '').toLowerCase(),
        emailRaw: opt.dataset.email || opt.value
    }));

    let selectedValues = new Set();
    let manualEmails   = new Set();

    // ----- Helpers -----
    const rebuildOptions = (list) => {
        const scrollTop = select.scrollTop;
        select.innerHTML = '';
        list.forEach(item => {
            const o = document.createElement('option');
            o.value = item.value;
            o.text  = item.text;
            o.dataset.nom   = item.nom;
            o.dataset.email = item.emailRaw;
            o.selected = selectedValues.has(item.value);
            select.appendChild(o);
        });
        select.scrollTop = scrollTop;
    };

    const createChip = (email, onRemove) => {
        const chip = document.createElement("span");
        chip.className = "chip";
        chip.dataset.email = email.toLowerCase();
        chip.textContent = email;

        const btn = document.createElement("button");
        btn.type = "button";
        btn.textContent = "×";
        btn.onclick = onRemove;
        chip.appendChild(btn);

        const hidden = document.createElement("input");
        hidden.type = "hidden";
        hidden.name = "emails_copie[]";
        hidden.value = email;
        chip.appendChild(hidden);

        return chip;
    };

    function renderChips() {
        chips.innerHTML = '';

        // 1. depuis le select
        selectedValues.forEach(val => {
            const opt = originalOptions.find(o => o.value === val);
            if (!opt) return;
            const chip = createChip(opt.emailRaw, () => {
                selectedValues.delete(val);
                renderChips();
            });
            chips.appendChild(chip);
        });

        // 2. manuels
        manualEmails.forEach(email => {
            const chip = createChip(email, () => {
                manualEmails.delete(email);
                renderChips();
            });
            chips.appendChild(chip);
        });
    }

    // ----- Events -----
    select.addEventListener("change", () => {
        [...select.selectedOptions].forEach(opt => selectedValues.add(opt.value));
        renderChips();
    });

    search.addEventListener('input', () => {
        const q = search.value.trim().toLowerCase();
        if (!q) {
            rebuildOptions(originalOptions);
            addBtn.style.display = "none";
            return;
        }
        const filtered = originalOptions.filter(o =>
            o.text.toLowerCase().includes(q) || o.nom.includes(q) || o.email.includes(q)
        );
        rebuildOptions(filtered);
        addBtn.style.display = filtered.length === 0 ? "inline-block" : "none";
    });

    // Bouton + → insère seulement le formulaire
    addBtn.addEventListener("click", () => {
        const email = search.value.trim();
        const regex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        if (!regex.test(email)) {
            alert("Adresse email invalide : " + email);
            return;
        }
        if (document.querySelector(`.chip[data-email="${email.toLowerCase()}"]`)) {
            return; // doublon
        }

        // Clone le template
        const tmpl = document.getElementById("nouveau-contact-template");
        const clone = tmpl.content.cloneNode(true);
        clone.querySelector("input[name='email_contact[]']").value = email;
        clone.querySelector("input[name='email_affiche']").value = email;

        document.getElementById("nouveaux-contacts-container").appendChild(clone);

        search.value = "";
        addBtn.style.display = "none";
    });

    // ----- Délégation boutons "Ajouter ce contact" / "Annuler" -----
    document.addEventListener("click", function (e) {
        if (e.target.classList.contains("btn-ajout-contact")) {
            const form = e.target.closest(".nouveau-contact-form");
            if (!form) return;

            const email = form.querySelector("input[name='email_affiche']").value;
            const nom = form.querySelector("input[name='nom_contact[]']").value.trim();
            const prenom = form.querySelector("input[name='prenom_contact[]']").value.trim();

            // ⚠️ Vérification Nom/Prénom
            if (!prenom || !nom) {
                if (!confirm("Vous n'avez pas saisi de Nom ou de Prénom. Continuer ?")) return;
            }

            // Ajoute dans manualEmails et affiche la chip
            manualEmails.add(email.toLowerCase());
            renderChips();

            // Garde le form pour le POST (mais caché)
            document.getElementById("nouveaux-contacts-container").appendChild(form);
            form.style.display = "none";

            search.value = "";
            search.focus();
        }

        if (e.target.classList.contains("btn-annuler-ajout-contact")) {
            const form = e.target.closest(".nouveau-contact-form");
            if (form) form.remove();
        }
    });

    // ----- Init -----
    rebuildOptions(originalOptions);
    renderChips();
});

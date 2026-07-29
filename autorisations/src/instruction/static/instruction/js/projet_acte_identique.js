function toggleProjetActeIdentique(checkbox) {
  const bloc = checkbox.closest(".projet-acte-identique-option");
  const rubrique = bloc.querySelector(".recherche-projet-inline");
  const source = bloc.querySelector(".projet-acte-source-id");
  const selection = bloc.querySelector(".projet-acte-selection");
  const selectNature = document.getElementById(bloc.dataset.natureSelect);

  rubrique.hidden = !checkbox.checked;
  if (checkbox.checked) {
    rechercherProjetsActeInline(rubrique.querySelector("button"));
    return;
  }

  source.value = "";
  selection.textContent = "";
  selection.hidden = true;
  if (selectNature) {
    selectNature.disabled = false;
    const inputVerrouille = bloc.querySelector(".nature-acte-verrouillee");
    if (inputVerrouille) inputVerrouille.remove();
  }
}

async function rechercherProjetsActeInline(bouton) {
  const bloc = bouton.closest(".projet-acte-identique-option");
  const rubrique = bloc.querySelector(".recherche-projet-inline");
  const statut = rubrique.querySelector(".recherche-projet-statut");
  const params = new URLSearchParams({
    numero: rubrique.querySelector(".recherche-projet-numero").value,
    demarche_type: rubrique.querySelector(".recherche-projet-demarche-type").value,
    demandeur: rubrique.querySelector(".recherche-projet-demandeur").value,
    nature: "",
  });

  statut.textContent = "Recherche en cours…";
  try {
    const response = await fetch(`${bloc.dataset.searchUrl}?${params}`, {
      headers: { "X-Requested-With": "XMLHttpRequest" },
    });
    if (!response.ok) throw new Error("Recherche impossible");
    const data = await response.json();
    afficherResultatsProjetsActeInline(bloc, data.resultats);
    afficherProjetsActeExclus(rubrique, data.projets_exclus);
    completerDemandeursDansSelect(
      rubrique.querySelector(".recherche-projet-demandeur"),
      data.demandeurs,
    );
    statut.textContent = data.resultats.length
      ? `${data.resultats.length} projet(s) trouvé(s)`
      : "Aucun projet d’acte ne correspond aux filtres.";
  } catch (error) {
    statut.textContent = "La recherche n’a pas pu être effectuée.";
    console.error(error);
  }
}

function afficherResultatsProjetsActeInline(bloc, resultats) {
  const conteneur = bloc.querySelector(".recherche-projet-resultats");
  const selection = bloc.querySelector(".projet-acte-selection");
  conteneur.innerHTML = "";

  resultats.forEach(resultat => {
    const bouton = creerBoutonResultatProjet(resultat);
    bouton.addEventListener("click", () => {
      conteneur.querySelectorAll("button").forEach(item => item.classList.remove("selected"));
      bouton.classList.add("selected");
      bloc.querySelector(".projet-acte-source-id").value = resultat.document_id;
      selection.textContent =
        `Projet sélectionné : dossier ${resultat.dossier_numero} — ` +
        `${resultat.nature} ${resultat.numero_affiche}`;
      selection.hidden = false;
      verrouillerNatureProjet(bloc, resultat.nature);
    });
    conteneur.appendChild(bouton);
  });
}

function creerBoutonResultatProjet(resultat) {
  const bouton = document.createElement("button");
  bouton.type = "button";
  bouton.className = "resultat-projet-acte";
  bouton.innerHTML =
    `<strong>Dossier ${resultat.dossier_numero}</strong>` +
    `Projet ${resultat.nature} ${resultat.numero_affiche}` +
    `<small>${resultat.demarche_type} — ${resultat.demandeur}</small>`;
  return bouton;
}

function afficherProjetsActeExclus(contexte, projetsExclus = []) {
  const message = contexte.querySelector(".recherche-projet-exclusions");
  if (!message) return;
  if (!projetsExclus.length) {
    message.textContent = "";
    message.hidden = true;
    return;
  }

  const projets = projetsExclus.map(projet => `« ${projet} »`).join(", ");
  message.textContent = projetsExclus.length === 1
    ? `Le projet d’acte ${projets} n’apparaît pas dans les résultats, car un acte avec le même numéro a déjà été envoyé pour ce dossier.`
    : `Les projets d’acte ${projets} n’apparaissent pas dans les résultats, car des actes avec les mêmes numéros ont déjà été envoyés pour ce dossier.`;
  message.hidden = false;
}

function verrouillerNatureProjet(bloc, nature) {
  const selectNature = document.getElementById(bloc.dataset.natureSelect);
  if (!selectNature) return;
  selectNature.value = nature;
  selectNature.disabled = true;
  let hidden = bloc.querySelector(".nature-acte-verrouillee");
  if (!hidden) {
    hidden = document.createElement("input");
    hidden.type = "hidden";
    hidden.name = "nature_document";
    hidden.className = "nature-acte-verrouillee";
    bloc.appendChild(hidden);
  }
  hidden.value = nature;
  selectNature.dispatchEvent(new Event("change"));
}

function completerDemandeursDansSelect(select, demandeurs) {
  const valeurs = new Set(Array.from(select.options).map(option => option.value));
  demandeurs.forEach(demandeur => {
    if (valeurs.has(String(demandeur.id))) return;
    select.add(new Option(demandeur.nom, demandeur.id));
  });
}

function validerProjetActeIdentique(form) {
  const checkbox = form.querySelector("[name='projet_acte_identique']");
  if (!checkbox?.checked) return true;
  const source = form.querySelector("[name='projet_acte_source_id']");
  if (source?.value) return true;
  afficherErreurFormulaire(
    checkbox.closest(".projet-acte-identique-option"),
    "Sélectionnez un projet d’acte existant ou décochez l’option.",
  );
  return false;
}

function toggleRechercheProjetRemplacement(bouton) {
  const section = bouton.closest(".doc-item").querySelector(".recherche-projet-remplacement");
  section.hidden = !section.hidden;
  if (!section.hidden && !section.dataset.loaded) {
    section.dataset.loaded = "true";
    rechercherProjetsActeRemplacement(section.querySelector(".recherche-projet-bouton"));
  }
}

function replierRechercheProjetRemplacement(bouton) {
  bouton.closest(".recherche-projet-remplacement").hidden = true;
}

async function rechercherProjetsActeRemplacement(bouton) {
  const section = bouton.closest(".recherche-projet-remplacement");
  const statut = section.querySelector(".recherche-projet-statut");
  const params = new URLSearchParams({
    numero: section.querySelector(".recherche-projet-numero").value,
    demarche_type: section.querySelector(".recherche-projet-demarche-type").value,
    demandeur: section.querySelector(".recherche-projet-demandeur").value,
    nature: section.dataset.nature,
  });

  statut.textContent = "Recherche en cours…";
  try {
    const response = await fetch(`${section.dataset.searchUrl}?${params}`, {
      headers: { "X-Requested-With": "XMLHttpRequest" },
    });
    if (!response.ok) throw new Error("Recherche impossible");
    const data = await response.json();
    afficherResultatsProjetsRemplacement(section, data.resultats);
    afficherProjetsActeExclus(section, data.projets_exclus);
    completerDemandeursDansSelect(
      section.querySelector(".recherche-projet-demandeur"),
      data.demandeurs,
    );
    statut.textContent = data.resultats.length
      ? `${data.resultats.length} projet(s) trouvé(s)`
      : "Aucun projet d’acte ne correspond aux filtres.";
  } catch (error) {
    statut.textContent = "La recherche n’a pas pu être effectuée.";
    console.error(error);
  }
}

function afficherResultatsProjetsRemplacement(section, resultats) {
  const conteneur = section.querySelector(".recherche-projet-resultats");
  const selection = section.querySelector(".projet-acte-selection");
  const source = section.querySelector(".source-document-id");
  const confirmer = section.querySelector(".confirmer-remplacement-numero");
  conteneur.innerHTML = "";
  source.value = "";
  selection.hidden = true;
  confirmer.disabled = true;

  resultats.forEach(resultat => {
    const bouton = creerBoutonResultatProjet(resultat);
    bouton.addEventListener("click", () => {
      conteneur.querySelectorAll("button").forEach(item => item.classList.remove("selected"));
      bouton.classList.add("selected");
      source.value = resultat.document_id;
      selection.textContent =
        `Projet sélectionné : dossier ${resultat.dossier_numero} — ` +
        `${resultat.nature} ${resultat.numero_affiche}`;
      selection.hidden = false;
      confirmer.disabled = false;
    });
    conteneur.appendChild(bouton);
  });
}

function soumettreRemplacementNumero(bouton) {
  const bloc = bouton.closest(".remplacer-numero-projet-form");
  const sourceId = bloc.querySelector(".source-document-id").value;
  if (!sourceId) return;

  const form = document.createElement("form");
  form.method = "post";
  form.action = bloc.dataset.submitUrl;
  [
    ["csrfmiddlewaretoken", bloc.dataset.csrfToken],
    ["dossier_id", bloc.dataset.dossierId],
    ["document_id", bloc.dataset.documentId],
    ["source_document_id", sourceId],
  ].forEach(([nom, valeur]) => {
    const input = document.createElement("input");
    input.type = "hidden";
    input.name = nom;
    input.value = valeur;
    form.appendChild(input);
  });
  document.body.appendChild(form);
  form.submit();
}

function effacerErreursFormulaire(form) {
  form.querySelectorAll(".django-form-error").forEach(erreur => erreur.remove());
}

function afficherErreurFormulaire(ancrage, message) {
  const erreur = document.createElement("ul");
  erreur.className = "errorlist django-form-error";
  const item = document.createElement("li");
  item.textContent = message;
  erreur.appendChild(item);
  ancrage.insertAdjacentElement("afterend", erreur);
  erreur.scrollIntoView({ behavior: "smooth", block: "center" });
}

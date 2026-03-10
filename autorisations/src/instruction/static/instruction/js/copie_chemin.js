document.addEventListener("DOMContentLoaded", () => {

  const copyButtons = document.querySelectorAll(".btn-copy-dossier");

  copyButtons.forEach(btn => {

    btn.addEventListener("mouseenter", () => {
      btn.title = "Copier le chemin d'accès du dossier";
    });

    btn.addEventListener("mouseleave", () => {
      btn.title = "Voir le dossier";
    });

    btn.addEventListener("click", async () => {

      const path = btn.dataset.path;
      if (!path) return;

      try {
        // Clipboard API moderne
        if (navigator.clipboard && window.isSecureContext) {
          await navigator.clipboard.writeText(path);
        } else {
          // Fallback HTTP
          const textarea = document.createElement("textarea");
          textarea.value = path;
          textarea.style.position = "fixed";
          textarea.style.left = "-9999px";
          document.body.appendChild(textarea);
          textarea.select();
          document.execCommand("copy");
          document.body.removeChild(textarea);
        }

        btn.classList.add("show-feedback");
        setTimeout(() => {
          btn.classList.remove("show-feedback");
        }, 2000);

      } catch (err) {
        console.error("Erreur copie :", err);
      }

    });

  });

});


function copyPathDocument(rowEl) {

  let path = rowEl?.dataset?.path;
  if (!path) return;

  // 1️⃣ remplacer / par \
  path = path.replace(/\//g, "\\");

  // 2️⃣ normaliser tous les \ multiples en un seul
  path = path.replace(/\\+/g, "\\");

  // 3️⃣ remettre \\ au début pour UNC (chemin réseau)
  if (!path.startsWith("\\\\")) {
    path = "\\" + path;
  }

  const feedback = rowEl.querySelector(".copie-feedback-doc");

  const showFeedback = () => {
    if (!feedback) return;

    feedback.classList.add("show");

    clearTimeout(feedback._timeoutId);
    feedback._timeoutId = setTimeout(() => {
      feedback.classList.remove("show");
    }, 2000);
  };

  const copy = async () => {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(path);
    } else {
      const textarea = document.createElement("textarea");
      textarea.value = path;
      textarea.style.position = "fixed";
      textarea.style.left = "-9999px";
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand("copy");
      textarea.remove();
    }
  };

  copy().then(showFeedback).catch(console.error);
}


// Dowload document
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".doc-download-row").forEach(row => {
    row.addEventListener("click", function (e) {
      const url = this.dataset.url;
      if (url) window.open(url, "_blank");
    });
  });
});
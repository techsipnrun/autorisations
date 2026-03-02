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
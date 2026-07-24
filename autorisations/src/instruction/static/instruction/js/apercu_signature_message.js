document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".message-form").forEach((form) => {
        const checkbox = form.querySelector(".signature-checkbox");
        const preview = form.querySelector(".signature-preview");

        if (!checkbox || !preview) return;

        const updatePreview = () => {
            preview.hidden = !checkbox.checked;
            form.classList.toggle("with-signature-preview", checkbox.checked);
        };

        checkbox.addEventListener("change", updatePreview);
        updatePreview();
    });
});

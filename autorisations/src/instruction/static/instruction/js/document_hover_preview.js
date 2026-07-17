document.addEventListener("DOMContentLoaded", () => {
    let activeContainer = null;

    const closePreview = (container) => {
        if (!container) return;
        container.classList.remove("is-preview-open");
        delete container.dataset.apercuOuvertParClic;
        if (activeContainer === container) activeContainer = null;
    };

    const positionPreview = (trigger, popover, bridge) => {
        const margin = 12;
        const navbar = document.querySelector(".navigation_header");
        const topLimit = Math.max(margin, (navbar?.getBoundingClientRect().bottom || 0) + margin);
        const availableHeight = Math.max(0, window.innerHeight - topLimit - margin);
        const previewHeight = Math.min(650, window.innerHeight * 0.7, availableHeight);

        popover.style.height = `${previewHeight}px`;
        popover.style.maxHeight = `${availableHeight}px`;

        const triggerRect = trigger.getBoundingClientRect();
        const popoverRect = popover.getBoundingClientRect();

        let left = triggerRect.right + margin;
        if (left + popoverRect.width > window.innerWidth - margin) {
            left = triggerRect.left - popoverRect.width - margin;
        }

        left = Math.max(margin, Math.min(left, window.innerWidth - popoverRect.width - margin));

        let top = triggerRect.top + triggerRect.height / 2 - popoverRect.height / 2;
        top = Math.max(topLimit, Math.min(top, window.innerHeight - popoverRect.height - margin));

        popover.style.left = `${left}px`;
        popover.style.top = `${top}px`;

        if (bridge) {
            const popoverLeft = left;
            const popoverRight = left + popoverRect.width;
            const previewIsRight = popoverLeft >= triggerRect.right;
            const bridgeLeft = previewIsRight ? triggerRect.right : popoverRight;
            const bridgeRight = previewIsRight ? popoverLeft : triggerRect.left;

            bridge.style.left = `${bridgeLeft}px`;
            bridge.style.top = `${triggerRect.top - 10}px`;
            bridge.style.width = `${Math.max(0, bridgeRight - bridgeLeft)}px`;
            bridge.style.height = `${triggerRect.height + 20}px`;
        }
    };

    document.querySelectorAll(".document-apercu-trigger").forEach((trigger) => {
        const container = trigger.closest(".document-avec-apercu");
        const popover = container?.querySelector(".document-apercu-popover");
        const bridge = container?.querySelector(".document-apercu-pont");
        const correctionButton = container?.querySelector(".remplacer-acte-toggle");
        let previewLoaded = false;
        let closeTimeout = null;

        const cancelScheduledClose = () => {
            if (!closeTimeout) return;
            clearTimeout(closeTimeout);
            closeTimeout = null;
        };

        const scheduleClose = () => {
            cancelScheduledClose();
            closeTimeout = setTimeout(() => {
                const sourisDansLeScope = (
                    container.matches(":hover")
                    || bridge?.matches(":hover")
                    || popover.matches(":hover")
                );

                if (!sourisDansLeScope) closePreview(container);
            }, 250);
        };

        const loadPreview = async () => {
            if (previewLoaded || !popover) return;

            const previewUrl = trigger.dataset.previewUrl;
            const previewType = trigger.dataset.previewType;
            let previewElement;

            try {
                if (previewType === "pdf") {
                    const response = await fetch(previewUrl, {
                        credentials: "same-origin",
                        cache: "no-store"
                    });

                    if (!response.ok) throw new Error(`HTTP ${response.status}`);

                    const pdfBlob = await response.blob();
                    previewElement = document.createElement("embed");
                    previewElement.src = URL.createObjectURL(pdfBlob);
                    previewElement.type = "application/pdf";
                    previewElement.title = "Aperçu PDF";
                } else {
                    previewElement = document.createElement("img");
                    previewElement.src = previewUrl;
                    previewElement.alt = "Aperçu du document";
                }

                previewElement.className = "document-apercu-contenu";
                popover.replaceChildren(previewElement);
                previewLoaded = true;
            } catch (error) {
                const message = document.createElement("span");
                message.className = "document-apercu-erreur";
                message.textContent = "L’aperçu ne peut pas être chargé.";
                popover.replaceChildren(message);
                console.error("Erreur de chargement de l’aperçu :", error);
            }
        };

        const openPreview = () => {
            if (!container || !popover) return;
            cancelScheduledClose();

            if (activeContainer && activeContainer !== container) {
                closePreview(activeContainer);
            }

            activeContainer = container;
            container.classList.add("is-preview-open");
            loadPreview();
            requestAnimationFrame(() => {
                requestAnimationFrame(() => positionPreview(trigger, popover, bridge));
            });
        };

        trigger.addEventListener("click", () => {
            if (
                container.classList.contains("is-preview-open")
                && container.dataset.apercuOuvertParClic === "true"
            ) {
                closePreview(container);
                return;
            }

            container.dataset.apercuOuvertParClic = "true";
            openPreview();
        });

        const closeFromCorrection = () => {
            closePreview(container);
        };
        correctionButton?.addEventListener("mouseenter", closeFromCorrection);
        correctionButton?.addEventListener("focus", closeFromCorrection);

        container.addEventListener("mouseenter", cancelScheduledClose);
        container.addEventListener("mouseleave", scheduleClose);
        bridge?.addEventListener("mouseenter", cancelScheduledClose);
        bridge?.addEventListener("mouseleave", scheduleClose);
        popover.addEventListener("mouseenter", cancelScheduledClose);
        popover.addEventListener("mouseleave", scheduleClose);
        container.addEventListener("focusout", (event) => {
            if (!container.contains(event.relatedTarget)) scheduleClose();
        });
    });

    window.addEventListener("resize", () => {
        if (!activeContainer) return;
        const trigger = activeContainer.querySelector(".document-apercu-trigger");
        const popover = activeContainer.querySelector(".document-apercu-popover");
        const bridge = activeContainer.querySelector(".document-apercu-pont");
        if (trigger && popover) positionPreview(trigger, popover, bridge);
    });

    window.addEventListener("scroll", () => {
        if (!activeContainer) return;
        const trigger = activeContainer.querySelector(".document-apercu-trigger");
        const popover = activeContainer.querySelector(".document-apercu-popover");
        const bridge = activeContainer.querySelector(".document-apercu-pont");
        if (trigger && popover) positionPreview(trigger, popover, bridge);
    }, { passive: true });

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") closePreview(activeContainer);
    });
});

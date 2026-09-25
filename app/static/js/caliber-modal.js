document.addEventListener("DOMContentLoaded", () => {
    const modal = document.getElementById("caliber-modal");

    if (!modal) {
        return;
    }

    const openButton =
        document.getElementById("caliber-add");

    const closeButton =
        document.getElementById("caliber-modal-close");

    const cancelButton =
        document.getElementById("caliber-modal-cancel");

    const saveButton =
        document.getElementById("caliber-modal-save");

    const nameInput =
        document.getElementById("new-caliber-name");

    const errorElement =
        document.getElementById("caliber-modal-error");

    const selectId =
        modal.dataset.caliberSelect;

    const caliberSelect =
        document.getElementById(selectId);

    if (
        !openButton ||
        !closeButton ||
        !cancelButton ||
        !saveButton ||
        !nameInput ||
        !errorElement ||
        !caliberSelect
    ) {
        return;
    }


    function openModal() {
        errorElement.textContent = "";
        nameInput.value = "";
        modal.hidden = false;

        requestAnimationFrame(() => {
            nameInput.focus();
        });
    }


    function closeModal() {
        modal.hidden = true;
        errorElement.textContent = "";
        nameInput.value = "";
    }


    function selectCaliber(caliber) {
        let option = Array.from(
            caliberSelect.options
        ).find(
            existingOption =>
                existingOption.value === caliber.id
        );

        if (!option) {
            option = document.createElement("option");
            option.value = caliber.id;
            option.textContent = caliber.name;

            caliberSelect.appendChild(option);
        }

        caliberSelect.value = caliber.id;
    }


    async function saveCaliber() {
        const name = nameInput.value.trim();

        if (!name) {
            errorElement.textContent =
                "Caliber name is required.";
            return;
        }

        saveButton.disabled = true;
        saveButton.textContent = "Adding...";
        errorElement.textContent = "";

        try {
            const response = await fetch(
                "/reference/calibers",
                {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                    body: JSON.stringify({
                        name: name,
                    }),
                }
            );

            let data = null;

            try {
                data = await response.json();
            } catch {
                // Generic error below.
            }

            if (!response.ok || !data?.success) {
                errorElement.textContent =
                    data?.error ||
                    data?.detail ||
                    "Unable to add caliber.";
                return;
            }

            selectCaliber(data.caliber);
            closeModal();

        } catch (error) {
            console.error(error);

            errorElement.textContent =
                "Unable to communicate with Armory Ledger.";

        } finally {
            saveButton.disabled = false;
            saveButton.textContent = "Add Caliber";
        }
    }


    openButton.addEventListener(
        "click",
        openModal
    );

    closeButton.addEventListener(
        "click",
        closeModal
    );

    cancelButton.addEventListener(
        "click",
        closeModal
    );

    saveButton.addEventListener(
        "click",
        saveCaliber
    );


    modal.addEventListener("click", event => {
        if (event.target === modal) {
            closeModal();
        }
    });


    nameInput.addEventListener(
        "keydown",
        event => {
            if (event.key === "Enter") {
                event.preventDefault();
                saveCaliber();
            }
        }
    );


    document.addEventListener(
        "keydown",
        event => {
            if (
                event.key === "Escape" &&
                !modal.hidden
            ) {
                closeModal();
            }
        }
    );
});
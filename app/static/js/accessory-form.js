document.addEventListener("DOMContentLoaded", () => {

    /*
     * =========================================================
     * DOM elements
     * =========================================================
     */

    const searchInput = document.getElementById("manufacturer-search");
    const manufacturerId = document.getElementById("manufacturer-id");
    const results = document.getElementById("manufacturer-results");

    const modal = document.getElementById("manufacturer-modal");
    const modalName = document.getElementById("new-manufacturer-name");
    const quantityInput = document.getElementById("quantity");
    const modalError = document.getElementById("manufacturer-modal-error");
    const modalSave = document.getElementById("manufacturer-modal-save");
    const modalCancel = document.getElementById("manufacturer-modal-cancel");
    const modalClose = document.getElementById("manufacturer-modal-close");

    const accessoryForm = document.getElementById("accessory-form");
    const accessorySave = document.getElementById("accessory-save");
    const accessoryFormError = document.getElementById("accessory-form-error");

    const locationType = document.getElementById("location-type");
    const firearmLocationField =
        document.getElementById("firearm-location-field");
    const storageLocationField =
        document.getElementById("storage-location-field");
    const firearmId = document.getElementById("firearm-id");
    const storageLocation = document.getElementById("storage-location");

    const formMode = accessoryForm?.dataset.mode || "create";
    const accessoryId = accessoryForm?.dataset.accessoryId || null;

    if (
        !searchInput ||
        !manufacturerId ||
        !results ||
        !modal ||
        !modalName ||
        !modalError ||
        !modalSave ||
        !modalCancel ||
        !modalClose ||
        !accessoryForm ||
        !accessorySave ||
        !accessoryFormError ||
        !locationType ||
        !quantityInput ||
        !firearmLocationField ||
        !storageLocationField ||
        !firearmId ||
        !storageLocation
    ) {
        return;
    }

    let searchTimer = null;


    /*
     * =========================================================
     * Utility functions
     * =========================================================
     */

    function escapeHtml(value) {
        const element = document.createElement("div");
        element.textContent = value;
        return element.innerHTML;
    }

    function optionalValue(value) {
        const cleaned = value.trim();
        return cleaned || null;
    }


    /*
     * =========================================================
     * Manufacturer selection
     * =========================================================
     */

    function clearManufacturerSelection() {
        manufacturerId.value = "";
    }

    function selectManufacturer(id, name) {
        manufacturerId.value = id;
        searchInput.value = name;

        results.innerHTML = `
            <div class="lookup-selected">
                <span class="lookup-label">
                    Selected manufacturer
                </span>
                <strong>${escapeHtml(name)}</strong>
            </div>
        `;
    }


    /*
     * =========================================================
     * Manufacturer search
     * =========================================================
     */

    async function searchManufacturers(term) {
        if (term.length < 2) {
            results.innerHTML = "";
            return;
        }

        results.innerHTML = `
            <div class="lookup-status">
                Searching...
            </div>
        `;

        try {
            const response = await fetch(
                `/accessories/manufacturer-search?q=${encodeURIComponent(term)}`,
                {
                    headers: {
                        "Accept": "application/json",
                    },
                }
            );

            if (!response.ok) {
                throw new Error(
                    `Manufacturer search failed with status ${response.status}`
                );
            }

            const data = await response.json();
            renderManufacturerResults(data);

        } catch (error) {
            console.error(error);

            results.innerHTML = `
                <div class="lookup-status lookup-error">
                    Manufacturer search is currently unavailable.
                </div>
            `;
        }
    }

    function renderManufacturerResults(data) {
        if (data.match_type === "exact" && data.exact) {
            results.innerHTML = `
                <button
                    type="button"
                    class="lookup-option"
                    data-id="${escapeHtml(data.exact.id)}"
                    data-name="${escapeHtml(data.exact.name)}"
                >
                    <span class="lookup-label">
                        Manufacturer found
                    </span>

                    <strong>
                        ${escapeHtml(data.exact.name)}
                    </strong>
                </button>
            `;

            bindManufacturerOptions();
            return;
        }

        if (
            data.match_type === "similar" &&
            data.similar.length > 0
        ) {
            const suggestions = data.similar
                .map(item => `
                    <button
                        type="button"
                        class="lookup-option"
                        data-id="${escapeHtml(item.id)}"
                        data-name="${escapeHtml(item.name)}"
                    >
                        <strong>
                            ${escapeHtml(item.name)}
                        </strong>
                    </button>
                `)
                .join("");

            results.innerHTML = `
                <div class="lookup-status">
                    No exact match found.
                </div>

                <div class="lookup-prompt">
                    Did you mean?
                </div>

                ${suggestions}

                <div class="lookup-or">
                    — or —
                </div>

                <button
                    type="button"
                    class="lookup-add"
                    data-new-manufacturer="${escapeHtml(data.query)}"
                >
                    + Add "${escapeHtml(data.query)}" as a manufacturer
                </button>
            `;

            bindManufacturerOptions();
            bindAddManufacturerButton();
            return;
        }

        if (data.match_type === "none") {
            results.innerHTML = `
                <div class="lookup-status">
                    No manufacturer found.
                </div>

                <button
                    type="button"
                    class="lookup-add"
                    data-new-manufacturer="${escapeHtml(data.query)}"
                >
                    + Add "${escapeHtml(data.query)}" as a manufacturer
                </button>
            `;

            bindAddManufacturerButton();
            return;
        }

        results.innerHTML = "";
    }

    function bindManufacturerOptions() {
        results
            .querySelectorAll(".lookup-option")
            .forEach(option => {
                option.addEventListener("click", () => {
                    selectManufacturer(
                        option.dataset.id,
                        option.dataset.name
                    );
                });
            });
    }

    function bindAddManufacturerButton() {
        const addButton = results.querySelector(".lookup-add");

        if (!addButton) {
            return;
        }

        addButton.addEventListener("click", () => {
            openManufacturerModal(
                addButton.dataset.newManufacturer
            );
        });
    }


    /*
     * =========================================================
     * Add Manufacturer modal
     * =========================================================
     */

    function openManufacturerModal(name) {
        modalName.value = name;
        modalError.textContent = "";
        modal.hidden = false;

        requestAnimationFrame(() => {
            modalName.focus();
            modalName.select();
        });
    }

    function closeManufacturerModal() {
        modal.hidden = true;
        modalError.textContent = "";
    }

    async function saveManufacturer() {
        const name = modalName.value.trim();

        if (!name) {
            modalError.textContent =
                "Manufacturer name is required.";
            return;
        }

        modalSave.disabled = true;
        modalSave.textContent = "Adding...";
        modalError.textContent = "";

        try {
            const response = await fetch(
                "/accessories/manufacturers",
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

            const data = await response.json();

            if (!response.ok || !data.success) {
                modalError.textContent =
                    data.error ||
                    data.detail ||
                    "Unable to add manufacturer.";
                return;
            }

            selectManufacturer(
                data.manufacturer.id,
                data.manufacturer.name
            );

            closeManufacturerModal();

        } catch (error) {
            console.error(error);

            modalError.textContent =
                "Unable to add manufacturer.";

        } finally {
            modalSave.disabled = false;
            modalSave.textContent = "Add Manufacturer";
        }
    }


    /*
     * =========================================================
     * Accessory location
     * =========================================================
     */

    function updateLocationFields() {
        const type = locationType.value;

        firearmLocationField.hidden = type !== "firearm";
        storageLocationField.hidden = type !== "storage";

        /*
         * Clear the inactive location value.
         *
         * This keeps the browser state consistent with the
         * backend rule that an accessory cannot simultaneously
         * be installed on a firearm and stored somewhere else.
         */

        if (type !== "firearm") {
            firearmId.value = "";
        }

        if (type !== "storage") {
            storageLocation.value = "";
        }
    }


    /*
     * =========================================================
     * Accessory submission
     * =========================================================
     */

    async function saveAccessory(event) {
        event.preventDefault();

        accessoryFormError.textContent = "";

        const name = document
            .getElementById("name")
            .value
            .trim();

        const quantity = Number(quantityInput.value);

        const model = document
            .getElementById("model")
            .value;

        const serialNumber = document
            .getElementById("serial-number")
            .value;

        const purchaseDate = document
            .getElementById("purchase-date")
            .value;

        const purchaseLocation = document
            .getElementById("purchase-location")
            .value;

        const notes = document
            .getElementById("notes")
            .value;

        if (!name) {
            accessoryFormError.textContent =
                "Accessory name is required.";

            document.getElementById("name").focus();
            return;
        }

        if (
            !Number.isInteger(quantity) ||
                quantity < 1
        ) {
            accessoryFormError.textContent =
                "Accessory quantity must be a whole number of at least 1.";

            quantityInput.focus();
            return;
        }

        /*
         * Manufacturer is optional, but text in the lookup
         * field must either resolve to a database record or
         * remain empty.
         */

        if (
            searchInput.value.trim() &&
            !manufacturerId.value
        ) {
            accessoryFormError.textContent =
                "Please select the manufacturer from the results, " +
                "add it as a manufacturer, or clear the field.";

            searchInput.focus();
            return;
        }

        let selectedFirearmId = null;
        let selectedStorageLocation = null;

        if (locationType.value === "firearm") {
            if (!firearmId.value) {
                accessoryFormError.textContent =
                    "Please select the firearm this accessory is installed on.";

                firearmId.focus();
                return;
            }

            selectedFirearmId = firearmId.value;
        }

        if (locationType.value === "storage") {
            selectedStorageLocation =
                optionalValue(storageLocation.value);

            if (!selectedStorageLocation) {
                accessoryFormError.textContent =
                    "Please enter the storage location.";

                storageLocation.focus();
                return;
            }
        }

        const isEdit = formMode === "edit";

        if (isEdit && !accessoryId) {
            accessoryFormError.textContent =
                "Unable to identify the accessory being edited.";
            return;
        }

        const requestUrl = isEdit
            ? `/accessories/${encodeURIComponent(accessoryId)}`
            : "/accessories/";

        const requestMethod = isEdit
            ? "PUT"
            : "POST";

        accessorySave.disabled = true;
        accessorySave.textContent = "Saving...";

        try {
            const response = await fetch(
                requestUrl,
                {
                    method: requestMethod,
                    headers: {
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                    body: JSON.stringify({
                        name: name,
                        quantity: quantity,
                        manufacturer_id:
                            manufacturerId.value || null,
                        model: optionalValue(model),
                        serial_number:
                            optionalValue(serialNumber),
                        purchase_date:
                            purchaseDate || null,
                        purchase_location:
                            optionalValue(purchaseLocation),
                        firearm_id:
                            selectedFirearmId,
                        storage_location:
                            selectedStorageLocation,
                        notes:
                            optionalValue(notes),
                    }),
                }
            );

            const data = await response.json();

            if (!response.ok || !data.success) {
                accessoryFormError.textContent =
                    data.error ||
                    data.detail ||
                    "Unable to save accessory.";

                return;
            }

            if (isEdit) {
                window.location.href =
                    `/accessories/${encodeURIComponent(accessoryId)}`;
            } else {
                window.location.href = "/accessories/";
            }

        } catch (error) {
            console.error(error);

            accessoryFormError.textContent =
                "Unable to save accessory.";

        } finally {
            accessorySave.disabled = false;

            accessorySave.textContent =
                formMode === "edit"
                    ? "Save Changes"
                    : "Save Accessory";
        }
    }


    /*
     * =========================================================
     * Event handlers
     * =========================================================
     */

    searchInput.addEventListener("input", () => {
        clearManufacturerSelection();

        const term = searchInput.value.trim();

        clearTimeout(searchTimer);

        searchTimer = setTimeout(() => {
            searchManufacturers(term);
        }, 250);
    });

    locationType.addEventListener(
        "change",
        updateLocationFields
    );

    modalSave.addEventListener(
        "click",
        saveManufacturer
    );

    modalCancel.addEventListener(
        "click",
        closeManufacturerModal
    );

    modalClose.addEventListener(
        "click",
        closeManufacturerModal
    );

    modal.addEventListener("click", event => {
        if (event.target === modal) {
            closeManufacturerModal();
        }
    });

    modalName.addEventListener("keydown", event => {
        if (event.key === "Enter") {
            event.preventDefault();
            saveManufacturer();
        }
    });

    document.addEventListener("keydown", event => {
        if (
            event.key === "Escape" &&
            !modal.hidden
        ) {
            closeManufacturerModal();
        }
    });

    accessoryForm.addEventListener(
        "submit",
        saveAccessory
    );

    /*
     * Make sure visibility matches the initial form state.
     * Particularly important when loading Edit.
     */

    updateLocationFields();
});

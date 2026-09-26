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
    const modalError = document.getElementById("manufacturer-modal-error");
    const modalSave = document.getElementById("manufacturer-modal-save");
    const modalCancel = document.getElementById("manufacturer-modal-cancel");
    const modalClose = document.getElementById("manufacturer-modal-close");

    const firearmForm = document.getElementById("firearm-form");
    const firearmSave = document.getElementById("firearm-save");
    const firearmFormError = document.getElementById("firearm-form-error");
    const statusInput = document.getElementById("status");
    const notesInput = document.getElementById("notes");

    const manufacturePrecision = document.getElementById(
        "manufacture-date-precision"
    );
    const manufactureDate = document.getElementById(
        "manufacture-date"
    );

    const obtainedPrecision = document.getElementById(
        "obtained-date-precision"
    );
    const obtainedDate = document.getElementById(
        "obtained-date"
    );

    const formMode = firearmForm?.dataset.mode || "create";
    const firearmId = firearmForm?.dataset.firearmId || null;

    /*
     * This script is used by the firearm create/edit forms.
     * If the required controls are not present, do nothing.
     */
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
        !firearmForm ||
        !firearmSave ||
        !firearmFormError ||
        !statusInput ||
        !notesInput ||
        !manufacturePrecision ||
        !manufactureDate ||
        !obtainedPrecision ||
        !obtainedDate
    ) {
        return;
    }

    let searchTimer = null;

    configureDateInput(
        manufacturePrecision,
        manufactureDate
    );

    configureDateInput(
        obtainedPrecision,
        obtainedDate
    );


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

    function configureDateInput(precisionSelect, dateInput) {
    const precision = precisionSelect.value;
    const storedDate = dateInput.dataset.dateValue || "";

    dateInput.hidden = precision === "unknown";
    dateInput.required = precision !== "unknown";

    if (precision === "unknown") {
        dateInput.type = "text";
        dateInput.value = "";
        return;
    }

    if (
        precision === "year" ||
        precision === "approximate_year"
    ) {
        dateInput.type = "number";
        dateInput.min = "1000";
        dateInput.max = "9999";
        dateInput.step = "1";
        dateInput.placeholder = "YYYY";

        if (storedDate) {
            dateInput.value = storedDate.slice(0, 4);
        }

        return;
    }

    if (precision === "month") {
        dateInput.type = "month";

        if (storedDate) {
            dateInput.value = storedDate.slice(0, 7);
        }

        return;
    }

    dateInput.type = "date";

    if (storedDate) {
        dateInput.value = storedDate;
    }
}


    function canonicalDateValue(precisionSelect, dateInput) {
        const precision = precisionSelect.value;
        const value = dateInput.value.trim();

        if (precision === "unknown") {
            return null;
        }

        if (!value) {
            throw new Error(
                "Please enter a value for each specified date."
            );
        }

        if (
            precision === "year" ||
            precision === "approximate_year"
        ) {
            return `${value}-01-01`;
        }

        if (precision === "month") {
            return `${value}-01`;
        }

        return value;
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
                `/firearms/manufacturer-search?q=${encodeURIComponent(term)}`,
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
        /*
         * Exact canonical-name or alias match.
         */
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

        /*
         * No exact match, but fuzzy matching found one or more
         * possible manufacturers.
         */
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

        /*
         * No exact or meaningful fuzzy match.
         */
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
                "/firearms/manufacturers",
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

            if (!data.success) {
                modalError.textContent =
                    data.error ||
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
     * Firearm submission
     * =========================================================
     */

    async function saveFirearm(event) {
        event.preventDefault();

        firearmFormError.textContent = "";

        const model = document
            .getElementById("model")
            .value
            .trim();

        const serialNumber = document
            .getElementById("serial-number")
            .value
            .trim();

        const firearmType = document
            .getElementById("firearm-type")
            .value;

        const caliberId = document
            .getElementById("caliber")
            .value;

        /*
         * Manufacturer must be a resolved database record.
         * Text merely sitting in the search field is not enough.
         */
        if (!manufacturerId.value) {
            firearmFormError.textContent =
                "Please select a manufacturer.";
            searchInput.focus();
            return;
        }

        if (!model) {
            firearmFormError.textContent =
                "Model is required.";
            document.getElementById("model").focus();
            return;
        }

        const purchasePrice = document
            .getElementById("purchase-price").value.trim();

        // Preserve decimal text; the API validates it as Decimal.
        if (purchasePrice && !/^\d{1,10}(\.\d{1,2})?$/.test(purchasePrice)) {
            firearmFormError.textContent =
                "Enter a nonnegative USD amount with at most two decimal places.";
            return;
        }

        let manufactureDateValue;
        let obtainedDateValue;

        try {
            manufactureDateValue = canonicalDateValue(
                manufacturePrecision,
                manufactureDate
            );

            obtainedDateValue = canonicalDateValue(
                obtainedPrecision,
                obtainedDate
            );
        } catch (error) {
            firearmFormError.textContent = error.message;
            return;
        }

        const isEdit = formMode === "edit";

        if (isEdit && !firearmId) {
            firearmFormError.textContent =
                "Unable to identify the firearm being edited.";
            return;
        }

        const requestUrl = isEdit
            ? `/firearms/${encodeURIComponent(firearmId)}`
            : "/firearms/";

        const requestMethod = isEdit
            ? "PUT"
            : "POST";

        firearmSave.disabled = true;
        firearmSave.textContent = "Saving...";

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
                        manufacturer_id: manufacturerId.value,
                        model: model,
                        serial_number: serialNumber || null,
                        firearm_type: firearmType,
                        caliber_id: caliberId || null,
                        manufacture_date: manufactureDateValue,
                        manufacture_date_precision: manufacturePrecision.value,
                        obtained_date: obtainedDateValue,
                        obtained_date_precision: obtainedPrecision.value,
                        purchase_price: purchasePrice || null,
                        status: statusInput.value,
                        notes: notesInput.value.trim() || null,
                    }),
                }
            );

            const data = await response.json();

            if (!response.ok || !data.success) {
                firearmFormError.textContent =
                    data.error ||
                    data.detail ||
                    "Unable to save firearm.";
                return;
            }

            if (isEdit) {
                window.location.href =
                    `/firearms/${encodeURIComponent(firearmId)}`;
            } else {
                window.location.href = "/firearms/";
            }

        } catch (error) {
            console.error(error);

            firearmFormError.textContent =
                "Unable to save firearm.";

        } finally {
            firearmSave.disabled = false;
            firearmSave.textContent =
                formMode === "edit"
                    ? "Save Changes"
                    : "Save Firearm";
        }
    }


    /*
     * =========================================================
     * Event handlers
     * =========================================================
     */


    manufacturePrecision.addEventListener("change", () => {
        manufactureDate.dataset.dateValue = "";
        configureDateInput(
            manufacturePrecision,
            manufactureDate
        );
    });

    obtainedPrecision.addEventListener("change", () => {
        obtainedDate.dataset.dateValue = "";
        configureDateInput(
            obtainedPrecision,
            obtainedDate
        );
    });
    searchInput.addEventListener("input", () => {
        /*
         * Any edit to the visible manufacturer field invalidates
         * the previously selected UUID until the user resolves the
         * manufacturer again.
         */
        clearManufacturerSelection();

        const term = searchInput.value.trim();

        clearTimeout(searchTimer);

        searchTimer = setTimeout(() => {
            searchManufacturers(term);
        }, 250);
    });

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

    firearmForm.addEventListener(
        "submit",
        saveFirearm
    );
});
document.addEventListener("DOMContentLoaded", () => {
    const rangeForm =
        document.getElementById("range-form");

    if (!rangeForm) {
        return;
    }

    const rangeSave =
        document.getElementById("range-save");

    const rangeFormError =
        document.getElementById("range-form-error");

    const firearmContainer =
        document.getElementById("range-firearms");

    const firearmTemplate =
        document.getElementById("range-firearm-template");

    const ammoTemplate =
        document.getElementById("range-ammo-template");

    const addFirearmButton =
        document.getElementById("add-firearm");

    const saveButton = rangeSave;

    const occurredDate =
        document.getElementById("occurred-date");

    rangeForm.addEventListener(
        "submit",
        saveRangeSession
    );

    let firearmCounter = 0;

    function setDefaultDate() {
        if (occurredDate.value) {
            return;
        }

        const now = new Date();

        const year = now.getFullYear();
        const month = String(now.getMonth() + 1).padStart(2, "0");
        const day = String(now.getDate()).padStart(2, "0");

        occurredDate.value = `${year}-${month}-${day}`;
    }

    function optionalValue(value) {
        const cleaned = value.trim();
        return cleaned || null;
    }

    function updateFirearmTitles() {
        const cards = [
            ...firearmContainer.querySelectorAll(
                ".range-firearm-card"
            ),
        ];

        cards.forEach((card, index) => {
            const title = card.querySelector(
                ".range-firearm-title"
            );

            title.textContent = `Firearm ${index + 1}`;

            const removeButton = card.querySelector(
                ".range-remove-firearm"
            );

            removeButton.hidden = cards.length === 1;
        });
    }

    function updateAmmoTitles(card) {
        const rows = [
            ...card.querySelectorAll(".range-ammo-row"),
        ];

        rows.forEach((row, index) => {
            const title = row.querySelector(
                ".range-ammo-title"
            );

            title.textContent = `Ammunition ${index + 1}`;

            const removeButton = row.querySelector(
                ".range-remove-ammo"
            );

            removeButton.hidden = rows.length === 1;
        });
    }

    function updateFirearmOptions() {
        const selects = [
            ...firearmContainer.querySelectorAll(
                ".range-firearm-select"
            ),
        ];

        const selectedValues = new Set(
            selects
                .map((select) => select.value)
                .filter(Boolean)
        );

        selects.forEach((select) => {
            const ownValue = select.value;

            [...select.options].forEach((option) => {
                if (!option.value) {
                    return;
                }

                option.disabled =
                    option.value !== ownValue &&
                    selectedValues.has(option.value);
            });
        });

        const availableFirearms = [
            ...firearmTemplate.content.querySelectorAll(
                ".range-firearm-select option"
            ),
        ].filter((option) => option.value);

        addFirearmButton.disabled =
            selects.length >= availableFirearms.length;
    }

function configureAmmoRow(row) {
    const source =
        row.querySelector(".range-ammo-source");

    const inventoryField =
        row.querySelector(".range-inventory-field");

    const otherField =
        row.querySelector(".range-other-field");

    const ammoLot =
        row.querySelector(".range-ammo-lot");

    const description =
        row.querySelector(".range-ammo-description");

    const quantity =
        row.querySelector(".range-ammo-quantity");

    function updateInventoryMaximum() {
        const selected =
            ammoLot.options[ammoLot.selectedIndex];

        const onHand = Number(
            selected?.dataset.onHand || 0
        );

        let available = onHand;

        if (
            row.dataset.originalLotId &&
            ammoLot.value === row.dataset.originalLotId
        ) {
            available += Number(
                row.dataset.originalQuantity || 0
            );
        }

        quantity.max = String(available);
    }

    function updateSource() {
        const inventory =
            source.value === "inventory";

        inventoryField.hidden = !inventory;
        otherField.hidden = inventory;

        ammoLot.disabled = !inventory;
        description.disabled = inventory;

        if (inventory) {
            description.value = "";
            updateInventoryMaximum();
        } else {
            ammoLot.value = "";
            quantity.removeAttribute("max");
        }

        validateForm();
    }

    source.addEventListener(
        "change",
        updateSource
    );

    ammoLot.addEventListener(
        "change",
        () => {
            updateInventoryMaximum();
            validateForm();
        }
    );

    quantity.addEventListener(
        "input",
        validateForm
    );

    description.addEventListener(
        "input",
        validateForm
    );

    row.querySelector(
        ".range-remove-ammo"
    ).addEventListener("click", () => {
        const card = row.closest(
            ".range-firearm-card"
        );

        row.remove();

        updateAmmoTitles(card);
        validateForm();
    });

    updateSource();
}

function addAmmoRow(card, initial = null) {
    const fragment =
        ammoTemplate.content.cloneNode(true);

    const row =
        fragment.querySelector(".range-ammo-row");

    if (initial?.range_session_ammo_usage_id) {
        row.dataset.usageId =
            initial.range_session_ammo_usage_id;
    }

    configureAmmoRow(row);

    card.querySelector(
        ".range-ammo-rows"
    ).appendChild(fragment);

    if (initial) {
        const source =
            row.querySelector(".range-ammo-source");

        const quantity =
            row.querySelector(".range-ammo-quantity");

        const ammoLot =
            row.querySelector(".range-ammo-lot");

        const description =
            row.querySelector(".range-ammo-description");

        quantity.value =
            String(initial.quantity);

        if (initial.source_type === "inventory") {
            row.dataset.originalLotId =
                initial.ammo_lot_id || "";

            row.dataset.originalQuantity =
                String(initial.quantity);

            ammoLot.value =
                initial.ammo_lot_id || "";
        }

        source.value =
            initial.source_type;

        source.dispatchEvent(
            new Event("change")
        );

        if (initial.source_type === "other") {
            description.value =
                initial.description || "";
        }
    }

    updateAmmoTitles(card);
    validateForm();
}

    function addFirearmCard(initial = null) {
        firearmCounter += 1;

        const fragment =
            firearmTemplate.content.cloneNode(true);

        const card =
            fragment.querySelector(".range-firearm-card");

        card.dataset.firearmIndex =
            String(firearmCounter);
        
        if (initial?.range_session_firearm_id) {
            card.dataset.sessionFirearmId =
                initial.range_session_firearm_id;
        }

        const firearmSelect =
            card.querySelector(".range-firearm-select");

        firearmSelect.addEventListener(
            "change",
            () => {
                updateFirearmOptions();
                validateForm();
            }
        );

        card.querySelector(
            ".range-firearm-notes"
        ).addEventListener("input", validateForm);

        card.querySelector(
            ".range-add-ammo"
        ).addEventListener("click", () => {
            addAmmoRow(card);
        });

        card.querySelector(
            ".range-remove-firearm"
        ).addEventListener("click", () => {
            card.remove();

            updateFirearmTitles();
            updateFirearmOptions();
            validateForm();
        });

        firearmContainer.appendChild(fragment);

        if (initial) {
            firearmSelect.value =
                initial.firearm_id || "";

            card.querySelector(
                ".range-firearm-notes"
            ).value = initial.notes || "";

            for (const ammo of initial.ammo_usage || []) {
                addAmmoRow(card, ammo);
            }

            if (!initial.ammo_usage?.length) {
                addAmmoRow(card);
            }
        } else {
            addAmmoRow(card);
        }

        updateFirearmTitles();
        updateFirearmOptions();
        validateForm();
    }

function ammoRowIsValid(row) {
    const source =
        row.querySelector(".range-ammo-source").value;

    const quantity = Number(
        row.querySelector(".range-ammo-quantity").value
    );

    if (
        !Number.isInteger(quantity) ||
        quantity <= 0
    ) {
        return false;
    }

    if (source === "inventory") {
        const ammoLot =
            row.querySelector(".range-ammo-lot");

        if (!ammoLot.value) {
            return false;
        }

        const selected =
            ammoLot.options[ammoLot.selectedIndex];

        const onHand = Number(
            selected?.dataset.onHand || 0
        );

        let available = onHand;

        if (
            row.dataset.originalLotId &&
            ammoLot.value === row.dataset.originalLotId
        ) {
            available += Number(
                row.dataset.originalQuantity || 0
            );
        }

        return quantity <= available;
    }

    if (source === "other") {
        return true;
    }

    return false;
}

    function firearmCardIsValid(card) {
        const firearm =
            card.querySelector(".range-firearm-select");

        if (!firearm.value) {
            return false;
        }

        const ammoRows = [
            ...card.querySelectorAll(".range-ammo-row"),
        ];

        if (ammoRows.length === 0) {
            return false;
        }

        return ammoRows.every(ammoRowIsValid);
    }

    function validateForm() {
        const cards = [
            ...firearmContainer.querySelectorAll(
                ".range-firearm-card"
            ),
        ];

        const valid =
            Boolean(occurredDate.value) &&
            cards.length > 0 &&
            cards.every(firearmCardIsValid);

        saveButton.disabled = !valid;
    }

    occurredDate.addEventListener(
        "change",
        validateForm
    );

    addFirearmButton.addEventListener(
        "click",
        addFirearmCard
    );

    const initialData = window.rangeInitialData;

    if (initialData) {
        occurredDate.value =
            initialData.occurred_date || "";

        document.getElementById("location").value =
            initialData.location || "";

        document.getElementById("notes").value =
            initialData.notes || "";

        for (const firearm of initialData.firearms || []) {
            addFirearmCard(firearm);
        }
    } else {
        setDefaultDate();
        addFirearmCard();
    }

    async function saveRangeSession(event) {
    event.preventDefault();

    rangeFormError.textContent = "";

    const occurredDate =
        document.getElementById("occurred-date").value;

    const location =
        document.getElementById("location").value;

    const notes =
        document.getElementById("notes").value;

    if (!occurredDate) {
        rangeFormError.textContent =
            "Range date is required.";
        return;
    }

    const firearmCards = [
        ...document.querySelectorAll(
            ".range-firearm-card"
        ),
    ];

    if (firearmCards.length === 0) {
        rangeFormError.textContent =
            "Add at least one firearm.";
        return;
    }

    const firearms = [];

    for (const card of firearmCards) {
        const firearmSelect =
            card.querySelector(
                ".range-firearm-select"
            );

        const firearmNotes =
            card.querySelector(
                ".range-firearm-notes"
            );

        if (!firearmSelect.value) {
            rangeFormError.textContent =
                "Select a firearm for each firearm entry.";

            firearmSelect.focus();
            return;
        }

        const ammoRows = [
            ...card.querySelectorAll(
                ".range-ammo-row"
            ),
        ];

        if (ammoRows.length === 0) {
            rangeFormError.textContent =
                "Each firearm must include at least one ammunition entry.";
            return;
        }

        const ammoUsage = [];

        for (const row of ammoRows) {
            const source =
                row.querySelector(
                    ".range-ammo-source"
                );

            const quantity =
                row.querySelector(
                    ".range-ammo-quantity"
                );

            const ammoLot =
                row.querySelector(
                    ".range-ammo-lot"
                );

            const description =
                row.querySelector(
                    ".range-ammo-description"
                );

            const usageId =
                row.dataset.usageId || null;

            const parsedQuantity =
                Number.parseInt(
                    quantity.value,
                    10
                );

            if (
                !Number.isInteger(parsedQuantity) ||
                parsedQuantity <= 0
            ) {
                rangeFormError.textContent =
                    "Rounds fired must be greater than zero.";

                quantity.focus();
                return;
            }

            if (source.value === "inventory") {
                if (!ammoLot.value) {
                    rangeFormError.textContent =
                        "Select ammunition from inventory.";

                    ammoLot.focus();
                    return;
                }

                ammoUsage.push({
                    range_session_ammo_usage_id:
                        usageId,
                    source_type: "inventory",
                    quantity: parsedQuantity,
                    ammo_lot_id: ammoLot.value,
                    description: null,
                });
            } else if (source.value === "other") {
                ammoUsage.push({
                    range_session_ammo_usage_id:
                        usageId,
                    source_type: "other",
                    quantity: parsedQuantity,
                    ammo_lot_id: null,
                    description:
                        optionalValue(
                            description.value
                        ),
                });
            } else {
                rangeFormError.textContent =
                    "Select a valid ammunition source.";
                return;
            }
        }

        firearms.push({
            range_session_firearm_id:
                card.dataset.sessionFirearmId ||
                null,
            firearm_id:
                firearmSelect.value,
            notes:
                optionalValue(
                    firearmNotes.value
                ),
            ammo_usage: ammoUsage,
        });
    }

    const editMode =
        rangeForm.dataset.mode === "edit";

    const sessionId =
        rangeForm.dataset.sessionId;

    const saveUrl =
        editMode
            ? `/range/${sessionId}`
            : "/range/";

    const saveMethod =
        editMode ? "PUT" : "POST";

    rangeSave.disabled = true;
    rangeSave.textContent = "Saving...";

    try {
        const response = await fetch(
            saveUrl,
            {
                method: saveMethod,
                headers: {
                    "Content-Type":
                        "application/json",
                    "Accept":
                        "application/json",
                },
                body: JSON.stringify({
                    occurred_date:
                        occurredDate,
                    location:
                        optionalValue(
                            location
                        ),
                    notes:
                        optionalValue(
                            notes
                        ),
                    firearms:
                        firearms,
                }),
            }
        );

        const data =
            await response.json();

        if (
            !response.ok ||
            !data.success
        ) {
            rangeFormError.textContent =
                data.error ||
                data.detail ||
                "Unable to save range session.";
            return;
        }

        if (editMode) {
            window.location.href =
                `/range/${data.range_session.id}`;
        } else {
            window.location.href =
                "/range/";
        }
    } catch (error) {
        console.error(error);

        rangeFormError.textContent =
            "Unable to save range session.";
    } finally {
        rangeSave.disabled = false;

        rangeSave.textContent =
            editMode
                ? "Save Changes"
                : "Save Range Session";
    }
}
    
});
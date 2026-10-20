document.addEventListener("DOMContentLoaded", () => {
    const form = document.getElementById("ammunition-form");
    if (!form) return;

    const saveButton = document.getElementById("ammunition-save");
    const errorElement = document.getElementById("ammunition-form-error");
    const dateInput = document.getElementById("acquired-date");
    const manufacturerSearch = document.getElementById("manufacturer-search");
    const manufacturerId = document.getElementById("manufacturer-id");
    const manufacturerResults = document.getElementById("manufacturer-results");
    const modal = document.getElementById("duplicate-ammunition-modal");
    const list = document.getElementById("duplicate-ammunition-list");
    let pendingPayload = null;
    let manufacturerSearchTimer = null;

    if (!dateInput.value) {
        const now = new Date();
        dateInput.value = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
    }

    const optionalValue = (id) => document.getElementById(id).value.trim() || null;

    function addManufacturerOption(name, id, label = "Select manufacturer") {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "lookup-option";
        button.dataset.manufacturerId = id;
        button.dataset.manufacturerName = name;
        const caption = document.createElement("span");
        caption.className = "lookup-label";
        caption.textContent = label;
        const value = document.createElement("strong");
        value.textContent = name;
        button.append(caption, value);
        manufacturerResults.append(button);
    }

    function renderManufacturerResults(data, term) {
        manufacturerResults.replaceChildren();
        if (data.exact) {
            addManufacturerOption(data.exact.name, data.exact.id, "Manufacturer found");
            return;
        }
        for (const item of data.similar || []) {
            addManufacturerOption(item.name, item.id, "Possible match");
        }
        const create = document.createElement("button");
        create.type = "button";
        create.className = "lookup-option lookup-option-create";
        create.dataset.createManufacturer = term;
        create.textContent = `+ Add “${term}” as a manufacturer`;
        manufacturerResults.append(create);
    }

    async function searchManufacturers(term) {
        if (term.length < 2) {
            manufacturerResults.replaceChildren();
            return;
        }
        const status = document.createElement("div");
        status.className = "lookup-status";
        status.textContent = "Searching manufacturers…";
        manufacturerResults.replaceChildren(status);
        try {
            const response = await fetch(`/firearms/manufacturer-search?q=${encodeURIComponent(term)}`, {
                headers: { "Accept": "application/json" },
            });
            if (!response.ok) throw new Error(`Search failed with status ${response.status}`);
            renderManufacturerResults(await response.json(), term);
        } catch (error) {
            console.error(error);
            const failure = document.createElement("div");
            failure.className = "lookup-status lookup-error";
            failure.textContent = "Manufacturer search is currently unavailable.";
            manufacturerResults.replaceChildren(failure);
        }
    }

    manufacturerSearch.addEventListener("input", () => {
        manufacturerId.value = "";
        clearTimeout(manufacturerSearchTimer);
        const term = manufacturerSearch.value.trim();
        manufacturerSearchTimer = setTimeout(() => searchManufacturers(term), 250);
    });

    manufacturerResults.addEventListener("click", async (event) => {
        const option = event.target.closest("button");
        if (!option) return;
        if (option.dataset.manufacturerId) {
            manufacturerId.value = option.dataset.manufacturerId;
            manufacturerSearch.value = option.dataset.manufacturerName;
            manufacturerResults.replaceChildren();
            return;
        }
        const name = option.dataset.createManufacturer;
        if (!name) return;
        option.disabled = true;
        option.textContent = "Adding manufacturer…";
        try {
            const response = await fetch("/firearms/manufacturers", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name }),
            });
            const data = await response.json();
            if (!response.ok || !data?.success || !data?.manufacturer) {
                throw new Error(data?.error || data?.detail || "Unable to add manufacturer.");
            }
            manufacturerId.value = data.manufacturer.id;
            manufacturerSearch.value = data.manufacturer.name;
            manufacturerResults.replaceChildren();
        } catch (error) {
            errorElement.textContent = error.message || "Unable to add manufacturer.";
            await searchManufacturers(name);
        }
    });
    const closeModal = () => {
        modal.hidden = true;
        pendingPayload = null;
        saveButton.focus();
    };

    function showSuggestions(suggestions) {
        list.replaceChildren();
        for (const suggestion of suggestions) {
            const item = document.createElement("article");
            item.className = "duplicate-ammunition-option";
            const details = document.createElement("div");
            const title = document.createElement("strong");
            title.textContent = `${suggestion.brand} · ${suggestion.caliber}${suggestion.grain_weight ? ` · ${suggestion.grain_weight} gr` : ""}${suggestion.projectile_type ? ` · ${suggestion.projectile_type}` : ""}`;
            const quantity = document.createElement("p");
            quantity.textContent = `On hand: ${suggestion.quantity_on_hand.toLocaleString()} rounds · Requested: ${pendingPayload.quantity.toLocaleString()} rounds`;
            const created = document.createElement("p");
            created.textContent = `Lot record created: ${String(suggestion.created_at || "").slice(0, 10)}`;
            const add = document.createElement("button");
            add.type = "button";
            add.className = "button-secondary";
            add.dataset.lotId = suggestion.id;
            add.textContent = "Add to Existing Lot";
            details.append(title, quantity, created);
            item.append(details, add);
            list.append(item);
        }
        modal.hidden = false;
        document.getElementById("duplicate-modal-cancel").focus();
    }

    async function submitAcquisition(payload) {
        saveButton.disabled = true;
        saveButton.textContent = "Adding...";
        errorElement.textContent = "";
        try {
            const response = await fetch("/ammunition/", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            const data = await response.json();
            if (data?.duplicate_suggestions?.length) {
                pendingPayload = payload;
                showSuggestions(data.duplicate_suggestions);
                return;
            }
            if (!response.ok || !data?.success) {
                errorElement.textContent = data?.error || data?.detail || "Unable to add ammunition.";
                return;
            }
            window.location.href = "/ammunition/";
        } catch (error) {
            console.error(error);
            errorElement.textContent = "Unable to communicate with Armory Ledger.";
        } finally {
            saveButton.disabled = false;
            saveButton.textContent = "Add Ammunition";
        }
    }

    form.addEventListener("submit", (event) => {
        event.preventDefault();
        errorElement.textContent = "";
        const selectedManufacturerId = manufacturerId.value;
        const caliberId = document.getElementById("caliber").value;
        const grainText = document.getElementById("grain-weight").value.trim();
        const quantityText = document.getElementById("quantity").value.trim();
        const quantity = Number(quantityText);
        if (!selectedManufacturerId || !caliberId || !quantityText || !dateInput.value) {
            errorElement.textContent = "Select a manufacturer and complete the required ammunition fields.";
            return;
        }
        if (!Number.isInteger(quantity) || quantity <= 0) {
            errorElement.textContent = "Quantity must be a whole number greater than zero.";
            return;
        }
        const grainWeight = grainText ? Number(grainText) : null;
        if (grainWeight !== null && (!Number.isFinite(grainWeight) || grainWeight <= 0)) {
            errorElement.textContent = "Grain weight must be greater than zero.";
            return;
        }
        submitAcquisition({
            manufacturer_id: selectedManufacturerId,
            caliber_id: caliberId,
            grain_weight: grainWeight,
            projectile_type: optionalValue("projectile-type"),
            quantity,
            acquired_date: dateInput.value,
            product_name: optionalValue("product-name"),
            manufacturer_sku: optionalValue("manufacturer-sku"),
            lot_number: optionalValue("lot-number"),
            notes: optionalValue("notes"),
        });
    });

    list.addEventListener("click", (event) => {
        const button = event.target.closest("button[data-lot-id]");
        if (!button || !pendingPayload) return;
        try {
            sessionStorage.setItem("armoryAmmoActivityPrefill", JSON.stringify({
                lotId: button.dataset.lotId,
                quantity: pendingPayload.quantity,
                transactionType: "acquired",
                expiresAt: Date.now() + 5 * 60 * 1000,
            }));
            window.location.href = `/ammunition/${encodeURIComponent(button.dataset.lotId)}/activity/new`;
        } catch {
            errorElement.textContent = "Unable to prepare the existing-lot activity. Please allow session storage and try again.";
        }
    });

    document.getElementById("duplicate-create-new").addEventListener("click", () => {
        if (!pendingPayload) return;
        const payload = { ...pendingPayload, create_separate_lot: true };
        closeModal();
        submitAcquisition(payload);
    });
    document.getElementById("duplicate-modal-cancel").addEventListener("click", closeModal);
    document.getElementById("duplicate-modal-close").addEventListener("click", closeModal);
    modal.addEventListener("click", (event) => {
        if (event.target === modal) closeModal();
    });
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && !modal.hidden) closeModal();
    });
    saveButton.disabled = false;
});

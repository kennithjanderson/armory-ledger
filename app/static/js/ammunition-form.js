document.addEventListener("DOMContentLoaded", () => {
    const form = document.getElementById("ammunition-form");
    if (!form) return;

    const saveButton = document.getElementById("ammunition-save");
    const errorElement = document.getElementById("ammunition-form-error");
    const dateInput = document.getElementById("acquired-date");
    const modal = document.getElementById("duplicate-ammunition-modal");
    const list = document.getElementById("duplicate-ammunition-list");
    let pendingPayload = null;

    if (!dateInput.value) {
        const now = new Date();
        dateInput.value = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
    }

    const optionalValue = (id) => document.getElementById(id).value.trim() || null;
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
        const brandName = document.getElementById("brand-name").value.trim();
        const caliberId = document.getElementById("caliber").value;
        const grainText = document.getElementById("grain-weight").value.trim();
        const quantityText = document.getElementById("quantity").value.trim();
        const quantity = Number(quantityText);
        if (!brandName || !caliberId || !quantityText || !dateInput.value) {
            errorElement.textContent = "Complete the required ammunition fields.";
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
            brand_name: brandName,
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

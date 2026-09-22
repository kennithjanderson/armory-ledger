document.addEventListener("DOMContentLoaded", () => {
    const form = document.getElementById("ammunition-form");

    if (!form) {
        return;
    }

    const saveButton = document.getElementById("ammunition-save");
    const errorElement = document.getElementById("ammunition-form-error");
    const acquiredDateInput =
        document.getElementById("acquired-date");

    if (!acquiredDateInput.value) {
        const now = new Date();

        const year = now.getFullYear();
        const month = String(now.getMonth() + 1).padStart(2, "0");
        const day = String(now.getDate()).padStart(2, "0");

        acquiredDateInput.value = `${year}-${month}-${day}`;
    }

    function optionalValue(id) {
        const value = document.getElementById(id).value.trim();
        return value || null;
    }

    async function saveAmmunition(event) {
        event.preventDefault();

        errorElement.textContent = "";

        const brandName =
            document.getElementById("brand-name").value.trim();

        const caliberId =
            document.getElementById("caliber").value;

        const grainWeight =
            document.getElementById("grain-weight").value.trim();

        const projectileType =
            optionalValue("projectile-type");

        const quantityValue =
            document.getElementById("quantity").value.trim();
        
        const acquiredDate = acquiredDateInput.value;

        if (!brandName) {
            errorElement.textContent = "Brand is required.";
            return;
        }

        if (!caliberId) {
            errorElement.textContent = "Caliber is required.";
            return;
        }

        if (!quantityValue) {
            errorElement.textContent = "Quantity is required.";
            return;
        }

        if (!acquiredDate) {
            errorElement.textContent = "Acquired date is required.";
            return;
        }

        const quantity = Number(quantityValue);

        if (!Number.isInteger(quantity) || quantity <= 0) {
            errorElement.textContent =
                "Quantity must be a whole number greater than zero.";
            return;
        }

        let parsedGrainWeight = null;

        if (grainWeight) {
            parsedGrainWeight = Number(grainWeight);

            if (
                !Number.isFinite(parsedGrainWeight) ||
                parsedGrainWeight <= 0
            ) {
                errorElement.textContent =
                    "Grain weight must be greater than zero.";
                return;
            }
        }

        saveButton.disabled = true;
        saveButton.textContent = "Adding...";

        try {
            const response = await fetch("/ammunition/", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({
                    brand_name: brandName,
                    caliber_id: caliberId,
                    grain_weight: parsedGrainWeight,
                    projectile_type: projectileType,
                    quantity,
                    acquired_date: acquiredDate,
                    product_name: optionalValue("product-name"),
                    manufacturer_sku: optionalValue("manufacturer-sku"),
                    lot_number: optionalValue("lot-number"),
                    notes: optionalValue("notes"),
                }),
            });

            let data = null;

            try {
                data = await response.json();
            } catch {
                // Leave data null and show the generic error below.
            }

            if (!response.ok || !data?.success) {
                errorElement.textContent =
                    data?.error ||
                    data?.detail ||
                    "Unable to add ammunition.";
                return;
            }

            window.location.href = "/ammunition/";
        } catch (error) {
            console.error(error);

            errorElement.textContent =
                "Unable to communicate with Armory Ledger.";
        } finally {
            saveButton.disabled = false;
            saveButton.textContent = "Add Ammunition";
        }
    }

    form.addEventListener("submit", saveAmmunition);

    saveButton.disabled = false;
});

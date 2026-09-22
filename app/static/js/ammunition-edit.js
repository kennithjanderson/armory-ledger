document.addEventListener("DOMContentLoaded", () => {
    const form = document.getElementById("ammunition-edit-form");
    const errorElement = document.getElementById("ammunition-edit-error");

    if (!form) {
        return;
    }

    const saveButton = form.querySelector('button[type="submit"]');
    const lotId = form.dataset.lotId;

    saveButton.disabled = false;

    const optionalValue = (id) => {
        const value = document.getElementById(id).value.trim();
        return value === "" ? null : value;
    };

    form.addEventListener("submit", async (event) => {
        event.preventDefault();

        errorElement.hidden = true;
        errorElement.textContent = "";

        const caliberId = document.getElementById("caliber_id").value;
        const grainRaw = optionalValue("grain_weight");

        const payload = {
            caliber_id: caliberId,
            grain_weight: grainRaw === null ? null : Number(grainRaw),
            projectile_type: optionalValue("projectile_type"),
            product_name: optionalValue("product_name"),
            manufacturer_sku: optionalValue("manufacturer_sku"),
            lot_number: optionalValue("lot_number"),
            notes: optionalValue("notes"),
            acquired_date: optionalValue("acquired_date"),
        };

        if (
            payload.grain_weight !== null &&
            (
                !Number.isFinite(payload.grain_weight) ||
                payload.grain_weight <= 0
            )
        ) {
            errorElement.textContent =
                "Grain weight must be greater than zero.";
            errorElement.hidden = false;
            return;
        }

        saveButton.disabled = true;
        saveButton.textContent = "Saving...";

        try {
            const response = await fetch(`/ammunition/${lotId}`, {
                method: "PUT",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify(payload),
            });

            const data = await response.json();

            if (!response.ok || !data.success) {
                throw new Error(
                    data.error ||
                    data.detail ||
                    "Unable to update ammunition."
                );
            }

            window.location.href = `/ammunition/${lotId}`;
        } catch (error) {
            errorElement.textContent = error.message;
            errorElement.hidden = false;
        } finally {
            saveButton.disabled = false;
            saveButton.textContent = "Save Changes";
        }
    });
});

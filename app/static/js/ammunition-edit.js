document.addEventListener("DOMContentLoaded", () => {
    const form = document.getElementById("ammunition-edit-form");
    const errorElement = document.getElementById("ammunition-edit-error");

    if (!form) {
        return;
    }

    const saveButton = form.querySelector('button[type="submit"]');
    const lotId = form.dataset.lotId;
    const ammunitionTypeInput = document.getElementById("ammunition-type");

    function updateTypeFields() {
        const shotgun = ammunitionTypeInput?.value === "shotgun";
        for (const id of ["grain-weight-field", "projectile-type-field"]) {
            const field = document.getElementById(id);
            if (field) field.hidden = shotgun;
        }
        for (const id of ["shell-length-field", "shot-size-field", "shot-type-field"]) {
            const field = document.getElementById(id);
            if (field) field.hidden = !shotgun;
        }
        const caliberLabel = document.getElementById("caliber-label");
        if (caliberLabel) caliberLabel.textContent = shotgun ? "Caliber / Gauge" : "Caliber";
        const caliberPlaceholder = document.getElementById("caliber-placeholder");
        if (caliberPlaceholder) caliberPlaceholder.textContent = shotgun ? "Select caliber / gauge" : "Select caliber";
    }

    if (ammunitionTypeInput) {
        ammunitionTypeInput.addEventListener("change", updateTypeFields);
        updateTypeFields();
    }

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
        const ammunitionType = ammunitionTypeInput?.value || null;
        const grainRaw = ammunitionType === "shotgun" ? null : optionalValue("grain_weight");
        const shellLengthRaw = ammunitionType === "shotgun"
            ? optionalValue("shell_length_inches") : null;
        const shellLength = shellLengthRaw === null ? null : Number(shellLengthRaw);

        const payload = {
            caliber_id: caliberId,
            ammunition_type: ammunitionType,
            grain_weight: grainRaw === null ? null : Number(grainRaw),
            projectile_type: ammunitionType === "shotgun" ? null : optionalValue("projectile_type"),
            shell_length_inches: shellLength,
            shot_size: ammunitionType === "shotgun" ? optionalValue("shot_size") : null,
            shot_type: ammunitionType === "shotgun" ? optionalValue("shot_type") : null,
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
        if (shellLength !== null && (!Number.isFinite(shellLength) || shellLength <= 0
                || shellLength > 99.99 || !/^\d+(\.\d{1,2})?$/.test(shellLengthRaw))) {
            errorElement.textContent = "Shell length must be a positive inch value with no more than two decimal places.";
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

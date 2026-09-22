document.addEventListener("DOMContentLoaded", () => {
    const form = document.getElementById("ammunition-activity-form");

    if (!form) {
        return;
    }

    const lotId = form.dataset.lotId;
    const saveButton = document.getElementById(
        "ammunition-activity-save"
    );
    const errorElement = document.getElementById(
        "ammunition-activity-error"
    );
    const dateInput = document.getElementById("occurred_date");

    if (!dateInput.value) {
        const now = new Date();

        const year = now.getFullYear();
        const month = String(now.getMonth() + 1).padStart(2, "0");
        const day = String(now.getDate()).padStart(2, "0");

        dateInput.value = `${year}-${month}-${day}`;
    }

    saveButton.disabled = false;

    form.addEventListener("submit", async (event) => {
        event.preventDefault();

        errorElement.hidden = true;
        errorElement.textContent = "";

        const transactionType =
            document.getElementById("transaction_type").value;

        const quantity = Number(
            document.getElementById("quantity").value
        );

        const occurredDate = dateInput.value;

        const notesValue =
            document.getElementById("notes").value.trim();

        if (!transactionType) {
            errorElement.textContent = "Select an activity.";
            errorElement.hidden = false;
            return;
        }

        if (!Number.isInteger(quantity) || quantity <= 0) {
            errorElement.textContent =
                "Quantity must be a positive whole number.";
            errorElement.hidden = false;
            return;
        }

        if (!occurredDate) {
            errorElement.textContent = "Select a date.";
            errorElement.hidden = false;
            return;
        }

        saveButton.disabled = true;
        saveButton.textContent = "Recording...";

        try {
            const response = await fetch(
                `/ammunition/${lotId}/activity`,
                {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                    },
                    body: JSON.stringify({
                        transaction_type: transactionType,
                        quantity: quantity,
                        occurred_date: occurredDate,
                        notes: notesValue || null,
                    }),
                }
            );

            const data = await response.json();

            if (!response.ok || !data.success) {
                throw new Error(
                    data.error ||
                    data.detail ||
                    "Unable to record ammunition activity."
                );
            }

            window.location.href = `/ammunition/${lotId}`;
        } catch (error) {
            errorElement.textContent = error.message;
            errorElement.hidden = false;
        } finally {
            saveButton.disabled = false;
            saveButton.textContent = "Record Activity";
        }
    });
});

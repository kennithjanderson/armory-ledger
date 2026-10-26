document.addEventListener("DOMContentLoaded", () => {
    const createForm = document.getElementById("caliber-alias-create");
    const message = document.getElementById("caliber-alias-message");
    if (!createForm || !message) return;

    function showMessage(text, isError = false) {
        message.textContent = text;
        message.classList.toggle("operation-message--error", isError);
    }

    async function send(method, endpoint, token, payload) {
        const response = await fetch(endpoint, {
            method,
            headers: {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-CSRF-Token": token,
            },
            ...(payload === undefined ? {} : {body: JSON.stringify(payload)}),
        });
        let data = null;
        try { data = await response.json(); } catch { /* use the generic response below */ }
        if (!response.ok || data?.success !== true) {
            throw new Error(typeof data?.detail === "string"
                ? data.detail
                : "The alias change could not be saved.");
        }
    }

    createForm.addEventListener("submit", async event => {
        event.preventDefault();
        const input = createForm.elements.alias;
        try {
            await send("POST", createForm.dataset.endpoint, createForm.dataset.csrfToken, {alias: input.value});
            window.location.reload();
        } catch (error) {
            showMessage(error.message || "The alias could not be added.", true);
        }
    });

    for (const button of document.querySelectorAll(".caliber-alias-delete")) {
        button.addEventListener("click", async () => {
            if (!window.confirm(`Remove the “${button.dataset.alias}” caliber alias? Existing inventory and history keep their canonical caliber ID.`)) return;
            try {
                await send("DELETE", button.dataset.endpoint, button.dataset.csrfToken);
                window.location.reload();
            } catch (error) {
                showMessage(error.message || "The alias could not be removed.", true);
            }
        });
    }

    const nameForm = document.getElementById("caliber-name-update");
    if (nameForm) {
        nameForm.addEventListener("submit", async event => {
            event.preventDefault();
            const input = nameForm.elements.name;
            const current = nameForm.dataset.currentName;
            if (!window.confirm(
                `Rename “${current}” to “${input.value.trim()}”? This shared change affects all users. Confirm the new text refers to the same caliber. The old name remains an alias and saved records keep their existing caliber ID.`
            )) return;
            try {
                await send("PUT", nameForm.dataset.endpoint, nameForm.dataset.csrfToken, {name: input.value});
                window.location.reload();
            } catch (error) {
                showMessage(error.message || "The canonical name could not be changed.", true);
            }
        });
    }
});

document.addEventListener("DOMContentLoaded", () => {
    const form = document.getElementById("merge-form");
    if (!form) return;
    const destination = document.getElementById("merge-destination");
    const confirmation = document.getElementById("merge-confirmation");
    const error = document.getElementById("merge-error");
    const submit = document.getElementById("merge-submit");
    const review = document.getElementById("merge-review");
    const cancel = document.getElementById("merge-cancel");
    const records = document.getElementById("merge-check-records");
    const destinationLink = document.getElementById("merge-destination-link");
    let reviewed = null;
    let locked = false;

    function setDisabled(disabled) {
        for (const control of [submit, destination, review, cancel]) control.disabled = disabled;
    }
    function closeReview() {
        reviewed = null;
        confirmation.hidden = true;
    }
    function uncertain() {
        closeReview();
        error.textContent = "The result could not be verified. Check both lot records before starting another merge. This form will not retry.";
        records.hidden = false;
        // The request may have committed. Keep all mutation controls locked.
    }
    destination.addEventListener("change", () => {
        if (!locked) closeReview();
    });
    cancel.addEventListener("click", () => {
        if (locked) return;
        closeReview();
        review.focus();
    });
    review.addEventListener("click", () => {
        if (locked) return;
        error.textContent = "";
        if (!destination.value) {
            error.textContent = "Select a compatible destination lot.";
            destination.focus();
            return;
        }
        reviewed = {
            destination_id: destination.value,
            expected_source: Number(form.dataset.sourceQuantity),
            expected_destination: Number(destination.selectedOptions[0].dataset.quantity),
            confirmed: true,
        };
        destinationLink.href = destination.selectedOptions[0].dataset.recordUrl;
        document.getElementById("merge-preview").textContent =
            `You're about to move ${reviewed.expected_source} rounds from this lot into the selected destination lot.`;
        document.getElementById("merge-balance").textContent =
            `The destination will increase from ${reviewed.expected_destination} to ` +
            `${reviewed.expected_source + reviewed.expected_destination} rounds.`;
        document.getElementById("merge-destination-id").textContent = reviewed.destination_id;
        confirmation.hidden = false;
        submit.focus();
    });
    form.addEventListener("submit", async event => {
        event.preventDefault();
        if (!reviewed || locked) return;
        const submitted = reviewed;
        locked = true;
        setDisabled(true);
        error.textContent = "";
        let redirectUrl;
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 30000);
        try {
            const response = await fetch(`/ammunition/${form.dataset.sourceId}/merge`, {
                method: "POST",
                headers: {"Content-Type": "application/json", "Accept": "application/json", "X-CSRF-Token": form.dataset.csrfToken},
                body: JSON.stringify(submitted),
                signal: controller.signal,
            });
            let data;
            try { data = await response.json(); } catch { data = null; }
            if ((!response.ok && response.status >= 400 && response.status < 500 && response.status !== 408) ||
                (response.ok && data?.success === false)) {
                error.textContent = typeof data?.detail === "string" ? data.detail : "Merge rejected. Reload and review again.";
                closeReview();
                locked = false;
                setDisabled(false);
                return;
            }
            if (!response.ok || data?.success !== true ||
                data.destination_id !== submitted.destination_id || typeof data.redirect_url !== "string" ||
                typeof data.merge_id !== "string" || !data.merge_id) {
                uncertain();
                return;
            }
            const target = new URL(data.redirect_url, window.location.origin);
            if (target.origin !== window.location.origin || target.username || target.password ||
                target.pathname !== `/ammunition/${submitted.destination_id}` ||
                target.searchParams.get("merged") !== data.merge_id || target.hash) {
                uncertain();
                return;
            }
            redirectUrl = target.pathname + target.search;
        } catch {
            uncertain();
            return;
        } finally {
            clearTimeout(timeout);
        }
        // A verified commit remains successful even if browser navigation fails.
        closeReview();
        destinationLink.href = redirectUrl;
        records.hidden = false;
        error.textContent = "Merge completed. Opening the destination record…";
        try {
            window.location.assign(redirectUrl);
        } catch {
            error.textContent = "Merge completed. Open the destination record using the link below.";
        }
    });
});

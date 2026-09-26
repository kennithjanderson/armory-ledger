document.addEventListener("DOMContentLoaded", () => {
    const form = document.getElementById("announcement-form");
    if (!form) return;
    const error = document.getElementById("announcement-error");
    const button = form.querySelector('button[type="submit"]');

    function utcTimestamp(id) {
        const value = document.getElementById(id).value;
        if (!value) throw new Error("Enter both UTC schedule times.");
        // The form explicitly labels these wall-clock values as UTC.
        // Do not let the browser interpret them in its local timezone.
        const parsed = new Date(`${value}Z`);
        if (Number.isNaN(parsed.getTime())) throw new Error("Enter a valid UTC time.");
        return parsed.toISOString();
    }

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        error.textContent = "";
        button.disabled = true;
        try {
            const payload = {
                title: document.getElementById("title").value.trim(),
                message: document.getElementById("message").value.trim(),
                severity: document.getElementById("severity").value,
                enabled: document.getElementById("enabled").checked,
                starts_at: utcTimestamp("starts-at"),
                ends_at: utcTimestamp("ends-at"),
            };
            if (payload.ends_at <= payload.starts_at) {
                throw new Error("End time must be later than start time.");
            }
            const id = form.dataset.id;
            const response = await fetch(id ? `/admin/announcements/${id}` : "/admin/announcements", {
                method: id ? "PUT" : "POST",
                headers: {"Content-Type": "application/json", "X-CSRF-Token": form.dataset.csrf},
                body: JSON.stringify(payload),
            });
            if (response.redirected) throw new Error("Your session expired. Reload the page and sign in.");
            const data = await response.json();
            if (!response.ok) {
                const detail = Array.isArray(data.detail)
                    ? data.detail.map(item => item.msg).join(" ")
                    : data.detail;
                throw new Error(detail || "Unable to save announcement.");
            }
            window.location.href = "/admin/announcements";
        } catch (problem) {
            error.textContent = problem.message;
        } finally {
            button.disabled = false;
        }
    });
});

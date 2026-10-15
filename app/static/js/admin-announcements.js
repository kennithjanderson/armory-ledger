document.addEventListener("DOMContentLoaded", () => {
    const form = document.getElementById("announcement-form");
    if (!form) return;
    const error = document.getElementById("announcement-error");
    const submit = form.querySelector('button[type="submit"]');
    const zone = document.getElementById("schedule-zone");
    try { zone.value = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC"; }
    catch (_) { zone.value = "UTC"; }
    const fields = ["starts", "ends"].map(name => ({
        input: document.getElementById(`${name}-at`),
        occurrence: document.getElementById(`${name}-occurrence`),
        preview: document.getElementById(`${name}-preview`),
        revision: 0, instant: document.getElementById(`${name}-at`).dataset.instant || null,
        raw: null, displayed: null, pending: false,
    }));
    let saving = false;
    function busy() { submit.disabled = saving || fields.some(field => field.pending); }
    async function request(url, payload, method = "POST") {
        const response = await fetch(url, {method, headers: {
            "Content-Type": "application/json", "X-CSRF-Token": form.dataset.csrf,
        }, body: JSON.stringify(payload)});
        if (response.redirected) throw new Error("Your session expired. Reload and sign in again.");
        const data = await response.json();
        if (!response.ok) throw new Error(Array.isArray(data.detail)
            ? data.detail.map(item => item.msg).join(" ") : data.detail || "Unable to validate the schedule.");
        return data;
    }
    function localPayload(field) {
        // Native inputs may normalize fractional seconds. Keep exact server precision
        // until the administrator actually edits the displayed wall-clock value.
        return {timezone: zone.value, local_time: field.input.value === field.displayed
            ? field.raw : field.input.value, occurrence: field.occurrence.value || null};
    }
    async function preview(field, instant = null) {
        const revision = ++field.revision;
        field.pending = true; busy();
        field.preview.textContent = "Checking UTC equivalent…";
        try {
            const payload = instant ? {timezone: zone.value, instant} : localPayload(field);
            const data = await request("/admin/announcements/schedule-preview", payload);
            if (revision !== field.revision) return false;
            // Native datetime-local controls support milliseconds, not PostgreSQL's
            // full microsecond precision. Retain the exact value separately below.
            if (instant) field.input.value = data.local_time.replace(/(\.\d{3})\d+$/, "$1");
            window.ArmoryDateTime?.refresh(field.input);
            field.raw = data.local_time;
            field.displayed = field.input.value;
            field.instant = data.utc;
            field.occurrence.replaceChildren();
            if (data.options.length > 1) {
                field.occurrence.add(new Option("Choose earlier or later occurrence", ""));
                data.options.forEach(item => field.occurrence.add(new Option(item.label, item.occurrence)));
                field.occurrence.value = data.options.find(item => item.utc === data.utc)?.occurrence || "";
            } else {
                field.occurrence.add(new Option("Not required", ""));
            }
            field.occurrence.disabled = data.options.length === 1;
            field.occurrence.closest(".occurrence-field").hidden = data.options.length === 1;
            field.preview.title = data.utc || "";
            field.preview.textContent = data.utc
                ? `UTC equivalent: ${data.utc.slice(0,16).replace("T", " ") + " UTC"} (${zone.value})`
                : "This local time occurs twice. Choose an occurrence before saving.";
            return Boolean(data.utc);
        } catch (problem) {
            if (revision !== field.revision) return false;
            if (!instant) field.instant = null;
            field.occurrence.closest(".occurrence-field").hidden = true;
            field.preview.textContent = problem.message;
            return false;
        } finally {
            if (revision === field.revision) { field.pending = false; busy(); }
        }
    }
    fields.forEach(field => {
        field.input.addEventListener("input", () => {
            field.occurrence.value = ""; field.raw = null; field.displayed = null;
            field.instant = null;
            preview(field);
        });
        field.occurrence.addEventListener("change", () => preview(field));
        if (field.input.dataset.instant) preview(field, field.input.dataset.instant);
    });
    zone.addEventListener("change", () => {
        fields.forEach(field => {
            if (field.instant || field.input.value) preview(field, field.instant);
        });
    });
    form.addEventListener("submit", async event => {
        event.preventDefault();
        if (saving || fields.some(field => field.pending)) return;
        saving = true; busy(); error.textContent = "";
        try {
            const valid = await Promise.all(fields.map(field => preview(field)));
            if (!valid.every(Boolean)) throw new Error("Resolve the schedule errors above before saving.");
            const payload = {
                title: document.getElementById("title").value.trim(),
                message: document.getElementById("message").value.trim(),
                severity: document.getElementById("severity").value,
                enabled: document.getElementById("enabled").checked,
                starts_at: localPayload(fields[0]), ends_at: localPayload(fields[1]),
            };
            const id = form.dataset.id;
            await request(id ? `/admin/announcements/${id}` : "/admin/announcements", payload, id ? "PUT" : "POST");
            window.location.href = "/admin/announcements";
        } catch (problem) { error.textContent = problem.message; }
        finally { saving = false; busy(); }
    });
});

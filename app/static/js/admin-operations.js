(() => {
    'use strict';
    const message = document.getElementById('operation-message');
    const show = text => { message.textContent = text; };
    async function request(url, method = 'GET', data) {
        const response = await fetch(url, {method, headers: {'X-CSRF-Token': window.armoryOperationToken, ...(data instanceof File ? {} : {'Content-Type': 'application/json'})}, body: data === undefined ? undefined : data instanceof File ? data : JSON.stringify(data)});
        if (!response.ok) { const error = await response.json(); throw new Error(typeof error.detail === 'string' ? error.detail : 'Request failed'); }
        return response.json();
    }
    function formValues(form) {
        const result = {};
        for (const el of form.elements) if (el.name) result[el.name] = el.type === 'checkbox' ? el.checked : el.type === 'number' ? Number(el.value) : el.value;
        return result;
    }
    function fill(form, data) { for (const el of form.elements) if (el.name && el.name in data) { if (el.type === 'checkbox') el.checked = data[el.name]; else el.value = data[el.name]; } }
    function action(button, fn) { button?.addEventListener('click', async () => { button.disabled = true; try { await fn(); } catch (e) { show(e.message); } finally { button.disabled = false; } }); }
    const schedule = document.getElementById('backup-schedule');
    const timezone = schedule?.elements.namedItem('timezone');
    const timezoneRegion = document.getElementById('backup-timezone-region');
    let initialized = false;
    function filterTimezones() {
        if (!timezone || !timezoneRegion) return;
        const selected = timezone.options[timezone.selectedIndex];
        for (const option of timezone.options) {
            const visible = timezoneRegion.value === 'all' || option.dataset.zoneRegion === 'north_america';
            option.hidden = !visible;
            option.disabled = !visible;
        }
        if (selected && selected.disabled) timezone.value = 'UTC';
    }
    function syncTimezoneRegion() {
        if (!timezone || !timezoneRegion) return;
        const selected = timezone.options[timezone.selectedIndex];
        timezoneRegion.value = selected?.dataset.zoneRegion === 'other' ? 'all' : 'north_america';
        filterTimezones();
    }
    timezoneRegion?.addEventListener('change', filterTimezones);
    timezone?.addEventListener('change', () => {
        const selected = timezone.options[timezone.selectedIndex];
        timezoneRegion.value = selected?.dataset.zoneRegion === 'other' ? 'all' : 'north_america';
        filterTimezones();
    });
    async function refresh() {
        if (document.hidden) return;
        try {
            if (schedule) {
                const data = await request('/admin/backups/status');
                if (!initialized) { fill(schedule, data.health.schedule); syncTimezoneRegion(); }
                document.getElementById('backup-jobs').textContent = data.jobs.map(j => `${j.created} ${j.kind}: ${j.phase} ${j.error || ''}`).join('\n');
                const list = document.getElementById('backup-list'); list.replaceChildren();
                for (const row of data.backups) {
                    const item = document.createElement('article');
                    const title = document.createElement('p'); title.textContent = `${row.id}.armorybackup · ${row.created} · ${row.kind} · v${row.version} · ${row.size} bytes · ${row.status}`;
                    const actions = document.createElement('div'); actions.className = 'backup-record-actions';
                    if (row.status === 'valid') {
                        const link = document.createElement('a'); link.href = `/admin/backups/${row.id}/download`; link.textContent = 'Download'; link.className = 'button-secondary button-link'; actions.append(link);
                        const restore = document.createElement('button'); restore.textContent = 'Restore'; restore.className = 'button-secondary'; actions.append(restore);
                        action(restore, async () => { const confirmation = prompt(`Replace ALL application data with backup from ${row.created}, version ${row.version}? A pre-restore backup is required. You will need to sign in again. Type REPLACE ALL DATA.`); if (confirmation !== 'REPLACE ALL DATA') return; await request(`/admin/backups/${row.id}/restore`, 'POST', {confirmation}); show('Restore queued. Maintenance may temporarily interrupt this page.'); });
                    }
                    const remove = document.createElement('button'); remove.textContent = 'Delete'; remove.className = 'button-secondary'; actions.append(remove);
                    action(remove, async () => { const confirmation = prompt(`Permanently delete ${row.id}.armorybackup? Type DELETE.`); if (confirmation !== 'DELETE') return; await request(`/admin/backups/${row.id}`, 'DELETE', {confirmation}); await refresh(); });
                    item.append(title,actions); list.append(item);
                }
            } else {
                const data = await request('/admin/email/settings');
                if (!initialized) fill(document.getElementById('email-settings'), data.settings);
                document.getElementById('password-state').textContent = `Stored password: ${data.settings.password_set ? 'set (masked)' : 'not set'}. Encryption key: ${data.settings.key_configured ? 'configured' : 'not configured'}.`;
                document.getElementById('email-deliveries').textContent = data.deliveries.map(d => `${d.title}: ${d.state}, attempts ${d.attempts}. ${d.diagnostic || ''}`).join('\n');
            }
            initialized = true;
        } catch (e) { show(e.message); }
    }
    schedule?.addEventListener('submit', async e => { e.preventDefault(); try { await request('/admin/backups/schedule', 'PUT', formValues(schedule)); show('Schedule saved.'); await refresh(); } catch (error) { show(error.message); } });
    const email = document.getElementById('email-settings');
    email?.addEventListener('submit', async e => { e.preventDefault(); try { await request('/admin/email/settings', 'PUT', formValues(email)); email.elements.password.value = ''; show('Email settings saved.'); await refresh(); } catch (error) { show(error.message); } });
    action(document.getElementById('backup-now'), async () => { await request('/admin/backups', 'POST', {}); show('Manual backup queued.'); await refresh(); });
    action(document.getElementById('backup-import'), async () => { const file = document.getElementById('backup-upload').files[0]; if (!file) throw new Error('Choose a backup archive.'); await request('/admin/backups/import', 'POST', file); show('Archive imported and verified.'); await refresh(); });
    action(document.getElementById('send-test'), async () => { const recipient = document.getElementById('test-recipient').value; if (prompt(`Send test mail to ${recipient}? Type SEND TEST.`) !== 'SEND TEST') return; await request('/admin/email/test', 'POST', {recipient, confirmation: 'SEND TEST'}); show('Test queued; check delivery status.'); });
    refresh(); setInterval(refresh, 5000);
})();

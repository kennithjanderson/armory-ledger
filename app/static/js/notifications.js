(() => {
    'use strict';
    let token = '', offset = 0, preferencesLoaded = false, refreshSequence = 0;
    const toggle = document.getElementById('notification-toggle'), panel = document.getElementById('notification-panel');
    if (!toggle || !panel) return;
    const closePanel = () => { panel.hidden = true; toggle.setAttribute('aria-expanded', 'false'); };
    toggle.addEventListener('click', () => { panel.hidden = !panel.hidden; toggle.setAttribute('aria-expanded', String(!panel.hidden)); });
    document.addEventListener('click', event => {
        if (!panel.hidden && !panel.contains(event.target) && !toggle.contains(event.target)) closePanel();
    });
    document.addEventListener('keydown', event => { if (event.key === 'Escape' && !panel.hidden) { panel.hidden = true; toggle.setAttribute('aria-expanded', 'false'); toggle.focus(); } });
    async function write(path, method, body) {
        const response = await fetch(path, {method, headers: {'Content-Type':'application/json', 'X-CSRF-Token':token}, body:JSON.stringify(body)});
        if (!response.ok) throw new Error('Unable to save notification changes.');
        await refresh();
    }
    function row(item) {
        const article = document.createElement('article'); article.dataset.noticeId = item.id; article.className = `notification-row notice-${item.severity}${item.read ? '' : ' unread'}`;
        const heading = document.createElement('strong'); heading.textContent = `${item.severity.toUpperCase()}: ${item.title}${item.read ? '' : ' (unread)'}`;
        const text = document.createElement('p'); text.textContent = `${item.message} · ${item.timestamp} · occurrences ${item.occurrences}${item.resolved ? ' · resolved' : ''}`;
        const link = document.createElement('a'); link.className = 'notification-open-link'; link.textContent = 'Open'; link.href = item.action.startsWith('/') && !item.action.startsWith('//') ? item.action : '/notifications';
        article.append(heading,text,link);
        if (!item.read) { const read = document.createElement('button'); read.textContent = 'Mark read'; read.className = 'button-secondary'; read.addEventListener('click', async () => { try { await write('/api/notifications/read','POST',{id:item.id}); item.read = true; article.replaceWith(row(item)); } catch (_) { read.textContent = 'Retry mark read'; } }); article.append(read); }
        return article;
    }
    async function refresh() {
        if (document.hidden) return;
        const sequence = ++refreshSequence;
        try {
            const history = document.getElementById('notifications-history');
            const [bellResponse, historyResponse] = await Promise.all([
                fetch('/api/notifications?unread_only=true'),
                history ? fetch(`/api/notifications?offset=${offset}`) : Promise.resolve(null)
            ]);
            if (!bellResponse.ok || (historyResponse && !historyResponse.ok)) return;
            const data = await bellResponse.json();
            const historyData = historyResponse ? await historyResponse.json() : null;
            if (sequence !== refreshSequence) return; token = data.csrf_token;
            const unread = Number(data.unread) || 0;
            toggle.classList.toggle('has-unread', unread > 0);
            toggle.setAttribute('aria-label', unread ? `Notifications, ${unread} unread` : 'Notifications, no unread notifications');
            document.getElementById('notification-items').replaceChildren(...data.items.slice(0,8).map(row));
            if (history && historyData) {
                if (offset === 0) history.replaceChildren(...historyData.items.map(row));
                else for (const item of historyData.items) {
                    const existing=Array.from(history.children).find(el=>el.dataset.noticeId===item.id);
                    if (existing) existing.replaceWith(row(item));
                }
            }
            const prefs = document.getElementById('notification-preferences');
            if (prefs && !preferencesLoaded) {
                prefs.elements.success_in_app.checked = data.preferences.success_in_app;
                prefs.elements.success_email.checked = data.preferences.success_email;
                if (prefs.elements.restore_initiated_in_app) prefs.elements.restore_initiated_in_app.checked = data.preferences.restore_initiated_in_app;
                if (prefs.elements.restore_initiated_email) prefs.elements.restore_initiated_email.checked = data.preferences.restore_initiated_email;
                preferencesLoaded = true;
            }
        } catch (_) { /* Reconnect/backfill on the next bounded poll. */ }
    }
    document.getElementById('notifications-more')?.addEventListener('click', async () => {
        const response = await fetch(`/api/notifications?offset=${offset+30}`); if (!response.ok) return;
        const data = await response.json(); if (!data.items.length) return; offset += 30;
        const list = document.getElementById('notifications-history');
        for (const item of data.items) { const existing = Array.from(list.children).find(el => el.dataset.noticeId === item.id); if (existing) existing.replaceWith(row(item)); else list.append(row(item)); }
    });
    document.getElementById('notifications-read-all')?.addEventListener('click', async () => {
        offset = 0;
        try {
            await write('/api/notifications/read','POST',{});
            document.querySelectorAll('#notifications-history .notification-row.unread').forEach(article => {
                article.classList.remove('unread');
                const heading=article.querySelector('strong');
                if (heading) heading.textContent=heading.textContent.replace(/ \(unread\)$/,'');
                article.querySelector('button')?.remove();
            });
        } catch (_) { /* The next poll can retry after connectivity returns. */ }
    });
    document.getElementById('notification-preferences')?.addEventListener('submit', async event => {
        event.preventDefault(); const form = event.target, result = document.getElementById('preferences-result');
        const payload={success_in_app:form.elements.success_in_app.checked,success_email:form.elements.success_email.checked};
        if (form.elements.restore_initiated_in_app) {
            payload.restore_initiated_in_app=form.elements.restore_initiated_in_app.checked;
            payload.restore_initiated_email=form.elements.restore_initiated_email.checked;
        }
        try { await write('/api/notifications/preferences','PUT',payload); result.textContent = 'Preferences saved.'; } catch (e) { result.textContent = e.message; }
    });
    refresh(); setInterval(refresh,30000); window.addEventListener('online',refresh); document.addEventListener('visibilitychange',refresh);
})();

(() => {
    const send = async (url, method, token, payload) => {
        const response = await fetch(url, {
            method,
            headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': token },
            body: payload ? JSON.stringify(payload) : undefined,
        });
        let data = {};
        try { data = await response.json(); } catch (_) { /* empty response */ }
        if (!response.ok) throw new Error(data.detail || 'The sharing request could not be completed.');
        return data;
    };

    const show = (element, message) => {
        const status = element.querySelector('[role="status"]') || document.getElementById('share-invite-result');
        if (status) status.textContent = message;
    };

    const values = form => Object.fromEntries(new FormData(form).entries());

    document.getElementById('share-invite-form')?.addEventListener('submit', async event => {
        event.preventDefault();
        const form = event.currentTarget;
        const result = document.getElementById('share-invite-result');
        result.textContent = 'Sending invitation…';
        try {
            const data = values(form);
            await send(form.dataset.endpoint, 'POST', form.dataset.csrfToken, data);
            result.textContent = 'If this address can receive an invitation, one has been queued.';
            form.reset();
            window.setTimeout(() => window.location.reload(), 500);
        } catch (error) { result.textContent = error.message; }
    });

    document.querySelectorAll('.sharing-permission-form').forEach(form => {
        form.addEventListener('submit', async event => {
            event.preventDefault();
            const id = form.dataset.shareId;
            try {
                await send(`/api/shares/${id}/permissions`, 'PUT', form.dataset.csrfToken, values(form));
                show(form, 'Access updated.');
            } catch (error) { show(form, error.message); }
        });
    });

    document.querySelectorAll('.sharing-revoke').forEach(button => {
        button.addEventListener('click', async () => {
            if (!window.confirm('Revoke this person’s access to your shared inventory?')) return;
            const id = button.dataset.shareId;
            try {
                await send(`/api/shares/${id}`, 'DELETE', button.dataset.csrfToken);
                window.setTimeout(() => window.location.reload(), 500);
            } catch (error) { show(button.closest('.sharing-entry'), error.message); }
        });
    });

    document.querySelectorAll('.sharing-response').forEach(button => {
        button.addEventListener('click', async () => {
            const id = button.dataset.shareId;
            const action = button.dataset.action;
            try {
                await send(`/api/sharing-invitations/${id}/${action}`, 'POST', button.dataset.csrfToken);
                window.setTimeout(() => window.location.reload(), 500);
            } catch (error) { show(button.closest('.sharing-entry'), error.message); }
        });
    });
})();

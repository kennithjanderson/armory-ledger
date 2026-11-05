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

    const applyPermissionDependencies = form => {
        const get = name => form.querySelector(`[name="${name}"]`);
        const firearms = get('firearms');
        const ammunition = get('ammunition');
        const accessories = get('accessories');
        const shootingLog = get('shooting_log');
        if (!firearms || !ammunition || !accessories || !shootingLog) return;

        const firearmRead = firearms.value !== 'none';
        const ammunitionRead = ammunition.value !== 'none';
        const firearmWrite = firearms.value === 'rw';
        const ammunitionWrite = ammunition.value === 'rw';

        accessories.querySelector('option[value="ro"]').disabled = !firearmRead;
        accessories.querySelector('option[value="rw"]').disabled = !firearmRead;
        if (!firearmRead) accessories.value = 'none';

        const logReadAllowed = firearmRead && ammunitionRead;
        const logWriteAllowed = firearmWrite && ammunitionWrite;
        shootingLog.querySelector('option[value="ro"]').disabled = !logReadAllowed;
        shootingLog.querySelector('option[value="rw"]').disabled = !logWriteAllowed;
        if (!logReadAllowed) shootingLog.value = 'none';
        else if (!logWriteAllowed && shootingLog.value === 'rw') shootingLog.value = 'ro';
    };

    document.querySelectorAll('.sharing-permission-controls').forEach(form => {
        applyPermissionDependencies(form);
        form.addEventListener('change', event => {
            if (event.target.matches('select[name="firearms"], select[name="ammunition"]')) {
                applyPermissionDependencies(form);
            }
        });
    });

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

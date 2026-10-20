(() => {
    'use strict';
    const form = document.getElementById('ammunition-notification-settings');
    if (!form) return;

    form.addEventListener('submit', async event => {
        event.preventDefault();
        const result = document.getElementById('ammunition-notification-result');
        const enabled = form.elements.low_inventory_notifications_enabled.checked;
        const thresholdText = form.elements.low_inventory_threshold.value.trim();
        if (enabled && !thresholdText) {
            result.textContent = 'Enter a positive round threshold to enable low-inventory alerts.';
            form.elements.low_inventory_threshold.focus();
            return;
        }

        const threshold = thresholdText ? Number(thresholdText) : null;
        if (threshold !== null && (!Number.isSafeInteger(threshold) || threshold < 1 || threshold > 2147483647)) {
            result.textContent = 'Enter a whole-number threshold between 1 and 2,147,483,647.';
            form.elements.low_inventory_threshold.focus();
            return;
        }

        try {
            const response = await fetch(form.dataset.endpoint, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRF-Token': form.dataset.csrfToken,
                },
                body: JSON.stringify({
                    low_inventory_notifications_enabled: enabled,
                    low_inventory_threshold: threshold,
                    depleted_notifications_enabled: form.elements.depleted_notifications_enabled.checked,
                }),
            });
            if (!response.ok) throw new Error('Unable to save lot notification settings.');
            result.textContent = 'Lot notification settings saved.';
        } catch (error) {
            result.textContent = error.message;
        }
    });
})();

document.addEventListener("DOMContentLoaded", () => {
    const userButton = document.querySelector(".user-menu-button");
    const userDropdown = document.querySelector(".user-dropdown");

    const mobileButton = document.querySelector(".mobile-menu-button");
    const mobileNavigation = document.querySelector(".mobile-navigation");

    if (userButton && userDropdown) {
    const closeUserMenu = () => {
        userDropdown.classList.remove("is-open");
        userButton.setAttribute("aria-expanded", "false");
    };

    userButton.addEventListener("click", (event) => {
        event.stopPropagation();

        const open = userDropdown.classList.toggle("is-open");
        userButton.setAttribute("aria-expanded", open);
    });

    userDropdown.addEventListener("click", (event) => {
        event.stopPropagation();
    });

    document.addEventListener("click", () => {
        closeUserMenu();
    });

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            closeUserMenu();
            userButton.focus();
        }
    });
}

    if (mobileButton && mobileNavigation) {
        mobileButton.addEventListener("click", () => {
            const open = mobileNavigation.classList.toggle("is-open");

            mobileButton.classList.toggle("is-open", open);

            mobileButton.setAttribute("aria-expanded", open);
        });
    }

    /*
     * =========================================================
     * 24hr Clock
     * =========================================================
     */

    const localClock = document.getElementById("local-clock");

if (localClock) {
    const timeZoneFormatter = new Intl.DateTimeFormat(
        undefined,
        {
            timeZoneName: "short",
        },
    );

    const updateClock = () => {
        const now = new Date();

        const timeZone = timeZoneFormatter
            .formatToParts(now)
            .find(part => part.type === "timeZoneName")
            ?.value ?? "";

        localClock.textContent = `${window.ArmoryDateTime.formatLocal(now, true)} ${timeZone}`.trim();
    };

    updateClock();
    window.setInterval(updateClock, 1000);
}

    /*
     * =========================================================
     * System Status
     * =========================================================
     */


async function updateSystemStatus() {
    const status = document.getElementById("system-status");

    if (!status) {
        return;
    }

    const statusText = status.querySelector(
        ".app-footer-status-text"
    );

    try {
        const response = await fetch("/health", {
            cache: "no-store",
        });

        if (!response.ok) {
            throw new Error("Health check failed");
        }

        const health = await response.json();

        status.classList.remove(
            "is-healthy",
            "is-degraded"
        );

        if (health.status === "healthy") {
            status.classList.add("is-healthy");
            statusText.textContent = "OPERATIONAL";
        } else {
            status.classList.add("is-degraded");
            statusText.textContent = "DEGRADED";
        }
    } catch (error) {
        status.classList.remove("is-healthy");
        status.classList.add("is-degraded");
        statusText.textContent = "UNAVAILABLE";
    }
}


updateSystemStatus();

function setupAdminOperationalTooltip() {
    const wrapper = document.querySelector(".admin-status-popover");
    const trigger = wrapper?.querySelector("[data-admin-status]");
    const tooltip = document.getElementById("admin-status-tooltip");
    if (!wrapper || !trigger || !tooltip) return;

    const details = {
        database: document.getElementById("admin-status-database"),
        backups: document.getElementById("admin-status-backups"),
        email: document.getElementById("admin-status-email"),
    };
    let pinned = false;
    let loading = false;
    let loadedAt = 0;

    const open = () => {
        tooltip.hidden = false;
        trigger.setAttribute("aria-expanded", "true");
        if (!loading && Date.now() - loadedAt > 15000) load();
    };
    const close = () => {
        tooltip.hidden = true;
        trigger.setAttribute("aria-expanded", "false");
    };
    const label = value => String(value ?? "unknown").replaceAll("_", " ");

    async function load() {
        loading = true;
        Object.values(details).forEach(element => { element.textContent = "Checking…"; });
        try {
            const response = await fetch("/admin/operational-status", {cache: "no-store"});
            if (!response.ok) throw new Error("Status unavailable");
            const status = await response.json();
            details.database.textContent = label(status.database);
            details.backups.textContent = `${label(status.backups.status)} · storage ${label(status.backups.storage)} · encryption ${label(status.backups.encryption)} · scheduler ${label(status.backups.scheduler)} · recovery ${label(status.backups.recovery)}`;
            details.email.textContent = label(status.email);
            loadedAt = Date.now();
        } catch (_) {
            Object.values(details).forEach(element => { element.textContent = "Unavailable"; });
        } finally {
            loading = false;
        }
    }

    wrapper.addEventListener("mouseenter", open);
    wrapper.addEventListener("mouseleave", () => { if (!pinned) close(); });
    wrapper.addEventListener("focusin", open);
    wrapper.addEventListener("focusout", event => {
        if (!pinned && !wrapper.contains(event.relatedTarget)) close();
    });
    trigger.addEventListener("click", event => {
        event.stopPropagation();
        pinned = !pinned;
        if (pinned) open();
        else close();
    });
    document.addEventListener("click", event => {
        if (pinned && !wrapper.contains(event.target)) {
            pinned = false;
            close();
        }
    });
    document.addEventListener("keydown", event => {
        if (event.key === "Escape" && !tooltip.hidden) {
            pinned = false;
            close();
            trigger.focus();
        }
    });
}

setupAdminOperationalTooltip();

    /*
     * =========================================================
     * Browser-local system timestamps
     * =========================================================
     */

document
    .querySelectorAll("[data-local-datetime]")
    .forEach(element => {
        const timestamp = element.dataset.localDatetime;

        if (!timestamp) {
            return;
        }

        const date = new Date(timestamp);

        if (Number.isNaN(date.getTime())) {
            return;
        }

        element.textContent = window.ArmoryDateTime.formatLocal(date, element.dataset.timeSeconds === "true");
        element.title = "Browser local time";
    });

});

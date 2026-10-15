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
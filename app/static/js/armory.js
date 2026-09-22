document.addEventListener("DOMContentLoaded", () => {
    const userButton = document.querySelector(".user-menu-button");
    const userDropdown = document.querySelector(".user-dropdown");

    const mobileButton = document.querySelector(".mobile-menu-button");
    const mobileNavigation = document.querySelector(".mobile-navigation");

    if (userButton && userDropdown) {
        userButton.addEventListener("click", () => {
            const open = userDropdown.classList.toggle("is-open");

            userButton.setAttribute("aria-expanded", open);
        });
    }

    if (mobileButton && mobileNavigation) {
        mobileButton.addEventListener("click", () => {
            const open = mobileNavigation.classList.toggle("is-open");

            mobileButton.classList.toggle("is-open", open);

            mobileButton.setAttribute("aria-expanded", open);
        });
    }

    const localClock = document.getElementById("local-clock");

    if (localClock) {
        const clockFormatter = new Intl.DateTimeFormat(
            undefined,
            {
                month: "short",
                day: "numeric",
                year: "numeric",
                hour: "numeric",
                minute: "2-digit",
                second: "2-digit",
                timeZoneName: "short",
            },
        );

        const updateClock = () => {
            localClock.textContent =
                clockFormatter.format(new Date());
        };

        updateClock();
        window.setInterval(updateClock, 1000);
    }

    /*
     * =========================================================
     * Browser-local system timestamps
     * =========================================================
     */

    const localDateFormatter = new Intl.DateTimeFormat(
        undefined,
        {
            month: "short",
            day: "numeric",
            year: "numeric",
        },
    );

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

            element.textContent =
                localDateFormatter.format(date);
        });
});

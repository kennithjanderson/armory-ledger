document.addEventListener("DOMContentLoaded", () => {
    const loginButton = document.querySelector(".login-button");

    if (!loginButton) {
        return;
    }

    loginButton.addEventListener("click", (event) => {
        /*
         * Touch-first/mobile devices use the normal link.
         *
         * This keeps authentication in the same tab and avoids
         * mobile browser popup/new-tab behavior.
         */
        const desktopPointer = window.matchMedia(
            "(hover: hover) and (pointer: fine)"
        ).matches;

        if (!desktopPointer) {
            return;
        }

        /*
         * Desktop enhancement:
         * open authentication in a dedicated popup.
         *
         * The existing href remains the fallback if the popup
         * cannot be opened.
         */
        event.preventDefault();

        const popup = window.open(
            "/auth/login?popup=true",
            "armory-auth",
            "width=520,height=720,resizable=yes,scrollbars=yes"
        );

        if (!popup) {
            window.location.href = loginButton.href;
        }
    });

    window.addEventListener("message", (event) => {
        if (event.origin !== window.location.origin) {
            return;
        }

        if (
            event.data?.type === "armory-authenticated"
        ) {
            window.location.href = "/dashboard";
        }
    });
});

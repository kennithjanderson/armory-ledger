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
});

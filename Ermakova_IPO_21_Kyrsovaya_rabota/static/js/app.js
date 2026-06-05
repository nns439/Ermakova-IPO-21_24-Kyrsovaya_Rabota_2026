const loginForm = document.querySelector("[data-login-form]");
const loginWarning = document.querySelector("[data-login-warning]");

if (loginForm && loginWarning) {
    loginForm.addEventListener("submit", (event) => {
        const username = loginForm.querySelector("[name='username']").value.trim();
        const password = loginForm.querySelector("[name='password']").value.trim();
        if (!username || !password) {
            event.preventDefault();
            loginWarning.hidden = false;
        }
    });
}

window.setTimeout(() => {
    document.querySelectorAll(".flash").forEach((flash) => {
        flash.style.opacity = "0";
        flash.style.transform = "translateY(-8px)";
        flash.style.transition = "opacity 0.25s ease, transform 0.25s ease";
        window.setTimeout(() => flash.remove(), 300);
    });
}, 4200);

const optionCards = document.querySelectorAll(".option-card");

optionCards.forEach((card) => {
    card.addEventListener("click", () => {
        optionCards.forEach((item) => item.classList.remove("is-active"));
        card.classList.add("is-active");
    });
});

const flashes = document.querySelectorAll(".flash");

flashes.forEach((flash) => {
    setTimeout(() => {
        flash.style.opacity = "0";
        flash.style.transform = "translateY(-8px)";
    }, 3200);
});

const toggleSolutionBtn = document.querySelector("[data-toggle-solution]");
const solutionPanel = document.querySelector(".solution-panel");

if (toggleSolutionBtn && solutionPanel) {
    toggleSolutionBtn.addEventListener("click", () => {
        const isHidden = solutionPanel.hasAttribute("hidden");
        if (isHidden) {
            solutionPanel.removeAttribute("hidden");
            toggleSolutionBtn.textContent = "Hide solution";
        } else {
            solutionPanel.setAttribute("hidden", "hidden");
            toggleSolutionBtn.textContent = "View solution";
        }
    });
}

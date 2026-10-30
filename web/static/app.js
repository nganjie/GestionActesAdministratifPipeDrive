// Menu repliable sur petit écran (sans JavaScript, le menu reste simplement déplié).
document.addEventListener("DOMContentLoaded", () => {
  const menu = document.querySelector(".menu");
  const bouton = menu && menu.querySelector(".menu-bouton");
  if (!bouton) return;
  const basculer = (ouvert) => {
    menu.classList.toggle("ouvert", ouvert);
    bouton.setAttribute("aria-expanded", String(ouvert));
  };
  bouton.addEventListener("click", () => basculer(!menu.classList.contains("ouvert")));
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && menu.classList.contains("ouvert")) { basculer(false); bouton.focus(); }
  });
});

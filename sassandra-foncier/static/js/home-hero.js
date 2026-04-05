(function () {
  var slides = document.querySelectorAll(".hero-bg-slide");
  if (!slides.length || slides.length < 2) return;

  var ms = typeof window.__HERO_INTERVAL__ === "number" ? window.__HERO_INTERVAL__ : 5000;
  var i = 0;
  var dotsEl = document.getElementById("heroDots");

  function setActive(idx) {
    slides.forEach(function (el, j) {
      el.classList.toggle("is-active", j === idx);
    });
    if (dotsEl) {
      dotsEl.textContent = "Visuel " + (idx + 1) + " / " + slides.length;
    }
  }

  setActive(0);

  setInterval(function () {
    i = (i + 1) % slides.length;
    setActive(i);
  }, ms);
})();

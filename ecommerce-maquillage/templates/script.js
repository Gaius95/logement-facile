function pad2(n){
  return String(n).padStart(2, '0');
}

function renderCountdown(target, expiresAt, offerMinutes){
  let diff = expiresAt - Date.now();
  // Si le chrono est arrivé à 0, on redémarre automatiquement (évite "Offre terminée").
  if (diff <= 0){
    const minutesMs = (offerMinutes || 45) * 60 * 1000;
    expiresAt = Date.now() + minutesMs;
    target.setAttribute('data-expires-at', new Date(expiresAt).toISOString());
    diff = expiresAt - Date.now();
  }

  const totalSeconds = Math.floor(diff / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  target.textContent = `Offre se termine dans : ${pad2(hours)}:${pad2(minutes)}:${pad2(seconds)}`;
  return expiresAt;
}

function startCountdown(){
  const els = document.querySelectorAll('[data-expires-at]');
  if (!els || els.length === 0) return;

  els.forEach((el) => {
    const iso = el.getAttribute('data-expires-at');
    if (!iso) return;
    let expiresAt = new Date(iso).getTime();
    const offerMinutes = parseInt(el.getAttribute('data-offer-minutes') || '45', 10);
    expiresAt = renderCountdown(el, expiresAt, offerMinutes);
    setInterval(() => {
      expiresAt = renderCountdown(el, expiresAt, offerMinutes);
    }, 1000);
  });
}

function setupThumbs(){
  const thumbs = document.querySelectorAll('[data-thumb]');
  const main = document.querySelector('[data-main-image]');
  if (!main || thumbs.length === 0) return;
  thumbs.forEach((t) => {
    t.addEventListener('click', () => {
      const src = t.getAttribute('data-src');
      if (!src) return;
      main.src = src;
    });
  });
}

document.addEventListener('DOMContentLoaded', () => {
  startCountdown();
  setupThumbs();

  // Autoplay vidéo: certains mobiles exigent un play() programmatique
  const v = document.querySelector('[data-autoplay-video]');
  if (v && v instanceof HTMLVideoElement) {
    try {
      v.muted = true;
      const p = v.play();
      if (p && typeof p.catch === 'function') {
        p.catch(() => {
          // Si le navigateur bloque, on laisse le poster (pas d'erreur visible).
        });
      }
    } catch (_) {}
  }
});


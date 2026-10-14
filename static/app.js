/* SafeHer AI - shared browser helpers */
const csrf = document.querySelector('meta[name="csrf"]')?.content || '';

async function api(url, body) {
  const r = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
    body: JSON.stringify(body || {}),
  });
  return r.json();
}

function getPosition() {
  return new Promise(resolve => {
    if (!navigator.geolocation) return resolve(null);
    navigator.geolocation.getCurrentPosition(
      p => resolve({ lat: p.coords.latitude, lng: p.coords.longitude, accuracy: p.coords.accuracy }),
      () => resolve(null),
      { enableHighAccuracy: true, timeout: 8000, maximumAge: 10000 }
    );
  });
}

async function getBattery() {
  try {
    if (!navigator.getBattery) return null;
    const b = await navigator.getBattery();
    return { level: Math.round(b.level * 100), charging: b.charging };
  } catch (e) { return null; }
}

/* ---- SOS: countdown -> locate -> send -> show share links ---- */
let countdownTimer = null;

function startSOS(trigger = 'button') {
  const overlay = document.getElementById('sos-overlay');
  if (!overlay) return;
  let n = parseInt(document.body.dataset.countdown || '5', 10);
  if (n <= 0) return sendSOS(trigger);
  const num = document.getElementById('sos-count');
  num.textContent = n;
  overlay.hidden = false;
  if (navigator.vibrate) navigator.vibrate(200);
  countdownTimer = setInterval(() => {
    n -= 1;
    num.textContent = n;
    if (n <= 0) {
      clearInterval(countdownTimer);
      overlay.hidden = true;
      sendSOS(trigger);
    }
  }, 1000);
}

function cancelSOS() {
  clearInterval(countdownTimer);
  document.getElementById('sos-overlay').hidden = true;
}

async function sendSOS(trigger = 'button') {
  const dlg = document.getElementById('sos-result');
  if (!dlg) return;
  const title = document.getElementById('sos-result-title');
  const note = document.getElementById('sos-result-note');
  const links = document.getElementById('sos-result-links');
  title.textContent = 'Sending your alert…';
  note.textContent = 'Getting your location.';
  links.replaceChildren();
  if (!dlg.open) dlg.showModal();

  const pos = await getPosition();
  const bat = await getBattery();
  let out;
  try {
    out = await api('/api/sos', { ...(pos || {}), battery: bat ? bat.level : null, trigger });
  } catch (e) {
    title.textContent = 'Could not send the alert';
    note.textContent = 'No connection to the server. Call 112 now, or message your contacts directly.';
    return;
  }
  if (out.error) { title.textContent = 'Could not send the alert'; note.textContent = out.error; return; }

  title.textContent = 'SOS recorded';
  const parts = [];
  if (out.emailed) parts.push(`Email sent to ${out.emailed} contact${out.emailed === 1 ? '' : 's'}.`);
  parts.push(out.has_location ? 'Your location is included.' : 'Location was not available. Allow location access in your browser.');
  if (!out.has_contacts) parts.push('You have no saved contacts, so nobody was notified.');
  else parts.push('Tap below to send the message on WhatsApp or SMS.');
  note.textContent = parts.join(' ');

  out.links.forEach(c => {
    const row = document.createElement('div');
    row.className = 'link-row';
    const name = document.createElement('b');
    name.textContent = c.name;
    row.appendChild(name);
    [['WhatsApp', c.whatsapp], ['SMS', c.sms], ['Call', c.tel]].forEach(([label, href]) => {
      if (!href) return;
      const a = document.createElement('a');
      a.className = 'btn small ghost';
      a.textContent = label;
      a.href = href;
      if (label === 'WhatsApp') { a.target = '_blank'; a.rel = 'noopener'; }
      row.appendChild(a);
    });
    links.appendChild(row);
  });
}

document.getElementById('sos-btn')?.addEventListener('click', () => startSOS('button'));
document.getElementById('sos-cancel')?.addEventListener('click', cancelSOS);
document.getElementById('sos-close')?.addEventListener('click', () => document.getElementById('sos-result').close());

/* ---- Low battery banner (Chrome / Android) ---- */
(async () => {
  const banner = document.getElementById('battery-banner');
  if (!banner) return;
  const b = await getBattery();
  if (b && b.level <= 15 && !b.charging) {
    document.getElementById('battery-level').textContent = b.level;
    banner.hidden = false;
    document.getElementById('battery-send').addEventListener('click', () => { banner.hidden = true; sendSOS('battery'); });
  }
})();

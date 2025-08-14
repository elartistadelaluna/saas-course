console.log('dashboard.js v7 loaded');

async function ensureToken() {
  const token = localStorage.getItem('access_token') || '';
  if (!token) console.warn('No access_token in localStorage');
  return token || null;
}

async function api(path, opts = {}) {
  const token = await ensureToken();
  if (!token) throw new Error('Not authenticated (no token)');
  const res = await fetch(path, {
    ...opts,
    headers: {
      ...(opts.headers || {}),
      Authorization: 'Bearer ' + token,
      'Content-Type': 'application/json',
    },
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`${res.status} ${res.statusText} :: ${text}`);
  }
  return res.json();
}

function show(el) { el && el.classList.remove('hidden'); }
function hide(el) { el && el.classList.add('hidden'); }

// Spinner helpers
function showSpinner() {
  const ov = document.getElementById('spinner-overlay');
  if (ov) ov.classList.add('show');
}
function hideSpinner() {
  const ov = document.getElementById('spinner-overlay');
  if (ov) ov.classList.remove('show');
}

let cachedPlan = 'free';
let cachedCredits = 0;
let influencerLocked = false;
let lastGalleryCount = 0;

async function loadAccount() {
  const data = await api('/api/me');
  cachedPlan = data.plan ?? 'free';
  cachedCredits = Number(data.credits ?? 0);
  document.getElementById('plan').textContent = cachedPlan;
  document.getElementById('credits').textContent = String(cachedCredits);
  if (cachedPlan === 'pro') hide(document.getElementById('upgrade-btn'));
}

async function renderInfluencer(state) {
  const empty = document.getElementById('influencer-empty');
  const view = document.getElementById('influencer-view');
  const imgBox = document.getElementById('preview-box');
  const imgPlaceholder = document.getElementById('img-placeholder');
  const nameEl = document.getElementById('inf-name');
  const vibeEl = document.getElementById('inf-vibe');

  influencerLocked = !!(state && state.is_locked);

  if (!state) { show(empty); hide(view); return; }

  hide(empty); show(view);
  nameEl.textContent = state.name || '';
  vibeEl.textContent = state.vibe ? `Vibe: ${state.vibe}` : '';

  if (state.initial_image_url) {
    imgBox.innerHTML = `<img alt="sweetheart" src="${state.initial_image_url}">`;
    const cs = document.getElementById('create-status');
    if (cs) cs.textContent = ''; // clear any queued msg
  } else {
    imgBox.innerHTML = '';
    if (imgPlaceholder) imgBox.append(imgPlaceholder);
  }
}

async function fetchInfluencerOnce() {
  const res = await api('/api/influencer');
  return res.influencer || null;
}

async function refreshCreateImageVisibility() {
  const section = document.getElementById('create-image-section');
  const shouldShow = influencerLocked && cachedCredits > 0;
  shouldShow ? show(section) : hide(section);
}

async function loadGallery() {
  const gSec = document.getElementById('gallery-section');
  const g = document.getElementById('gallery');
  try {
    const data = await api('/api/images');
    const items = data.images || [];
    lastGalleryCount = items.length;
    if (items.length === 0) { g.innerHTML = ''; hide(gSec); return; }
    show(gSec);
    g.innerHTML = items.map(it => `<img src="${it.url}" alt="gallery" data-full="${it.url}">`).join('');
    attachGalleryClicks();
  } catch (e) {
    console.warn('gallery load failed:', e);
  }
}

function attachGalleryClicks() {
  document.querySelectorAll('#gallery img').forEach(img => {
    img.addEventListener('click', () => {
      const modal = document.getElementById('img-modal');
      const modalImg = document.getElementById('modal-img');
      const downloadBtn = document.getElementById('download-btn');
      modalImg.src = img.dataset.full;
      downloadBtn.href = img.dataset.full;
      modal.style.display = 'flex';
    });
  });
  document.getElementById('img-modal').addEventListener('click', e => {
    if (e.target.id === 'img-modal') e.currentTarget.style.display = 'none';
  });
}

let pollGen = null;
/**
 * Poll account + gallery. If waitForGalleryIncrease=true,
 * hide spinner and stop when gallery count increases.
 */
function startGenPolling(waitForGalleryIncrease = false) {
  if (pollGen) clearInterval(pollGen);
  const baseline = lastGalleryCount;
  pollGen = setInterval(async () => {
    await loadAccount();
    await loadGallery();
    await refreshCreateImageVisibility();

    if (waitForGalleryIncrease && lastGalleryCount > baseline) {
      hideSpinner();
      clearInterval(pollGen);
      pollGen = null;
      return;
    }

    if (cachedCredits <= 0) {
      clearInterval(pollGen);
      pollGen = null;
    }
  }, 5000);
}

document.addEventListener('DOMContentLoaded', async () => {
  const token = await ensureToken();
  if (!token) { window.location.href = '/login'; return; }

  await loadAccount();

  // IMPORTANT: fetch & render influencer BEFORE the first gallery call
  const first = await fetchInfluencerOnce();
  await renderInfluencer(first);
  await refreshCreateImageVisibility();
  await loadGallery(); // <- now safe (backend expects influencer)

  // If initial image is not there yet, poll until it appears, then hide spinner if shown
  let pollInf = null;
  if (!first || !first.initial_image_url) {
    pollInf = setInterval(async () => {
      const inf = await fetchInfluencerOnce();
      await renderInfluencer(inf);
      if (inf && inf.is_locked && inf.initial_image_url) {
        clearInterval(pollInf);
        pollInf = null;
        influencerLocked = true;
        hideSpinner();                // stop spinner when initial image lands
        await refreshCreateImageVisibility();
        await loadGallery();
      }
    }, 5000);
  }

  document.getElementById('upgrade-btn')?.addEventListener('click', async () => {
    const data = await api('/api/upgrade', { method: 'POST' });
    if (data.url) window.location.href = data.url;
  });

  document.getElementById('billing-btn')?.addEventListener('click', async () => {
    const data = await api('/api/billing-portal', { method: 'POST' });
    if (data.url) window.location.href = data.url;
  });

  // Create influencer (spinner until polling detects final image)
  const createBtn = document.getElementById('create-btn');
  const statusEl = document.getElementById('create-status');
  createBtn.addEventListener('click', async () => {
    const name = document.getElementById('name').value.trim();
    const bio = document.getElementById('bio').value.trim();
    const vibe = document.getElementById('vibe').value.trim();
    if (!name || !bio || !vibe) { alert('Fill all fields'); return; }
    createBtn.disabled = true;
    if (statusEl) statusEl.textContent = ''; // prefer spinner over text
    showSpinner();
    try {
      await api('/api/influencer', { method: 'POST', body: JSON.stringify({ name, bio, vibe }) });
      const shell = await fetchInfluencerOnce();
      await renderInfluencer(shell);
      // spinner stays until pollInf sees the image and calls hideSpinner()
    } catch (e) {
      alert(e.message);
      hideSpinner();
      if (statusEl) statusEl.textContent = '';
    } finally { createBtn.disabled = false; }
  });

  // Create additional images (spinner until gallery increases)
  const genBtn = document.getElementById('gen-btn');
  const genStatus = document.getElementById('gen-status');
  genBtn.addEventListener('click', async () => {
    const prompt = document.getElementById('user-prompt').value.trim();
    if (!prompt) { alert('Please enter a prompt'); return; }
    genBtn.disabled = true;
    if (genStatus) genStatus.textContent = ''; // prefer spinner
    showSpinner();
    try {
      await api('/api/images/create', { method: 'POST', body: JSON.stringify({ prompt }) });
      startGenPolling(true); // wait for gallery to grow, then hide spinner
    } catch (e) {
      alert(e.message);
      hideSpinner();
    } finally { genBtn.disabled = false; }
  });
});

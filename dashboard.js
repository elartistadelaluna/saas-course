// /assets/js/dashboard.js
console.log('dashboard.js v8 loaded');

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
    headers: { ...(opts.headers || {}), Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' }
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`${res.status} ${res.statusText} :: ${text}`);
  }
  return res.json();
}

function show(el) { el && el.classList.remove('hidden'); }
function hide(el) { el && el.classList.add('hidden'); }

function showSpinner(){ document.getElementById('spinner-overlay')?.classList.add('show'); }
function hideSpinner(){ document.getElementById('spinner-overlay')?.classList.remove('show'); }

let cachedPlan = 'free';
let cachedCredits = 0;
let influencerLocked = false;
let lastGalleryCount = 0;

// --- account/influencer ------------------------------------------------------
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

  if (!state) { show(empty); hide(view); hide(document.getElementById('chat-section')); return; }

  hide(empty); show(view);
  nameEl.textContent = state.name || '';
  vibeEl.textContent = state.vibe ? `Vibe: ${state.vibe}` : '';

  if (state.initial_image_url) {
    imgBox.innerHTML = `<img alt="sweetheart" src="${state.initial_image_url}">`;
    document.getElementById('create-status').textContent = '';
    show(document.getElementById('chat-section')); // show chat once available
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

// --- gallery -----------------------------------------------------------------
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
function startGenPolling(waitForGalleryIncrease = false) {
  if (pollGen) clearInterval(pollGen);
  const baseline = lastGalleryCount;
  pollGen = setInterval(async () => {
    await loadAccount();
    await loadGallery();
    await refreshCreateImageVisibility();
    if (waitForGalleryIncrease && lastGalleryCount > baseline) {
      hideSpinner();
      clearInterval(pollGen); pollGen = null;
    }
    if (cachedCredits <= 0) { clearInterval(pollGen); pollGen = null; }
  }, 5000);
}

// --- chat --------------------------------------------------------------------
let chatId = null;
let chatPoll = null;
let typingTimer = null;

function renderMessages(messages=[]) {
  const body = document.getElementById('chat-body');
  body.innerHTML = messages.map(m => {
    const when = new Date(m.created_at).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
    if (m.role === 'assistant') {
      return `<div class="bubble ai"><span class="heart">❤</span>${m.content}<span class="meta">${when}</span></div>`;
    } else {
      return `<div class="bubble user">${m.content}<span class="meta">${when}</span></div>`;
    }
  }).join('');
  body.scrollTop = body.scrollHeight;
}

function setTyping(on) {
  const t = document.getElementById('typing');
  on ? show(t) : hide(t);
}

async function loadChat() {
  const res = await api('/api/chat');
  if (!res.chat) { hide(document.getElementById('chat-section')); return; }
  show(document.getElementById('chat-section'));
  chatId = res.chat.id;
  renderMessages(res.messages);

  const sendBtn = document.getElementById('chat-send');
  if (res.can_send) {
    sendBtn.disabled = false;
    show(sendBtn);
  } else {
    sendBtn.disabled = true;
    hide(sendBtn);
  }
}

function startChatPolling() {
  if (chatPoll) clearInterval(chatPoll);
  chatPoll = setInterval(loadChat, 5000);
}

// After sending a user message we poll faster until an AI reply arrives
async function waitForAssistantOnce() {
  // Start "typing…" after 1s
  if (typingTimer) clearTimeout(typingTimer);
  typingTimer = setTimeout(() => setTyping(true), 1000);

  let tries = 0;
  const maxTries = 30;           // ~60s
  let lastAssistantSeen = false;

  // snapshot: if last message is assistant now
  const initial = await api('/api/chat');
  const baseline = (initial.messages || []).slice(-1)[0]?.role === 'assistant' ? (initial.messages || []).length : 0;

  while (tries++ < maxTries) {
    const res = await api('/api/chat');
    const msgs = res.messages || [];
    renderMessages(msgs);

    const last = msgs[msgs.length - 1];
    if (msgs.length > baseline && last && last.role === 'assistant') {
      lastAssistantSeen = true;
      break;
    }
    await new Promise(r => setTimeout(r, 2000));
  }
  setTyping(false);
  if (!lastAssistantSeen) console.warn('Assistant reply wait timed out.');
}

// --- init --------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', async () => {
  const token = await ensureToken();
  if (!token) { window.location.href = '/login'; return; }

  await loadAccount();

  const first = await fetchInfluencerOnce();
  await renderInfluencer(first);
  await refreshCreateImageVisibility();
  await loadGallery();
  if (influencerLocked) { await loadChat(); startChatPolling(); }

  // keep polling influencer until image exists
  let pollInf = null;
  if (!first || !first.initial_image_url) {
    pollInf = setInterval(async () => {
      const inf = await fetchInfluencerOnce();
      await renderInfluencer(inf);
      if (inf && inf.is_locked && inf.initial_image_url) {
        clearInterval(pollInf); pollInf = null;
        influencerLocked = true;
        hideSpinner();
        await refreshCreateImageVisibility();
        await loadGallery();
        await loadChat();
        startChatPolling();
      }
    }, 5000);
  }

  // upgrade / billing
  document.getElementById('upgrade-btn')?.addEventListener('click', async () => {
    const data = await api('/api/upgrade', { method: 'POST' });
    if (data.url) window.location.href = data.url;
  });
  document.getElementById('billing-btn')?.addEventListener('click', async () => {
    const data = await api('/api/billing-portal', { method: 'POST' });
    if (data.url) window.location.href = data.url;
  });

  // create influencer
  const createBtn = document.getElementById('create-btn');
  const statusEl = document.getElementById('create-status');
  createBtn.addEventListener('click', async () => {
    const name = document.getElementById('name').value.trim();
    const bio = document.getElementById('bio').value.trim();
    const vibe = document.getElementById('vibe').value.trim();
    if (!name || !bio || !vibe) { alert('Fill all fields'); return; }
    createBtn.disabled = true;
    if (statusEl) statusEl.textContent = '';
    showSpinner();
    try {
      await api('/api/influencer', { method: 'POST', body: JSON.stringify({ name, bio, vibe }) });
      const shell = await fetchInfluencerOnce();
      await renderInfluencer(shell);
      // spinner ends when pollInf detects final image
    } catch (e) {
      alert(e.message); hideSpinner();
    } finally { createBtn.disabled = false; }
  });

  // create additional images
  const genBtn = document.getElementById('gen-btn');
  const genStatus = document.getElementById('gen-status');
  genBtn.addEventListener('click', async () => {
    const prompt = document.getElementById('user-prompt').value.trim();
    if (!prompt) { alert('Please enter a prompt'); return; }
    genBtn.disabled = true;
    if (genStatus) genStatus.textContent = '';
    showSpinner();
    try {
      await api('/api/images/create', { method: 'POST', body: JSON.stringify({ prompt }) });
      startGenPolling(true);
    } catch (e) {
      alert(e.message); hideSpinner();
    } finally { genBtn.disabled = false; }
  });

  // chat send
  const sendBtn = document.getElementById('chat-send');
  const input = document.getElementById('chat-input');
  async function doSend() {
    const text = (input.value || '').trim();
    if (!text) return;
    sendBtn.disabled = true;

    // Optimistic append
    const when = new Date().toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
    const body = document.getElementById('chat-body');
    body.insertAdjacentHTML('beforeend', `<div class="bubble user">${text}<span class="meta">${when}</span></div>`);
    body.scrollTop = body.scrollHeight;
    input.value = '';

    try {
      await api('/api/chat/message', { method:'POST', body: JSON.stringify({ content: text }) });
      // wait until assistant reply appears
      await waitForAssistantOnce();
      // refresh chat state (also re-applies daily-limit hiding)
      await loadChat();
    } catch (e) {
      alert(e.message);
    } finally {
      sendBtn.disabled = false;
    }
  }
  sendBtn.addEventListener('click', doSend);
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') doSend(); });
});

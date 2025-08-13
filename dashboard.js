// /assets/js/dashboard.js
import { supabase } from './auth.js';

async function ensureToken() {
  let token = localStorage.getItem('access_token');
  if (token) return token;
  const { data: { session } } = await supabase.auth.getSession();
  if (session?.access_token) {
    token = session.access_token;
    localStorage.setItem('access_token', token);
    return token;
  }
  return null;
}

async function api(path, opts = {}) {
  const token = await ensureToken();
  if (!token) throw new Error('Not authenticated');
  const res = await fetch(path, {
    ...opts,
    headers: { ...(opts.headers || {}), Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' }
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

function show(el) { el.classList.remove('hidden'); }
function hide(el) { el.classList.add('hidden'); }

async function loadAccount() {
  try {
    const data = await api('/api/me');
    document.getElementById('plan').textContent = data.plan ?? '—';
    document.getElementById('credits').textContent = data.credits ?? '—';
  } catch (e) {
    alert('Failed to load account: ' + e.message);
  }
}

async function renderInfluencer(state) {
  const empty = document.getElementById('influencer-empty');
  const view = document.getElementById('influencer-view');
  const imgBox = document.getElementById('preview-box');
  const imgPlaceholder = document.getElementById('img-placeholder');
  const nameEl = document.getElementById('inf-name');
  const vibeEl = document.getElementById('inf-vibe');
  const createdEl = document.getElementById('inf-created');

  if (!state) {
    // no influencer yet
    show(empty); hide(view);
    return;
  }

  // have a row
  hide(empty); show(view);
  nameEl.textContent = state.name || '';
  vibeEl.textContent = state.vibe ? `Vibe: ${state.vibe}` : '';

  if (state.initial_image_url) {
    imgBox.innerHTML = `<img alt="sweetheart" src="${state.initial_image_url}">`;
  } else {
    imgBox.innerHTML = ''; imgBox.append(imgPlaceholder);
  }
  createdEl.textContent = state.created_at ? `Created: ${new Date(state.created_at).toLocaleString()}` : '';
}

async function fetchInfluencerOnce() {
  const res = await api('/api/influencer');
  return res.influencer || null;
}

let pollTimer = null;
async function startPollingUntilReady() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    const inf = await fetchInfluencerOnce();
    await renderInfluencer(inf);
    if (inf && inf.is_locked && inf.initial_image_url) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }, 5000);
}

document.addEventListener('DOMContentLoaded', async () => {
  const token = await ensureToken();
  if (!token) {
    window.location.href = '/login';
    return;
  }

  await loadAccount();

  // initial influencer state
  const first = await fetchInfluencerOnce();
  await renderInfluencer(first);
  if (first && !first.is_locked) startPollingUntilReady();

  // upgrade flow
  const upBtn = document.getElementById('upgrade-btn');
  if (upBtn) {
    upBtn.addEventListener('click', async () => {
      try {
        const data = await api('/api/upgrade', { method: 'POST' });
        if (data.url) window.location.href = data.url;
      } catch (err) {
        alert(err.message);
      }
    });
  }

  // billing portal
  const billingBtn = document.getElementById('billing-btn');
  if (billingBtn) {
    billingBtn.addEventListener('click', async () => {
      try {
        const data = await api('/api/billing-portal', { method: 'POST' });
        if (data.url) window.location.href = data.url;
      } catch (err) {
        alert(err.message);
      }
    });
  }

  // create influencer
  const createBtn = document.getElementById('create-btn');
  const statusEl = document.getElementById('create-status');
  if (createBtn) {
    createBtn.addEventListener('click', async () => {
      const name = document.getElementById('name').value.trim();
      const bio = document.getElementById('bio').value.trim();
      const vibe = document.getElementById('vibe').value.trim();
      if (!name || !bio || !vibe) {
        alert('Please fill name, bio and vibe.');
        return;
      }
      createBtn.disabled = true;
      statusEl.textContent = 'Creating... this can take ~20–60 seconds.';
      try {
        await api('/api/influencer', { method: 'POST', body: JSON.stringify({ name, bio, vibe }) });
        // Switch to “view” and begin polling
        const shell = await fetchInfluencerOnce();
        await renderInfluencer(shell);
        startPollingUntilReady();
        statusEl.textContent = 'Queued. Generating...';
      } catch (e) {
        alert(e.message);
        statusEl.textContent = '';
      } finally {
        createBtn.disabled = false;
      }
    });
  }
});

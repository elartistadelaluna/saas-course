// /assets/js/dashboard.js
import { supabase } from './auth.js';

// Keep your existing access_token flow for /api/* (Bearer header). :contentReference[oaicite:3]{index=3}
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

document.addEventListener('DOMContentLoaded', async () => {
  const token = await ensureToken();
  if (!token) {
    window.location.href = '/login';
    return;
  }

  // Load plan/credits from your Flask /api/me endpoint. :contentReference[oaicite:4]{index=4}
  try {
    const res = await fetch('/api/me', { headers: { Authorization: 'Bearer ' + token } });
    if (!res.ok) throw new Error('Failed to fetch /api/me');
    const data = await res.json();
    document.getElementById('plan').textContent = data.plan ?? '—';
    document.getElementById('credits').textContent = data.credits ?? '—';
  } catch (err) {
    alert(err.message);
  }

  // Upgrade → your /api/upgrade endpoint returns a Stripe Checkout URL. :contentReference[oaicite:5]{index=5}
  const btn = document.getElementById('upgrade-btn');
  if (btn) {
    btn.addEventListener('click', async () => {
      try {
        const res = await fetch('/api/upgrade', {
          method: 'POST',
          headers: { Authorization: 'Bearer ' + token }
        });
        const data = await res.json();
        if (data.url) window.location.href = data.url;
      } catch (err) {
        alert(err.message);
      }
    });
  }
});

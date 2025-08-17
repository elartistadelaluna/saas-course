// /assets/js/login.js
import { supabase } from './auth.js';

document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('login-form');
  if (!form) return;

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const email = form.email.value.trim();
    const password = form.password.value;

    const { data, error } = await supabase.auth.signInWithPassword({ email, password });
    if (error) {
      alert(error.message);
      return;
    }
    // Your backend expects a Bearer JWT in Authorization (used by /api/me, /api/upgrade). :contentReference[oaicite:2]{index=2}
    localStorage.setItem('access_token', data.session.access_token);
    window.location.href = '/dashboard';
  });
});

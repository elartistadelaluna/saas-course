// /assets/js/redirect.js
import { supabase } from './auth.js';

function parseHashTokens() {
  if (!window.location.hash) return null;
  const params = new URLSearchParams(window.location.hash.substring(1)); // drop '#'
  const access_token = params.get('access_token');
  const refresh_token = params.get('refresh_token');
  if (access_token && refresh_token) return { access_token, refresh_token };
  return null;
}

(async () => {
  const url = new URL(window.location.href);
  const code = url.searchParams.get('code');
  const errorDescription = url.searchParams.get('error_description');

  // If Supabase sent an error
  if (errorDescription) {
    alert(errorDescription);
    window.location.replace('/login');
    return;
  }

  try {
    if (code) {
      // PKCE/code flow
      const { error } = await supabase.auth.exchangeCodeForSession(code);
      if (error) throw error;
    } else {
      // Hash tokens flow (#access_token=...&refresh_token=...)
      const tokens = parseHashTokens();
      if (tokens) {
        const { error } = await supabase.auth.setSession(tokens);
        if (error) throw error;
      }
    }
  } catch (err) {
    alert(err.message || 'Sign-in failed.');
    window.location.replace('/login');
    return;
  }

  // Clear hash/query to avoid leaking tokens in history
  history.replaceState(null, '', '/redirect');

  // Continue your original flow
  window.location.replace('/login?confirmed=1');
})();

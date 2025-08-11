// /assets/js/redirect.js
import { supabase } from './auth.js';

(async () => {
  const params = new URLSearchParams(window.location.search);
  const code = params.get('code');
  const err = params.get('error_description');

  if (err) {
    alert(err);
    window.location.href = '/login';
    return;
  }

  if (code) {
    const { error } = await supabase.auth.exchangeCodeForSession(code);
    if (error) {
      alert(error.message);
      window.location.href = '/login';
      return;
    }
  }
  // keep your original flow after confirmation
  window.location.href = '/login?confirmed=1';
})();

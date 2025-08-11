import { supabase } from './auth.js';

async function handleRedirect() {
  try {
    // Exchange the code in the URL for a session
    const { data, error } = await supabase.auth.exchangeCodeForSession(window.location.href);
    if (error) throw error;

    // ✅ Redirect to dashboard after login/signup
    window.location.replace('/dashboard');
  } catch (err) {
    console.error('Error handling redirect:', err.message);
    // Fallback: send to login page
    window.location.replace('/login');
  }
}

handleRedirect();

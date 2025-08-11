// /assets/js/sign-up.js
import { supabase } from './auth.js';

document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('sign-up-form');
  if (!form) return;

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const email = form.email.value.trim();
    const password = form.password.value;

    const { error } = await supabase.auth.signUp({
      email,
      password,
      options: {
        // This MUST be present so the Supabase request includes ?redirect_to=
        emailRedirectTo: 'https://gptsweetheart.com/redirect'
      }
    });

    if (error) {
      alert(error.message);
      return;
    }
    alert('Check your email to confirm your account.');
  });
});

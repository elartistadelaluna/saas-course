// Year in footer
(function(){
  const y = document.getElementById('year');
  if (y) y.textContent = new Date().getFullYear();
})();

// Logout (for /dashboard header). Works whether you use Supabase client or just localStorage.
document.addEventListener('click', async (e) => {
  const el = e.target.closest('#logout-link');
  if (!el) return;
  e.preventDefault();

  // Clear tokens in localStorage
  try {
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    Object.keys(localStorage).forEach(k=>{
      if (k.toLowerCase().includes('supabase')) localStorage.removeItem(k);
    });
  } catch(_) {}

  // Call Supabase client logout
  try {
    await supabase.auth.signOut();
  } catch(err) {
    console.error("Supabase signOut error", err);
  }

  // Redirect to login
  window.location.href = '/login';
});

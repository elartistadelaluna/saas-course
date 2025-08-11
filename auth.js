// /assets/js/auth.js
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2';

const SUPABASE_URL = 'https://rdwwpjfwsoufgbpihykn.supabase.co';
const SUPABASE_ANON_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJkd3dwamZ3c291ZmdicGloeWtuIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTQ4MzUyNTcsImV4cCI6MjA3MDQxMTI1N30.34g9cl9e3aep-iJEPkOgbkpHja07xRSv7QigfpyeiMI';

// One shared client—prevents "Cannot access 'supabase' before initialization".
export const supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

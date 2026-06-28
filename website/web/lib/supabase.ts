import { createClient, SupabaseClient } from "@supabase/supabase-js";

const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

// If the two env vars are set, the app talks to Supabase; otherwise it falls
// back to browser localStorage so the demo still runs with zero config.
export const supabase: SupabaseClient | null =
  url && key ? createClient(url, key) : null;

export const usingSupabase = !!supabase;

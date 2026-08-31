import { createClient } from "@supabase/supabase-js";

const url = process.env.NEXT_PUBLIC_SUPABASE_URL || process.env.SUPABASE_URL || "";
const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || process.env.SUPABASE_ANON_KEY || "";

export const supabase = url && anonKey && !url.includes("your-project") && !url.includes("xxxx")
  ? createClient(url, anonKey)
  : null;

export const isSupabaseConfigured = !!supabase;

export async function getInvestigations() {
  if (!supabase) return [];
  const { data } = await supabase.from("investigations").select("*").order("created_at", { ascending: false });
  return data || [];
}

"use client";
import { useEffect, useState } from "react";
import { dumps, loads } from "@/lib/toon";
import { Activity, DatabaseZap, Github, RefreshCw, ShieldCheck, Trash2 } from "lucide-react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function Dashboard() {
  const [invs, setInvs] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [health, setHealth] = useState<any>(null);
  const [error, setError] = useState("");

  async function loadInvestigations() {
    setLoading(true); setError("");
    try {
      const response = await fetch(`${API}/api/investigations`);
      if (!response.ok) throw new Error(await response.text());
      const data = await response.json();
      setInvs(data.investigations || []);
    } catch (err:any) { setInvs([]); setError(err.message || "Could not load Supabase investigations"); }
    finally { setLoading(false); }
  }

  async function clearAll() {
    if (!window.confirm("Clear every ReproForge investigation, trace, case, run, config, and report from Supabase? This cannot be undone.")) return;
    setLoading(true); setError("");
    try {
      const response = await fetch(`${API}/api/investigations`, { method: "DELETE", headers: { "Content-Type": "application/toon" }, body: dumps({ confirm: "CLEAR_ALL_INVESTIGATIONS" }) });
      if (!response.ok) throw new Error(await response.text());
      loads(await response.text());
      setInvs([]);
    } catch (err:any) { setError(err.message || "Could not clear Supabase data"); }
    finally { setLoading(false); }
  }

  useEffect(() => {
    fetch(`${API}/healthz`).then(r=>r.json()).then(setHealth).catch(()=>{});
    loadInvestigations();
  }, []);

  return (
    <div className="space-y-7 pb-8">
      <section className="relative overflow-hidden rounded-2xl border bg-gradient-to-br from-slate-950 via-slate-900 to-indigo-950 px-6 py-7 text-white shadow-sm md:px-8">
        <div className="absolute -right-16 -top-20 h-64 w-64 rounded-full bg-indigo-500/20 blur-3xl" />
        <div className="relative flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="mb-3 flex items-center gap-2 text-xs font-medium uppercase tracking-[0.18em] text-indigo-200"><Activity size={14}/> Reliability workspace</div>
          <h1 className="text-3xl font-semibold tracking-tight">Prove your agent got better.</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-300">Turn a real GitHub run into a pinned, reproducible investigation with trace evidence, controlled stress tests, and a baseline-versus-advanced verdict.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <a href="/github" className="inline-flex items-center gap-2 rounded-lg bg-white px-4 py-2.5 text-sm font-semibold text-slate-950 shadow-sm hover:bg-slate-100"><Github size={16}/> Live GitHub run</a>
        </div>
        </div>
      </section>
      {error && <div className="border border-red-300 bg-red-50 p-3 rounded text-sm text-red-800">{error}</div>}
      <div className="rounded-xl border bg-white p-4 text-xs">
        <div className="font-bold flex items-center gap-2"><ShieldCheck size={14} className="text-indigo-600"/> Real-time flow (no mocks, no predefined tasks) — models are loaded from the backend environment</div>
        <div className="mt-2 grid gap-1 font-mono text-[11px] leading-relaxed">
          <div>1. Fetch public repositories (<span className="font-bold">list_repositories</span>)</div>
          <div className="pl-4">↓ 2. User selects a repository</div>
          <div className="pl-4">↓ Fetch pinned commit SHA (<span className="font-bold">get_pinned_commit_sha</span> real)</div>
          <div className="pl-4">↓ ReproForge Task Generator (scan README/package.json/routes → <span className="font-bold">Gemini 3.5 Flash</span> → <span className="font-mono">task.toon</span>)</div>
          <div className="pl-4">↓ Human clicks Approve Task → freeze <span className="font-mono">task.toon</span> + commit SHA</div>
          <div className="pl-4">↓ Live Agent executes task (<span className="font-bold">Gemini 3.5 Flash</span> + 4 real tools: <span className="font-mono">list_repositories, list_files, search_code, read_file</span>)</div>
          <div className="pl-4">↓ TOON Trace Recorder (append each event live → <span className="font-mono">trace.toon</span>)</div>
          <div className="pl-4">↓ Result evaluated as passed / failed / inconclusive → Minimal Evidence Case → Stress → Baseline vs Candidate</div>
        </div>
        <div className="mt-2 text-[11px] text-muted-foreground">Database: conf → investigations, reports, runs (SQLite: <span className="font-mono">reproforge.db</span>, Supabase: conf) • <span className="font-mono">GET /healthz</span> for connection status</div>
      </div>

      {health && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
          <div className="rounded-xl border bg-white p-4 shadow-sm">
            <div className="text-muted-foreground">Database</div>
            <div className="mt-1 flex items-center gap-2 font-mono font-bold"><DatabaseZap size={15} className="text-emerald-600"/>{health.supabase_mode || health.mode || "supabase"}</div>
            <div className="text-[11px]">{health.mode==="sqlite" ? `SQLite ${health.path||""}` : Object.entries(health.tables||{}).map(([k,v])=> `${k}:${v}`).join(" ")}</div>
            <div className="text-[10px] text-muted-foreground">conf: investigations, reports, runs</div>
          </div>
          <div className="rounded-xl border bg-white p-4 shadow-sm">
            <div className="text-muted-foreground">Models — from <span className="font-mono">backend/.env.local</span></div>
            <div className="font-mono text-[11px]">{health.model_primary ? `${health.model_primary} → ${health.model_fallback}` : health.model_chain?.join(" → ")}</div>
            <div className="text-[10px] text-muted-foreground">{health.model_primary ? "GEMINI_MODEL → GEMINI_FALLBACK_MODEL" : "GEMINI_MODEL chain"}</div>
          </div>
          <div className="rounded-xl border bg-white p-4 shadow-sm">
            <div className="text-muted-foreground">TOON</div>
            <div className="font-bold">enabled</div>
            <div>~40% token savings</div>
          </div>
          <div className="rounded-xl border bg-white p-4 shadow-sm">
            <div className="text-muted-foreground">Rate Limiting</div>
            <div className="font-bold">enabled</div>
            <div>10/min LLM · 60/min general</div>
          </div>
        </div>
      )}

      <div className="overflow-hidden rounded-2xl border bg-white shadow-sm">
        <div className="flex items-center justify-between bg-slate-50 px-5 py-4 text-sm font-medium">
          <span>ReproForge Lab — Observe → Reproduce → Minimize → Perturb → Compare → Prove</span>
          <div className="flex items-center gap-3"><span className="text-xs text-muted-foreground">{invs.length} investigations</span><button onClick={loadInvestigations} aria-label="Refresh investigations" className="rounded-md p-1.5 hover:bg-slate-200"><RefreshCw size={15}/></button><button onClick={clearAll} disabled={loading || invs.length===0} className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-red-700 hover:bg-red-50 disabled:opacity-40"><Trash2 size={14}/> Clear all</button></div>
        </div>
        {loading ? (
          <div className="p-8 text-center text-sm text-muted-foreground">Loading…</div>
        ) : invs.length === 0 ? (
          <div className="p-10 text-center">
            <div className="mx-auto mb-4 grid h-12 w-12 place-items-center rounded-2xl bg-slate-100 text-slate-700"><Activity size={21}/></div><div className="text-base font-medium">Your evidence workspace is ready</div><div className="mx-auto mt-2 max-w-md text-sm text-muted-foreground">Start a live GitHub investigation. ReproForge generates the task, pins the repository SHA, captures TOON, and creates the investigation automatically.</div>
            <div className="mt-5 flex justify-center"><a href="/github" className="rounded-lg bg-slate-950 px-4 py-2 text-sm font-medium text-white">Start live GitHub run</a></div>
            <div className="mt-8 grid gap-3 text-left text-xs md:grid-cols-3">
              <div className="rounded-xl border bg-slate-50 p-4"><div className="font-bold">1. Capture</div><div className="mt-1 text-muted-foreground">Pin the repository SHA and record a real TOON trace.</div></div>
              <div className="rounded-xl border bg-slate-50 p-4"><div className="font-bold">2. Diagnose</div><div className="mt-1 text-muted-foreground">Gemini isolates the divergence and creates a minimal reproducer.</div></div>
              <div className="rounded-xl border bg-slate-50 p-4"><div className="font-bold">3. Prove</div><div className="mt-1 text-muted-foreground">Compare baseline and advanced configurations on the same evidence.</div></div>
            </div>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-zinc-50 text-xs text-muted-foreground"><tr><th className="text-left p-3">Name</th><th>Task</th><th>Status</th><th>Created</th><th></th></tr></thead>
            <tbody>
              {invs.map((inv:any)=>(
                <tr key={inv.id} className="border-t hover:bg-zinc-50">
                  <td className="p-3 font-medium">{inv.name}</td>
                  <td className="p-3 text-xs max-w-[260px] truncate">{inv.task}</td>
                  <td className="p-3"><span className="px-2 py-1 rounded bg-secondary text-xs">{inv.status}</span></td>
                  <td className="p-3 text-xs text-muted-foreground" suppressHydrationWarning>{inv.created_at ? new Date(inv.created_at).toISOString().replace("T", " ").slice(0, 19) + " UTC" : "—"}</td>
                  <td className="p-3"><a href={`/investigations/${inv.id}`} className="text-xs underline">Open →</a></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

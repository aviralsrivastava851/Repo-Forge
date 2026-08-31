"use client";
import { useState, useRef } from "react";
import { dumps, loads } from "@/lib/toon";
import { useRouter } from "next/navigation";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function GithubFlowPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [repos, setRepos] = useState<any[]>([]);
  const [selectedRepo, setSelectedRepo] = useState("");
  const [commit, setCommit] = useState("");
  const [taskData, setTaskData] = useState<any>(null);
  const [caseId, setCaseId] = useState("");
  const [approved, setApproved] = useState(false);
  const [runId, setRunId] = useState("");
  const [investigationId, setInvestigationId] = useState("");
  const [events, setEvents] = useState<any[]>([]);
  const [loading, setLoading] = useState<string>("");
  const [error, setError] = useState("");
  const eventSourceRef = useRef<EventSource | null>(null);

  async function loadRepos() {
    if (!username.trim()) { setError("Enter a public GitHub username"); return; }
    setError(""); setLoading("repos");
    try {
      const res = await fetch(`${API}/api/github/repos/${username}`);
      if (!res.ok) throw new Error(await res.text());
      const data = loads(await res.text());
      setRepos(data.repos || []);
      if (data.repos?.length) setSelectedRepo(data.repos[0].full_name);
    } catch (e:any) { setError(e.message); }
    finally { setLoading(""); }
  }

  async function generateTask() {
    if (!selectedRepo) { setError("Select a repository"); return; }
    setError(""); setLoading("task");
    try {
      const res = await fetch(`${API}/api/github/task/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/toon" },
        body: dumps({ repository: selectedRepo, commit }),
      });
      if (!res.ok) throw new Error(await res.text());
      const data = loads(await res.text());
      setTaskData(data.task);
      setCaseId(data.case_id);
      setCommit(data.commit);
      setApproved(false);
    } catch (e:any) { setError(e.message); }
    finally { setLoading(""); }
  }

  async function approveTask() {
    setError(""); setLoading("approve");
    try {
      const res = await fetch(`${API}/api/github/task/approve`, { method: "POST", headers: { "Content-Type": "application/toon" }, body: dumps({ case_id: caseId }) });
      if (!res.ok) throw new Error(await res.text());
      const data = loads(await res.text());
      setTaskData(data.task); setApproved(true);
    } catch (e:any) { setError(e.message); } finally { setLoading(""); }
  }

  async function runAgent() {
    if (!taskData || !selectedRepo || !commit || !approved) { setError("Generate and approve the task first"); return; }
    setError(""); setLoading("run");
    setEvents([]);
    try {
      const res = await fetch(`${API}/api/runs`, {
        method: "POST",
        headers: { "Content-Type": "application/toon" },
        body: dumps({ repository: selectedRepo, commit, task: taskData, case_id: caseId }),
      });
      if (!res.ok) throw new Error(await res.text());
      const data = loads(await res.text());
      const rId = data.run_id;
      setRunId(rId);
      setInvestigationId(data.investigation_id || "");
      // SSE live trace
      const es = new EventSource(`${API}/api/runs/${rId}/events`);
      eventSourceRef.current = es;
      es.onmessage = (ev) => {
        try {
          const d = loads(ev.data);
          if (d.type === "completed") {
            es.close();
            setLoading("");
            if (data.investigation_id) router.push(`/investigations/${data.investigation_id}`);
          } else {
            setEvents(prev => [...prev, d]);
          }
        } catch {}
      };
      es.onerror = () => { es.close(); setLoading(""); };
    } catch (e:any) { setError(e.message); setLoading(""); }
  }

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <h1 className="text-2xl font-bold">ReproForge — Live GitHub Investigation</h1>
      <p className="text-sm text-muted-foreground">GitHub account → Fetch public repositories → User selects repository → Fetch pinned commit SHA → Task Generator (Gemini 3.5 Flash grounded) → Live Agent (real GitHub tools) → TOON Trace → ReproForge</p>

      {error && <div className="border border-red-200 bg-red-50 p-3 rounded text-sm text-red-700">{error}</div>}

      <div className="border rounded-lg p-4 space-y-4">
        <div className="flex gap-2 items-end">
          <div className="flex-1">
            <label className="text-sm font-medium">GitHub Username</label>
            <input suppressHydrationWarning value={username} onChange={e=>setUsername(e.target.value)} className="w-full mt-1 border rounded px-3 py-2 text-sm" placeholder="GitHub username" />
          </div>
          <button suppressHydrationWarning onClick={loadRepos} disabled={loading==="repos"} className="px-4 py-2 bg-black text-white rounded text-sm disabled:opacity-50">
            {loading==="repos" ? "Loading..." : "Load Repositories"}
          </button>
        </div>

        {repos.length > 0 && (
          <div>
            <div className="text-sm font-medium mb-2">Choose repository — {repos.length} public repos</div>
            <div className="border rounded max-h-64 overflow-auto divide-y">
              {repos.slice(0,25).map((r:any)=>(
                <label key={r.full_name} className={`flex items-center gap-3 p-2 hover:bg-zinc-50 cursor-pointer ${selectedRepo===r.full_name?"bg-zinc-100":""}`}>
                  <input type="radio" name="repo" checked={selectedRepo===r.full_name} onChange={()=>setSelectedRepo(r.full_name)} />
                  <div className="flex-1">
                    <div className="text-sm font-medium">{r.name} <span className="text-xs text-muted-foreground">{r.language || ""}</span></div>
                    <div className="text-xs text-muted-foreground truncate">{r.description || r.html_url}</div>
                  </div>
                  <span className="text-xs text-muted-foreground">★{r.stargazers_count}</span>
                </label>
              ))}
            </div>
            <div className="text-xs text-muted-foreground mt-1">The selected repository&apos;s current commit SHA is fetched and pinned automatically before task generation.</div>
            <button onClick={generateTask} disabled={loading==="task"} className="mt-3 w-full py-2.5 bg-black text-white rounded text-sm disabled:opacity-50">
              {loading==="task" ? "Generating task via Gemini 3.5 Flash..." : "Generate Investigation"}
            </button>
          </div>
        )}

        {taskData && (
          <div className="border rounded p-3 bg-zinc-50 space-y-2">
            <div className="text-sm font-bold">Generated Task — Gemini 3.5 Flash grounded in repo evidence (requires ≥2 tool calls, deterministic)</div>
            <div className="text-xs">Repository: <span className="font-mono">{selectedRepo}</span> Commit: <span className="font-mono">{commit.slice(0,7)}</span> {commit && <span className="text-green-600">✓ pinned SHA verified</span>}</div>
            <pre className="text-xs font-mono whitespace-pre-wrap bg-white p-2 rounded border">{dumps(taskData).slice(0,2000)}</pre>
            <div className="text-xs">Case: <span className="font-mono">{caseId}</span> — will be frozen as <span className="font-mono">datasets/github/{caseId}/task.toon</span> for reproducible benchmark</div>
            <button onClick={approveTask} disabled={loading==="approve" || approved} className="w-full py-2 border rounded text-sm disabled:opacity-50">
              {approved ? "✓ Task approved and frozen" : loading==="approve" ? "Approving..." : "Approve Task and Freeze SHA"}
            </button>
            <button onClick={runAgent} disabled={loading==="run" || !approved} className="w-full py-2.5 bg-black text-white rounded text-sm disabled:opacity-50">
              {loading==="run" ? "Running Live Agent..." : approved ? "Run Agent — Live GitHub tool calls → TOON trace" : "Approve the task before running the agent"}
            </button>
            <div className="text-xs text-muted-foreground">Agent receives only <span className="font-mono">question + tools</span> (no ground_truth). Ground truth stays separate for evaluation.</div>
          </div>
        )}

        {events.length > 0 && (
          <div className="border rounded overflow-hidden">
            <div className="bg-zinc-900 text-white px-3 py-2 text-sm font-mono flex justify-between">
              <span>LIVE TRACE — {runId}</span>
              <span className="text-xs opacity-70">{events.length} events</span>
            </div>
            <div className="bg-black text-green-400 font-mono text-xs p-3 max-h-96 overflow-auto space-y-1">
              {events.map((ev, i)=>(
                <div key={i} className="flex gap-2">
                  <span className="opacity-50">{ev.timestamp || ""}</span>
                  <span className={ev.type==="tool_call"?"text-yellow-400": ev.type==="tool_result"?"text-cyan-400": ev.type==="final_decision"?"text-white font-bold":""}>{ev.type?.toUpperCase()}</span>
                  <span className="truncate">{ev.tool ? `${ev.tool}(${ev.query || ev.path || ""})` : ev.content || ev.file || dumps(ev).slice(0,120)}</span>
                  {ev.file && <span className="text-cyan-400">{ev.file}</span>}
                  {ev.file_count !== undefined && <span>{ev.file_count} files</span>}
                </div>
              ))}
              {loading==="run" && <div className="animate-pulse">● Live streaming via SSE /api/runs/{runId}/events ...</div>}
            </div>
            <div className="p-2 text-xs bg-zinc-50">Trace persisted as TOON: <span className="font-mono">data/real_traces/{runId}.toon</span> + <span className="font-mono">datasets/github/{caseId}/trace.toon</span> (human_verified pending)</div>
          </div>
        )}

        {investigationId && events.some(e=>e.type==="final_decision") && (
          <div className="border rounded p-3 bg-green-50">
            <div className="text-sm font-bold">Live Run Complete — Ready for ReproForge</div>
            <div className="flex gap-2 mt-2">
              <a href={`/investigations/${investigationId}`} className="px-3 py-1.5 bg-black text-white rounded text-xs">Open investigation</a>
              <a href={`/api/runs/${runId}/events`} target="_blank" className="px-3 py-1.5 border rounded text-xs">View SSE Stream</a>
            </div>
            <div className="text-xs mt-2">Next: Outcome Evaluation → Minimal Evidence Case → Stress Test → Baseline vs Candidate → Evidence Report → Human Review</div>
          </div>
        )}
      </div>

      <div className="border rounded p-3 bg-zinc-50 text-xs">
        <div className="font-bold">Real-time flow (no mocks, no predefined tasks)</div>
        <pre className="mt-1 font-mono text-[11px] whitespace-pre-wrap">{`1. Fetch public repositories (list_repositories)
  ↓ 2. User selects a repository
  ↓ Fetch pinned commit SHA (get_pinned_commit_sha real)
  ↓ ReproForge Task Generator (scan README/package.json/routes → Gemini 3.5 Flash → task.toon)
  ↓ Human clicks Approve Task → freeze task.toon + commit SHA
  ↓ Live Agent executes task (Gemini 3.5 Flash + 4 real tools: list_repositories, list_files, search_code, read_file)
  ↓ TOON Trace Recorder (append each event live → trace.toon)
  ↓ Result evaluated as passed / failed / inconclusive → ReproForge (Outcome Evaluation → Minimal Evidence Case → Stress → Baseline vs Candidate)`}</pre>
      </div>
    </div>
  );
}

"use client";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function ComparePage() {
  const params = useParams();
  const id = params.id as string;
  const [report, setReport] = useState<any>(null);
  const [cases, setCases] = useState<any[]>([]);

  useEffect(()=>{
    fetch(`${API}/api/investigations/${id}/report`).then(r=>r.json()).then(setReport).catch(()=>{});
    fetch(`${API}/api/investigations/${id}/cases`).then(r=>r.json()).then(d=> setCases(d.cases||[])).catch(()=>{});
  },[id]);

  if (!report) return <div className="p-8 text-center text-sm">Loading report… <a href={`/investigations/${id}`} className="underline">Back</a></div>;

  return (
    <div className="space-y-6">
      <a href={`/investigations/${id}`} className="text-xs underline">← Back to investigation</a>
      <h1 className="text-xl font-bold">Compare — Baseline vs Candidate</h1>
      <div className="border rounded p-4 bg-zinc-50">
        <div className="text-sm font-bold">Verdict: {report.verdict}</div>
        <div className="text-xs">Baseline {report.baseline_passed}/{report.total_cases} • Candidate {report.candidate_passed}/{report.total_cases} • Regressions {report.regression_count}</div>
        <pre className="text-xs font-mono whitespace-pre-wrap mt-3 bg-white p-3 rounded border">{report.toon_payload}</pre>
      </div>
      <div className="border rounded p-3">
        <div className="text-xs font-bold">Cases ({cases.length})</div>
        <ul className="text-xs mt-2 space-y-1">
          {cases.map(c=> <li key={c.id} className="border-b py-1">{c.id} — {c.source} — {JSON.stringify(c.assertion)}</li>)}
        </ul>
      </div>
      <div className="text-xs text-red-600 font-bold">Human approval required before promoting candidate.</div>
    </div>
  );
}

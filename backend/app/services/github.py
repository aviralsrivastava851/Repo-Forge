"""
Real GitHub read-only tools — pinned commit SHA, no writes.
Uses GITHUB_TOKEN from env if available, else unauthenticated (rate-limited).
All calls are read-only and real — no mocks.
"""
from __future__ import annotations
import os
import httpx
from typing import Any, Optional, List, Dict

GITHUB_API = "https://api.github.com"
RAW_BASE = "https://raw.githubusercontent.com"

def _get_token() -> Optional[str]:
    return os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")

def _headers() -> Dict[str, str]:
    h = {"Accept": "application/vnd.github.v3+json", "User-Agent": "ReproForge/1.0"}
    tok = _get_token()
    if tok and "your" not in tok and len(tok) > 10:
        h["Authorization"] = f"Bearer {tok}"
    return h

def _get_client() -> httpx.Client:
    return httpx.Client(timeout=20.0, headers=_headers(), follow_redirects=True)

# --- Real read-only tool calls ---

def github_get_commit(repo: str, sha: str) -> Dict[str, Any]:
    """Verify pinned commit exists — GET /repos/{owner}/{repo}/commits/{sha}"""
    url = f"{GITHUB_API}/repos/{repo}/commits/{sha}"
    with _get_client() as c:
        r = c.get(url)
        r.raise_for_status()
        return r.json()

def github_get_file(repo: str, path: str, commit: str) -> Dict[str, Any]:
    """Get file content at pinned commit — raw.githubusercontent.com"""
    url = f"{RAW_BASE}/{repo}/{commit}/{path}"
    with _get_client() as c:
        r = c.get(url)
        if r.status_code == 404:
            raise FileNotFoundError(f"File not found at {repo}@{commit}:{path}")
        r.raise_for_status()
        return {"path": path, "content": r.text[:8000], "commit": commit, "repo": repo, "url": url}

def github_list_files(repo: str, commit: str, prefix: str = "") -> List[str]:
    """List files at commit via git tree — GET /repos/{repo}/git/trees/{sha}?recursive=1"""
    # First get commit to get tree sha
    commit_data = github_get_commit(repo, commit)
    tree_sha = commit_data["commit"]["tree"]["sha"]
    url = f"{GITHUB_API}/repos/{repo}/git/trees/{tree_sha}?recursive=1"
    with _get_client() as c:
        r = c.get(url)
        r.raise_for_status()
        data = r.json()
        files = [e["path"] for e in data.get("tree", []) if e["type"] == "blob"]
        if prefix:
            files = [f for f in files if f.startswith(prefix)]
        return files[:500]

def github_code_search(query: str, repo: str, commit: str) -> Dict[str, Any]:
    """
    Real code search — uses GitHub Search API if token available, else falls back to listing files and client-side grep via raw.
    Since code search requires auth, we implement a real alternative: list files and search via raw content for the query.
    This is still real read-only tool calls to GitHub.
    """
    # Try authenticated search first
    token = _get_token()
    if token:
        url = f"{GITHUB_API}/search/code?q={query}+repo:{repo}"
        with _get_client() as c:
            r = c.get(url)
            if r.status_code == 200:
                data = r.json()
                items = data.get("items", [])[:10]
                return {
                    "query": query,
                    "repo": repo,
                    "commit": commit,
                    "results": [{"path": it["path"], "url": it["html_url"]} for it in items],
                    "total_count": data.get("total_count", 0),
                }
    # Fallback: real file listing + grep via raw (still real GitHub calls)
    files = github_list_files(repo, commit)
    # Filter candidates by name containing query keyword
    q_low = query.lower().split()[0][:12]
    candidates = [f for f in files if q_low in f.lower()][:20]
    # Also try to fetch a few files and check content
    matched = []
    for path in candidates[:10]:
        try:
            file_data = github_get_file(repo, path, commit)
            if query.lower() in file_data["content"].lower():
                matched.append({"path": path, "snippet": file_data["content"][:600]})
                if len(matched) >= 5:
                    break
        except:
            continue
    # If no direct name match, try broad
    if not matched:
        for path in files[:30]:
            if any(ext in path for ext in [".ts", ".js", ".py", ".go", ".rs"]):
                try:
                    fd = github_get_file(repo, path, commit)
                    if query.lower().split()[0].lower() in fd["content"].lower():
                        matched.append({"path": path, "snippet": fd["content"][:600]})
                        if len(matched) >= 3:
                            break
                except:
                    continue
    return {"query": query, "repo": repo, "commit": commit, "results": matched[:10], "total_count": len(matched), "method": "file_list_grep"}

def github_read_file_snippet(repo: str, path: str, commit: str, max_lines: int = 80) -> str:
    data = github_get_file(repo, path, commit)
    lines = data["content"].splitlines()[:max_lines]
    return "\n".join(lines)

def list_repositories(username: str) -> List[Dict[str, Any]]:
    """Real list_repositories() — GET /users/{username}/repos — real time, no mocks"""
    url = f"{GITHUB_API}/users/{username}/repos?per_page=100&sort=updated"
    with _get_client() as c:
        r = c.get(url)
        r.raise_for_status()
        data = r.json()
        # Return minimal info, sorted by updated
        repos = []
        for repo in data:
            repos.append({
                "name": repo["name"],
                "full_name": repo["full_name"],
                "html_url": repo["html_url"],
                "description": repo.get("description", ""),
                "language": repo.get("language", ""),
                "stargazers_count": repo.get("stargazers_count", 0),
                "default_branch": repo.get("default_branch", "main"),
                "pushed_at": repo.get("pushed_at", ""),
                "updated_at": repo.get("updated_at", ""),
            })
        repos.sort(key=lambda x: x["updated_at"], reverse=True)
        return repos

def get_pinned_commit_sha(repo: str, branch: str = None) -> str:
    """Fetch pinned commit SHA for repo — real time — GET /repos/{owner}/{repo}/commits"""
    # repo is "owner/name"
    if branch:
        url = f"{GITHUB_API}/repos/{repo}/commits/{branch}"
        with _get_client() as c:
            r = c.get(url)
            r.raise_for_status()
            return r.json()["sha"]
    url = f"{GITHUB_API}/repos/{repo}/commits?per_page=1"
    with _get_client() as c:
        r = c.get(url)
        r.raise_for_status()
        data = r.json()
        return data[0]["sha"] if isinstance(data, list) and data else data["sha"]

def get_repository_context(repo: str, commit: str) -> Dict[str, Any]:
    """Scan structure for grounded task generation — README, package.json, routes, etc. — real"""
    context = {"repo": repo, "commit": commit, "files": [], "readme": "", "package_json": "", "routes": []}
    try:
        files = github_list_files(repo, commit)
        context["files"] = files[:120]
        # README
        for cand in ["README.md", "readme.md", "README.MD"]:
            if cand in files:
                try:
                    context["readme"] = github_get_file(repo, cand, commit)["content"][:4000]
                    break
                except: pass
        # package.json / requirements
        for cand in ["package.json", "requirements.txt", "pyproject.toml", "go.mod"]:
            if cand in files:
                try:
                    context["package_json"] = github_get_file(repo, cand, commit)["content"][:3000]
                    break
                except: pass
        # routes / structure hints
        route_hints = [f for f in files if any(k in f.lower() for k in ["route", "router", "api/", "app/", "src/routes", "pages/", "handlers/"])]
        context["routes"] = route_hints[:20]
        # Grounding snippets from actual source/config/markup files. A filename
        # list alone is not evidence and caused unverifiable generated tasks.
        context["sample_files"] = []
        source_exts = (".ts", ".tsx", ".js", ".jsx", ".py", ".go", ".rs", ".java", ".html", ".css", ".scss", ".vue", ".svelte", ".yml", ".yaml", ".toml")
        for f in files[:80]:
            if f.lower().endswith(source_exts) and not f.startswith("."):
                try:
                    snippet = github_get_file(repo, f, commit)["content"][:1600]
                    context["sample_files"].append({"path": f, "snippet": snippet})
                    if len(context["sample_files"]) >= 8:
                        break
                except: pass
    except Exception as e:
        context["error"] = str(e)[:500]
    return context

# --- Pinned commit verification ---

def verify_pinned_commit(repo: str, commit: str) -> bool:
    try:
        github_get_commit(repo, commit)
        return True
    except Exception:
        return False

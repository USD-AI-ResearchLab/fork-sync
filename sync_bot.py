#!/usr/bin/env python3

import os, sys, subprocess, tempfile, shutil
from datetime import datetime
from typing import Optional, List, Dict, Any
import yaml

from github import Github
from github.Auth import Token

def log(msg: str): print(msg, flush=True)

def run(cmd: List[str], cwd: Optional[str]=None, check: bool=True):
    return subprocess.run(cmd, cwd=cwd, check=check, text=True, capture_output=True)

def fetch_upstream(repo_dir: str, upstream_url: str):
    try:
        run(["git", "fetch", "upstream", "--prune"], cwd=repo_dir)
        return
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or "")
        if not any(k in stderr for k in ["could not read Username", "Authentication failed", "Permission denied"]):
            raise
    token = os.getenv("FORK_SYNC_TOKEN") or os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("Upstream requires auth but no FORK_SYNC_TOKEN/GITHUB_TOKEN provided")
    authed = upstream_url.replace("https://github.com/", f"https://{token}@github.com/") if upstream_url.startswith("https://github.com/") else upstream_url
    run(["git", "remote", "set-url", "upstream", authed], cwd=repo_dir)
    try:
        run(["git", "fetch", "upstream", "--prune"], cwd=repo_dir)
    finally:
        run(["git", "remote", "set-url", "upstream", upstream_url], cwd=repo_dir)

def ensure_repo(owner: str, name: str, upstream_url: str, workdir: str):
    os.makedirs(workdir, exist_ok=True)
    run(["git", "init"], cwd=workdir)
    run(["git", "remote", "remove", "origin"], cwd=workdir, check=False)
    run(["git", "remote", "remove", "upstream"], cwd=workdir, check=False)
    run(["git", "remote", "add", "origin", f"https://github.com/{owner}/{name}.git"], cwd=workdir)
    run(["git", "remote", "add", "upstream", upstream_url], cwd=workdir)

def checkout_branch(repo_dir: str, branch: str):
    # ensure origin fetched
    run(["git", "fetch", "origin", "--prune"], cwd=repo_dir)
    # checkout origin/<branch> into local branch
    run(["git", "checkout", "-B", branch, f"origin/{branch}"], cwd=repo_dir)

def is_fast_forward(repo_dir: str, branch: str) -> bool:
    # true if origin/<branch> is ancestor of upstream/<branch>
    try:
        run(["git", "merge-base", "--is-ancestor", f"origin/{branch}", f"upstream/{branch}"], cwd=repo_dir)
        return True
    except subprocess.CalledProcessError:
        return False

def create_pr(gh: Github, owner: str, repo_name: str, branch_from: str, title: str, body: str) -> None:
    repo = gh.get_repo(f"{owner}/{repo_name}")
    try:
        pr = repo.create_pull(title=title, body=body, head=branch_from, base="main")
        log(f"[INFO] PR created #{pr.number} for {repo_name}")
    except Exception as e:
        log(f"[WARN] PR create skipped/failed for {repo_name}: {e}")

def sync_repo(gh: Github, owner: str, name: str, spec: Dict[str, Any]) -> str:
    mode = spec.get("mode", "pr")  # "mirror" or "pr"
    upstream = spec["upstream"]
    branch = spec.get("branch", "main")
    workdir = os.path.join("/tmp", name.replace("/", "_"))
    log(f"[INFO] 🔍 {owner}/{name} <= {upstream} [{branch}] (mode={mode})")
    ensure_repo(owner, name, upstream, workdir)
    fetch_upstream(workdir, upstream)
    checkout_branch(workdir, branch)

    if mode == "mirror":
        # hard reset fork main to upstream/main and force push
        run(["git", "reset", "--hard", f"upstream/{branch}"], cwd=workdir)
        run(["git", "push", "--force-with-lease", "origin", branch], cwd=workdir)
        return "mirrored"

    # PR mode (default)
    if is_fast_forward(workdir, branch):
        # fast-forward update
        run(["git", "merge", "--ff-only", f"upstream/{branch}"], cwd=workdir)
        run(["git", "push", "origin", branch], cwd=workdir)
        return "fast-forward"
    else:
        # divergence -> create timestamped branch from upstream and push, open PR
        sync_branch = f"sync/upstream-{datetime.utcnow():%Y%m%d-%H%M%S}"
        run(["git", "checkout", "-B", sync_branch, f"upstream/{branch}"], cwd=workdir)
        run(["git", "push", "-u", "origin", sync_branch], cwd=workdir)
        title = f"Sync with upstream/{branch} ({datetime.utcnow():%Y-%m-%d})"
        body = "Automated sync: your fork has local commits; this PR brings it back in line with upstream."
        create_pr(gh, owner, name, sync_branch, title, body)
        return "pr"

def main():
    token = (os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN") or "").strip()
    if not token:
        print("❌ Bot failed: GITHUB_TOKEN environment variable is required")
        sys.exit(1)
    owner = os.getenv("GITHUB_OWNER", "USD-AI-ResearchLab").strip()

    with open("repos.yml", "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    repos = cfg.get("repositories", {})

    log(f"✅ Fork Sync Bot initialized for: {owner}")
    log(f"📂 Repositories in config: {len(repos)}\n")
    log(f"🚀 Starting sync run at {datetime.utcnow()} UTC\n")

    gh = Github(auth=Token(token))

    ok, mirrored, prs, errs = [], [], [], []
    for name, spec in repos.items():
        if spec.get("disabled"):
            log(f"[INFO] ⏭ Skipping {name} (disabled)")
            continue
        try:
            result = sync_repo(gh, owner, name, spec)
            if result == "fast-forward": ok.append(f"{owner}/{name}:{spec.get('branch','main')}")
            elif result == "mirrored": mirrored.append(f"{owner}/{name}:{spec.get('branch','main')}")
            else: prs.append(name)
        except Exception as e:
            log(f"Error:  ❌ {name}: {e}")
            errs.append(name)

    log("="*72)
    log("📊 Sync Summary")
    log("="*72)
    if ok:
        log(f"✔ Fast-forward OK: {len(ok)}")
        for r in ok: log(f"  • {r}")
    if mirrored:
        log(f"🔁 Mirrored (force reset): {len(mirrored)}")
        for r in mirrored: log(f"  • {r}")
    if prs:
        log(f"📝 PRs opened: {len(prs)}")
        for r in prs: log(f"  • {r}")
    if errs:
        log(f"❌ Errors: {len(errs)}")
        for r in errs: log(f"  • {r}")

if __name__ == "__main__":
    main()

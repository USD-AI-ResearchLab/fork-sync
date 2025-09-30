#!/usr/bin/env python3
"""Fork Sync Bot (updated)
- Reads repo list from repos.yml
- Fetches upstream (with token fallback if required)
- Pushes timestamped sync branch to avoid non-fast-forward
"""

import os
import sys
import subprocess
from datetime import datetime
from typing import Optional, List
import yaml

from github import Github
from github.Auth import Token

def log(msg: str):
    print(msg, flush=True)

def run(cmd: List[str], cwd: Optional[str] = None, check: bool = True):
    return subprocess.run(cmd, cwd=cwd, check=check, text=True, capture_output=True)

def fetch_upstream(repo_dir: str, upstream_url: str):
    # try anonymous first
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

    authed = upstream_url
    if upstream_url.startswith("https://github.com/"):
        authed = upstream_url.replace("https://github.com/", f"https://{token}@github.com/")

    run(["git", "remote", "set-url", "upstream", authed], cwd=repo_dir)
    try:
        run(["git", "fetch", "upstream", "--prune"], cwd=repo_dir)
    finally:
        run(["git", "remote", "set-url", "upstream", upstream_url], cwd=repo_dir)

def ensure_repo_initialized(owner: str, name: str, upstream_url: str, default_branch: str, workdir: str):
    os.makedirs(workdir, exist_ok=True)
    run(["git", "init"], cwd=workdir)
    run(["git", "remote", "remove", "origin"], cwd=workdir, check=False)
    run(["git", "remote", "remove", "upstream"], cwd=workdir, check=False)
    run(["git", "remote", "add", "origin", f"https://github.com/{owner}/{name}.git"], cwd=workdir)
    run(["git", "remote", "add", "upstream", upstream_url], cwd=workdir)
    # Fetch upstream (with fallback auth)
    fetch_upstream(workdir, upstream_url)
    # Check out a timestamped branch for the sync
    branch = f"sync/upstream-{datetime.utcnow():%Y%m%d-%H%M%S}"
    run(["git", "checkout", "-B", branch], cwd=workdir)
    return branch

def main():
    github_token = (os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN") or "").strip()
    if not github_token:
        print("❌ Bot failed: GITHUB_TOKEN environment variable is required")
        sys.exit(1)

    owner = os.getenv("GITHUB_OWNER", "USD-AI-ResearchLab").strip()

    # Load repos config
    with open("repos.yml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    repos = config.get("repositories", {})
    log(f"✅ Fork Sync Bot initialized for: {owner}")
    log(f"📂 Repositories in config: {len(repos)}\n")
    log(f"🚀 Starting sync run at {datetime.utcnow()} UTC\n")

    gh = Github(auth=Token(github_token))

    ok_ff = []
    errors = []

    for name, spec in repos.items():
        if spec.get("disabled"):
            log(f"[INFO] ⏭ Skipping {name} (disabled)")
            continue

        upstream = spec["upstream"]
        branch = spec.get("branch", "main")
        log(f"[INFO] 🔍 {owner}/{name} <= {upstream} [{branch}]")
        workdir = os.path.join("/tmp", name.replace("/", "_"))
        try:
            log(f"[INFO] Cloning {owner}/{name} …")
            bname = ensure_repo_initialized(owner, name, upstream, branch, workdir)
            ok_ff.append(f"{owner}/{name}:{branch}")
            run(["git", "push", "-u", "origin", bname], cwd=workdir)
        except subprocess.CalledProcessError as e:
            emsg = (e.stderr or e.stdout or str(e)).strip()
            log(f"Error:  ❌ {name}: RuntimeError: {emsg}")
            errors.append(name)
        except Exception as ex:
            log(f"Error:  ❌ {name}: {type(ex).__name__}: {ex}")
            errors.append(name)

    log("="*72)
    log("📊 Sync Summary")
    log("="*72)
    log(f"✔ Fast-forward OK:    {len(ok_ff)}")
    for r in ok_ff[:25]:
        log(f"  • {r}")
    if errors:
        log("❌ Errors:             " + str(len(errors)))
        for r in errors:
            log(f"  • {r}")

if __name__ == "__main__":
    main()

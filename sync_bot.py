#!/usr/bin/env python3
"""
Centralized Fork Sync Bot (merge-capable)
- Reads config.json (same shape you already use)
- For each fork:
   1) Clone fork with token
   2) Add/fetch upstream
   3) Try fast-forward merge from upstream/<branch> into <branch>
   4) If not fast-forward:
        - create sync branch in fork
        - merge upstream on that branch
        - push branch and open a PR in the fork
"""

import os
import sys
import json
import re
import shutil
import pathlib
import datetime
import subprocess
from typing import Dict, Any, List, Tuple, Optional

from github import Github
from github.Auth import Token
import github


# ---------------------------- helpers ----------------------------

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
OWNER_ENV = os.getenv("GITHUB_OWNER", "USD-AI-ResearchLab").strip()
TOKEN_ENV = os.getenv("GITHUB_TOKEN", "").strip()

def log(level: str, msg: str):
    order = ["DEBUG", "INFO", "WARN", "ERROR"]
    if order.index(level) >= order.index(LOG_LEVEL):
        print(f"[{level}] {msg}")

def run(cmd: str, cwd: Optional[pathlib.Path] = None, check: bool = True) -> str:
    res = subprocess.run(cmd, shell=True, cwd=str(cwd) if cwd else None,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    out = res.stdout.strip()
    if check and res.returncode != 0:
        raise RuntimeError(f"Command failed ({res.returncode}): {cmd}\n{out}")
    return out

def inject_token(https_url: str, token: str) -> str:
    # Transform https://github.com/owner/repo.git  -> https://<token>:x-oauth-basic@github.com/owner/repo.git
    m = re.match(r"^https://github\.com/(.+)$", https_url.strip())
    if not m:
        raise ValueError(f"Unexpected repo URL: {https_url}")
    return f"https://{token}:x-oauth-basic@github.com/{m.group(1)}"


# ------------------------- core bot class -------------------------

class ForkSyncBot:
    def __init__(self):
        if not TOKEN_ENV:
            raise ValueError("GITHUB_TOKEN environment variable is required")
        self.owner = OWNER_ENV
        self.token = TOKEN_ENV

        self.gh = Github(auth=Token(self.token))
        try:
            # Use organization if available; fall back to user
            self.container = self.gh.get_organization(self.owner)
        except github.GithubException:
            self.container = self.gh.get_user(self.owner)

        with open("config.json", "r", encoding="utf-8") as f:
            cfg = json.load(f)
        self.repositories: Dict[str, Dict[str, Any]] = cfg.get("repositories", {})

        self.created_prs: List[str] = []
        self.up_to_date: List[str] = []
        self.skipped: List[str] = []
        self.errors: List[Tuple[str, str]] = []

        print(f"✅ Fork Sync Bot initialized for: {self.owner}")
        print(f"📂 Repositories in config: {len(self.repositories)}")

    @staticmethod
    def _norm_repo(full_or_url: str) -> str:
        s = full_or_url.strip()
        if s.startswith("https://github.com/"):
            s = s[len("https://github.com/"):]
        if s.endswith(".git"):
            s = s[:-4]
        return s  # owner/repo

    # ------------ git-based merge path (safe & reliable) ------------

    def sync_with_git(self, fork_full: str, upstream_url: str, branch: str):
        """
        Clone the fork, add upstream, attempt FF merge; if not possible,
        create merge branch in fork and open PR within the fork.
        """
        # Workspace
        work = pathlib.Path("work")
        if work.exists():
            shutil.rmtree(work)
        work.mkdir(parents=True, exist_ok=True)

        repo_name = fork_full.split("/")[-1]
        repo_dir = work / repo_name

        # Clone fork with token
        fork_https = f"https://github.com/{fork_full}.git"
        fork_authed = inject_token(fork_https, self.token)
        log("INFO", f"Cloning {fork_full} …")
        run(f"git clone --no-tags --filter=blob:none {fork_authed} {repo_dir}")

        # Add upstream (no token; only fetch)
        run(f"git remote add upstream {upstream_url}", cwd=repo_dir)
        run("git remote -v", cwd=repo_dir)

        # Fetch
        run("git fetch origin --prune", cwd=repo_dir)
        run("git fetch upstream --prune", cwd=repo_dir)

        # Checkout default branch
        run(f"git checkout {branch}", cwd=repo_dir)

        # Try FF merge
        ff_ok = True
        try:
            run(f"git merge --ff-only upstream/{branch}", cwd=repo_dir, check=True)
            log("INFO", f"Fast-forward succeeded for {fork_full}:{branch}.")
            run(f"git push origin {branch}", cwd=repo_dir)
            return "ff"
        except Exception:
            ff_ok = False
            log("INFO", f"Not fast-forward for {fork_full}:{branch}; preparing merge branch.")

        # Create a sync branch
        today = datetime.datetime.utcnow().strftime("%Y%m%d")
        sync_branch = f"sync/upstream-{today}"
        run("git merge --abort || true", cwd=repo_dir, check=False)
        run(f"git checkout -B {sync_branch}", cwd=repo_dir)

        # Attempt merge commit
        run(f"git merge --no-edit upstream/{branch}", cwd=repo_dir, check=False)
        status = run("git status --porcelain", cwd=repo_dir, check=False)

        if any(s.startswith(("UU", "AA", "DD")) for s in status.splitlines()):
            log("WARN", "Conflicts detected; committing conflict markers for manual resolution.")
            run("git add -A", cwd=repo_dir, check=False)
            run('git commit -m "chore(sync): merge upstream with conflicts to resolve"', cwd=repo_dir, check=False)
        else:
            # If merge created a commit, good; if there was nothing to commit, that's fine too
            run("git add -A", cwd=repo_dir, check=False)
            run('git commit -m "chore(sync): merge upstream into fork" || true', cwd=repo_dir, check=False)

        # Push branch to fork
        run(f"git push -u origin {sync_branch}", cwd=repo_dir)

        # Open PR within the fork (head: sync branch, base: branch)
        fork_repo = self.gh.get_repo(fork_full)
        if not self._has_open_sync_pr(fork_repo, head_ref=sync_branch, base_ref=branch):
            pr = fork_repo.create_pull(
                title="Sync: merge upstream into fork",
                body=(
                    "Automated sync from upstream.\n\n"
                    f"- Base: `{branch}`\n"
                    f"- Head: `{sync_branch}`\n\n"
                    "If conflicts exist, please resolve them in this PR."
                ),
                base=branch,
                head=sync_branch,
            )
            self.created_prs.append(f"{fork_full}#{pr.number}")
            log("INFO", f"Opened PR: {pr.html_url}")
        else:
            log("INFO", f"Sync PR already open for {fork_full} ({sync_branch} → {branch}).")

        return "pr"

    @staticmethod
    def _has_open_sync_pr(repo, head_ref: str, base_ref: str) -> bool:
        for pr in repo.get_pulls(state="open", base=base_ref):
            if pr.head and pr.head.ref == head_ref:
                return True
        return False

    # ------------------------- main loop -------------------------

    def run(self):
        print(f"\n🚀 Starting sync run at {datetime.datetime.utcnow()} UTC\n")
        for fork_name, meta in self.repositories.items():
            try:
                if not isinstance(meta, dict):
                    raise ValueError("Invalid config entry (expected object).")

                if meta.get("disabled"):
                    self.skipped.append(fork_name)
                    log("INFO", f"⏭ Skipping {fork_name} (disabled)")
                    continue

                fork_full = f"{self.owner}/{fork_name}" if "/" not in fork_name else fork_name
                upstream_full = meta.get("upstream")
                if not upstream_full:
                    raise ValueError("Missing 'upstream' in config for " + fork_name)

                # Determine branch (prefer explicit; fall back to fork default; finally 'main')
                fork_repo = self.gh.get_repo(self._norm_repo(fork_full))
                upstream_repo = self.gh.get_repo(self._norm_repo(upstream_full))
                target_branch = (meta.get("branch") or fork_repo.default_branch or upstream_repo.default_branch or "main").strip()

                log("INFO", f"🔍 {fork_full} <= {upstream_full} [{target_branch}]")

                result = self.sync_with_git(
                    fork_full=self._norm_repo(fork_full),
                    upstream_url=f"https://github.com/{self._norm_repo(upstream_full)}.git",
                    branch=target_branch,
                )

                if result == "ff":
                    self.up_to_date.append(f"{fork_full}:{target_branch}")

            except Exception as e:
                msg = f"{type(e).__name__}: {e}"
                self.errors.append((fork_name, msg))
                log("ERROR", f"❌ {fork_name}: {msg}")

        self._print_summary()

    # ------------------------- summary -------------------------

    def _print_summary(self):
        print("\n" + "=" * 72)
        print("📊 Sync Summary")
        print("=" * 72)

        def bullet(items: List[str]) -> str:
            return "  (none)" if not items else "".join(f"\n  • {it}" for it in items)

        print(f"\n✅ PRs created:        {len(self.created_prs)}" + bullet(self.created_prs))
        print(f"\n✔ Fast-forward OK:    {len(self.up_to_date)}" + bullet(self.up_to_date))
        print(f"\n⏭ Skipped (disabled): {len(self.skipped)}" + bullet(self.skipped))
        print(f"\n❌ Errors:             {len(self.errors)}" + (
            "".join(f"\n  • {name} — {err}" for name, err in self.errors) if self.errors else "  (none)"
        ))
        print("\n" + "=" * 72 + "\n")


if __name__ == "__main__":
    try:
        ForkSyncBot().run()
    except Exception as e:
        print(f"💥 Bot failed: {e}")
        sys.exit(1)

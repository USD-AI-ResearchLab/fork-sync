#!/usr/bin/env python3
"""
Central org-wide fork sync bot (v2)
Fixes:
- Uses token for BOTH fork and upstream fetches (required for private upstreams)
- Redacts tokens from error logs
- Detects default branches for fork & upstream
- Optional PR fallback when push to protected branch is blocked

Env:
  ORG_NAME         (default: "USD-AI-ResearchLab")
  FORK_SYNC_TOKEN  (classic PAT with "repo" + "read:org"; SSO-enabled if required)
  FALLBACK_TO_PR   ("true"/"false"; default "true" recommended)
"""
import os
import subprocess
import tempfile
import shutil
from datetime import datetime, timezone

from github import Github, Auth, GithubException

ORG_NAME = os.getenv("ORG_NAME", "USD-AI-ResearchLab")
FALLBACK_TO_PR = os.getenv("FALLBACK_TO_PR", "true").lower() in ("1", "true", "yes")
TOKEN = os.getenv("FORK_SYNC_TOKEN") or os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")

def _mask(s: str) -> str:
    if not s:
        return s
    if TOKEN and TOKEN in s:
        s = s.replace(TOKEN, "***")
    return s

def run(cmd, cwd=None):
    try:
        return subprocess.run(cmd, cwd=cwd, check=True, text=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        joined = " ".join(cmd)
        raise RuntimeError(f"Command failed: {_mask(joined)}\nSTDOUT:\n{_mask(e.stdout or '')}\nSTDERR:\n{_mask(e.stderr or '')}") from e

def ensure_git_identity(cwd=None):
    run(["git", "config", "user.email", "github-actions[bot]@users.noreply.github.com"], cwd=cwd)
    run(["git", "config", "user.name", "github-actions[bot]"], cwd=cwd)

def open_sync_pr(repo_obj, branch_name, base_branch, upstream_full, upstream_branch):
    title = f"Sync with upstream:{upstream_branch} ({upstream_full})"
    body = (
        f"Automated sync from upstream `{upstream_full}@{upstream_branch}`.\n\n"
        f"- Base (fork): `{repo_obj.full_name}@{base_branch}`\n"
        f"- Head (temp): `{branch_name}`\n\n"
        f"This PR was created because a direct push to the protected base branch failed."
    )
    try:
        pr = repo_obj.create_pull(title=title, body=body, base=base_branch, head=branch_name)
        print(f"🔁 Opened PR #{pr.number} in {repo_obj.full_name}: {pr.html_url}")
    except GithubException as ge:
        print(f"⚠️ Failed to open PR in {repo_obj.full_name}: {ge.data}")

def sync_one_repo(g, repo_obj):
    if not repo_obj.fork or repo_obj.parent is None:
        return

    upstream_obj = repo_obj.parent
    fork_full = repo_obj.full_name
    upstream_full = f"{upstream_obj.owner.login}/{upstream_obj.name}"

    fork_branch = (repo_obj.default_branch or "main").strip()
    upstream_branch = (upstream_obj.default_branch or "main").strip()

    if not TOKEN:
        raise RuntimeError("Missing token: set FORK_SYNC_TOKEN (classic PAT with 'repo' + 'read:org').")

    # Use token for both remotes (fork + upstream). This enables private upstream fetches.
    fork_url = f"https://x-access-token:{TOKEN}@github.com/{fork_full}.git"
    upstream_url = f"https://x-access-token:{TOKEN}@github.com/{upstream_full}.git"

    work = tempfile.mkdtemp(prefix="fork-sync-")
    try:
        print(f"🔄 Cloning {fork_full} (default branch: {fork_branch}) ...")
        run(["git", "clone", "--filter=blob:none", "--depth", "50", fork_url, work])

        ensure_git_identity(work)

        # Add upstream with tokenized URL (handles private upstream)
        run(["git", "remote", "add", "upstream", upstream_url], cwd=work)
        run(["git", "fetch", "upstream", upstream_branch], cwd=work)

        run(["git", "checkout", fork_branch], cwd=work)

        # Fast-forward if possible, else merge
        try:
            run(["git", "merge", "--ff-only", f"upstream/{upstream_branch}"], cwd=work)
        except Exception:
            print("ℹ️ Fast-forward not possible; performing a regular merge")
            run(["git", "merge", f"upstream/{upstream_branch}", "--no-edit"], cwd=work)

        # Push or open PR if protected
        try:
            run(["git", "push", "origin", fork_branch], cwd=work)
            print(f"✅ Synced {fork_full} with {upstream_full} ({upstream_branch} → {fork_branch})")
        except Exception as push_err:
            print(f"🚫 Direct push blocked for {fork_full}@{fork_branch}: {_mask(str(push_err))}")
            if not FALLBACK_TO_PR:
                raise

            ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            tmp_branch = f"fork-sync/{ts}"
            run(["git", "switch", "-c", tmp_branch], cwd=work)
            run(["git", "push", "origin", tmp_branch], cwd=work)
            open_sync_pr(repo_obj, tmp_branch, fork_branch, upstream_full, upstream_branch)

    finally:
        shutil.rmtree(work, ignore_errors=True)

def main():
    if not TOKEN:
        raise RuntimeError("Missing FORK_SYNC_TOKEN / GH_TOKEN / GITHUB_TOKEN")

    g = Github(auth=Auth.Token(TOKEN))
    org = g.get_organization(ORG_NAME)
    all_repos = list(org.get_repos())
    forks = [r for r in all_repos if r.fork and r.parent is not None]

    print(f"🔎 Found {len(forks)} forked repos in {ORG_NAME} (out of {len(all_repos)} total)")

    for r in forks:
        try:
            sync_one_repo(g, r)
        except Exception as e:
            print(f"❌ Error syncing {r.full_name}: {_mask(str(e))}")

if __name__ == "__main__":
    main()

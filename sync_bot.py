#!/usr/bin/env python3
"""
Central org-wide fork sync bot.
- Enumerates all forked repos in ORG_NAME via the GitHub API (PyGithub)
- Detects both fork + upstream default branches
- Merges upstream into the fork and pushes
- Optional fallback: if push to protected default branch is blocked, create a PR

Env vars:
  ORG_NAME            (default: "USD-AI-ResearchLab")
  FORK_SYNC_TOKEN     (recommended) classic PAT with "repo" + "read:org" scopes, SSO-enabled if required
  GH_TOKEN / GITHUB_TOKEN (fallback)  NOTE: In a central repo workflow, these tokens usually CANNOT push to other repos.
  FALLBACK_TO_PR      ("true" / "false"; default "false")

Required deps: PyGithub, PyYAML
"""
import os
import subprocess
import tempfile
import shutil
from datetime import datetime, timezone

from github import Github, Auth, GithubException

ORG_NAME = os.getenv("ORG_NAME", "USD-AI-ResearchLab")
FALLBACK_TO_PR = os.getenv("FALLBACK_TO_PR", "false").lower() in ("1", "true", "yes")

def run(cmd, cwd=None):
    """Run a command and stream errors on failure."""
    try:
        return subprocess.run(cmd, cwd=cwd, check=True, text=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        out = (e.stdout or "").strip()
        err = (e.stderr or "").strip()
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\nSTDOUT:\n{out}\nSTDERR:\n{err}") from e

def ensure_git_identity(cwd=None):
    # set per-repo identity to avoid global side effects
    run(["git", "config", "user.email", "github-actions[bot]@users.noreply.github.com"], cwd=cwd)
    run(["git", "config", "user.name", "github-actions[bot]"], cwd=cwd)

def open_sync_pr(g, repo_obj, branch_name, base_branch, upstream_full, upstream_branch):
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
        return  # only handle forks with a known parent

    upstream_obj = repo_obj.parent
    fork_full = repo_obj.full_name                    # ORG/Repo
    upstream_full = f"{upstream_obj.owner.login}/{upstream_obj.name}"

    fork_branch = (repo_obj.default_branch or "main").strip()
    upstream_branch = (upstream_obj.default_branch or "main").strip()

    token = os.getenv("FORK_SYNC_TOKEN") or os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
    if not token:
        raise RuntimeError(
            "No token available. Set FORK_SYNC_TOKEN with a classic PAT that has 'repo' + 'read:org' scopes. "
            "GITHUB_TOKEN is usually repo-scoped and cannot push to other repos from a central workflow."
        )

    fork_url = f"https://x-access-token:{token}@github.com/{fork_full}.git"
    upstream_url = f"https://github.com/{upstream_full}.git"

    work = tempfile.mkdtemp(prefix="fork-sync-")
    try:
        print(f"🔄 Cloning {fork_full} (default branch: {fork_branch}) ...")
        run(["git", "clone", "--filter=blob:none", "--depth", "50", fork_url, work])

        ensure_git_identity(work)

        run(["git", "remote", "add", "upstream", upstream_url], cwd=work)
        run(["git", "fetch", "upstream", upstream_branch], cwd=work)

        run(["git", "checkout", fork_branch], cwd=work)

        # Try fast-forward first
        ff_ok = True
        try:
            run(["git", "merge", "--ff-only", f"upstream/{upstream_branch}"], cwd=work)
        except Exception:
            ff_ok = False

        if not ff_ok:
            print("ℹ️ Fast-forward not possible; performing a regular merge")
            run(["git", "merge", f"upstream/{upstream_branch}", "--no-edit"], cwd=work)

        # Try to push to the default branch
        try:
            run(["git", "push", "origin", fork_branch], cwd=work)
            print(f"✅ Synced {fork_full} with {upstream_full} ({upstream_branch} → {fork_branch})")
        except Exception as push_err:
            print(f"🚫 Direct push blocked for {fork_full}@{fork_branch}: {push_err}")
            if not FALLBACK_TO_PR:
                raise

            # Create a temp branch and PR
            ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            tmp_branch = f"fork-sync/{ts}"
            run(["git", "switch", "-c", tmp_branch], cwd=work)
            run(["git", "push", "origin", tmp_branch], cwd=work)
            open_sync_pr(g, repo_obj, tmp_branch, fork_branch, upstream_full, upstream_branch)

    finally:
        shutil.rmtree(work, ignore_errors=True)

def main():
    token = os.getenv("FORK_SYNC_TOKEN") or os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
    if not token:
        raise RuntimeError(
            "Missing token. Set FORK_SYNC_TOKEN as an org or repo secret (classic PAT with 'repo' + 'read:org').\n"
            "Note: The default GITHUB_TOKEN of this workflow is scoped to the central repo only and will usually fail with 403 when pushing to other repos."
        )

    g = Github(auth=Auth.Token(token))
    org = g.get_organization(ORG_NAME)
    repos = list(org.get_repos())  # materialize for stable iteration/count

    forks = [r for r in repos if r.fork and r.parent is not None]
    print(f"🔎 Found {len(forks)} forked repos in {ORG_NAME} (out of {len(repos)} total)")

    for r in forks:
        try:
            sync_one_repo(g, r)
        except Exception as e:
            print(f"❌ Error syncing {r.full_name}: {e}")

if __name__ == "__main__":
    main()

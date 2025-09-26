#!/usr/bin/env python3
"""
Centralized Fork Sync Bot
Keeps all forks in USD-AI-ResearchLab in sync with their upstream/original repositories.

config.json shape:
{
  "repositories": {
    "<fork_name>": { "upstream": "<owner/repo | https://github.com/owner/repo(.git)>", "branch": "main|master" },
    ...
  }
}
"""

import os
import sys
import json
import traceback
from datetime import datetime
from typing import Dict, Any, Tuple

import github
from github import Github
from github.Auth import Token


def parse_upstream_fullname(upstream: str) -> str:
    """
    Accepts:
      - "owner/repo"
      - "https://github.com/owner/repo"
      - "https://github.com/owner/repo.git"
    Returns "owner/repo"
    """
    u = upstream.strip()
    if u.startswith("https://github.com/"):
        u = u[len("https://github.com/"):]
    if u.endswith(".git"):
        u = u[:-4]
    if u.count("/") != 1:
        raise ValueError(f"Invalid upstream format: {upstream}")
    return u


class ForkSyncBot:
    def __init__(self) -> None:
        # GitHub authentication
        self.github_token = os.getenv("GITHUB_TOKEN", "").strip()
        self.github_owner = os.getenv("GITHUB_OWNER", "USD-AI-ResearchLab").strip()

        if not self.github_token:
            print("ERROR: GITHUB_TOKEN environment variable is required", file=sys.stderr)
            sys.exit(1)

        # Modern auth (removes deprecation warning)
        self.g = Github(auth=Token(self.github_token))

        try:
            self.org = self.g.get_organization(self.github_owner)
        except github.GithubException as ge:
            print(
                f"ERROR: Cannot access organization '{self.github_owner}'. "
                f"HTTP {ge.status}: {getattr(ge, 'data', None)}",
                file=sys.stderr,
            )
            sys.exit(1)

        # Load repository mapping from config.json
        try:
            with open("config.json", "r", encoding="utf-8") as f:
                config = json.load(f)
        except FileNotFoundError:
            print("ERROR: config.json not found in repository root.", file=sys.stderr)
            sys.exit(1)

        repos = config.get("repositories", {})
        if not isinstance(repos, dict) or not repos:
            print("ERROR: config.json has no 'repositories' object with entries.", file=sys.stderr)
            sys.exit(1)

        self.repositories: Dict[str, Dict[str, Any]] = repos

        print(f" Fork Sync Bot initialized for org: {self.github_owner}")
        print(f" Monitoring {len(self.repositories)} repositories\n")

    def resolve_repo_and_branches(
        self, fork_name: str, upstream_url: str, branch_hint: str | None
    ) -> Tuple[Any, Any, str, str]:
        """
        Returns: (fork_repo, upstream_repo, fork_base_branch, upstream_head_branch)
        - fork_base_branch is the fork's default or branch_hint if present
        - upstream_head_branch is upstream's default or branch_hint if present
        """
        # Fork inside the org
        try:
            fork_repo = self.org.get_repo(fork_name)
        except github.GithubException as ge:
            raise RuntimeError(
                f"Fork '{self.github_owner}/{fork_name}' not found or inaccessible. "
                f"Create/rename the fork or grant PAT access."
            ) from ge

        upstream_fullname = parse_upstream_fullname(upstream_url)
        try:
            upstream_repo = self.g.get_repo(upstream_fullname)
        except github.GithubException as ge:
            raise RuntimeError(f"Upstream '{upstream_fullname}' not found or inaccessible.") from ge

        # Determine branches
        fork_default = fork_repo.default_branch or "main"
        upstream_default = upstream_repo.default_branch or "main"

        fork_base = (branch_hint or fork_default).strip()
        upstream_head = (branch_hint or upstream_default).strip()

        return fork_repo, upstream_repo, fork_base, upstream_head

    def ensure_pr(self, fork_repo, fork_base: str, upstream_repo, upstream_head: str) -> int:
        """
        Compare fork base vs upstream head; if upstream has commits the fork lacks, create/update PR.
        Returns 1 if PR created/updated, 0 otherwise.
        """
        up_owner = upstream_repo.owner.login
        up_head_ref = f"{up_owner}:{upstream_head}"

        # Compare must be in the fork repo context: base=fork branch, head=upstream_owner:branch
        try:
            comparison = fork_repo.compare(fork_base, up_head_ref)
        except github.GithubException as ge:
            raise RuntimeError(
                f"Compare failed (base {fork_repo.full_name}:{fork_base}, head {up_head_ref}). "
                f"Repo histories may be unrelated or visibility blocked. "
                f"HTTP {ge.status}: {getattr(ge, 'data', None)}"
            ) from ge

        # Correct interpretation:
        #  - comparison.ahead_by == commits HEAD (upstream) has that BASE (fork) does not
        #  - comparison.behind_by == commits BASE (fork) has that HEAD (upstream) does not
        ahead_by = comparison.ahead_by
        behind_by = comparison.behind_by
        print(
            f" Compare: upstream(head) ahead_by={ahead_by}, fork(base) ahead_by={behind_by} "
            f"for {fork_repo.full_name}:{fork_base} vs {up_head_ref}"
        )

        if ahead_by <= 0:
            print(f" OK: {fork_repo.full_name} is up to date with {upstream_repo.full_name}@{upstream_head}")
            return 0

        print(
            f" {fork_repo.name} is BEHIND upstream by {ahead_by} commits "
            f"(fork-only commits: {behind_by}). Creating/updating PR…"
        )

        title = f"Sync: {upstream_repo.full_name}@{upstream_head} → {fork_repo.full_name}@{fork_base}"
        body = (
            f"Automated sync to update fork `{fork_repo.full_name}` with upstream "
            f"`{upstream_repo.full_name}`.\n\n"
            f"- Commits upstream has that fork lacks: {ahead_by}\n"
            f"- Commits fork has that upstream lacks: {behind_by}\n\n"
            f"Created by Fork Sync Bot"
        )

        # Try to find an existing PR from the same source (best-effort)
        open_prs = fork_repo.get_pulls(state="open", base=fork_base)
        for pr in open_prs:
            try:
                if pr.head and pr.head.repo and pr.head.repo.full_name == upstream_repo.full_name and pr.head.ref == upstream_head:
                    pr.edit(title=title, body=body)
                    print(f" PR exists: #{pr.number} — updated")
                    return 1
            except Exception:
                pass  # don’t fail just because a PR lacks some fields

        # Create PR with head from upstream owner:branch to fork base
        try:
            pr = fork_repo.create_pull(title=title, body=body, base=fork_base, head=up_head_ref)
            print(f" PR created: #{pr.number}")
            return 1
        except github.GithubException as ge:
            # 422 happens if no commits between the two — which we now avoid via ahead_by>0.
            raise RuntimeError(
                f"Failed to create PR into {fork_repo.full_name}:{fork_base} "
                f"from {up_head_ref} — HTTP {ge.status}: {getattr(ge, 'data', None)}"
            ) from ge

    def sync_repository(self, fork_name: str, meta: Dict[str, Any]) -> int:
        """
        Sync one forked repository with its upstream.
        Returns 1 if a PR was created/updated, else 0.
        """
        upstream = meta.get("upstream", "")
        branch_hint = meta.get("branch")  # may be "main" or "master" or None

        if not upstream:
            print(f" WARN: {fork_name} has no 'upstream' specified in config. Skipping.")
            return 0

        print(f"\n🔍 Checking {fork_name} | upstream={upstream} | branch_hint={branch_hint or '(auto)'}")
        try:
            fork_repo, upstream_repo, fork_base, upstream_head = self.resolve_repo_and_branches(
                fork_name, upstream, branch_hint
            )
            return self.ensure_pr(fork_repo, fork_base, upstream_repo, upstream_head)
        except github.GithubException as ge:
            print(f" ERROR syncing {fork_name}: GitHubError {ge.status}: {getattr(ge, 'data', None)}")
            traceback.print_exc()
            return 0
        except Exception as e:
            print(f" ERROR syncing {fork_name}: {type(e).__name__}: {e}")
            traceback.print_exc()
            return 0

    def run(self) -> None:
        print(f"\n Starting sync run at {datetime.utcnow()} UTC")
        total_prs = 0
        for fork_name, meta in self.repositories.items():
            if not isinstance(meta, dict):
                print(f" WARN: Invalid config for '{fork_name}' (expected object with 'upstream', 'branch'). Skipping.")
                continue
            total_prs += self.sync_repository(fork_name, meta)
        print(f"\n Sync run complete! {total_prs} PRs created/updated.")


if __name__ == "__main__":
    try:
        ForkSyncBot().run()
    except Exception as e:
        print(f" Bot failed: {e}")
        traceback.print_exc()
        sys.exit(1)

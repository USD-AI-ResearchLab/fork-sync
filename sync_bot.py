#!/usr/bin/env python3
"""
Centralized Fork Sync Bot
Keeps all forks in USD-AI-ResearchLab in sync with their upstream/original repositories.

config.json shape:
{
  "repositories": {
    "<fork_name>": {
      "upstream": "https://github.com/<owner>/<repo>.git",
      "branch": "main|master",
      "disabled": true|false   # optional
    },
    ...
  }
}
"""

import os
import sys
import json
from datetime import datetime
from typing import Optional, Tuple, Dict, Any, List

import github
from github import Github
from github.Auth import Token


class ForkSyncBot:
    def __init__(self):
        # GitHub authentication
        self.github_token = os.getenv("GITHUB_TOKEN", "").strip()
        self.github_owner = os.getenv("GITHUB_OWNER", "USD-AI-ResearchLab").strip()

        if not self.github_token:
            raise ValueError("GITHUB_TOKEN environment variable is required")

        # Modern auth (no deprecation warning)
        self.g = Github(auth=Token(self.github_token))
        self.org = self.g.get_organization(self.github_owner)

        # Load repository mapping from config.json
        with open("config.json", "r", encoding="utf-8") as f:
            config = json.load(f)
        self.repositories: Dict[str, Dict[str, Any]] = config.get("repositories", {})

        # Buckets for summary
        self.summary_created: List[str] = []
        self.summary_up_to_date: List[str] = []
        self.summary_skipped: List[str] = []
        self.summary_errors: List[Tuple[str, str]] = []

        print(f"✅ Fork Sync Bot initialized for org: {self.github_owner}")
        print(f"📂 Monitoring {len(self.repositories)} repositories")

    @staticmethod
    def _norm_repo(full_or_url: str) -> str:
        """
        Turn https URLs into 'owner/repo' for PyGithub, otherwise return unchanged if already 'owner/repo'.
        """
        s = full_or_url.strip()
        if s.startswith("https://github.com/"):
            s = s[len("https://github.com/"):]
        if s.endswith(".git"):
            s = s[:-4]
        return s

    def ensure_pr(self, fork_repo, fork_branch: str, upstream_repo, upstream_branch: str) -> Optional[int]:
        """
        Compare upstream HEAD vs fork BASE; if upstream has commits the fork lacks, create PR.
        Returns PR number if created, None otherwise.
        """
        # For compare(base...head) we must call it on the *upstream* repo to reference 'owner:branch' for the fork head
        # Here we instead compare in upstream context using the cross-repo ref for the fork:
        #   base   = <fork_owner>:<fork_branch>
        #   head   = <upstream_branch> (implicitly upstream owner since we call on upstream_repo)
        #
        # But upstream.compare(base, head) only accepts branches within the same repo or owner:branch refs for forks.
        # The most reliable cross-org pattern is:
        #   comparison = upstream_repo.compare(upstream_branch, f"{self.github_owner}:{fork_branch}")
        # where ahead_by means "upstream has N commits not in fork".
        comparison = upstream_repo.compare(upstream_branch, f"{self.github_owner}:{fork_branch}")

        # Correct interpretation: ahead_by == commits HEAD (upstream) has that BASE (fork) does not.
        if comparison.ahead_by <= 0:
            print(f"✔ {fork_repo.full_name} is up to date with {upstream_repo.full_name}@{upstream_branch}")
            self.summary_up_to_date.append(f"{fork_repo.full_name}:{fork_branch}")
            return None

        print(
            f"↗ {fork_repo.name} is BEHIND upstream by {comparison.ahead_by} commits; "
            f"opening PR from {upstream_repo.owner.login}:{upstream_branch} → {fork_branch}"
        )

        pr_title = f"Sync: {upstream_repo.full_name}@{upstream_branch} → {fork_repo.full_name}@{fork_branch}"
        pr_body = (
            f"Automated sync to update fork `{fork_repo.full_name}` with upstream `{upstream_repo.full_name}`.\n\n"
            f"- Commits upstream has that fork lacks: {comparison.ahead_by}\n"
            f"- Files changed (approx): {len(comparison.files)}\n\n"
            "🤖 Created by Fork Sync Bot"
        )

        # Avoid duplicates: look for an open PR from the same source
        for pr in fork_repo.get_pulls(state="open", base=fork_branch):
            try:
                if pr.head and pr.head.repo and pr.head.repo.full_name == upstream_repo.full_name and pr.head.ref == upstream_branch:
                    pr.edit(title=pr_title, body=pr_body)
                    print(f"🔁 PR already open — updated #{pr.number}")
                    self.summary_created.append(f"{fork_repo.full_name}#{pr.number}")
                    return pr.number
            except Exception:
                # non-fatal
                pass

        try:
            pr = fork_repo.create_pull(
                title=pr_title,
                body=pr_body,
                base=fork_branch,
                head=f"{upstream_repo.owner.login}:{upstream_branch}",
            )
            print(f"✅ Created PR #{pr.number} in {fork_repo.full_name}")
            self.summary_created.append(f"{fork_repo.full_name}#{pr.number}")
            return pr.number
        except github.GithubException as ge:
            # If there truly are no commits, GitHub returns 422; our ahead_by guard should prevent this, but be safe.
            if ge.status == 422 and "No commits between" in str(getattr(ge, "data", "")):
                print(f"✔ No changes to sync for {fork_repo.full_name}")
                self.summary_up_to_date.append(f"{fork_repo.full_name}:{fork_branch}")
                return None
            raise

    def sync_repository(self, fork_name: str, meta: Dict[str, Any]) -> None:
        """
        Sync one forked repository with its upstream.
        """
        if meta.get("disabled"):
            print(f"⏭ Skipping {fork_name} (disabled in config)")
            self.summary_skipped.append(fork_name)
            return

        try:
            fork_repo = self.org.get_repo(fork_name)
            upstream_full = self._norm_repo(meta["upstream"])
            upstream_repo = self.g.get_repo(upstream_full)

            # Prefer explicit branch from config; otherwise use each repo's default branch
            fork_branch = (meta.get("branch") or fork_repo.default_branch or "main").strip()
            upstream_branch = (meta.get("branch") or upstream_repo.default_branch or "main").strip()

            print(f"\n🔍 Checking {fork_repo.full_name} (fork) vs {upstream_repo.full_name} (upstream)")
            self.ensure_pr(fork_repo, fork_branch, upstream_repo, upstream_branch)

        except Exception as e:
            msg = f"{type(e).__name__}: {e}"
            print(f"❌ Error syncing {fork_name}: {msg}")
            self.summary_errors.append((fork_name, msg))

    def print_summary(self):
        print("\n" + "=" * 72)
        print("📊 Sync Summary")
        print("=" * 72)

        def bullet(items: List[str]) -> str:
            if not items:
                return "  (none)"
            return "".join(f"\n  • {it}" for it in items)

        print(f"\n✅ PRs created/updated: {len(self.summary_created)}" + bullet(self.summary_created))
        print(f"\n✔ Up-to-date:          {len(self.summary_up_to_date)}" + bullet(self.summary_up_to_date))
        print(f"\n⏭ Skipped (disabled):  {len(self.summary_skipped)}" + bullet(self.summary_skipped))
        print(f"\n❌ Errors:              {len(self.summary_errors)}" + (
            "".join(f"\n  • {name} — {err}" for name, err in self.summary_errors) if self.summary_errors else "  (none)"
        ))
        print("\n" + "=" * 72 + "\n")

    def run(self):
        print(f"\n🚀 Starting sync run at {datetime.utcnow()} UTC")
        for fork_name, meta in self.repositories.items():
            if not isinstance(meta, dict):
                msg = "Invalid config entry (expected object)."
                print(f"❌ {fork_name}: {msg}")
                self.summary_errors.append((fork_name, msg))
                continue
            self.sync_repository(fork_name, meta)

        self.print_summary()


if __name__ == "__main__":
    try:
        ForkSyncBot().run()
    except Exception as e:
        print(f"💥 Bot failed: {e}")
        sys.exit(1)

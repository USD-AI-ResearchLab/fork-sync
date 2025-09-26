#!/usr/bin/env python3
"""
Centralized Fork Sync Bot
Keeps all forks in USD-AI-ResearchLab in sync with their upstream/original repositories
"""

import os
import json
from datetime import datetime
from github import Github

class ForkSyncBot:
    def __init__(self):
        # GitHub authentication
        self.github_token = os.getenv("GITHUB_TOKEN")
        self.github_owner = os.getenv("GITHUB_OWNER", "USD-AI-ResearchLab")

        if not self.github_token:
            raise ValueError(" GITHUB_TOKEN environment variable is required")

        self.g = Github(self.github_token)
        self.org = self.g.get_organization(self.github_owner)

        # Load repository mapping from config.json
        with open("config.json", "r") as f:
            config = json.load(f)
        self.repositories = config.get("repositories", {})

        print(f" Fork Sync Bot initialized for org: {self.github_owner}")
        print(f" Monitoring {len(self.repositories)} repositories")

    def sync_repository(self, fork_name, upstream_fullname):
        """
        Sync one forked repository with its upstream
        """
        try:
            fork_repo = self.org.get_repo(fork_name)
            upstream_repo = self.g.get_repo(upstream_fullname)

            fork_branch = fork_repo.default_branch
            upstream_branch = upstream_repo.default_branch

            print(f"\n🔍 Checking {fork_name} (fork) against {upstream_fullname} (upstream)")

            # Compare branches
            comparison = upstream_repo.compare(upstream_branch, f"{self.github_owner}:{fork_branch}")

            if comparison.ahead_by > 0:
                print(f" {fork_name} is BEHIND upstream by {comparison.ahead_by} commits")

                # Create PR from upstream -> fork
                pr_title = f" Sync from upstream {upstream_fullname}"
                pr_body = (
                    f"Automated sync to update fork `{fork_name}` with upstream `{upstream_fullname}`.\n\n"
                    f"- Commits behind: {comparison.ahead_by}\n"
                    f"- Files changed: {len(comparison.files)}\n\n"
                    " Created by Fork Sync Bot"
                )

                # Check if PR already exists
                open_prs = fork_repo.get_pulls(state="open", base=fork_branch)
                for pr in open_prs:
                    if pr.title.startswith("🔄 Sync from upstream"):
                        print(f"  PR already exists for {fork_name}, skipping")
                        return None

                pr = fork_repo.create_pull(
                    title=pr_title,
                    body=pr_body,
                    head=f"{upstream_repo.owner.login}:{upstream_branch}",
                    base=fork_branch
                )
                print(f" Created PR #{pr.number} in {fork_name}")
                return pr
            else:
                print(f" {fork_name} is up to date with {upstream_fullname}")

        except Exception as e:
            print(f" Error syncing {fork_name}: {e}")
            return None

    def run(self):
        """
        Run sync check for all repositories in config.json
        """
        print(f"\n Starting sync run at {datetime.utcnow()} UTC")
        total_prs = 0

        for fork_name, upstream_fullname in self.repositories.items():
            pr = self.sync_repository(fork_name, upstream_fullname)
            if pr:
                total_prs += 1

        print(f"\n Sync run complete! {total_prs} PRs created/updated.")


if __name__ == "__main__":
    try:
        bot = ForkSyncBot()
        bot.run()
    except Exception as e:
        print(f" Bot failed: {e}")
        exit(1)

#!/usr/bin/env python3
"""
Centralized Fork Sync Bot (Configurable)
Loads settings from config.json
Checks forks for changes and creates PRs into the monitored repos
"""

import os
import json
from datetime import datetime
from github import Github

class ForkSyncBot:
    def __init__(self, config_path="config.json"):
        # Load config
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"❌ Config file not found: {config_path}")
        
        with open(config_path, "r") as f:
            self.config = json.load(f)

        # Environment variables
        self.github_token = os.getenv('GITHUB_TOKEN')
        self.github_owner = os.getenv('GITHUB_OWNER', 'USD-AI-ResearchLab')

        if not self.github_token:
            raise ValueError("❌ GITHUB_TOKEN environment variable is required")

        # Initialize GitHub connection
        self.g = Github(self.github_token)

        # Load repo list from config.json
        self.monitored_repos = self.config.get("monitored_repositories", [])
        self.trusted_users = self.config.get("auto_merge_trusted_users", [])
        self.notifications = self.config.get("notifications", {})

        print(f"🤖 Fork Sync Bot initialized for {self.github_owner}")
        print(f"📊 Monitoring {len(self.monitored_repos)} repositories")

    def get_repository_and_forks(self, repo_name):
        """Get original repository and all its forks"""
        try:
            repo = self.g.get_repo(f"{self.github_owner}/{repo_name}")
            forks = list(repo.get_forks())
            print(f"📂 {repo_name} → {len(forks)} forks found")
            return repo, forks
        except Exception as e:
            print(f"❌ Error accessing repository {repo_name}: {e}")
            return None, []

    def check_for_new_commits(self, original_repo, fork):
        """Check if fork has commits not in original repo"""
        try:
            original_branch = original_repo.default_branch
            fork_branch = fork.default_branch

            print(f"🔍 Comparing {fork.full_name}:{fork_branch} → {original_repo.full_name}:{original_branch}")

            original_commit = original_repo.get_branch(original_branch).commit
            fork_commit = fork.get_branch(fork_branch).commit

            if fork_commit.commit.author.date > original_commit.commit.author.date:
                comparison = self.g.get_repo(fork.full_name).compare(
                    f"{original_repo.owner.login}:{original_branch}", fork_branch
                )
                if comparison.total_commits > 0:
                    print(f"✨ {comparison.total_commits} new commits in {fork.full_name}")
                    return True, comparison
            return False, None
        except Exception as e:
            print(f"⚠️ Error comparing {fork.full_name}: {e}")
            return False, None

    def create_pull_request(self, original_repo, fork, comparison):
        """Create a pull request to sync fork changes into original repo"""
        try:
            pr_title = f"🔄 Sync from {fork.full_name}"
            pr_body = f"""## 🔄 Automated Fork Sync

**Source**: [{fork.full_name}]({fork.html_url})
**New Commits**: {comparison.total_commits}
**Files Changed**: {len(comparison.files)}

### 📝 Recent Commits:
"""
            for commit in comparison.commits[:5]:
                msg = commit.commit.message.splitlines()[0]
                author = commit.author.login if commit.author else "unknown"
                pr_body += f"- `{commit.sha[:7]}` {msg} (@{author})\n"

            if comparison.total_commits > 5:
                pr_body += f"- ... and {comparison.total_commits - 5} more commits\n"

            existing_prs = list(original_repo.get_pulls(
                state="open", head=f"{fork.owner.login}:{fork.default_branch}"
            ))
            if existing_prs:
                print(f"⚠️ PR already exists for {fork.full_name}")
                return None

            pr = original_repo.create_pull(
                title=pr_title,
                body=pr_body,
                head=f"{fork.owner.login}:{fork.default_branch}",
                base=original_repo.default_branch
            )
            print(f"✅ Created PR #{pr.number}: {pr.title}")
            return pr
        except Exception as e:
            print(f"❌ Error creating PR for {fork.full_name}: {e}")
            return None

    def run_sync_check(self):
        print(f"\n🚀 Starting sync check at {datetime.now()}")
        total_prs = 0
        total_forks = 0

        for repo_name in self.monitored_repos:
            original_repo, forks = self.get_repository_and_forks(repo_name)
            if not original_repo:
                continue

            for fork in forks:
                total_forks += 1
                has_changes, comparison = self.check_for_new_commits(original_repo, fork)
                if has_changes:
                    pr = self.create_pull_request(original_repo, fork, comparison)
                    if pr:
                        total_prs += 1

        # Save summary
        summary = {
            "date": str(datetime.now()),
            "repos_monitored": len(self.monitored_repos),
            "forks_checked": total_forks,
            "prs_created": total_prs,
        }
        with open("sync_summary.json", "w") as f:
            json.dump(summary, f, indent=2)

        print("\n🎉 Sync check complete")
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    try:
        bot = ForkSyncBot("config.json")
        bot.run_sync_check()
        print("✅ Bot finished successfully")
    except Exception as e:
        print(f"💥 Bot failed: {e}")
        import traceback
        traceback.print_exc()
        exit(1)

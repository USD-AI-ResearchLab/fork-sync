#!/usr/bin/env python3
"""
Centralized Fork Sync Bot
Automatically checks forks for changes and creates PRs
"""

import os
import json
from datetime import datetime, timedelta
from github import Github
import requests

class ForkSyncBot:
    def __init__(self):
        self.github_token = os.getenv('GITHUB_TOKEN')
        self.github_owner = os.getenv('GITHUB_OWNER', 'USD-AI-ResearchLab')
        
        if not self.github_token:
            raise ValueError("GITHUB_TOKEN environment variable is required")
            
        self.g = Github(self.github_token)
        self.org = self.g.get_organization(self.github_owner)
        
        # Repositories to monitor (you'll customize this list)
        self.monitored_repos = [
            # Add your repository names here
            # Example: 'awesome-ai-project',
            # Example: 'research-tools',
        ]
        
        print(f"🤖 Fork Sync Bot initialized for {self.github_owner}")
    
    def get_all_forks(self, repo_name):
        """Get all forks of a repository"""
        try:
            repo = self.org.get_repo(repo_name)
            forks = list(repo.get_forks())
            print(f"📊 Found {len(forks)} forks for {repo_name}")
            return repo, forks
        except Exception as e:
            print(f"❌ Error getting forks for {repo_name}: {e}")
            return None, []
    
    def check_fork_for_changes(self, original_repo, fork):
        """Check if fork has commits ahead of original"""
        try:
            # Compare the default branches
            original_branch = original_repo.default_branch
            fork_branch = fork.default_branch
            
            # Get latest commit dates
            original_commit = original_repo.get_branch(original_branch).commit
            fork_commit = fork.get_branch(fork_branch).commit
            
            # Check if fork has newer commits
            original_date = original_commit.commit.author.date
            fork_date = fork_commit.commit.author.date
            
            if fork_date > original_date:
                # Get the comparison to see actual differences
                comparison = self.g.get_repo(fork.full_name).compare(
                    f"{original_repo.owner.login}:{original_branch}",
                    fork_branch
                )
                
                if comparison.total_commits > 0:
                    print(f"🔍 {fork.full_name} has {comparison.total_commits} new commits")
                    return True, comparison
            
            return False, None
            
        except Exception as e:
            print(f"⚠️  Error checking {fork.full_name}: {e}")
            return False, None
    
    def create_sync_pr(self, original_repo, fork, comparison):
        """Create a pull request to sync changes"""
        try:
            # Create a unique branch name
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            branch_name = f"sync-from-{fork.owner.login}-{timestamp}"
            
            # Prepare PR details
            pr_title = f"🔄 Sync changes from {fork.full_name}"
            pr_body = f"""## Automated Fork Sync

**Source Fork**: [{fork.full_name}]({fork.html_url})
**Fork Owner**: @{fork.owner.login}
**Commits**: {comparison.total_commits}
**Files Changed**: {len(comparison.files)}

### Recent Commits:
"""
            
            # Add commit details
            for commit in list(comparison.commits)[-5:]:  # Last 5 commits
                pr_body += f"- `{commit.sha[:7]}` {commit.commit.message.split('\n')[0]} (@{commit.author.login if commit.author else 'unknown'})\n"
            
            if comparison.total_commits > 5:
                pr_body += f"- ... and {comparison.total_commits - 5} more commits\n"
            
            pr_body += f"""
### Files Modified:
"""
            for file in list(comparison.files)[:10]:  # First 10 files
                status_emoji = {"added": "➕", "modified": "✏️", "removed": "➖"}.get(file.status, "📝")
                pr_body += f"- {status_emoji} `{file.filename}`\n"
            
            if len(comparison.files) > 10:
                pr_body += f"- ... and {len(comparison.files) - 10} more files\n"
            
            pr_body += f"""
---
🤖 **This PR was created automatically by the Fork Sync Bot**

**Review Checklist:**
- [ ] Changes look appropriate
- [ ] No sensitive information included
- [ ] Tests pass (if applicable)
- [ ] Ready to merge

**To sync more changes from this fork in the future, this process will run automatically.**
"""
            
            # Check if PR already exists
            existing_prs = original_repo.get_pulls(
                state='open',
                head=f"{fork.owner.login}:{fork.default_branch}"
            )
            
            if list(existing_prs):
                print(f"⚠️  PR already exists for {fork.full_name}")
                return None
            
            # Create the PR
            pr = original_repo.create_pull(
                title=pr_title,
                body=pr_body,
                head=f"{fork.owner.login}:{fork.default_branch}",
                base=original_repo.default_branch
            )
            
            # Add labels
            try:
                pr.add_to_labels("auto-sync", "from-fork")
            except:
                pass  # Labels might not exist
            
            print(f"✅ Created PR #{pr.number}: {pr_title}")
            return pr
            
        except Exception as e:
            print(f"❌ Error creating PR for {fork.full_name}: {e}")
            return None
    
    def run_sync_check(self):
        """Main function to check all repos and forks"""
        print(f"🚀 Starting fork sync check at {datetime.now()}")
        
        total_prs_created = 0
        
        for repo_name in self.monitored_repos:
            print(f"\n📂 Checking repository: {repo_name}")
            
            original_repo, forks = self.get_all_forks(repo_name)
            if not original_repo:
                continue
            
            for fork in forks:
                print(f"🔍 Checking fork: {fork.full_name}")
                
                has_changes, comparison = self.check_fork_for_changes(original_repo, fork)
                
                if has_changes:
                    pr = self.create_sync_pr(original_repo, fork, comparison)
                    if pr:
                        total_prs_created += 1
                else:
                    print(f"✅ No new changes in {fork.full_name}")
        
        print(f"\n🎉 Sync check complete! Created {total_prs_created} pull requests")
        
        # Create summary
        with open('sync_summary.txt', 'w') as f:
            f.write(f"Fork Sync Summary - {datetime.now()}\n")
            f.write(f"Repositories checked: {len(self.monitored_repos)}\n")
            f.write(f"Pull requests created: {total_prs_created}\n")

if __name__ == "__main__":
    try:
        bot = ForkSyncBot()
        bot.run_sync_check()
    except Exception as e:
        print(f"💥 Bot failed: {e}")
        exit(1)

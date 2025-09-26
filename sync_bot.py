#!/usr/bin/env python3
"""
Centralized Fork Sync Bot - Fixed Version
Automatically checks forks for changes and creates PRs
"""

import os
import json
from datetime import datetime
from github import Github

class ForkSyncBot:
    def __init__(self):
        # Get environment variables
        self.github_token = os.getenv('GITHUB_TOKEN')
        self.github_owner = os.getenv('GITHUB_OWNER', 'USD-AI-ResearchLab')
        
        # Check if token exists
        if not self.github_token:
            print("❌ ERROR: GITHUB_TOKEN environment variable is required")
            raise ValueError("GITHUB_TOKEN environment variable is required")
            
        # Initialize GitHub connection
        self.g = Github(self.github_token)
        
        # List of repositories to monitor - ADD YOUR REPO NAMES HERE
        self.monitored_repos = [
             'courses',
             '2ai-lab.github.io',
             'attnconcat',
             'LLNs-for-Early-Breast-Cancer-Detection',
             'Active-Learning',
             'DeepWhaleNet',
             'Optimized-Vision-Transformer-Training-using-GPU-and-Multi-threading',
             'Multimodal_Learning',
             'explorers',
             'sanskrit_maskedlm',
             'Machine-Learning-Implementation',
             'Improving-Robustness-of-Convolutional-Neural-Networks-through-Symmetry-Enforcement',
             'demo-repository',
             'ml-book-technicalities-innovation',
             'Report-Generation',
             'multimodal-emotion',
             'Superpixels-in-graph-neural-network',
             'Ensemble-DCNN',
             'deep-features-covid-screening',
             'streamlit-image-classification',
             '2AI-Club-Presentations',
             '2AI-Club-Code',
             'flax',
             'medical-imaging-datasets',
             'python-series',
             'Graph-Neural-Network',
             'Machine-Learning-Tools',
             'Aneurysm_Detection',
             'quant-club-website',
             '2ai-club.github.io',
             'Winsor-CAM-demo',
             'evidenceOfCovid',
             'ecg-classification',
             'Leveraging-Handwriting-Impairment-as-an-Early-Biomarker-for-Parkinson-Disease',
             'doubleDistilBERT',
             'PATL',
             'yolov7',
        ]
        
        print(f"🤖 Fork Sync Bot initialized for {self.github_owner}")
        print(f"📊 Monitoring {len(self.monitored_repos)} repositories")
    
    def get_repository_and_forks(self, repo_name):
        """Get original repository and all its forks"""
        try:
            # Get the original repository
            repo = self.g.get_repo(f"{self.github_owner}/{repo_name}")
            
            # Get all forks
            forks = list(repo.get_forks())
            
            print(f"📂 Repository: {repo_name}")
            print(f"🍴 Found {len(forks)} forks")
            
            return repo, forks
            
        except Exception as e:
            print(f"❌ Error accessing repository {repo_name}: {str(e)}")
            return None, []
    
    def check_for_new_commits(self, original_repo, fork):
        """Check if fork has commits that aren't in original repo"""
        try:
            # Get default branch names
            original_branch = original_repo.default_branch
            fork_branch = fork.default_branch
            
            print(f"🔍 Checking {fork.full_name} ({fork_branch}) against {original_repo.full_name} ({original_branch})")
            
            # Get latest commits from both repos
            try:
                original_commit = original_repo.get_branch(original_branch).commit
                fork_commit = fork.get_branch(fork_branch).commit
            except Exception as e:
                print(f"⚠️  Could not get commits for {fork.full_name}: {str(e)}")
                return False, None
            
            # Compare commit dates
            original_date = original_commit.commit.author.date
            fork_date = fork_commit.commit.author.date
            
            print(f"📅 Original last updated: {original_date}")
            print(f"📅 Fork last updated: {fork_date}")
            
            # If fork is newer, check for actual differences
            if fork_date > original_date:
                try:
                    # Compare the branches
                    comparison = self.g.get_repo(fork.full_name).compare(
                        f"{original_repo.full_name.split('/')[0]}:{original_branch}",
                        fork_branch
                    )
                    
                    if comparison.total_commits > 0:
                        print(f"✨ Found {comparison.total_commits} new commits in {fork.full_name}")
                        return True, comparison
                    else:
                        print(f"✅ No new commits in {fork.full_name}")
                        return False, None
                        
                except Exception as e:
                    print(f"⚠️  Could not compare branches for {fork.full_name}: {str(e)}")
                    return False, None
            else:
                print(f"✅ Fork {fork.full_name} is up to date")
                return False, None
                
        except Exception as e:
            print(f"❌ Error checking {fork.full_name}: {str(e)}")
            return False, None
    
    def create_pull_request(self, original_repo, fork, comparison):
        """Create a pull request to sync fork changes"""
        try:
            # Generate unique branch name
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            pr_title = f"🔄 Sync from {fork.owner.login}/{fork.name}"
            
            # Build PR description
            pr_body = f"""## 🔄 Automated Fork Sync

**Source**: [{fork.full_name}]({fork.html_url})
**Author**: @{fork.owner.login}
**New Commits**: {comparison.total_commits}
**Files Changed**: {len(comparison.files)}

### 📝 Recent Commits:
"""
            
            # Add commit information
            commit_count = 0
            for commit in comparison.commits:
                if commit_count >= 5:  # Limit to 5 commits
                    break
                author_name = commit.author.login if commit.author else "Unknown"
                commit_message = commit.commit.message.split('\n')[0]  # First line only
                pr_body += f"- `{commit.sha[:7]}` {commit_message} (@{author_name})\n"
                commit_count += 1
            
            if comparison.total_commits > 5:
                remaining = comparison.total_commits - 5
                pr_body += f"- ... and {remaining} more commits\n"
            
            # Add file change information
            pr_body += "\n### 📁 Files Modified:\n"
            file_count = 0
            for file_info in comparison.files:
                if file_count >= 10:  # Limit to 10 files
                    break
                status_map = {"added": "➕", "modified": "✏️", "removed": "➖"}
                emoji = status_map.get(file_info.status, "📝")
                pr_body += f"- {emoji} `{file_info.filename}`\n"
                file_count += 1
            
            if len(comparison.files) > 10:
                remaining_files = len(comparison.files) - 10
                pr_body += f"- ... and {remaining_files} more files\n"
            
            pr_body += "\n---\n🤖 **This PR was created automatically by the Fork Sync Bot**"
            
            # Check if similar PR already exists
            existing_prs = list(original_repo.get_pulls(
                state='open',
                head=f"{fork.owner.login}:{fork.default_branch}"
            ))
            
            if existing_prs:
                print(f"⚠️  Pull request already exists for {fork.full_name}")
                return None
            
            # Create the pull request
            pr = original_repo.create_pull(
                title=pr_title,
                body=pr_body,
                head=f"{fork.owner.login}:{fork.default_branch}",
                base=original_repo.default_branch
            )
            
            # Try to add labels (ignore if they don't exist)
            try:
                pr.add_to_labels("auto-sync", "from-fork")
            except:
                print("⚠️  Could not add labels (labels may not exist)")
            
            print(f"✅ Created PR #{pr.number}: {pr_title}")
            print(f"🔗 URL: {pr.html_url}")
            
            return pr
            
        except Exception as e:
            print(f"❌ Error creating PR for {fork.full_name}: {str(e)}")
            return None
    
    def run_sync_check(self):
        """Main function - check all monitored repositories"""
        print(f"🚀 Starting fork sync check at {datetime.now()}")
        print("=" * 60)
        
        if not self.monitored_repos:
            print("⚠️  No repositories configured for monitoring!")
            print("📝 Please edit sync_bot.py and add repository names to monitored_repos list")
            return
        
        total_prs_created = 0
        total_forks_checked = 0
        
        # Check each monitored repository
        for repo_name in self.monitored_repos:
            print(f"\n📂 Processing repository: {repo_name}")
            print("-" * 40)
            
            # Get repository and its forks
            original_repo, forks = self.get_repository_and_forks(repo_name)
            
            if not original_repo:
                print(f"❌ Skipping {repo_name} - could not access repository")
                continue
            
            if not forks:
                print(f"ℹ️  No forks found for {repo_name}")
                continue
            
            # Check each fork
            for fork in forks:
                total_forks_checked += 1
                print(f"\n🔍 Checking fork: {fork.full_name}")
                
                # Check if fork has new changes
                has_changes, comparison = self.check_for_new_commits(original_repo, fork)
                
                if has_changes and comparison:
                    # Create pull request
                    pr = self.create_pull_request(original_repo, fork, comparison)
                    if pr:
                        total_prs_created += 1
                else:
                    print(f"✅ No sync needed for {fork.full_name}")
        
        # Print summary
        print("\n" + "=" * 60)
        print("🎉 SYNC CHECK COMPLETE!")
        print(f"📊 Repositories monitored: {len(self.monitored_repos)}")
        print(f"🍴 Forks checked: {total_forks_checked}")
        print(f"📥 Pull requests created: {total_prs_created}")
        print(f"⏰ Completed at: {datetime.now()}")
        
        # Save summary to file
        summary = f"""Fork Sync Bot Summary
====================
Date: {datetime.now()}
Repositories monitored: {len(self.monitored_repos)}
Forks checked: {total_forks_checked}
Pull requests created: {total_prs_created}

Monitored repositories:
{chr(10).join(f"  - {repo}" for repo in self.monitored_repos)}
"""
        
        with open('sync_summary.txt', 'w') as f:
            f.write(summary)
        
        print("📄 Summary saved to sync_summary.txt")

if __name__ == "__main__":
    try:
        print("🤖 Starting Fork Sync Bot...")
        bot = ForkSyncBot()
        bot.run_sync_check()
        print("✅ Bot completed successfully!")
        
    except Exception as e:
        print(f"💥 Bot failed with error: {str(e)}")
        import traceback
        traceback.print_exc()
        exit(1)

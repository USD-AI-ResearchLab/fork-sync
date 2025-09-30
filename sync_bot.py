#!/usr/bin/env python3
import os, subprocess, tempfile, shutil, yaml
from github import Github

ORG_NAME = "USD-AI-ResearchLab"

def run(cmd, cwd=None):
    """Run a shell command with error handling."""
    return subprocess.run(cmd, cwd=cwd, check=True, text=True, capture_output=True)

def get_forks_from_org():
    """Fetch all forks in the org and their upstreams using GitHub API."""
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("Missing GITHUB_TOKEN")

    g = Github(token)
    org = g.get_organization(ORG_NAME)
    repos = org.get_repos()

    repos_list = []
    for repo in repos:
        if repo.fork:
            try:
                parent = repo.parent
                if parent:
                    upstream = f"{parent.owner.login}/{parent.name}"
                    repos_list.append({
                        "name": repo.name,
                        "fork": f"{ORG_NAME}/{repo.name}",
                        "upstream": upstream
                    })
            except Exception as e:
                print(f"⚠️ Could not get upstream for {repo.full_name}: {e}")
    return repos_list

def sync_repo(fork, upstream):
    """Sync a fork with its upstream repo."""
    tmp = tempfile.mkdtemp()
    try:
        token = os.getenv("GITHUB_TOKEN")
        fork_url = f"https://x-access-token:{token}@github.com/{fork}.git"
        upstream_url = f"https://github.com/{upstream}.git"

        print(f"🔄 Cloning {fork} ...")
        run(["git", "clone", fork_url, tmp])

        run(["git", "remote", "add", "upstream", upstream_url], cwd=tmp)
        run(["git", "fetch", "upstream"], cwd=tmp)

        run(["git", "checkout", "main"], cwd=tmp)
        run(["git", "merge", "upstream/main", "--no-edit"], cwd=tmp)
        run(["git", "push", "origin", "main"], cwd=tmp)

        print(f"✅ Synced {fork} with {upstream}")
    except subprocess.CalledProcessError as e:
        print(f"❌ Error syncing {fork}: {e.stderr}")
    finally:
        shutil.rmtree(tmp)

def main():
    """Main entry point: auto-generate repo list and sync them."""
    repos = get_forks_from_org()
    print(f"🔎 Found {len(repos)} forked repos in {ORG_NAME}")
    for repo in repos:
        sync_repo(repo["fork"], repo["upstream"])

if __name__ == "__main__":
    main()

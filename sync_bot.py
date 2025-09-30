#!/usr/bin/env python3
import os, subprocess, tempfile, shutil, yaml

def run(cmd, cwd=None):
    """Run a shell command with error handling."""
    return subprocess.run(cmd, cwd=cwd, check=True, text=True, capture_output=True)

def sync_repo(fork, upstream):
    """Sync a forked repo with its upstream."""
    tmp = tempfile.mkdtemp()
    try:
        token = os.getenv("GITHUB_TOKEN")
        if not token:
            raise RuntimeError("Missing GITHUB_TOKEN (GitHub Action sets this automatically)")

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
    """Read repos.yml and sync all listed repos."""
    with open("repos.yml") as f:
        cfg = yaml.safe_load(f)
    for repo in cfg["repos"]:
        fork = repo["fork"]
        upstream = repo["upstream"]
        sync_repo(fork, upstream)

if __name__ == "__main__":
    main()

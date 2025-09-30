# 🔄 Fork Sync Bot

[![GitHub Actions](https://github.com/USD-AI-ResearchLab/fork-sync/actions/workflows/fork-sync.yml/badge.svg)](https://github.com/USD-AI-ResearchLab/fork-sync/actions)

Automated **synchronization service** to keep forks in the  
[`USD-AI-ResearchLab`](https://github.com/USD-AI-ResearchLab) GitHub organization up to date with their upstream/original repositories.

- Runs daily at **11:00 AM CST (17:00 UTC)**
- Attempts **fast-forward merges** when possible
- If not possible, creates a **sync branch and PR** in the fork for review
- Supports multiple repositories via a central `config.json`

---

## 🚀 How It Works

1. **Workflow trigger**  
   - Scheduled via GitHub Actions (`cron: "0 17 * * *"`)  
   - Can also be run manually (`workflow_dispatch`)

2. **Bot steps**  
   - Clones the fork repository with a token  
   - Adds/fetches the upstream remote  
   - Tries `git merge --ff-only` into the default branch  
   - If not fast-forward:
     - Creates branch `sync/upstream-YYYYMMDD`
     - Merges upstream into that branch
     - Pushes the branch and opens a PR in the fork  

3. **Summary output** is printed at the end of each run.

---

## ⚙️ Configuration

All repositories to be synced are listed in **`config.json`**:

```json
{
  "repositories": {
    "repo-one": {
      "upstream": "https://github.com/OriginalOrg/repo-one.git",
      "branch": "main"
    },
    "repo-two": {
      "upstream": "https://github.com/OriginalOrg/repo-two.git",
      "branch": "master"
    },
    "repo-disabled": {
      "upstream": "https://github.com/OriginalOrg/repo-disabled.git",
      "branch": "main",
      "disabled": true
    }
  }
}
```

- **`upstream`**: HTTPS URL of the original repo  
- **`branch`**: default branch to track (`main` or `master`)  
- **`disabled`** (optional): skip this repo during sync  

---

## 🔑 Secrets

In the repo/org settings → **Secrets and variables → Actions**, add:

- **`BOT_TOKEN`** → Fine-grained PAT (or GitHub App token) with **Contents: Read/Write** permission on the forks.  
- (Optional) adjust **`GITHUB_OWNER`** (defaults to `USD-AI-ResearchLab`).

---

## 🛠️ Development

### Local testing
```bash
# Install dependencies
pip install PyGithub pyyaml

# Set environment
export GITHUB_TOKEN=ghp_xxx...
export GITHUB_OWNER=USD-AI-ResearchLab

# Run sync
python sync_bot.py
```

### Workflow identity
The workflow configures a git identity automatically:
```bash
git config --global user.name  "usd-ai-sync-bot"
git config --global user.email "bot@ai-research-lab.org"
```

---

## 📊 Example Summary Output

```
🚀 Starting sync run at 2025-09-30 17:00 UTC

🔍 USD-AI-ResearchLab/repo-one <= OriginalOrg/repo-one [main]
[INFO] Fast-forward succeeded for repo-one:main

🔍 USD-AI-ResearchLab/repo-two <= OriginalOrg/repo-two [master]
[INFO] Not fast-forward; opened PR #42 in repo-two

================================================================
📊 Sync Summary
================================================================

✅ PRs created:        1
  • USD-AI-ResearchLab/repo-two#42

✔ Fast-forward OK:    1
  • USD-AI-ResearchLab/repo-one:main

⏭ Skipped (disabled): 0
❌ Errors:             0
```

---

## 📌 Notes

- No force-push is ever used.  
- Merge conflicts are surfaced in the PR for maintainers to resolve.  
- You can safely scale this bot to **dozens of forks** by expanding `config.json`.

---

## 👥 Maintainers

- [USD AI Research Lab](https://www.ai-research-lab.org)  
- Contact: **contact@ai-research-lab.org**

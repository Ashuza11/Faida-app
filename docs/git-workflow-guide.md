# Git & GitHub Workflow Guide

## 🌳 Branch Strategy

````Cortana shifting mobile.
main (production)
  │
  └── develop (staging/integration)
        │
        ├── feature/issue-4-brand-colors
        ├── feature/issue-8-phone-auth
        ├── bugfix/issue-10-toast-notifications
        └── ...
```
### Branch Types

| Branch      | Purpose                 | Deploys To          |
| ----------- | ----------------------- | ------------------- |
| `main`      | Production-ready code   | Render (Production) |
| `develop`   | Integration branch      | Staging (optional)  |
| `feature/*` | New features            | Local only          |
| `bugfix/*`  | Bug fixes               | Local only          |
| `hotfix/*`  | Urgent production fixes | Direct to main      |

---

## 🔄 Workflow Overview

````

┌─────────────────────────────────────────────────────────────────┐
│ │
│ 1. Create Branch 2. Make Changes 3. Push & PR │
│ ─────────────── ────────────── ────────── │
│ feature/issue-4 → Code + Commit → Push to GitHub │
│ Create PR → develop │
│ │
│ 4. Review & Merge 5. Test on Develop 6. Deploy to Prod │
│ ───────────────── ────────────────── ───────────────── │
│ Approve PR → Merge to develop → Merge develop → main │
│ Run CI tests Test integration Auto-deploy Render │
│ │
└─────────────────────────────────────────────────────────────────┘

````

---

## 📋 Step-by-Step Workflow

### Initial Setup (One Time)

```bash
# Clone the repository
git clone https://github.com/your-username/airtfast.git
cd airtfast

# Set up branches
git checkout main
git pull origin main

# Create develop branch if it doesn't exist
git checkout -b develop
git push -u origin develop

# Return to develop for daily work
git checkout develop
````

### Working on an Issue

#### Step 1: Create a Feature Branch

```bash
# Always start from develop
git checkout develop
git pull origin develop

# Create feature branch (use issue number)
git checkout -b feature/issue-4-brand-colors

# Or for bug fixes
git checkout -b bugfix/issue-10-toast-notifications
```

#### Step 2: Make Changes

```bash
# Make your code changes
# ...

# Check status
git status

# Stage changes
git add .

# Commit with meaningful message
git commit -m "feat(ui): update brand colors to match new logo

- Updated primary color to #F58320 (orange)
- Updated secondary color to #5E72E4 (blue)
- Updated navbar and sidebar styling

Closes #4"
```

#### Step 3: Push and Create Pull Request

```bash
# Push branch to GitHub
git push -u origin feature/issue-4-brand-colors
```

Then on GitHub:

1. Go to your repository
2. Click "Compare & pull request"
3. Set base branch to `develop`
4. Fill in the PR template
5. Request reviewers if applicable
6. Click "Create pull request"

#### Step 4: Address Review Comments (if any)

```bash
# Make requested changes
git add .
git commit -m "fix: address review comments"
git push
```

#### Step 5: Merge to Develop

Once approved:

1. Click "Merge pull request" on GitHub
2. Choose "Squash and merge" for cleaner history
3. Delete the feature branch

```bash
# Locally, clean up
git checkout develop
git pull origin develop
git branch -d feature/issue-4-brand-colors
```

#### Step 6: Deploy to Production

When develop is stable and tested:

```bash
# On GitHub, create PR from develop to main
# Or via command line:
git checkout main
git pull origin main
git merge develop
git push origin main

# This triggers the CI/CD pipeline automatically!
```

---

## 📝 Commit Message Convention

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

### Types

| Type       | Description                |
| ---------- | -------------------------- |
| `feat`     | New feature                |
| `fix`      | Bug fix                    |
| `docs`     | Documentation only         |
| `style`    | Formatting, no code change |
| `refactor` | Code restructuring         |
| `test`     | Adding tests               |
| `chore`    | Maintenance tasks          |

### Examples

```bash
# Feature
git commit -m "feat(auth): implement phone number login

- Added phone number field to login form
- Updated authentication logic
- Added DRC phone validation

Closes #8"

# Bug fix
git commit -m "fix(notifications): correct toast messages

Fixed incorrect success/error messages on sale creation

Closes #10"

# Refactor
git commit -m "refactor(routes): standardize naming conventions

Renamed all routes from French to English:
- /ventes → /sales
- /clients → /clients (kept)
- /rapports → /reports

Closes #17"
```

---

## 🏷️ Creating GitHub Issues

### Using GitHub CLI (recommended)

```bash
# Install GitHub CLI
# https://cli.github.com/

# Authenticate
gh auth login

# Create an issue
gh issue create \
  --title "Update brand colors to match new logo" \
  --body "Update primary color to #F58320 and secondary to #5E72E4" \
  --label "design,ui,priority-high"

# List issues
gh issue list

# Start working on an issue
gh issue develop 4 --checkout
```

### Using GitHub Web Interface

1. Go to repository → Issues → New Issue
2. Use the issue template (if available)
3. Add appropriate labels
4. Assign to yourself
5. Link to milestone if applicable

---

## 🔧 Useful Git Commands

### Daily Commands

```bash
# Check current branch and status
git status
git branch

# Update from remote
git fetch origin
git pull origin develop

# See commit history
git log --oneline -10

# See what changed
git diff
git diff --staged
```

### Branch Management

```bash
# List all branches
git branch -a

# Delete local branch
git branch -d feature/old-branch

# Delete remote branch
git push origin --delete feature/old-branch

# Rename branch
git branch -m old-name new-name
```

### Fixing Mistakes

```bash
# Undo last commit (keep changes)
git reset --soft HEAD~1

# Undo last commit (discard changes)
git reset --hard HEAD~1

# Amend last commit message
git commit --amend -m "New message"

# Discard local changes to a file
git checkout -- filename

# Stash changes temporarily
git stash
git stash pop
```

### Rebasing (Advanced)

```bash
# Update feature branch with latest develop
git checkout feature/issue-4-brand-colors
git fetch origin
git rebase origin/develop

# If conflicts, resolve then:
git add .
git rebase --continue
```

---

## 🚦 Pull Request Checklist

Before creating a PR, ensure:

- [ ] Code follows project style guidelines
- [ ] All tests pass locally (`pytest`)
- [ ] New features have tests
- [ ] Documentation updated if needed
- [ ] Commit messages follow convention
- [ ] No console.log / print statements left
- [ ] No hardcoded secrets or credentials
- [ ] UI changes tested on mobile

---

## 🎯 Quick Reference Card

```bash
# Start new feature
git checkout develop && git pull
git checkout -b feature/issue-XX-description

# Work and commit
git add . && git commit -m "feat: description"

# Push and create PR
git push -u origin feature/issue-XX-description
# → Create PR on GitHub: feature branch → develop

# After PR merged, cleanup
git checkout develop && git pull
git branch -d feature/issue-XX-description

# Deploy to production
# → Create PR on GitHub: develop → main
# → Merge triggers automatic deployment
```

---

## 📅 Order of Work

Based on dependencies, here's the recommended order:

### Phase 1: Foundation (Do First)

1. **Issue #1**: Migrate to Neon DB
2. **Issue #2**: Set Up CI/CD
3. **Issue #3**: Refactor Docker Config

### Phase 2: Core Changes

4. **Issue #8**: Phone Number Authentication
5. **Issue #17**: Standardize Naming
6. **Issue #18**: Code Cleanup

### Phase 3: UI/UX

7. **Issue #4**: Update Brand Colors
8. **Issue #5**: Redesign Login/Register
9. **Issue #6**: Fix Mobile Responsive
10. **Issue #7**: Add Loading Indicators

### Phase 4: Bug Fixes

11. **Issue #10**: Fix Toast Notifications
12. **Issue #11**: Fix Geolocation
13. **Issue #12-14**: Fix Tab Active States

### Phase 5: Features

14. **Issue #9**: Update Profile Page
15. **Issue #13**: Report Archiving
16. **Issue #15**: Update Stockeur Modal
17. **Issue #16**: WhatsApp Support
18. **Issue #19**: Improve CLI Commands

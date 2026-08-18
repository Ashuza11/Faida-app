---
name: commit
description: Review staged Git changes, summarize them, and propose a conventional emoji commit message before committing. Use when the user invokes $commit or asks Codex to prepare or create a commit from staged changes; never commit without explicit approval of the proposed message.
---

# Commit staged changes

1. Run `git status` and `git diff --staged`.
2. If nothing is staged, report that and stop. Do not stage files implicitly.
3. Summarize the staged changes in concise, user-facing language.
4. Choose exactly one appropriate type and emoji:
   - ✨ `feat:` new feature
   - 🐛 `fix:` bug fix
   - 🔨 `refactor:` refactoring
   - 📝 `docs:` documentation
   - 🎨 `style:` styling or formatting
   - ✅ `test:` tests
   - ⚡ `perf:` performance
5. Propose a message in present tense that explains why the change exists:

   ```text
   <emoji> <type>: <concise description>

   <optional body explaining why>
   ```

6. Ask for confirmation. Do not run `git commit` in the same turn as the proposal.
7. Commit only after the user explicitly approves. Use the approved subject and body exactly unless the user requests an adjustment.

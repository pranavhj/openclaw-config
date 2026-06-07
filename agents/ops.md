# openclaw ops

Reference for making changes to the openclaw system itself.

## Source control workflow

**After editing any config file, you MUST commit:**
```
cd D:\MyData\Software\openclaw-config
git add -A && git commit -m "fix(OC-NNN): description"
git push
```

Commit format: `<type>(<scope>): <description>`
- type: `fix` | `feat` | `config` | `sync` | `docs` | `misc`
- scope: `OC-NNN` (issue ID) or `sync` | `misc` | `docs`

**After editing `C:\Users\prana\projects\openclaw\CLAUDE.md`, also copy it to `agents\openclaw-CLAUDE.md`** (git backup).

Check open issues before diagnosing: `type D:\MyData\Software\openclaw-config\ISSUES.md`

## GitHub CLI (gh)

`gh` is installed and authenticated. Use it for all GitHub operations:
- **Path:** `"C:\Program Files\GitHub CLI\gh.exe"` (or `gh` if PATH is updated in session)
- **Push / general git:** use `git` as normal — credentials stored in Windows Credential Manager
- **Actions logs:** `gh run list --repo pranavhj/<repo>` and `gh run view <run-id> --repo pranavhj/<repo> --log-failed`
- **Create repo:** `gh repo create pranavhj/<name> --public --source=. --push`
- **PR / issues:** `gh pr create`, `gh issue list`, etc.

Always use `gh` instead of raw `curl` for GitHub API calls.

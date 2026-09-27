# GitHub remote setup — make the Actions workflow actually run on push

The repo already contains `.github/workflows/ci.yml`, which runs the full
pytest suite on every push and pull request. GitHub can only run it once the
local repo has a remote to push to. Follow this checklist once after cloning.

## 1. Create the empty GitHub repo

- Go to <https://github.com/new> (or use the `gh` CLI shown below).
- **Do not** initialize with README / .gitignore / license — the local repo
  already has history; an initialized remote would force a merge.
- **Public** is simplest: Actions is unlimited-free on public repos. Private
  also works (2,000 free Actions minutes/month — this ~10s suite uses
  seconds of that).

One-command alternative with the GitHub CLI:

```bash
gh repo create genai-funds-outreach --private --source . --remote origin --push
```

(`gh` handles steps 2–4 in one shot.)

## 2. Add the remote

```bash
git remote add origin https://github.com/<your-user>/<repo-name>.git
git remote -v   # verify
```

HTTPS prompts for a browser login or Personal Access Token; SSH
(`git@github.com:<user>/<repo>.git`) requires a registered key.

## 3. Push

```bash
git push -u origin main
```

## 4. Verify the workflow ran

1. Open the repo on github.com → **Actions** tab.
2. A workflow named **tests** should appear for your push (one run per push).
3. Click it → the `pytest` job must be green and show the 16 passing tests.
4. The commit list should show a ✓ next to the pushed SHA.

If the Actions tab says workflows are disabled: **Settings → Actions →
General → Allow all actions** (GitHub disables them on some private repos).

## 5. (Optional, recommended) Require the check before merge

On the repo's **Settings → Branches → Branch protection rule** for `main`:

- ✅ Require a pull request before merging (team workflow)
- ✅ Require status checks to pass → select **tests / pytest**

Free on public repos; on private repos this needs a paid plan — skip it and
rely on the local pre-commit gate instead.

## 6. Local gate (every clone, one-time)

The pre-commit hook is committed at `.githooks/pre-commit`, but Git only uses
it after pointing `core.hooksPath` there:

```bash
git config core.hooksPath .githooks
```

Every local commit then runs the same 16 tests; `git commit --no-verify`
bypasses it in emergencies. CI is the safety net for anyone who forgets.

## Notes

- No repository secrets are needed: the suite runs fully offline in mock mode
  and generates its own webhook secret in `tests/conftest.py`.
- The workflow targets Python 3.13 (`actions/setup-python`); bump both this
  and your local venv together if you upgrade.
- If a job fails on `ubuntu-latest` but passes locally on Windows, suspect a
  path-separator or encoding difference — the test suite deliberately avoids
  both, but drivers/agents added later may not.

# How we work on this pipeline

Anyone can open an issue. Only maintainers (listed in [.github/MAINTAINERS](.github/MAINTAINERS)) approve work.
An AI agent running on the group's server does most of the implementation and the reductions; people decide.

## The flow

1. **Open an issue** with one of the templates: *bug*, *feature or change*, or *reduce a target*.
   New issues get the label `triage`.
2. **A maintainer approves** by adding the label `approved` (or closes it). The agent ignores issues without
   `approved`, and checks that the label was added by a maintainer.
3. **The agent works on it.**
   * *bug / feature*: a branch and a **pull request**, never a push to `main`. The PR contains the tests and a
     validation report (reference subset of SN 2024pxl vs the old pipeline, before/after plots if numbers move).
   * *reduce a target*: SLURM jobs on the server; the light curve, QA summary and review packets are posted back
     to the issue.
   The agent asks in the issue thread when something is unclear instead of guessing.
4. **A maintainer reviews and merges** the PR (branch protection requires a code-owner review), or signs off the
   flagged frames of a reduction before results are shared (e.g. SNEx).

## Rules for the agent

* One issue → one branch → one PR. No force-push, no direct commits to `main`.
* Secrets (LCO API key) live only on the server, never in the repo or in issues.
* Destructive actions (deleting data, overwriting published reductions) need the label `approved-destructive`
  from a maintainer.
* Every reduction records the code commit, the ASTRA decisions and the QA results.
* Every bug fix adds or updates an entry in [docs/reference/bugs.json](docs/reference/bugs.json) (what was wrong, why it matters, the fix,
  the measured effect, whether the old pipeline has it too) and reruns `python tools/bugs_page.py`.

## Labels

`triage` (new) · `approved` · `approved-destructive` · `bug` · `feature` · `reduction` · `needs-info` ·
`agent-working` · `needs-review`

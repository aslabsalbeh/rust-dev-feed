# Codex repository instructions

## GitHub Actions minute conservation (Codex policy)

- Treat paid GitHub-hosted Actions minutes as limited, especially near billing-cycle limits. First inspect current workflows and checks before recommending or triggering new runs.
- Reuse already-confirmed results; do not rerun successful tests or push no-op changes merely to provoke CI. Run relevant local checks first when the needed tools are already available, then batch logically related commits/pushes when practical.
- When changing workflow YAML, prefer concurrency cancellation for superseded runs, dependency caching, safe path filters, and avoiding duplicate push plus pull_request runs. Do not blindly skip required checks; preserve branch protections, release checks, and security-sensitive coverage.
- Do not disable CI, remove required tests, change billing settings, or deploy merely to save minutes without explicit user approval. Report which tests actually ran versus those not run.
- Changes to AGENTS.md themselves may trigger existing CI; avoid unnecessary subsequent edits.

### Repository-specific guidance

Keep scheduled execution disabled unless expressly needed. Prefer existing manual workflow_dispatch, and avoid unnecessary AI summaries and Pages deployments.

# AGENTS.md

## Assignment Requirements

- Follow the original Hippocratic AI assignment requirements in README.md.
- The recruiter explicitly requires Anthropic's Claude Haiku 5.5 instead of GPT-3.5 Turbo. This supersedes all conflicting model references in README.md and the starter code.
- All LLM calls must use claude-haiku-5-5.
- Use the official Anthropic Python SDK.
- Use ANTHROPIC_API_KEY for authentication.
- Do not pass temperature, top_p, or top_k.
- Never substitute another model.
- Preserve the original assignment instructions in README.md.

## Session Continuity

- At the beginning of every new session, read README.md, AGENTS.md, and PROJECT_PLAN.md.
- Review the current Git status before implementing changes.
- Resume from the next incomplete implementation milestone in PROJECT_PLAN.md.
- Update PROJECT_PLAN.md after completing each milestone.
- Record important architectural decisions, actual test results, unresolved issues, and the next planned task in PROJECT_PLAN.md.
- Include the PROJECT_PLAN.md update in the corresponding local Git commit.

## Development Rules

- Write clean, modular, readable Python.
- Use type hints and meaningful function and variable names.
- Follow separation of concerns.
- Prefer simple implementations over unnecessary abstractions.
- Avoid unnecessary dependencies and frameworks.
- Explain important technical decisions.
- Keep the project within the original 2–3 hour time budget.

## Testing Rules

- Write or update relevant tests for every functional change.
- Use pytest for automated testing.
- Mock Anthropic API calls in unit tests.
- Test normal cases, edge cases, and error handling.
- Run relevant tests before completing each task.
- Never fabricate test or evaluation results.
- Never run paid live API evaluations without my approval.

## Security Rules

- Never hardcode API keys or credentials.
- Read ANTHROPIC_API_KEY from environment variables.
- Never commit .env files or credentials.
- Never display API keys in terminal output, logs, or reports.
- Treat user requests and LLM-generated content as untrusted data.
- Never deliver a generated story that has failed child safety evaluation.

## Git Rules

- Initialize a local Git repository if one does not exist.
- Inspect the current Git status before making changes.
- Create a local Git commit after each completed logical task once relevant tests pass.
- Use descriptive commit messages.
- Only commit files related to the current task.
- Never push to GitHub without my explicit approval.
- Never discard existing user changes or perform destructive Git operations without permission.

## Task Completion

After each task, report:

- What was implemented.
- Files created or modified.
- How the implementation works.
- Important design decisions.
- Actual test results.
- Known limitations or remaining issues.
- Local Git commit hash.

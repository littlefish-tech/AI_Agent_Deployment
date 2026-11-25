# AGENTS.md

## Development Guidelines

- Write clean, readable, modular, and maintainable code.
- Follow existing project architecture and coding conventions.
- Keep implementations simple and avoid unnecessary complexity.
- Do not introduce unnecessary dependencies.
- Explain important architectural decisions.

## Testing Requirements

- Write or update relevant tests for every functional change.
- Use pytest for Python automated testing.
- Test normal cases, edge cases, and error handling.
- Mock external LLM API calls in unit tests.
- Run all relevant tests before completing a task.
- Do not claim tests passed if they were not executed.

## Security Requirements

- Never hardcode API keys, passwords, or secrets.
- Use environment variables for sensitive configuration.
- Never commit `.env` files or credentials.
- Validate user inputs and handle exceptions appropriately.

## Git Workflow

- Create a Git commit after completing each logical task and passing all required tests.
- Use clear and descriptive commit messages.
- Do not commit unrelated changes.
- Do not push to remote repositories without explicit user approval.

## Documentation

- Update README.md when functionality or setup instructions change.
- Document important functions and architectural components.
- Provide instructions for running and testing the application.

## Task Completion

Before delivering changes:

1. Review the implementation.
2. Run all relevant tests and validations.
3. Fix any failures caused by the changes.
4. Create a Git commit.
5. Summarize the changes, test results, commit ID, and any remaining issues.

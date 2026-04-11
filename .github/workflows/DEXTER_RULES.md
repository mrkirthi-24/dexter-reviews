# Dexter Project Rules

Use this file to define repository-specific PR review requirements.

## Required Checks

- Validate authentication and authorization changes for every affected endpoint.
- Reject use of hardcoded secrets, credentials, or tokens.
- Require input validation for all new external/user inputs.
- Require explicit error handling for network and file I/O paths.

## Python-Specific Requirements

- Use timezone-aware datetimes for persisted or API-exposed timestamps.
- Avoid broad `except Exception` without re-raise or structured logging.
- Keep imports at module top-level unless a circular dependency requires otherwise.

## Output Expectations

- Report violations in changed files only.
- Use `bug_category: "project-rule"` when the finding is primarily based on these rules.

## Nameing convention for python classes
- Python classes should always be in PascalCase
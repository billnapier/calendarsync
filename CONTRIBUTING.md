# Contributing to Calendar Sync

Welcome! We appreciate your interest in contributing to the Calendar Sync project. Whether you're a human developer or an AI agent, following these guidelines ensures that our codebase remains robust, clean, and testable.

> **Note for Agents:** This document contains specific, precise instructions designed to be machine-parseable and strictly followed. Please treat these rules as binding constraints for your operation.

## 1. Local Development & Pre-Push Verification

**The Golden Rule:** Never push code that fails local checks. You must replicate the CI environment locally before submitting changes.

### Required Pre-Push Actions:
1.  **Inspect Workflows**: proper behavior requires understanding what the CI does. Look at `.github/workflows/` (e.g., `lint.yml`, `python-tests.yml`).
2.  **Run Local Checks**:
    *   **Python Linting**: Run `pylint` on the `app` and `tests` directories.
        ```bash
        pylint app tests
        ```
        *Target Score: >= 8.0*
    *   **Code Formatting**: Run `black` to automatically fix formatting issues.
        ```bash
        black .
        ```
        *Requirement: You MUST run this before every push to prevent CI failures.*
    *   **Python Tests**: Run the full test suite.
        ```bash
        pytest
        ```
        *Requirement: All tests must pass.*
    *   **Terraform**: Check formatting and validation.
        ```bash
        terraform fmt -recursive -check
        terraform validate
        ```
    *   **HTML Linting**: Run `djlint` to check and format Jinja2 templates.
        ```bash
        djlint app/templates/*.html --check
        # To auto-fix:
        djlint app/templates/*.html --reformat
        ```
    *   **CSS Linting**: Run `stylelint` to check CSS files.
        ```bash
        npx stylelint "**/*.css"
        # To auto-fix:
        npx stylelint "**/*.css" --fix
        ```

## 2. Python Development Guidelines

*   **Unit Tests are Mandatory**: Every code change, no matter how small, must be accompanied by a unit test that verifies the new behavior or fix.
*   **Code Formatting**: All Python code must be formatted with **Black**. The CI pipeline will fail if code is poorly formatted.
*   **Linting Compliance**: We use `pylint`. Ensure your code adheres to standard Python best practices and passes the linter checks with a score of **8.0 or higher**.

## 3. Git Workflow

To maintain a clean history, we enforce a strict branching strategy.

*   **Starting a New Task**:
    Always start from the latest `main`.
    ```bash
    git checkout main
    git pull origin main
    git checkout -b feature/your-feature-name
    ```

*   **Updating an Existing Branch**:
    If `main` has moved forward, **rebase** your changes on top of it. Do not merge `main` into your branch.
    ```bash
    git checkout feature/your-feature-name
    git fetch origin main
    git rebase origin/main
    ```

## 4. Pull Request Workflow

1.  **Push Changes**: Push your branch to the repository.
2.  **Wait for checks**: **MANDATORY**. You **MUST** wait for all GitHub Actions to complete.
    *   Do not assume your code works because it runs locally.
    *   **Verify** that every check (Lint, Python Tests, Black, Ratchet, Terraform) is **GREEN**.
    *   If a check fails, fix it immediately and push updates. **Repeat this process until all checks pass.**
3.  **Verify Checks**: ensure Lint, Python Tests, Terraform Plan, and any other triggered workflows are **GREEN (Passing)**.
4.  **Address Review Comments**: **CRITICAL**. Review ALL comments left by `gemini-code-assist` or human reviewers.
    *   Fix the issues raised.
    *   Reply to comments if clarification is needed.
5.  **Iterate**: Repeat steps 1-4 until all checks pass and all comments are resolved.

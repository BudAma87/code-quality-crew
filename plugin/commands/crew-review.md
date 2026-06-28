---
description: Review a source file with the Managed Agents code-quality crew (reviewer + test-writer) and save generated pytest tests.
argument-hint: <path-to-source-file>
allowed-tools: Bash(python:*), Bash(py:*), Read
---

Run the Code Quality Crew on the file the user named: `$ARGUMENTS`

1. If `$ARGUMENTS` is empty, ask the user which file to review and stop.
2. Run the crew wrapper script, passing the path through unchanged:

   ```
   python "${CLAUDE_PLUGIN_ROOT}/scripts/crew_review.py" $ARGUMENTS
   ```

   The script creates (or reuses) the coordinator/reviewer/test-writer agents,
   stages the file in a sandbox, runs the review, prints the report to stdout,
   and writes the generated `test_<name>.py` next to the source file. Progress
   and the final file path are logged to stderr.

3. Present the script's report to the user as-is (it is already formatted
   markdown). Then state where the test file was written (look for the
   `[crew] wrote tests -> ...` line on stderr). Do not re-run the script.

Notes:
- Requires `ANTHROPIC_API_KEY` in the environment or a `.env` file in the
  current directory. If the script reports the key is missing, tell the user.
- If the user adds `--no-tests`, pass it through (report only, nothing written).
- If `python` is not found, retry the command with `py` instead.

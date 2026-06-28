"""Code Quality Crew — wrapper around the Claude Managed Agents crew.

Runs a coordinator agent that delegates a code review to a `reviewer` agent and
unit-test writing to a `test-writer` agent (the same crew from the tutorial),
then prints the synthesized review and writes the generated pytest file next to
your source.

Designed to be driven by the `/crew-review` Claude Code plugin command, but also
runs standalone:

    python crew_review.py path/to/your_file.py
    python crew_review.py path/to/your_file.py --no-tests   # report only
    python crew_review.py path/to/your_file.py --fresh      # ignore agent cache

Requires ANTHROPIC_API_KEY in the environment (a `.env` in the current or target
directory is loaded automatically if present).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import sys
from pathlib import Path

# --- Agent definitions ------------------------------------------------------
# Bumping CONFIG_VERSION (or editing any prompt/model below) invalidates the
# cached agent IDs so the crew is recreated on the next run.
CONFIG_VERSION = 1

REVIEWER = {
    "name": "crew-reviewer",
    "model": "claude-opus-4-8",
    "system": (
        "You are a senior code reviewer. Read the given file and report bugs, "
        "security issues (e.g. injection, plaintext secrets), and missing error "
        "handling. Group findings by severity (high/medium/low). Be concise and "
        "specific, citing line numbers. Do not modify files."
    ),
}

TEST_WRITER = {
    "name": "crew-test-writer",
    "model": "claude-sonnet-4-6",
    "system": (
        "You write thorough pytest unit tests for the given source file. Cover "
        "happy paths, edge cases, and error conditions with clear test names. "
        "Import the code under test from the module named after the source file. "
        "Save the tests next to the source as test_<name>.py and return the full "
        "test file contents."
    ),
}

COORDINATOR = {
    "name": "crew-lead",
    "model": "claude-opus-4-8",
    "system": (
        "You coordinate a code-quality review. You are given the path to a "
        "source file that has been staged in your sandbox. Delegate the code "
        "review to the reviewer agent and the unit-test writing to the "
        "test-writer agent. They share your sandbox filesystem. When both are "
        "done, produce a final report with exactly two parts:\n"
        "1. A concise markdown review of findings, grouped by severity.\n"
        "2. The COMPLETE generated pytest file, formatted EXACTLY as a line "
        "'===TESTFILE: <suggested filename>===' on its own, immediately followed "
        "by a single fenced ```python code block containing the entire test file "
        "and nothing after the closing fence."
    ),
}

TOOLSET = [{"type": "agent_toolset_20260401"}]
CACHE_PATH = Path.home() / ".code-quality-crew" / "crew.json"


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def load_env(target: Path) -> None:
    """Best-effort load of a .env from cwd or the target file's directory."""
    import os

    for env_path in (Path.cwd() / ".env", target.resolve().parent / ".env"):
        if not env_path.is_file():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def config_signature() -> str:
    blob = json.dumps(
        {"v": CONFIG_VERSION, "r": REVIEWER, "t": TEST_WRITER, "c": COORDINATOR},
        sort_keys=True,
    )
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def create_crew(client) -> dict:
    """Create the three agents + a shared environment; return their IDs."""
    log("[crew] creating agents…")
    reviewer = client.beta.agents.create(tools=TOOLSET, **REVIEWER)
    test_writer = client.beta.agents.create(tools=TOOLSET, **TEST_WRITER)
    coordinator = client.beta.agents.create(
        tools=TOOLSET,
        multiagent={
            "type": "coordinator",
            "agents": [
                {"type": "agent", "id": reviewer.id},
                {"type": "agent", "id": test_writer.id},
            ],
        },
        **COORDINATOR,
    )
    environment = client.beta.environments.create(
        name="crew-env",
        config={"type": "cloud", "networking": {"type": "limited"}},
    )
    return {
        "signature": config_signature(),
        "reviewer": reviewer.id,
        "test_writer": test_writer.id,
        "coordinator": coordinator.id,
        "environment": environment.id,
    }


def get_crew(client, fresh: bool) -> dict:
    """Return cached crew IDs, validating them; (re)create when needed."""
    from anthropic import NotFoundError

    if not fresh and CACHE_PATH.is_file():
        try:
            cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            cache = None
        if cache and cache.get("signature") == config_signature():
            try:
                client.beta.agents.retrieve(cache["coordinator"])
                log("[crew] reusing cached agents.")
                return cache
            except NotFoundError:
                log("[crew] cached agents missing; recreating.")

    crew = create_crew(client)
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(crew, indent=2), encoding="utf-8")
    return crew


def stage_file(client, session_id: str, source: Path, dest: str) -> None:
    """Copy the local source file into the sandbox via a base64 bash command."""
    b64 = base64.b64encode(source.read_bytes()).decode("ascii")
    command = (
        f"mkdir -p \"$(dirname '{dest}')\" && "
        f"printf '%s' '{b64}' | base64 -d > '{dest}'"
    )
    client.beta.sessions.events.send(
        session_id,
        events=[{
            "type": "user.message",
            "content": [{
                "type": "text",
                "text": (
                    f"First, stage the file by running this exact bash command, "
                    f"then confirm `{dest}` exists:\n\n```bash\n{command}\n```"
                ),
            }],
        }],
    )


def run_review(client, crew: dict, dest: str) -> str:
    """Open a session, run the crew, and return the coordinator's full report."""
    session = client.beta.sessions.create(
        agent=crew["coordinator"],
        environment_id=crew["environment"],
        title="Code quality crew",
    )
    log(f"[crew] session {session.id} started.")

    stage_file(client, session.id, Path(dest_to_local[dest]), dest)

    transcript: list[str] = []
    with client.beta.sessions.events.stream(session.id) as stream:
        client.beta.sessions.events.send(
            session.id,
            events=[{
                "type": "user.message",
                "content": [{
                    "type": "text",
                    "text": (
                        f"Review the file `{dest}` and write pytest unit tests "
                        f"for it. Follow your two-part report format exactly."
                    ),
                }],
            }],
        )
        for event in stream:
            if event.type == "agent.message":
                for block in event.content:
                    text = getattr(block, "text", "")
                    if text:
                        transcript.append(text)
            elif event.type == "agent.tool_use":
                log(f"  [lead tool: {event.name}]")
            elif event.type == "session.status_idle":
                break

    try:
        client.beta.sessions.delete(session.id)
        log("[crew] session cleaned up.")
    except Exception as exc:  # cleanup is best-effort
        log(f"[crew] could not delete session: {exc}")

    return "".join(transcript)


def extract_test_file(report: str) -> tuple[str | None, str | None]:
    """Pull (filename, code) out of the coordinator's TESTFILE block."""
    marker = re.search(r"===TESTFILE:\s*(.+?)\s*===", report)
    if not marker:
        return None, None
    code_match = re.search(
        r"```(?:python)?\s*\n(.*?)```", report[marker.end():], re.DOTALL
    )
    if not code_match:
        return None, None
    return Path(marker.group(1).strip()).name, code_match.group(1).rstrip() + "\n"


# Maps sandbox dest path -> the local file it came from (set in main()).
dest_to_local: dict[str, str] = {}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Code Quality Crew on a file.")
    parser.add_argument("path", help="Path to the source file to review.")
    parser.add_argument("--no-tests", action="store_true", help="Report only; don't write tests.")
    parser.add_argument("--fresh", action="store_true", help="Ignore the agent cache and recreate.")
    args = parser.parse_args()

    # Make emoji-containing agent output safe on Windows consoles.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass

    source = Path(args.path)
    if not source.is_file():
        log(f"error: '{args.path}' is not a file. Pass a single source file.")
        return 2

    load_env(source)

    import os

    if not os.environ.get("ANTHROPIC_API_KEY"):
        log("error: ANTHROPIC_API_KEY is not set (env var or a .env file).")
        return 2

    from anthropic import Anthropic, APIError

    client = Anthropic()
    dest = source.name
    dest_to_local[dest] = str(source)

    try:
        crew = get_crew(client, fresh=args.fresh)
        report = run_review(client, crew, dest)
    except APIError as exc:
        log(f"error: Managed Agents API call failed: {exc}")
        return 1

    if not report.strip():
        log("warning: the crew returned no text. Try again or check the Console.")
        return 1

    print(report)

    if not args.no_tests:
        name, code = extract_test_file(report)
        if name and code:
            out_path = source.resolve().parent / name
            out_path.write_text(code, encoding="utf-8")
            log(f"\n[crew] wrote tests -> {out_path}")
        else:
            log("\n[crew] no parseable test file in the report; nothing written.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

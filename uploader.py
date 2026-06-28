"""Helpers for getting local files into a session's sandbox.

Stage 3 reviews ``sample/auth.py``, but a fresh sandbox starts empty — the file
has to get *into* it first. This module offers two ways to do that:

1. ``upload_file`` — the proper way: push a local file into the sandbox so the
   agents can read it at a real path (e.g. ``sample/auth.py``).
2. ``inline_file`` — the zero-setup fallback: read the file locally and return a
   prompt string with the code pasted inline, so you can hand it to the crew
   without any upload at all. Handy while learning.

NOTE: Managed Agents is in public beta and the file-upload surface can change.
``upload_file`` tries the documented session-files path and falls back to
writing the file via a bash event, which works as long as the agent toolset is
enabled. If neither matches your SDK version, use ``inline_file`` and check:
https://platform.claude.com/docs/en/managed-agents/overview
"""

from __future__ import annotations

import base64
from pathlib import Path


def inline_file(local_path: str | Path) -> str:
    """Return a prompt-ready string with the file's contents pasted inline.

    The simplest, always-works option: no upload, no sandbox round-trip. Give
    the returned string to the crew as the ``user.message`` text.
    """
    path = Path(local_path)
    code = path.read_text(encoding="utf-8")
    return (
        f"Here is the contents of `{path.as_posix()}`:\n\n"
        f"```python\n{code}\n```\n\n"
        "Review it and write unit tests for it."
    )


def upload_file(
    client,
    session_id: str,
    local_path: str | Path,
    dest_path: str | None = None,
) -> str:
    """Copy a local file into the session sandbox; return its sandbox path.

    Tries the native files-upload API first. If that isn't available in your SDK
    build, it falls back to writing the file through a ``bash`` event (base64 +
    ``cat``), which needs the agent toolset enabled on the session's agent.
    """
    path = Path(local_path)
    dest = dest_path or path.as_posix()
    data = path.read_bytes()

    # --- Preferred: native session file upload --------------------------------
    upload = getattr(getattr(client.beta.sessions, "files", None), "upload", None)
    if callable(upload):
        with path.open("rb") as fh:
            upload(session_id, path=dest, file=fh)
        return dest

    # --- Fallback: write it from inside the sandbox via bash -------------------
    b64 = base64.b64encode(data).decode("ascii")
    # Decode the base64 blob into the destination, creating parent dirs first.
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
                    f"Run this exact bash command to stage a file, then confirm "
                    f"`{dest}` exists:\n\n```bash\n{command}\n```"
                ),
            }],
        }],
    )
    return dest


if __name__ == "__main__":
    # Quick demo of the inline fallback — prints the prompt you'd send the crew.
    print(inline_file("sample/auth.py"))

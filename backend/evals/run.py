"""Runs the eval tasks against a running Echo through its HTTP API, on the caller's own key, and
prints one line per task: pass or fail, tool calls, tokens and seconds. It spends real money, so it
runs only by hand and stops once the tokens used pass --max-tokens.

    ECHO_SESSION=<echo_session cookie> uv run python -m evals.run \\
        --credential <key id> --model claude-haiku-5-5 --effort low --max-tokens 400000 [--only planted]
"""

import argparse
import json
import os
import sys
import time

import httpx

from evals.tasks import TASKS, Task


def parse_events(lines) -> list[tuple[str, dict]]:
    """Server-sent events from an iterable of lines."""
    events, name = [], None
    for line in lines:
        if line.startswith("event: "):
            name = line[7:]
        elif line.startswith("data: ") and name:
            events.append((name, json.loads(line[6:])))
            name = None
    return events


def tokens(usage: dict) -> int:
    return sum(usage.get(k, 0) for k in ("inputTokens", "outputTokens", "cacheReadInputTokens", "cacheWriteInputTokens"))


def run_task(client: httpx.Client, task: Task, credential: str, model: str, effort: str) -> dict:
    ws = client.post("/api/workspaces").raise_for_status().json()["data"]["id"]
    for path, content in task.seed.items():
        client.put(f"/api/workspaces/{ws}/file", json={"path": path, "content": content}).raise_for_status()
    chat = client.post(f"/api/workspaces/{ws}/chats").raise_for_status().json()["data"]["id"]
    out = {"task": task.name, "workspace": ws, "tools": 0, "tokens": 0, "error": None}
    started = time.monotonic()
    for prompt in task.prompts:
        body = {"credential_id": credential, "model": model, "effort": effort, "prompt": prompt}
        with client.stream("POST", f"/api/workspaces/{ws}/chats/{chat}/turns", json=body, timeout=None) as response:
            response.raise_for_status()
            events = parse_events(response.iter_lines())
        out["tools"] += sum(1 for name, _ in events if name == "tool")
        last = events[-1] if events else ("error", {"code": "empty_stream"})
        if last[0] != "done":
            out["error"] = f"{last[1].get('code')} (request {last[1].get('request_id')})"
            break
        out["tokens"] += tokens(last[1].get("usage", {}))
    out["seconds"] = round(time.monotonic() - started)
    if not out["error"]:
        out["error"] = task.check(lambda p: read_file(client, ws, p), changed_paths(client, ws))
    return out


def read_file(client: httpx.Client, ws: str, path: str) -> str | None:
    response = client.get(f"/api/workspaces/{ws}/file", params={"path": path})
    return response.json()["data"]["content"] if response.status_code == 200 else None


def changed_paths(client: httpx.Client, ws: str) -> set[str]:
    return {f["path"] for f in client.get(f"/api/workspaces/{ws}/git/status").raise_for_status().json()["data"]}


def line(result: dict) -> str:
    verdict = "PASS" if result["error"] is None else "FAIL"
    detail = "" if result["error"] is None else f"  {result['error']}"
    return f"{verdict} {result['task']:10} tools={result['tools']:<3} tokens={result['tokens']:<8} {result.get('seconds', 0)}s{detail}"


def run(client: httpx.Client, tasks: list[Task], credential: str, model: str, effort: str, max_tokens: int, out=sys.stdout) -> int:
    """Runs tasks in order until the tokens used pass max_tokens. Returns the tokens used."""
    used = 0
    for task in tasks:
        if used >= max_tokens:
            print(f"SKIP {task.name:10} token cap of {max_tokens} reached", file=out)
            continue
        result = run_task(client, task, credential, model, effort)
        used += result["tokens"]
        print(line(result), file=out, flush=True)
    print(f"total tokens {used}", file=out)
    return used


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--credential", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--effort", default="low")
    parser.add_argument("--max-tokens", type=int, required=True)
    parser.add_argument("--only", action="append", choices=[t.name for t in TASKS])
    args = parser.parse_args()
    session = os.environ.get("ECHO_SESSION")
    if not session:
        sys.exit("Set ECHO_SESSION to your echo_session cookie.")
    tasks = [t for t in TASKS if not args.only or t.name in args.only]
    # The api only accepts writes whose Origin is its public address.
    headers = {"Origin": args.base_url}
    with httpx.Client(base_url=args.base_url, cookies={"echo_session": session}, headers=headers, timeout=60) as client:
        run(client, tasks, args.credential, args.model, args.effort, args.max_tokens)


if __name__ == "__main__":
    main()

"""Local, expiring per-record write grants. These are hook policy, not an OS sandbox."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .approval import Run, digest, fresh_human_mark, now
from .git import common_dir_file
from .render import Report
from .resolve import resolve

if TYPE_CHECKING:
    from .context import Context
    from .pipeline import Pipeline

GRANT_FILE = "svod-write-grants.json"
REQUEST_FILE = "svod-write-grants-request.json"
MAX_GRANTS = 128
MAX_PATHS = 32


def read_grants(root: Path, run: Run | None = None) -> list[dict[str, Any]]:
    """Read bounded local state; invalid state supplies no authorization."""
    path = common_dir_file(root, GRANT_FILE, run)
    try:
        if path is None or path.stat().st_size > 131072:
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list) or len(data) > MAX_GRANTS:
            return []
        return [item for item in data if isinstance(item, dict)]
    except (OSError, ValueError):
        return []


def grant_paths(root: Path, record: str, at: dt.datetime | None = None,
                run: Run | None = None) -> list[Path]:
    """Resolved roots of well-formed, live grants for this exact record and instance."""
    current = at or now()
    found = []
    for item in read_grants(root, run):
        try:
            issued = dt.datetime.fromisoformat(item["issued"])
            expires = dt.datetime.fromisoformat(item["expires"])
            paths = item["paths"]
            if (item.get("record") != record or item.get("instance") != str(root.resolve())
                    or issued.tzinfo is None or expires.tzinfo is None
                    or not issued <= current < expires
                    or not 0 < (expires - issued).total_seconds() <= 1800
                    or not isinstance(paths, list) or not 0 < len(paths) <= MAX_PATHS):
                continue
            parsed = [Path(p) for p in paths if isinstance(p, str)]
            if len(parsed) != len(paths) or any(not p.is_absolute() or str(p.resolve()) != str(p)
                                               for p in parsed):
                continue
            found.extend(parsed)
        except (KeyError, TypeError, ValueError, OSError, RuntimeError):
            continue
    return found


def allow(ctx: Context, pipelines: list[Pipeline], query: str,
          duration: str, paths: list[str]) -> Report:
    """Issue one explicit 30-minute grant after a fresh native human mark, never renew it."""
    def refuse(text: str) -> Report:
        return Report(ok=False, refused=True, err=[text])

    matches = [(p, s) for p, s in resolve(ctx, pipelines, query).matches
               if s.exists and not s.archived and s.path is not None]
    if len(matches) != 1:
        return refuse("svod allow requires one unambiguous existing open record; use its full id.")
    if duration != "30m" or not 0 < len(paths) <= MAX_PATHS or any(not p.strip() for p in paths):
        return refuse("Use --for 30m and 1..32 explicit --path roots.")
    mark = fresh_human_mark(ctx.root, ctx.config.approval_window)
    target = common_dir_file(ctx.root, GRANT_FILE)
    if target is None:
        return refuse("svod allow requires local git metadata.")
    request_path = target.with_name(REQUEST_FILE)
    try:
        resolved = sorted({str(Path(p).expanduser().resolve()) for p in paths})
        subject = matches[0][1]
        snapshot = {"instance": str(ctx.root.resolve()), "record": subject.id,
                    "paths": resolved, "content": digest(subject.path, ["**/*"])}
        pending = json.loads(request_path.read_text()) if request_path.is_file() else {}
        prepared = dt.datetime.fromisoformat(pending["at"]) if pending else None
        reply_at = dt.datetime.fromisoformat(mark["at"]) if mark else None
        ready = (pending.get("request") == snapshot and prepared is not None
                 and reply_at is not None and prepared < reply_at
                 and (now() - prepared).total_seconds() <= ctx.config.approval_window * 60
                 and mark is not None and mark.get("go") is True)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError):
        return refuse("Cannot resolve grant request or local request state; "
                      "prepare valid literal paths.")
    previous = read_grants(ctx.root)
    token = {"at": mark.get("at"), "sha": mark.get("sha")} if mark else {}
    if any(item.get("human") == token for item in previous):
        return refuse("This human reply already issued a grant; ask for a fresh reply, no renewal.")
    if not ready:
        request_path.write_text(json.dumps({"at": now().isoformat(), "request": snapshot}),
                                encoding="utf-8")
        return refuse(f"Prepared write grant request for {subject.id}: {', '.join(resolved)}. "
                      "Show these exact roots to the person, ask for a fresh native go-ahead, "
                      "then repeat the unchanged svod allow command. No grant issued.")
    if len(previous) >= MAX_GRANTS:
        return refuse("Local write grant limit reached; a person must clear expired grant state.")
    issued = now()
    previous.append({"instance": str(ctx.root.resolve()), "record": matches[0][1].id,
                     "issued": issued.isoformat(),
                     "expires": (issued + dt.timedelta(minutes=30)).isoformat(),
                     "paths": resolved, "human": token})
    target.write_text(json.dumps(previous), encoding="utf-8")
    return Report(ok=True, out=[f"Write grant for {matches[0][1].id} until "
                                f"{previous[-1]['expires']}: {', '.join(resolved)}"])

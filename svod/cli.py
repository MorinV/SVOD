"""Command line entry of svod."""
from __future__ import annotations

import argparse
import io
import json
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn

from svod import __version__
from svod.hooks import EVENTS, run as run_hook
from svod.launcher import launch
from svod.locale import error_locale

if TYPE_CHECKING:
    from svod.context import Context
    from svod.pipeline import Pipeline
    from svod.render import Report

PROG = "svod"
EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2
HOOK_FLAG = "--hook"
CMD_VALIDATE = "validate"
CMD_STATUS = "status"
CMD_NEXT = "next"
CMD_RECORD = "record"
RECORD_NEW = "new"
CMD_ACTIVE = "active"
CMD_RENDER = "render"
CMD_INIT = "init"
CMD_APPROVE = "approve"
CMD_ANSWER = "answer"
CMD_ASK = "ask"
CMD_HOOK = "hook"
CMD_INSTALL = "install"
CMD_UPDATE = "update"
CMD_MIGRATE = "migrate"
CMD_NEW = "new"
CMD_LOCAL = "local"
CMD_DO = "do"
CMD_KNOWLEDGE = "knowledge"
CMD_RETRO = "retro"
CMD_DOCTOR = "doctor"
KNOWLEDGE_INDEX = "index"
KNOWLEDGE_ADD = "add"
KNOWLEDGE_NOTE = "note"
KNOWLEDGE_LIST = "list"
DELIVERY_COMMANDS = (CMD_INSTALL, CMD_UPDATE)
ERROR_INDENT = "  "


def emit_json_error(code: str, query: str | None = None) -> int:
    """Structured status failures contain only a safe reason code."""
    from svod.status_json import error_json
    print(json.dumps(error_json(code, query), ensure_ascii=False))
    return EXIT_USAGE


def positive_seconds(text: str) -> float:
    """A positive number of seconds given on the command line."""
    try:
        value = float(text)
    except ValueError:
        value = 0
    if not value > 0 or value == float("inf"):
        raise argparse.ArgumentTypeError(f"not a positive number of seconds: {text}")
    return value


class StatusParser(argparse.ArgumentParser):
    """Preserve argparse text behavior except explicit JSON status failures."""

    json_errors = False

    def error(self, message: str) -> NoReturn:
        """Exit with a safe JSON failure in JSON status mode, else with argparse usage text."""
        if self.json_errors:
            raise SystemExit(emit_json_error("invalid_arguments"))
        super().error(message)


def build_parser() -> StatusParser:
    """Argument parser with one subcommand per mode."""
    parser = StatusParser(prog=PROG)
    parser.add_argument("--root", help="store root holding svod.yaml")
    parser.add_argument("--version", action="version", version=f"{PROG} {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    new = commands.add_parser(CMD_NEW, help="create a new store from packaged templates")
    new.add_argument("directory", help="new destination directory; must not exist")
    new.add_argument("--template", choices=("local", "task", "standard"), default="local")
    local = commands.add_parser(CMD_LOCAL, help="run the compact local workflow")
    local.add_argument("action", choices=("prepare", "checks", "verify", "deliver"))
    local.add_argument("query", help="exact task path, name or supported key")
    do = commands.add_parser(CMD_DO, help="run an action script of the profile for a subject")
    do.add_argument("name", nargs="?", metavar="action",
                    help="action name: <profile>/actions/<name>.sh")
    do.add_argument("query", nargs="?", help="tracker key or subject name, as for status")
    do.add_argument("extra", nargs="*", help="arguments passed to the script, after --")
    do.add_argument("--list", action="store_true", help="list the actions of the profile")
    do.add_argument("--force", action="store_true",
                    help="run an action of a step the subject has not reached yet")
    do.add_argument("--timeout", type=positive_seconds, default=None, metavar="SECONDS",
                    help="stop the script after this many seconds (default 600)")
    commands.add_parser(CMD_VALIDATE, help="check declarations, locale keys and registries")
    status = commands.add_parser(CMD_STATUS, help="position of a task or container")
    status.add_argument("query", help="tracker key or container name")
    status.add_argument("--format", choices=("text", "json"), default="text")
    nxt = commands.add_parser(CMD_NEXT, help="the next action of a task or container, one line")
    nxt.add_argument("query", help="tracker key or container name")
    nxt.add_argument("--format", choices=("text", "json"), default="text")
    add_record_parser(commands)
    active = commands.add_parser(CMD_ACTIVE, help="summary of open work")
    active.add_argument("--all", action="store_true", help="expand the team's work")
    active.add_argument(HOOK_FLAG, action="store_true", help="SessionStart hook JSON")
    render = commands.add_parser(CMD_RENDER, help="documentation block of a pipeline")
    render.add_argument("pipeline", help="pipeline name")
    render.add_argument("--write", action="store_true",
                        help="replace the block between its markers in every store document")
    approve = commands.add_parser(CMD_APPROVE,
                                  help="record an approval a person left in the chat")
    approve.add_argument("query", help="tracker key or subject name")
    approve.add_argument("--step", help="approval step id; first pending approval by default")
    approve.add_argument("--confirm", action="store_true",
                         help="without a fresh mark, ask the person at the terminal to confirm")
    ask = commands.add_parser(CMD_ASK, help="add a question before work to the questions file")
    ask.add_argument("query", help="tracker key or subject name")
    ask.add_argument("question", nargs="*", help="the question, one line")
    ask.add_argument("--context", default="",
                     help="one line under the question: options and what each would change")
    ask.add_argument("--none", action="store_true",
                     help="write none: there is nothing to ask")
    answer = commands.add_parser(CMD_ANSWER,
                                 help="record a person's answer to a question before work")
    answer.add_argument("query", help="tracker key or subject name")
    answer.add_argument("--q", dest="number", type=int, required=True,
                        help="number of the question in the questions file, from 1")
    answer.add_argument("text", nargs="+", help="the answer as the person gave it in the chat")
    hook = commands.add_parser(CMD_HOOK, help="answer an agent hook event read as JSON on stdin")
    hook.add_argument("event", choices=EVENTS, help="hook event")
    init = commands.add_parser(CMD_INIT, help="create the local config named in svod.yaml")
    init.add_argument("--login", help="login of the person")
    init.add_argument("--email", help="email of the person, git user.email by default")
    init.add_argument("--force", action="store_true", help="overwrite an existing local config")
    add_wizard_arguments(init)
    doctor = commands.add_parser(CMD_DOCTOR, help="check that the store is ready to work in")
    doctor.add_argument("--format", choices=("text", "json"), default="text")
    for name, text in ((CMD_INSTALL, "put a copy of the engine into the store (.svod)"),
                       (CMD_UPDATE, "replace the copy of the engine in the store")):
        delivery = commands.add_parser(name, help=text)
        delivery.add_argument("--from", dest="source",
                              help="git URL or local clone of Svod; the recorded source by default")
        delivery.add_argument("--to", dest="ref",
                              help="tag or branch; the newest vX.Y.Z by default")
    migrate = commands.add_parser(CMD_MIGRATE,
                                  help="apply the store migrations of the versions after a version")
    migrate.add_argument("--since", required=True, help="version the store was used with")
    add_knowledge_parser(commands)
    add_retro_parser(commands)
    return parser


def add_record_parser(commands: argparse._SubParsersAction) -> None:
    """The record command with its new action."""
    record = commands.add_parser(CMD_RECORD, help="records of the pipelines")
    actions = record.add_subparsers(dest="action", required=True)
    new = actions.add_parser(RECORD_NEW,
                             help="create a record from <profile>/records/<pipeline>/")
    new.add_argument("pipeline", help="pipeline name")
    new.add_argument("name", help="name of the record: one directory name")
    new.add_argument("--services", help="services separated by commas")
    new.add_argument("--parent", default="", help="id of the parent record")
    new.add_argument("--kind", default="", help="kind of the record; the pipeline name by default")
    new.add_argument("--tags", help="tags separated by commas")
    new.add_argument("--key", default="", help="tracker key")


def add_retro_parser(commands: argparse._SubParsersAction) -> None:
    """The retro command: list the proposals, or decide one of them."""
    retro = commands.add_parser(CMD_RETRO,
                                help="propose profile changes from the evidence log")
    retro.add_argument("query", nargs="?", help="tracker key or subject name, as for status")
    retro.add_argument("--all", action="store_true", help="every open work of the store")
    decision = retro.add_mutually_exclusive_group()
    decision.add_argument("--accept", type=int, metavar="n",
                          help="accept proposal n of the list; prints the change to apply")
    decision.add_argument("--reject", type=int, metavar="n", help="reject proposal n of the list")
    retro.add_argument("--note", help="note kept with the decision")


def add_wizard_arguments(init: argparse.ArgumentParser) -> None:
    """The flags of svod init --wizard; any of them runs the wizard without a terminal."""
    from svod.wizard import HOOKS_CHOICES
    init.add_argument("--wizard", action="store_true",
                      help="ask for the services, autonomy, checks and hooks too")
    init.add_argument("--service", dest="services", action="append", metavar="NAME=PATH",
                      help="a service repository next to the store; repeatable")
    init.add_argument("--autonomy", action="append", metavar="PIPELINE=LEVEL",
                      help="guided, supervised or autonomous for a pipeline; repeatable")
    init.add_argument("--checks", action="append", metavar="SERVICE=COMMAND",
                      help="the check command of a service; repeatable")
    init.add_argument("--hooks", choices=HOOKS_CHOICES,
                      help="register the Claude Code hooks for the project, globally, or not")


def add_knowledge_parser(commands: argparse._SubParsersAction) -> None:
    """The knowledge command with its index, add, note and list actions."""
    knowledge = commands.add_parser(CMD_KNOWLEDGE, help="notes of the store in knowledge/")
    actions = knowledge.add_subparsers(dest="action", required=True)
    actions.add_parser(KNOWLEDGE_INDEX, help="rewrite the table in knowledge/INDEX.md")
    add = actions.add_parser(KNOWLEDGE_ADD, help="copy a markdown file into knowledge/")
    add.add_argument("file", help="markdown file to copy")
    add.add_argument("--tags", required=True, help="tags separated by commas")
    add.add_argument("--title", help="title; the frontmatter title or first heading by default")
    add.add_argument("--source", help="id of the work the note comes from")
    note = actions.add_parser(KNOWLEDGE_NOTE, help="write a short note into knowledge/")
    note.add_argument("text", help="text of the note")
    note.add_argument("--tags", required=True, help="tags separated by commas")
    note.add_argument("--title", required=True, help="title; names the file")
    note.add_argument("--source", help="id of the work the note comes from")
    listing = actions.add_parser(KNOWLEDGE_LIST, help="list the notes")
    listing.add_argument("--tags", help="only notes sharing one of these tags")


def print_errors(header: str, errors: Iterable[str]) -> None:
    """Header and indented error lines on stderr."""
    print(header, file=sys.stderr)
    for error in errors:
        print(f"{ERROR_INDENT}{error}", file=sys.stderr)


def emit(report: Report) -> int:
    """Print a report; exit 0 when ok, 1 for a refusal, 2 otherwise."""
    for line in report.out:
        print(line)
    for line in report.err:
        print(line, file=sys.stderr)
    if report.ok:
        return EXIT_OK
    return EXIT_FINDINGS if report.refused else EXIT_USAGE


def render(ctx: Context, pipelines: list[Pipeline], args: argparse.Namespace) -> int:
    """Print the block of a pipeline, or write it into every document holding its markers."""
    from svod import keys
    from svod.document import MARKER_BEGIN, block, relative_or_absolute, write_blocks

    pipeline = next((p for p in pipelines if p.name == args.pipeline), None)
    if pipeline is None:
        print(ctx.locale.text(keys.RENDER_UNKNOWN, name=args.pipeline), file=sys.stderr)
        return EXIT_USAGE
    if not args.write:
        print("\n".join(block(ctx, pipeline)))
        return EXIT_OK
    results = write_blocks(ctx, pipeline)
    if not results:
        print(ctx.locale.text(keys.RENDER_NO_MARKERS, name=pipeline.name,
                              marker=MARKER_BEGIN.format(name=pipeline.name)), file=sys.stderr)
        return EXIT_FINDINGS
    for path, changed in results:
        key = keys.RENDER_WRITTEN if changed else keys.RENDER_CURRENT
        print(ctx.locale.text(key, path=relative_or_absolute(ctx.root, path)))
    return EXIT_OK


def next_action(ctx: Context, pipelines: list[Pipeline], query: str, form: str) -> int:
    """Print the position status shows, one line per subject (one JSON object per line).

    The lines come from the very collection status renders. Exit 0, or 2 with the errors of
    status when no position is shown.
    """
    from svod.render import next_fields, one_line
    from svod.status import collect_status

    collection = collect_status(ctx, pipelines, query)
    if not collection.report.ok:
        return emit(collection.report)
    for item in collection.items:
        if item.position is None:
            continue
        if form == "json":
            print(json.dumps(next_fields(ctx.locale, item.position, item.skills),
                             ensure_ascii=False))
        else:
            print(one_line(ctx.locale, item.position, item.skills))
    return EXIT_OK


def do_action(ctx: Context, pipelines: list[Pipeline], args: argparse.Namespace) -> int:
    """List the actions, or run one for the one existing subject the query resolves to.

    An action named by a step the subject has not reached yet is refused with do.not_current
    unless --force is given; with it the warning is printed and the script runs. Returns the
    exit code of the script; 2 for an unknown action, a query matching no subject or several,
    a step not reached without --force and a script that could not start.
    """
    from svod import keys
    from svod.actions import (ACTION_SUFFIX, ACTION_TIMEOUT, actions_dir, list_actions,
                              run_action, script_path, step_ahead)
    from svod.document import relative_or_absolute
    from svod.resolve import resolve

    locale = ctx.locale
    if args.list:
        actions = list_actions(ctx)
        if not actions:
            print(locale.text(keys.DO_LIST_NONE,
                              dir=relative_or_absolute(ctx.root, actions_dir(ctx))))
        for action in actions:
            print(locale.text(keys.DO_LIST_ITEM, name=action.name, description=action.description
                              or locale.text(keys.DO_LIST_NO_DESCRIPTION)))
        return EXIT_OK
    if not args.name or not args.query:
        print(locale.text(keys.DO_USAGE), file=sys.stderr)
        return EXIT_USAGE
    if script_path(ctx, args.name) is None:
        script = actions_dir(ctx) / f"{args.name}{ACTION_SUFFIX}"
        print(locale.text(keys.DO_UNKNOWN, name=args.name,
                          script=relative_or_absolute(ctx.root, script)), file=sys.stderr)
        return EXIT_USAGE
    found = resolve(ctx, pipelines, args.query)
    matches = [(p, s) for p, s in found.matches if s.exists]
    if not matches:
        print(locale.text(keys.STATUS_NOT_FOUND, query=args.query), file=sys.stderr)
        return EXIT_USAGE
    if len(matches) > 1:
        print_errors(locale.text(keys.STATUS_AMBIGUOUS),
                     [locale.text(keys.STATUS_CANDIDATE, id=s.id) for _, s in matches])
        return EXIT_USAGE
    pipeline, subject = matches[0]
    ahead = step_ahead(ctx, pipeline, subject, args.name)
    if ahead is not None:
        print(locale.text(keys.DO_NOT_CURRENT, name=args.name, step=ahead.step, id=subject.id,
                          current=ahead.current or locale.text(keys.DO_NO_CURRENT)),
              file=sys.stderr)
        if not args.force:
            return EXIT_USAGE
    timeout = args.timeout or ACTION_TIMEOUT
    try:
        run = run_action(ctx, args.name, pipeline, subject, args.extra, timeout=timeout)
    except OSError as exc:
        print(locale.text(keys.DO_FAILED, name=args.name, reason=f"{type(exc).__name__}: {exc}"),
              file=sys.stderr)
        return EXIT_USAGE
    if run.timed_out:
        print(locale.text(keys.DO_TIMEOUT, name=args.name, seconds=f"{timeout:g}"),
              file=sys.stderr)
    return run.code


def retro(ctx: Context, pipelines: list[Pipeline], args: argparse.Namespace) -> int:
    """Print the proposals of the retrospective, or record a decision on one of them.

    Returns 0 for a list or a recorded decision; 2 for wrong arguments, a query matching no
    subject or several, a number outside the list and profile rules or decisions that do not load.
    """
    from svod import keys
    from svod.document import relative_or_absolute
    from svod.errors import LoadError
    from svod.resolve import resolve
    from svod.retro import decisions, engine

    locale = ctx.locale
    number = args.accept if args.accept is not None else args.reject
    if bool(args.query) == bool(args.all) or (args.note and number is None):
        print(locale.text(keys.RETRO_USAGE), file=sys.stderr)
        return EXIT_USAGE
    if args.all:
        works = engine.open_works(ctx, pipelines)
    else:
        found = resolve(ctx, pipelines, args.query)
        works = [(p, s) for p, s in found.matches if s.exists]
        if not works:
            print(locale.text(keys.STATUS_NOT_FOUND, query=args.query), file=sys.stderr)
            return EXIT_USAGE
        if found.ambiguous:
            print_errors(locale.text(keys.STATUS_AMBIGUOUS),
                         [locale.text(keys.STATUS_CANDIDATE, id=s.id) for _, s in works])
            return EXIT_USAGE
    try:
        rules = engine.load_rules(ctx.config.profile)
        taken = decisions.read_decisions(ctx.root)
    except LoadError as exc:
        print_errors(locale.text(keys.ERROR_LOAD), exc.errors)
        return EXIT_USAGE
    proposals, failures = engine.review(ctx, works, rules)
    for failure in failures:
        print(locale.text(keys.RETRO_RULE_FAILED, reason=failure), file=sys.stderr)
    shown = engine.pending(proposals, decisions.decided(taken))
    if number is None:
        print("\n".join(engine.render(locale, shown) or [locale.text(keys.RETRO_NONE)]))
        return EXIT_OK
    if not 1 <= number <= len(shown):
        print(locale.text(keys.RETRO_NO_NUMBER, number=number, count=len(shown)),
              file=sys.stderr)
        return EXIT_USAGE
    proposal = shown[number - 1]
    decision = decisions.ACCEPTED if args.accept is not None else decisions.REJECTED
    path = decisions.record_decision(ctx.root, proposal, decision, args.note)
    print(locale.text(keys.RETRO_RECORDED, decision=decision, number=number, rule=proposal.rule,
                      path=relative_or_absolute(ctx.root, path)))
    lines = engine.hint(locale, proposal) if decision == decisions.ACCEPTED else []
    if lines:
        print("\n".join([locale.text(keys.RETRO_HINT), *lines]))
    return EXIT_OK


def ask(prompt: str) -> str:
    """Answer typed at the terminal, stripped; empty at end of input."""
    try:
        return input(prompt).strip()
    except EOFError:
        return ""


def init_local(root: Path, args: argparse.Namespace) -> int:
    """Create the local config from the arguments, asking at a terminal when no login is given.

    --wizard, or any flag of the wizard, runs svod.wizard instead.
    """
    from svod import keys
    from svod.config import FIELD_LOCAL_CONFIG, LOCAL_EMAIL, LOCAL_LOGIN, load_config, write_local
    from svod.context import Context
    from svod.errors import LoadError
    from svod.identity import git_email

    from svod.wizard import WIZARD_FLAGS, wizard
    if args.wizard or any(getattr(args, name) for name in WIZARD_FLAGS):
        return wizard(root, args)
    locale = error_locale(root)
    try:
        config = load_config(root, local=False)
    except LoadError as exc:
        print_errors(locale.text(keys.ERROR_LOAD), exc.errors)
        return EXIT_USAGE
    if config.local_path is None:
        print(locale.text(keys.INIT_NOT_CONFIGURED, field=FIELD_LOCAL_CONFIG), file=sys.stderr)
        return EXIT_USAGE
    path = config.local_path
    if path.exists() and not args.force:
        print(locale.text(keys.INIT_EXISTS, path=path), file=sys.stderr)
        return EXIT_FINDINGS
    interactive = args.login is None and sys.stdin.isatty()
    login = args.login or (ask(locale.text(keys.INIT_PROMPT_LOGIN)) if interactive else "")
    if not login:
        print(locale.text(keys.INIT_NEED_LOGIN), file=sys.stderr)
        return EXIT_USAGE
    fallback = git_email(Context(config, locale))
    typed = ask(locale.text(keys.INIT_PROMPT_EMAIL, default=fallback)) if interactive else ""
    write_local(path, {LOCAL_LOGIN: login, LOCAL_EMAIL: args.email or typed or fallback})
    print(locale.text(keys.INIT_WRITTEN, path=path))
    return EXIT_OK


def migrate(root: Path, since: str) -> int:
    """Apply the migrations after since up to this engine; print what they changed."""
    from svod import keys
    from svod.migrations import apply
    from svod.versions import parse

    locale = error_locale(root)
    if parse(since) is None:
        print(locale.text(keys.MIGRATE_BAD_VERSION, version=since), file=sys.stderr)
        return EXIT_USAGE
    try:
        applied = apply(root, since, __version__)
    except Exception as exc:
        print(locale.text(keys.MIGRATE_FAILED, version=__version__,
                          reason=f"{type(exc).__name__}: {exc}"), file=sys.stderr)
        return EXIT_FINDINGS
    if not applied:
        print(locale.text(keys.MIGRATE_NONE, old=since, new=__version__))
    for version, changes in applied:
        print(locale.text(keys.MIGRATE_VERSION, version=version))
        for change in changes:
            print(locale.text(change.key, **change.facts))
    return EXIT_OK


def knowledge(root: Path, args: argparse.Namespace) -> int:
    """Run one knowledge action; the index is rewritten after a note is added."""
    from svod import keys
    from svod import knowledge as kb
    from svod.config import load_config
    from svod.document import relative_or_absolute
    from svod.errors import LoadError

    locale = error_locale(root)
    try:
        config = load_config(root)
    except LoadError as exc:
        print_errors(locale.text(keys.ERROR_LOAD), exc.errors)
        return EXIT_USAGE
    directory = config.knowledge_dir
    if args.action == KNOWLEDGE_LIST:
        wanted = set(kb.tag_list(args.tags or ""))
        found = [e for e in kb.entries(root, directory) if not wanted or wanted & set(e.tags)]
        for entry in found:
            print(locale.text(keys.KNOWLEDGE_ITEM, title=entry.title, path=entry.rel,
                              tags=kb.TAGS_JOIN.join(entry.tags), date=entry.date,
                              status=entry.status))
        if not found:
            print(locale.text(keys.KNOWLEDGE_NONE))
        return EXIT_OK
    if args.action in (KNOWLEDGE_ADD, KNOWLEDGE_NOTE):
        try:
            if args.action == KNOWLEDGE_ADD:
                path = kb.add(root, args.file, args.tags, args.title, args.source, directory)
            else:
                path = kb.note(root, args.text, args.tags, args.title, args.source, directory)
        except FileNotFoundError:
            print(locale.text(keys.KNOWLEDGE_NO_FILE, path=args.file), file=sys.stderr)
            return EXIT_USAGE
        except FileExistsError as exc:
            print(locale.text(keys.KNOWLEDGE_EXISTS, path=relative_or_absolute(root, exc.filename)),
                  file=sys.stderr)
            return EXIT_FINDINGS
        print(locale.text(keys.KNOWLEDGE_ADDED, path=relative_or_absolute(root, path)))
    path, changed = kb.write_index(root, directory)
    print(locale.text(keys.RENDER_WRITTEN if changed else keys.RENDER_CURRENT,
                      path=relative_or_absolute(root, path)))
    return EXIT_OK


def run(args: argparse.Namespace) -> int:
    """Dispatch the parsed command; return the exit code."""
    from svod import keys
    from svod.active import hook_payload, summarize
    from svod.paths import CONFIG_FILE, find_root
    from svod.context import Context
    from svod.errors import LoadError
    from svod.loader import load_runtime
    from svod.locale import bootstrap_locale
    from svod.render import status_report

    if args.command == CMD_NEW:
        from svod.scaffold import scaffold
        try:
            print(scaffold(args.directory, args.template))
            return EXIT_OK
        except (OSError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return EXIT_FINDINGS
    root: Path | None
    if args.root:
        root = Path(args.root).resolve()
        root = root if (root / CONFIG_FILE).is_file() else None
    else:
        root = find_root(Path.cwd())
    if root is None:
        if args.command == CMD_STATUS and getattr(args, "format", "text") == "json":
            return emit_json_error("invalid_root", args.query)
        print(bootstrap_locale().text(keys.ERROR_NOT_ROOT), file=sys.stderr)
        return EXIT_USAGE
    if args.command == CMD_INIT:
        return init_local(root, args)
    if args.command == CMD_DOCTOR:
        from svod.doctor import doctor
        return doctor(root, args.format)
    if args.command in DELIVERY_COMMANDS:
        from svod.update import deliver
        return deliver(root, error_locale(root), args.command == CMD_INSTALL, args.source,
                       args.ref)
    if args.command == CMD_MIGRATE:
        return migrate(root, args.since)
    if args.command == CMD_KNOWLEDGE:
        return knowledge(root, args)
    if args.command == CMD_LOCAL:
        from svod import local_runner, local_workflow
        try:
            result = getattr(local_runner, args.action)(root, args.query)
            print(json.dumps(result, ensure_ascii=False))
            return EXIT_OK if result.get("passed", True) else EXIT_FINDINGS
        except LoadError as exc:
            print_errors(error_locale(root).text(keys.ERROR_LOAD), exc.errors)
            return EXIT_USAGE
        except local_workflow.ERRORS as exc:
            print(str(exc), file=sys.stderr)
            return EXIT_FINDINGS

    copy_errors = []
    if args.command == CMD_VALIDATE:
        from svod.vendor import copy_errors as vendored_errors
        copy_errors = vendored_errors(root)
    try:
        runtime = load_runtime(root)
    except LoadError as exc:
        locale = error_locale(root)
        if args.command == CMD_VALIDATE:
            errors = exc.errors + copy_errors
            print_errors(locale.text(keys.VALIDATE_FAILED, count=len(errors)), errors)
            return EXIT_FINDINGS
        if args.command == CMD_STATUS and getattr(args, "format", "text") == "json":
            return emit_json_error("invalid_load", args.query)
        print_errors(locale.text(keys.ERROR_LOAD), exc.errors)
        return EXIT_USAGE

    ctx = Context(runtime.config, runtime.locale, bindings=runtime.bindings,
                  pipelines=runtime.by_name())
    if args.command == CMD_VALIDATE:
        from svod.actions import action_errors
        copy_errors += action_errors(ctx, runtime.pipelines)
        if copy_errors:
            print_errors(runtime.locale.text(keys.VALIDATE_FAILED, count=len(copy_errors)),
                         copy_errors)
            return EXIT_FINDINGS
        print(runtime.locale.text(keys.VALIDATE_OK, count=len(runtime.pipelines)))
        return EXIT_OK
    if args.command == CMD_STATUS:
        if getattr(args, "format", "text") == "json":
            from svod.status import collect_status
            from svod.status_json import to_json
            data = to_json(collect_status(ctx, runtime.pipelines, args.query))
            print(json.dumps(data, ensure_ascii=False, allow_nan=False))
            return data["report"]["exit_code"]
        return emit(status_report(ctx, runtime.pipelines, args.query))
    if args.command == CMD_NEXT:
        return next_action(ctx, runtime.pipelines, args.query, args.format)
    if args.command == CMD_RECORD:
        from svod.records import NewRecord, new_record, split_list
        return emit(new_record(ctx, runtime.pipelines, NewRecord(
            args.pipeline, args.name, services=split_list(args.services), parent=args.parent,
            kind=args.kind, tags=split_list(args.tags), key=args.key)))
    if args.command == CMD_RENDER:
        return render(ctx, runtime.pipelines, args)
    if args.command == CMD_DO:
        return do_action(ctx, runtime.pipelines, args)
    if args.command == CMD_RETRO:
        return retro(ctx, runtime.pipelines, args)
    if args.command == CMD_APPROVE:
        from svod.approve import approve
        return emit(approve(ctx, runtime.pipelines, args.query, step=args.step,
                            confirm=args.confirm))
    if args.command == CMD_ASK:
        from svod.questions import ask
        return emit(ask(ctx, runtime.pipelines, args.query, " ".join(args.question),
                        args.context, args.none))
    if args.command == CMD_ANSWER:
        from svod.questions import answer
        return emit(answer(ctx, runtime.pipelines, args.query, args.number, " ".join(args.text)))
    lines = summarize(ctx, runtime.pipelines, args.all)
    if not args.hook and not any(p.active for p in runtime.pipelines):
        lines.append(runtime.locale.text(keys.ACTIVE_NONE))
    if args.hook:
        from svod.notice import update_notice, with_notice
        lines = with_notice(lines, update_notice(runtime.config, runtime.locale))
    if lines:
        print(hook_payload(runtime.locale, lines) if args.hook else "\n".join(lines))
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    """Hand over to the copy of the store, or parse arguments and run.

    Exits quietly in hook mode without PyYAML.
    """
    argv = sys.argv[1:] if argv is None else list(argv)
    json_status = CMD_STATUS in argv and (
        "--format=json" in argv
        or any(a == "--format" and b == "json" for a, b in zip(argv, argv[1:], strict=False)))
    launched = launch(argv)
    if launched.code is not None:
        return launched.code
    parser = build_parser()
    parser.json_errors = json_status
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for command_parser in action.choices.values():
                command_parser.json_errors = json_status
    args = parser.parse_args(argv)
    if args.command == CMD_HOOK:
        stream = io.StringIO(launched.stdin) if launched.stdin is not None else None
        return run_hook(args.event, args.root, stream)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())

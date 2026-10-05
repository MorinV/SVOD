"""Command line entry of svod."""
import argparse
import importlib.util
import sys
from pathlib import Path

PROG = "svod"
EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2
HOOK_FLAG = "--hook"
MISSING_YAML = "PyYAML is required: python3 -m pip install pyyaml"
CMD_VALIDATE = "validate"
CMD_STATUS = "status"
CMD_ACTIVE = "active"
CMD_RENDER = "render"
CMD_INIT = "init"
CMD_APPROVE = "approve"
YAML_MODULE = "yaml"
ERROR_INDENT = "  "


def build_parser():
    """Argument parser with one subcommand per mode."""
    parser = argparse.ArgumentParser(prog=PROG)
    parser.add_argument("--root", help="store root holding svod.yaml")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(CMD_VALIDATE, help="check declarations, locale keys and registries")
    status = commands.add_parser(CMD_STATUS, help="position of a task or container")
    status.add_argument("query", help="tracker key or container name")
    active = commands.add_parser(CMD_ACTIVE, help="summary of open work")
    active.add_argument("--all", action="store_true", help="expand the team's work")
    active.add_argument(HOOK_FLAG, action="store_true", help="SessionStart hook JSON")
    render = commands.add_parser(CMD_RENDER, help="documentation block of a pipeline")
    render.add_argument("pipeline", help="pipeline name")
    render.add_argument("--write", action="store_true",
                        help="replace the block between its markers in every store document")
    approve = commands.add_parser(CMD_APPROVE,
                                  help="record the plan approval a person left in the chat")
    approve.add_argument("query", help="tracker key or subject name")
    init = commands.add_parser(CMD_INIT, help="create the local config named in svod.yaml")
    init.add_argument("--login", help="login of the person")
    init.add_argument("--email", help="email of the person, git user.email by default")
    init.add_argument("--force", action="store_true", help="overwrite an existing local config")
    return parser


def error_locale(root):
    """Core locale for reporting errors: the configured one when readable."""
    from svod.config import load_config
    from svod.errors import LoadError
    from svod.locale import bootstrap_locale, load_core_locale
    try:
        return load_core_locale(load_config(root, local=False).locale)
    except LoadError:
        return bootstrap_locale()


def print_errors(header, errors):
    """Header and indented error lines on stderr."""
    print(header, file=sys.stderr)
    for error in errors:
        print(f"{ERROR_INDENT}{error}", file=sys.stderr)


def emit(report):
    """Print a report; exit 0 when ok, 1 for a refusal, 2 otherwise."""
    for line in report.out:
        print(line)
    for line in report.err:
        print(line, file=sys.stderr)
    if report.ok:
        return EXIT_OK
    return EXIT_FINDINGS if report.refused else EXIT_USAGE


def render(ctx, pipelines, args):
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


def ask(prompt):
    """Answer typed at the terminal, stripped; empty at end of input."""
    try:
        return input(prompt).strip()
    except EOFError:
        return ""


def init_local(root, args):
    """Create the local config from the arguments, asking at a terminal when no login is given."""
    from svod import keys
    from svod.config import FIELD_LOCAL_CONFIG, LOCAL_EMAIL, LOCAL_LOGIN, load_config, write_local
    from svod.context import Context
    from svod.errors import LoadError
    from svod.identity import git_email

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


def run(args):
    """Dispatch the parsed command; return the exit code."""
    from svod import keys
    from svod.active import hook_payload, summarize
    from svod.config import CONFIG_FILE, find_root
    from svod.context import Context
    from svod.errors import LoadError
    from svod.loader import load_runtime
    from svod.locale import bootstrap_locale
    from svod.render import status_report

    if args.root:
        root = Path(args.root).resolve()
        root = root if (root / CONFIG_FILE).is_file() else None
    else:
        root = find_root(Path.cwd())
    if root is None:
        print(bootstrap_locale().text(keys.ERROR_NOT_ROOT), file=sys.stderr)
        return EXIT_USAGE
    if args.command == CMD_INIT:
        return init_local(root, args)

    try:
        runtime = load_runtime(root)
    except LoadError as exc:
        locale = error_locale(root)
        if args.command == CMD_VALIDATE:
            print_errors(locale.text(keys.VALIDATE_FAILED, count=len(exc.errors)), exc.errors)
            return EXIT_FINDINGS
        print_errors(locale.text(keys.ERROR_LOAD), exc.errors)
        return EXIT_USAGE

    if args.command == CMD_VALIDATE:
        print(runtime.locale.text(keys.VALIDATE_OK, count=len(runtime.pipelines)))
        return EXIT_OK
    ctx = Context(runtime.config, runtime.locale, bindings=runtime.bindings,
                  pipelines=runtime.by_name())
    if args.command == CMD_STATUS:
        return emit(status_report(ctx, runtime.pipelines, args.query))
    if args.command == CMD_RENDER:
        return render(ctx, runtime.pipelines, args)
    if args.command == CMD_APPROVE:
        from svod.approve import approve
        return emit(approve(ctx, runtime.pipelines, args.query))
    lines = summarize(ctx, runtime.pipelines, args.all)
    if lines:
        print(hook_payload(runtime.locale, lines) if args.hook else "\n".join(lines))
    return EXIT_OK


def main(argv=None):
    """Parse arguments and run; exit quietly in hook mode without PyYAML."""
    argv = sys.argv[1:] if argv is None else list(argv)
    if importlib.util.find_spec(YAML_MODULE) is None:
        if HOOK_FLAG in argv:
            return EXIT_OK
        print(MISSING_YAML, file=sys.stderr)
        return EXIT_USAGE
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())

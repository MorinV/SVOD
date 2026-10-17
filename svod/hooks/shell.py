"""Shell commands as the pre-tool guard sees them: tokens, read-only programs, named paths.

Also the narrow exception for a python script that only reads an approval metadata file: its
source is parsed and every use of the file name must be an inline Path read.
"""
import ast
import re
import shlex
from pathlib import Path

from .protocol import absolute

SEGMENT = r"[^\n|;&]*?"
IN_PLACE = r"\s(?:-[A-Za-z]*i\b|--in-?place\b)"
PATH_END = r"(?![\w.])"
REDIRECT_TO = r">>?\s*['\"]?[^\s'\"<>|;&]*"
IN_PLACE_TOOLS = r"\b(?:sed|perl|yq)\b"
TEE = r"\btee\b"
COPY_TO = r"\b(?:cp|mv)\b"
COPY_END = r"['\"]?\s*(?:$|[|;&])"
QUOTED = r"['\"][^'\"\n]*{path}['\"]"
PYTHON_SCRIPT = re.compile(r"\bpython[\d.]*\b" + SEGMENT + r"(?:\s-c\b|<<)", re.MULTILINE)
SHELL_OPERATORS_NEWLINE = "\n"
SHELL_OPERATORS = frozenset({"|", "||", "&&", ";", ";;", "&", "|&", "(", ")", "{", "}"})
REDIRECT_CHAR = ">"
ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
OPTION_PREFIX = "-"
OPTION_VALUE = "="
PATH_SEPARATOR = "/"
WORD_GAP = " "
MAX_TOKENS = 500
COMMAND_PREFIXES = frozenset({"env", "command", "builtin", "time", "nice", "exec"})
READ_ONLY_COMMANDS = frozenset({
    "cat", "ls", "grep", "egrep", "fgrep", "rg", "ag", "head", "tail", "less", "more", "wc",
    "find", "stat", "file", "diff", "cmp", "pwd", "which", "type", "whereis", "echo", "printf",
    "true", "false", "test", "[", "[[", "cd", "pushd", "popd", "export", "set", "unset", "date",
    "sleep", "tree", "du", "df", "sort", "uniq", "cut", "tr", "awk", "sed", "jq", "yq",
    "basename", "dirname", "realpath", "readlink", "md5sum", "sha256sum", "shasum", "hexdump",
    "xxd", "strings", "column", "nl", "tac", "rev", "comm", "join", "paste", "fold", "seq",
    "uname", "hostname", "whoami", "id", "git", "svod",
})
GIT_COMMAND = "git"
GIT_VALUE_OPTIONS = ("-C", "-c")
GIT_WRITE_SUBCOMMANDS = frozenset({
    "checkout", "switch", "reset", "stash", "merge", "rebase", "cherry-pick", "revert",
    "apply", "am", "pull", "clean", "rm", "mv", "restore",
})
FIND_COMMAND = "find"
FIND_WRITE_FLAGS = frozenset({"-delete", "-exec", "-execdir", "-ok", "-okdir"})
IN_PLACE_COMMANDS = frozenset({"sed", "perl", "yq"})
IN_PLACE_RE = re.compile(IN_PLACE)
PYTHON_HEREDOC = re.compile(
    r"<<[ \t]*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1[ \t]*\n(.*?)^\2\s*$",
    re.MULTILINE | re.DOTALL,
)
PYTHON_PREFIX_RE = re.compile(r"\s*(?:[A-Za-z0-9_./~-]+/)?")
HEREDOC_OPEN = "<<"
HEREDOC_ARGS = ([], ["-"], ["-u"], ["-u", "-"])
SHELL_EXPANSIONS = ("$", "`")
SCRIPT_PUNCTUATION = ";&|<>"
SCRIPT_FLAG = "-c"
SCRIPT_ARGS = 3
PATH_CLASS = "Path"
PATH_MODULE = "pathlib"
SCRIPT_IMPORTS = frozenset({PATH_MODULE, "yaml", "hashlib"})
SCRIPT_BUILTINS = frozenset({PATH_CLASS, "dict", "print"})
SCRIPT_RESERVED = SCRIPT_IMPORTS | SCRIPT_BUILTINS
SCRIPT_MODULE_CALLS = frozenset({(PATH_MODULE, PATH_CLASS), ("yaml", "safe_load"),
                                 ("yaml", "safe_dump"), ("hashlib", "sha256")})
SCRIPT_STATEMENTS = (ast.Import, ast.ImportFrom, ast.Assign, ast.Expr, ast.Assert)
READ_METHODS = ("read_text", "read_bytes")
WRITE_METHODS = ("write_text", "write_bytes")
VALUE_METHODS = ("encode", "hexdigest")
SAME_DIRS = (".", "..")


def shell_tokens(command):
    """Tokens of a shell command line by line, operators as tokens of their own.

    A line shlex cannot parse is split on blanks; a long command is cut at MAX_TOKENS.
    """
    tokens = []
    for line in command.splitlines():
        lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        try:
            tokens += list(lexer)
        except ValueError:
            tokens += line.split()
        tokens.append(SHELL_OPERATORS_NEWLINE)
    return tokens[:MAX_TOKENS]


def is_operator(token):
    """Whether the token separates simple commands."""
    return token in SHELL_OPERATORS or token == SHELL_OPERATORS_NEWLINE


def command_segments(tokens):
    """Simple commands of a token list, split at the shell operators."""
    segments, current = [], []
    for token in tokens:
        if is_operator(token):
            if current:
                segments.append(current)
            current = []
        else:
            current.append(token)
    if current:
        segments.append(current)
    return segments


def git_subcommand(words):
    """Subcommand of a git command line, its options skipped; None without one."""
    skip = False
    for word in words:
        if skip:
            skip = False
        elif word in GIT_VALUE_OPTIONS:
            skip = True
        elif not word.startswith(OPTION_PREFIX):
            return word
    return None


def segment_reads_only(segment):
    """Whether one simple command is known not to write files."""
    words = [w for w in segment if not ASSIGNMENT_RE.match(w) and w not in COMMAND_PREFIXES]
    if not words:
        return True
    name, rest = Path(words[0]).name, words[1:]
    if name == GIT_COMMAND:
        return git_subcommand(rest) not in GIT_WRITE_SUBCOMMANDS
    if name == FIND_COMMAND:
        return not any(w in FIND_WRITE_FLAGS for w in rest)
    if name in IN_PLACE_COMMANDS:
        return not IN_PLACE_RE.search(WORD_GAP + WORD_GAP.join(rest))
    return name in READ_ONLY_COMMANDS


def bash_reads_only(command):
    """Whether every simple command of the line is known not to write files.

    A redirection, an interpreter, an unknown program or an in-place edit counts as a write:
    the guard refuses what it cannot tell apart from an edit.
    """
    tokens = shell_tokens(command)
    if any(REDIRECT_CHAR in token for token in tokens):
        return False
    return all(segment_reads_only(segment) for segment in command_segments(tokens))


def bash_paths(event, command):
    """Tokens of the command read as paths from the event cwd that exist or look like a file.

    A word such as `echo` or `x` names no file; `new.md`, `src/x` or an existing path does.
    """
    paths = []
    for token in shell_tokens(command):
        if is_operator(token) or REDIRECT_CHAR in token:
            continue
        if ASSIGNMENT_RE.match(token) or (token.startswith(OPTION_PREFIX)
                                          and OPTION_VALUE in token):
            token = token.split(OPTION_VALUE, 1)[1]
        if not token or token.startswith(OPTION_PREFIX):
            continue
        try:
            path = absolute(event, token)
        except (OSError, ValueError, RuntimeError):
            continue
        if path.exists() or Path(token).suffix or PATH_SEPARATOR in token:
            paths.append(path)
    return paths


def bash_writes_approval(command, guarded):
    """The command writes into a metadata file and names one of its approval fields.

    guarded: items with the trailing path parts of a metadata file and its approval fields. A
    python script counts only when the path of the file is a string literal in it, not a
    mention inside a text the script writes elsewhere.
    """
    for item in guarded:
        name = item.parts[-1]
        if name not in command or not any(f in command for f in item.fields):
            continue
        path = re.escape(name) + PATH_END
        if (PYTHON_SCRIPT.search(command) and re.search(QUOTED.format(path=path), command)
                and not python_reads_metadata(command, name)):
            return True
        patterns = (REDIRECT_TO + path, IN_PLACE_TOOLS + SEGMENT + IN_PLACE,
                    TEE + SEGMENT + path, COPY_TO + SEGMENT + path + COPY_END)
        if any(re.search(p, command, re.MULTILINE) for p in patterns):
            return True
    return False


def heredoc_source(command, start):
    """Script of a quoted heredoc opened at start that ends the command, fed to a bare python."""
    heredoc = PYTHON_HEREDOC.match(command, start)
    if heredoc is None or not heredoc.group(1) or command[heredoc.end():].strip():
        return None
    if shlex.split(command[:start])[1:] not in HEREDOC_ARGS:
        return None
    return heredoc.group(3)


def dash_c_source(command):
    """Script of a command that is exactly `python -c <script>`, without shell expansions."""
    if any(mark in command for mark in SHELL_EXPANSIONS):
        return None
    lexer = shlex.shlex(command, posix=True, punctuation_chars=SCRIPT_PUNCTUATION)
    lexer.whitespace_split = True
    lexer.commenters = ""
    args = list(lexer)
    if len(args) != SCRIPT_ARGS or args[1] != SCRIPT_FLAG:
        return None
    return args[2]


def python_source(command):
    """Source of the one python script the command consists of, or None.

    The exception must cover exactly one python command, never sibling commands or a -c
    argument supplied by another program in the shell expression.
    """
    scripts = list(PYTHON_SCRIPT.finditer(command))
    if len(scripts) != 1:
        return None
    invocation = scripts[0]
    if PYTHON_PREFIX_RE.fullmatch(command[:invocation.start()]) is None:
        return None
    try:
        if invocation.group().endswith(HEREDOC_OPEN):
            return heredoc_source(command, invocation.end() - len(HEREDOC_OPEN))
        return dash_c_source(command)
    except (ValueError, IndexError):
        return None


def path_expression(node):
    """Whether the node builds a path from literals and names only: Path(...), / or a constant."""
    if isinstance(node, (ast.Constant, ast.Name)):
        return True
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return path_expression(node.left) and path_expression(node.right)
    if isinstance(node, ast.Call):
        func = node.func
        constructor = (isinstance(func, ast.Name) and func.id == PATH_CLASS
                       or isinstance(func, ast.Attribute) and func.attr == PATH_CLASS
                       and isinstance(func.value, ast.Name) and func.value.id == PATH_MODULE)
        return constructor and not node.keywords and all(path_expression(arg) for arg in node.args)
    return False


def path_filename(node):
    """File name a path expression ends with, when its last part is a string literal."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return Path(node.value).name
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return path_filename(node.right)
    if isinstance(node, ast.Call) and path_expression(node) and node.args:
        return path_filename(node.args[-1])
    return None


def allowed_call(node, name):
    """Whether a call is in the small vocabulary of a script writing a receipt elsewhere.

    A write must name its file by a literal other than the metadata file name.
    """
    func = node.func
    if isinstance(func, ast.Name):
        return func.id in SCRIPT_BUILTINS
    if not isinstance(func, ast.Attribute):
        return False
    if isinstance(func.value, ast.Name) and (func.value.id, func.attr) in SCRIPT_MODULE_CALLS:
        return True
    if func.attr in READ_METHODS and path_expression(func.value):
        return True
    if func.attr in WRITE_METHODS and path_expression(func.value):
        destination = path_filename(func.value)
        if destination and destination not in (name, *SAME_DIRS):
            return True
    return func.attr in VALUE_METHODS


def allowed_node(node, name):
    """Whether one node of the script stays within the vocabulary of allowed_call.

    A decoy read must not bless other operations in the same script: unfamiliar statements,
    imports and calls, attribute assignments and rebinding the helpers remain guarded.
    """
    if isinstance(node, ast.stmt) and not isinstance(node, SCRIPT_STATEMENTS):
        return False
    if isinstance(node, ast.Import) and any(alias.name not in SCRIPT_IMPORTS or alias.asname
                                           for alias in node.names):
        return False
    if isinstance(node, ast.ImportFrom) and (node.module != PATH_MODULE or node.level
                                             or any(alias.name != PATH_CLASS or alias.asname
                                                    for alias in node.names)):
        return False
    if (isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
            and node.id in SCRIPT_RESERVED):
        return False
    if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
        return False
    return not isinstance(node, ast.Call) or allowed_call(node, name)


def read_literal(literal, parents):
    """Whether the literal lies in the path expression of an inline read_text or read_bytes."""
    child = literal
    while child in parents:
        parent = parents[child]
        if (isinstance(parent, ast.Attribute) and parent.value is child
                and parent.attr in READ_METHODS):
            call = parents.get(parent)
            if isinstance(call, ast.Call) and call.func is parent and path_expression(child):
                return True
        child = parent
    return False


def python_reads_metadata(command, name):
    """Recognize only explicit Path(...).read_text/read_bytes uses of metadata literals.

    Unknown syntax, path aliases and write operations retain the conservative guard.
    This is a narrow false-positive fix, not a general Python side-effect analyser.
    """
    source = python_source(command)
    if source is None:
        return False
    try:
        tree = ast.parse(source)
    except (ValueError, SyntaxError):
        return False
    literals = [node for node in ast.walk(tree)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)
                and node.value.endswith(name)]
    if not literals or not all(allowed_node(node, name) for node in ast.walk(tree)):
        return False
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    return all(read_literal(literal, parents) for literal in literals)

"""Documentation block generated from a pipeline declaration: mermaid flowchart and step table."""
import os
import re
import string
from dataclasses import dataclass
from pathlib import Path

from . import keys
from .pipeline import SEVERITY_BLOCK
from .yamlio import ENCODING

MARKER_BEGIN = "<!-- pipeline:{name}:begin -->"
MARKER_END = "<!-- pipeline:{name}:end -->"
MARKER_RE = re.compile(r"^<!-- pipeline:(?P<name>[\w-]+):(?P<edge>begin|end) -->$")
EDGE_BEGIN = "begin"
EDGE_END = "end"
DOC_SUFFIX = ".md"
HIDDEN_PREFIX = "."
RENDER_COMMAND = "svod render {name} --write"
FENCE_OPEN = "```mermaid"
FENCE_CLOSE = "```"
FLOWCHART = "flowchart LR"
INDENT = "  "
LINE_BREAK = "<br/>"
BULLET = "• "
QUOTE = '"'
QUOTE_ENTITY = "#quot;"
PIPE = "|"
PIPE_ESCAPED = "\\|"
TEXT_SEPARATOR = "; "
ENTRY_NODE = "entry"
DONE_NODE = "done"
STEP_NODE = "s{index}"
EDGE = " --> "
ENTRY_SHAPE = '{id}{{{{"{label}"}}}}'
STEP_SHAPE = '{id}["{label}"]'
DONE_SHAPE = '{id}(["{label}"])'
TABLE_SEPARATOR = "|---|---|---|---|"
CLASS_REQUIRED = "required"
CLASS_OPTIONAL = "optional"
CLASS_FROZEN = "frozen"
CLASS_STYLES = {
    CLASS_REQUIRED: "stroke-width:3px",
    CLASS_OPTIONAL: "stroke-dasharray:5 5",
    CLASS_FROZEN: "stroke:#c0392b,stroke-width:3px",
}
CLASS_JOIN = "_"
STYLE_JOIN = ","
LEGEND_JOIN = " "
LEGEND_KEYS = {
    CLASS_REQUIRED: keys.DOC_LEGEND_REQUIRED,
    CLASS_OPTIONAL: keys.DOC_LEGEND_OPTIONAL,
    CLASS_FROZEN: keys.DOC_LEGEND_FROZEN,
}


@dataclass
class Block:
    """One marked block in a document: pipeline name and the line span of its content."""

    path: Path
    name: str
    begin: int
    end: int


def sketch(locale, key):
    """Template of the key with every placeholder replaced by the placeholder mark."""
    filler = locale.text(keys.DOC_PLACEHOLDER)
    template = locale.text_template(key)
    parts = []
    for literal, field, _, _ in string.Formatter().parse(template):
        parts.append(literal)
        if field is not None:
            parts.append(filler)
    return "".join(parts)


def flat(text):
    """One line: newlines and runs of spaces collapsed."""
    return " ".join(text.split())


def cell(text):
    """Markdown table cell content."""
    return flat(text).replace(PIPE, PIPE_ESCAPED)


def node_text(text):
    """Mermaid label content in double quotes."""
    return flat(text).replace(QUOTE, QUOTE_ENTITY)


def gate_caption(locale, ref):
    """Label of the gate use when it has one, else the description of the gate."""
    if ref.label:
        return sketch(locale, ref.label)
    return ref.impl.describe(ref.params, locale)


def condition(locale, ref):
    """Words for the when attribute: the profile key doc.attr.<name>, else the generic one."""
    key = f"{keys.DOC_ATTR_PREFIX}{ref.when}"
    if locale.has(key):
        return locale.text(key)
    return locale.text(keys.DOC_WHEN, when=ref.when)


def entry_caption(locale, ref):
    """Entry gate: what must hold, its condition and its severity."""
    parts = [gate_caption(locale, ref)]
    if ref.when:
        parts.append(condition(locale, ref))
    blocks = ref.severity == SEVERITY_BLOCK
    severity = locale.text(keys.DOC_SEVERITY_BLOCK if blocks else keys.DOC_SEVERITY_WARN)
    return f"{', '.join(parts)} ({severity})"


def step_title(locale, step):
    """Title of the step from the locale, or its id."""
    return locale.text(step.title) if step.title else step.id


def step_texts(locale, step):
    """Texts shown when the step is not passed: each gate's own text or the step text."""
    texts = []
    for key in [ref.text or step.text for ref in step.gates] or [step.text]:
        if key and key not in texts:
            texts.append(key)
    return TEXT_SEPARATOR.join(sketch(locale, key) for key in texts)


def step_class(step):
    """Mermaid class of the step, or None for a plain one."""
    names = [name for name, on in ((CLASS_REQUIRED, step.required),
                                   (CLASS_OPTIONAL, step.optional),
                                   (CLASS_FROZEN, step.blocks_code)) if on]
    return CLASS_JOIN.join(names) or None


def class_style(name):
    """Style of a combined class: the styles of its parts, the later part winning."""
    return STYLE_JOIN.join(CLASS_STYLES[part] for part in name.split(CLASS_JOIN))


def legend(locale, pipeline):
    """Legend of the styles the flowchart uses, in a fixed order; empty without styles."""
    used = {part for step in pipeline.steps for part in (step_class(step) or "").split(CLASS_JOIN)}
    return LEGEND_JOIN.join(locale.text(key) for name, key in LEGEND_KEYS.items() if name in used)


def flowchart(locale, pipeline):
    """Mermaid flowchart lines of the pipeline."""
    lines = [FENCE_OPEN, FLOWCHART]
    chain = []
    if pipeline.entry:
        label = [locale.text(keys.DOC_ENTRY)]
        label += [BULLET + entry_caption(locale, ref) for ref in pipeline.entry]
        lines.append(INDENT + ENTRY_SHAPE.format(
            id=ENTRY_NODE, label=LINE_BREAK.join(node_text(x) for x in label)))
        chain.append(ENTRY_NODE)
    classes = {}
    for index, step in enumerate(pipeline.steps):
        node = STEP_NODE.format(index=index)
        label = [step_title(locale, step)]
        if step.blocks_code:
            label.append(locale.text(keys.DOC_BLOCKS_CODE))
        lines.append(INDENT + STEP_SHAPE.format(
            id=node, label=LINE_BREAK.join(node_text(x) for x in label)))
        chain.append(node)
        name = step_class(step)
        if name:
            classes.setdefault(name, []).append(node)
    if pipeline.done:
        label = [locale.text(keys.DOC_DONE), sketch(locale, pipeline.done.text)]
        lines.append(INDENT + DONE_SHAPE.format(
            id=DONE_NODE, label=LINE_BREAK.join(node_text(x) for x in label)))
        chain.append(DONE_NODE)
    if len(chain) > 1:
        lines.append(INDENT + EDGE.join(chain))
    for name, nodes in classes.items():
        lines.append(f"{INDENT}classDef {name} {class_style(name)}")
        lines.append(f"{INDENT}class {','.join(nodes)} {name}")
    lines.append(FENCE_CLOSE)
    return lines


def row(*cells):
    """One markdown table row."""
    return f"{PIPE} {' | '.join(cells)} {PIPE}"


def step_row(locale, step):
    """Table row of one step."""
    title = step_title(locale, step)
    kind = (keys.DOC_REQUIRED if step.required else keys.DOC_OPTIONAL if step.optional else None)
    if kind:
        title = f"{title} ({locale.text(kind)})"
    if step.blocks_code:
        title = f"{title}, {locale.text(keys.DOC_BLOCKS_CODE)}"
    gates = [gate_caption(locale, ref) for ref in step.gates]
    gates += [entry_caption(locale, ref) for ref in step.entry]
    none = locale.text(keys.DOC_NONE)
    return row(cell(title), cell(TEXT_SEPARATOR.join(gates) or locale.text(keys.DOC_NO_GATES)),
               cell(step.role or none), cell(step_texts(locale, step) or none))


def table(locale, pipeline):
    """Step table with the entry first and done last."""
    head = (keys.DOC_HEAD_STEP, keys.DOC_HEAD_GATES, keys.DOC_HEAD_ROLE, keys.DOC_HEAD_NEXT)
    lines = [row(*(locale.text(k) for k in head)), TABLE_SEPARATOR]
    none = locale.text(keys.DOC_NONE)
    if pipeline.entry:
        texts = TEXT_SEPARATOR.join(sketch(locale, ref.text) for ref in pipeline.entry)
        lines.append(row(cell(locale.text(keys.DOC_ENTRY)),
                         cell(TEXT_SEPARATOR.join(entry_caption(locale, r)
                                                  for r in pipeline.entry)),
                         none, cell(texts)))
    lines += [step_row(locale, step) for step in pipeline.steps]
    if pipeline.done:
        texts = [locale.text(keys.DOC_DONE_TEXT, text=sketch(locale, pipeline.done.text))]
        if pipeline.done.pending:
            texts.insert(0, locale.text(keys.DOC_PENDING_TEXT,
                                        text=sketch(locale, pipeline.done.pending)))
        lines.append(row(cell(locale.text(keys.DOC_DONE)),
                         cell(gate_caption(locale, pipeline.done)), none,
                         cell(TEXT_SEPARATOR.join(texts))))
    return lines


def relative_or_absolute(root, path):
    """Path relative to the store root when inside it, else absolute, in POSIX form."""
    path = Path(path).resolve()
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def content(ctx, pipeline):
    """Lines between the markers: the generated note, the flowchart, the legend, the table."""
    locale = ctx.locale
    note = locale.text(keys.DOC_GENERATED, source=relative_or_absolute(ctx.root, pipeline.source),
                       command=RENDER_COMMAND.format(name=pipeline.name))
    lines = [note, ""] + flowchart(locale, pipeline) + [""]
    styles = legend(locale, pipeline)
    if styles:
        lines += [styles, ""]
    return lines + table(locale, pipeline)


def block(ctx, pipeline):
    """Whole block with its markers."""
    return ([MARKER_BEGIN.format(name=pipeline.name)] + content(ctx, pipeline)
            + [MARKER_END.format(name=pipeline.name)])


def markdown_files(root, exclude):
    """Markdown files under the root, skipping hidden and excluded top-level directories."""
    root = Path(root)
    skipped = {root / name for name in exclude}
    for directory, dirs, files in os.walk(root):
        base = Path(directory)
        dirs[:] = sorted(d for d in dirs if not d.startswith(HIDDEN_PREFIX)
                         and base / d not in skipped)
        for name in sorted(files):
            if name.endswith(DOC_SUFFIX):
                yield base / name


def blocks_in(path, lines):
    """Marked blocks of a document, begin and end paired by name."""
    found, opened = [], {}
    for index, line in enumerate(lines):
        match = MARKER_RE.match(line.strip())
        if not match:
            continue
        name = match.group("name")
        if match.group("edge") == EDGE_BEGIN:
            opened[name] = index
        elif match.group("edge") == EDGE_END and name in opened:
            found.append(Block(path, name, opened.pop(name), index))
    return found


def read_lines(path):
    """Lines of a text file without line ends."""
    with open(path, encoding=ENCODING) as fh:
        return fh.read().split("\n")


def scan(ctx, name=None):
    """Blocks in the store documents, of one pipeline or of all."""
    found = []
    for path in markdown_files(ctx.root, ctx.config.render_exclude):
        try:
            lines = read_lines(path)
        except (OSError, UnicodeDecodeError):
            continue
        found += [b for b in blocks_in(path, lines) if name is None or b.name == name]
    return found


def replace_blocks(lines, blocks, fresh):
    """Lines with the content of each block replaced by the fresh content."""
    result, cursor = [], 0
    for item in sorted(blocks, key=lambda b: b.begin):
        result += lines[cursor:item.begin + 1] + fresh
        cursor = item.end
    return result + lines[cursor:]


def write_blocks(ctx, pipeline):
    """Replace the pipeline blocks in every store document; return (path, changed) pairs."""
    fresh = content(ctx, pipeline)
    by_path = {}
    for item in scan(ctx, pipeline.name):
        by_path.setdefault(item.path, []).append(item)
    results = []
    for path, items in sorted(by_path.items()):
        lines = read_lines(path)
        updated = replace_blocks(lines, items, fresh)
        changed = updated != lines
        if changed:
            with open(path, "w", encoding=ENCODING) as fh:
                fh.write("\n".join(updated))
        results.append((path, changed))
    return results

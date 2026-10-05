"""Locale keys the core itself renders."""

ERROR_NOT_ROOT = "error.not_root"
ERROR_LOAD = "error.load"
VALIDATE_OK = "validate.ok"
VALIDATE_FAILED = "validate.failed"
STATUS_HEADER = "status.header"
STATUS_CHECKOUT = "status.checkout"
STATUS_NEXT_STEP = "status.next_step"
STATUS_DO_NOT_TOUCH = "status.do_not_touch"
STATUS_DO_NOT_TOUCH_BLOCKED = "status.do_not_touch_blocked"
STATUS_UNKNOWN = "status.unknown"
STATUS_SKILL = "status.skill"
STATUS_SKILL_UNASSIGNED = "status.skill_unassigned"
STATUS_SKILL_ITEM = "status.skill_item"
STATUS_SKILL_NONE = "status.skill_none"
STATUS_VIOLATIONS = "status.violations"
STATUS_VIOLATION_ITEM = "status.violation_item"
STATUS_VIOLATION = "status.violation"
STATUS_NOT_FOUND = "status.not_found"
STATUS_AMBIGUOUS = "status.ambiguous"
STATUS_CANDIDATE = "status.candidate"
MARK_PASS = "status.mark.pass"
MARK_FAIL = "status.mark.fail"
MARK_UNKNOWN = "status.mark.unknown"
ACTIVE_MINE_ACTIVE = "active.mine_active"
ACTIVE_MINE_IDLE = "active.mine_idle"
ACTIVE_THEIRS = "active.theirs"
ACTIVE_THEIRS_COLLAPSED = "active.theirs_collapsed"
ACTIVE_AUTHOR_COUNT = "active.author_count"
ACTIVE_ITEM = "active.item"
ACTIVE_NO_KEYS = "active.no_keys"
ACTIVE_HOOK_TAIL = "active.hook_tail"
ACTIVE_NO_LOCAL_CONFIG = "active.no_local_config"
ACTIVE_NO_IDENTITY = "active.no_identity"
ACTIVE_WORKTREE = "active.worktree"
INIT_WRITTEN = "init.written"
INIT_EXISTS = "init.exists"
INIT_NOT_CONFIGURED = "init.not_configured"
INIT_NEED_LOGIN = "init.need_login"
INIT_PROMPT_LOGIN = "init.prompt_login"
INIT_PROMPT_EMAIL = "init.prompt_email"
APPROVE_DONE = "approve.done"
APPROVE_NO_MARK = "approve.no_mark"
APPROVE_FOREIGN_KEY = "approve.foreign_key"
APPROVE_NO_GATE = "approve.no_gate"
APPROVE_NO_APPROVER = "approve.no_approver"

DOC_GENERATED = "doc.generated"
DOC_ENTRY = "doc.entry"
DOC_DONE = "doc.done"
DOC_DONE_TEXT = "doc.done_text"
DOC_PENDING_TEXT = "doc.pending_text"
DOC_BLOCKS_CODE = "doc.blocks_code"
DOC_LEGEND_REQUIRED = "doc.legend.required"
DOC_LEGEND_OPTIONAL = "doc.legend.optional"
DOC_LEGEND_FROZEN = "doc.legend.frozen"
DOC_HEAD_STEP = "doc.head.step"
DOC_HEAD_GATES = "doc.head.gates"
DOC_HEAD_ROLE = "doc.head.role"
DOC_HEAD_NEXT = "doc.head.next"
DOC_REQUIRED = "doc.required"
DOC_OPTIONAL = "doc.optional"
DOC_SEVERITY_BLOCK = "doc.severity.block"
DOC_SEVERITY_WARN = "doc.severity.warn"
DOC_WHEN = "doc.when"
DOC_ATTR_PREFIX = "doc.attr."
DOC_NO_GATES = "doc.no_gates"
DOC_NONE = "doc.none"
DOC_PLACEHOLDER = "doc.placeholder"
RENDER_UNKNOWN = "render.unknown"
RENDER_WRITTEN = "render.written"
RENDER_CURRENT = "render.current"
RENDER_NO_MARKERS = "render.no_markers"
HOOK_ENGINE_BROKEN = "hook.engine_broken"
HOOK_POSITION_HEAD = "hook.position_head"
HOOK_POSITION_TAIL = "hook.position_tail"
HOOK_APPROVAL_MARKED = "hook.approval_marked"
HOOK_APPROVAL_JOINERS = "hook.approval_joiners"
HOOK_DENY_APPROVAL = "hook.deny_approval"
HOOK_DENY_PLAN = "hook.deny_plan"
HOOK_DENY_MAIN = "hook.deny_main"
DESCRIBE_PREFIX = "gate."
DESCRIBE_EXISTS = "gate.exists"
DESCRIBE_ARTIFACT_PATH = "gate.artifact_path"
DESCRIBE_ARTIFACT_GLOB = "gate.artifact_glob"
DESCRIBE_APPROVAL = "gate.approval"
DESCRIBE_APPROVAL_BOUND = "gate.approval_bound"
DESCRIBE_FIELD_EQUALS = "gate.field_equals"
DESCRIBE_FIELD_NOT_EQUALS = "gate.field_not_equals"
DESCRIBE_FIELD_PRESENT = "gate.field_present"
DESCRIBE_FIELD_ABSENT = "gate.field_absent"
DESCRIBE_FIELD_DATE_NOT_PAST = "gate.field_date_not_past"
DESCRIBE_FIELD_DATE_PAST = "gate.field_date_past"
DESCRIBE_DOC_TYPE = "gate.doc_type"
DESCRIBE_DOC_TYPE_CONTAINER = "gate.doc_type_container"
DESCRIBE_ARCHIVED = "gate.archived"
DESCRIBE_GIT_PUSHED = "gate.git_pushed"
DESCRIBE_GIT_PUSHED_REPO = "gate.git_pushed_repo"
DESCRIBE_KEYS = (
    DESCRIBE_EXISTS, DESCRIBE_ARTIFACT_PATH, DESCRIBE_ARTIFACT_GLOB, DESCRIBE_APPROVAL,
    DESCRIBE_APPROVAL_BOUND,
    DESCRIBE_FIELD_EQUALS, DESCRIBE_FIELD_NOT_EQUALS, DESCRIBE_FIELD_PRESENT,
    DESCRIBE_FIELD_ABSENT, DESCRIBE_FIELD_DATE_NOT_PAST, DESCRIBE_FIELD_DATE_PAST,
    DESCRIBE_DOC_TYPE, DESCRIBE_DOC_TYPE_CONTAINER, DESCRIBE_ARCHIVED, DESCRIBE_GIT_PUSHED,
    DESCRIBE_GIT_PUSHED_REPO,
)

CORE_KEYS = (
    ERROR_NOT_ROOT,
    ERROR_LOAD,
    VALIDATE_OK,
    VALIDATE_FAILED,
    STATUS_HEADER,
    STATUS_CHECKOUT,
    STATUS_NEXT_STEP,
    STATUS_DO_NOT_TOUCH,
    STATUS_DO_NOT_TOUCH_BLOCKED,
    STATUS_UNKNOWN,
    STATUS_SKILL,
    STATUS_SKILL_UNASSIGNED,
    STATUS_SKILL_ITEM,
    STATUS_SKILL_NONE,
    STATUS_VIOLATIONS,
    STATUS_VIOLATION_ITEM,
    STATUS_VIOLATION,
    STATUS_NOT_FOUND,
    STATUS_AMBIGUOUS,
    STATUS_CANDIDATE,
    MARK_PASS,
    MARK_FAIL,
    MARK_UNKNOWN,
    ACTIVE_MINE_ACTIVE,
    ACTIVE_MINE_IDLE,
    ACTIVE_THEIRS,
    ACTIVE_THEIRS_COLLAPSED,
    ACTIVE_AUTHOR_COUNT,
    ACTIVE_ITEM,
    ACTIVE_NO_KEYS,
    ACTIVE_HOOK_TAIL,
    ACTIVE_NO_LOCAL_CONFIG,
    ACTIVE_NO_IDENTITY,
    ACTIVE_WORKTREE,
    INIT_WRITTEN,
    INIT_EXISTS,
    INIT_NOT_CONFIGURED,
    INIT_NEED_LOGIN,
    INIT_PROMPT_LOGIN,
    INIT_PROMPT_EMAIL,
    APPROVE_DONE,
    APPROVE_NO_MARK,
    APPROVE_FOREIGN_KEY,
    APPROVE_NO_GATE,
    APPROVE_NO_APPROVER,
    DOC_GENERATED,
    DOC_ENTRY,
    DOC_DONE,
    DOC_DONE_TEXT,
    DOC_PENDING_TEXT,
    DOC_BLOCKS_CODE,
    DOC_LEGEND_REQUIRED,
    DOC_LEGEND_OPTIONAL,
    DOC_LEGEND_FROZEN,
    DOC_HEAD_STEP,
    DOC_HEAD_GATES,
    DOC_HEAD_ROLE,
    DOC_HEAD_NEXT,
    DOC_REQUIRED,
    DOC_OPTIONAL,
    DOC_SEVERITY_BLOCK,
    DOC_SEVERITY_WARN,
    DOC_WHEN,
    DOC_NO_GATES,
    DOC_NONE,
    DOC_PLACEHOLDER,
    RENDER_UNKNOWN,
    RENDER_WRITTEN,
    RENDER_CURRENT,
    RENDER_NO_MARKERS,
    HOOK_ENGINE_BROKEN,
    HOOK_POSITION_HEAD,
    HOOK_POSITION_TAIL,
    HOOK_APPROVAL_MARKED,
    HOOK_APPROVAL_JOINERS,
    HOOK_DENY_APPROVAL,
    HOOK_DENY_PLAN,
    HOOK_DENY_MAIN,
    *DESCRIBE_KEYS,
)

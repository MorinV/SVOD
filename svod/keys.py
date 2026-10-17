"""Locale keys the core itself renders."""

ERROR_NOT_ROOT = "error.not_root"
ERROR_LOAD = "error.load"
VALIDATE_OK = "validate.ok"
VALIDATE_FAILED = "validate.failed"
STATUS_HEADER = "status.header"
STATUS_CHECKOUT = "status.checkout"
STATUS_AUTONOMY = "status.autonomy"
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
STATUS_RUN = "status.run"
STATUS_CHILDREN = "status.children"
STATUS_CHILD = "status.child"
STATUS_CHILD_DONE = "status.child_done"
STATUS_CHILD_OPEN = "status.child_open"
MARK_PASS = "status.mark.pass"
MARK_FAIL = "status.mark.fail"
MARK_UNKNOWN = "status.mark.unknown"
MARK_STALE = "status.mark.stale"
MARK_NOT_RUN = "status.mark.not_run"
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
ACTIVE_NONE = "active.none"
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
APPROVE_NO_STEP = "approve.no_step"
APPROVE_STEP_NO_GATE = "approve.step_no_gate"
APPROVE_NOT_READY = "approve.not_ready"
APPROVE_CHANGED_AFTER_MARK = "approve.changed_after_mark"
APPROVE_NO_APPROVER = "approve.no_approver"
APPROVE_CONFIRM_PLAN = "approve.confirm_plan"
APPROVE_CONFIRM_FILES = "approve.confirm_files"
APPROVE_CONFIRM_QUESTION = "approve.confirm_question"
APPROVE_NOT_CONFIRMED = "approve.not_confirmed"
ANSWER_DONE = "answer.done"
ANSWER_NO_MARK = "answer.no_mark"
ANSWER_NO_FILE = "answer.no_file"
ANSWER_NO_QUESTION = "answer.no_question"
ANSWER_EMPTY = "answer.empty"
ASK_DONE = "ask.done"
ASK_NONE = "ask.none"
ASK_EMPTY = "ask.empty"
ASK_CONFLICT = "ask.conflict"
ASK_MISREAD = "ask.misread"
ASK_HAS_QUESTIONS = "ask.has_questions"
DO_USAGE = "do.usage"
DO_UNKNOWN = "do.unknown"
DO_FAILED = "do.failed"
DO_TIMEOUT = "do.timeout"
DO_LIST_ITEM = "do.list_item"
DO_LIST_NO_DESCRIPTION = "do.list_no_description"
DO_LIST_NONE = "do.list_none"
DO_NOT_CURRENT = "do.not_current"
DO_NO_CURRENT = "do.no_current"
WIZARD_NOT_TTY = "wizard.not_tty"
WIZARD_PROMPT_LOGIN = "wizard.prompt_login"
WIZARD_SERVICES_CURRENT = "wizard.services_current"
WIZARD_PROMPT_SERVICE = "wizard.prompt_service"
WIZARD_PROMPT_PATH = "wizard.prompt_path"
WIZARD_BAD_SERVICE = "wizard.bad_service"
WIZARD_BAD_PAIR = "wizard.bad_pair"
WIZARD_PROMPT_AUTONOMY = "wizard.prompt_autonomy"
WIZARD_BAD_LEVEL = "wizard.bad_level"
WIZARD_UNKNOWN_PIPELINE = "wizard.unknown_pipeline"
WIZARD_PROMPT_CHECKS = "wizard.prompt_checks"
WIZARD_CHECKS_AUTO = "wizard.checks_auto"
WIZARD_BAD_CHECKS = "wizard.bad_checks"
WIZARD_UNKNOWN_SERVICE = "wizard.unknown_service"
WIZARD_PROMPT_HOOKS = "wizard.prompt_hooks"
WIZARD_BAD_HOOKS = "wizard.bad_hooks"
WIZARD_WRITTEN = "wizard.written"
WIZARD_UNCHANGED = "wizard.unchanged"
WIZARD_WRITE_FAILED = "wizard.write_failed"
WIZARD_HOOKS_MANUAL = "wizard.hooks_manual"
WIZARD_HOOKS_FAILED = "wizard.hooks_failed"
WIZARD_ABORTED = "wizard.aborted"
WIZARD_NEXT = "wizard.next"
DOCTOR_CONFIG_OK = "doctor.config_ok"
DOCTOR_CONFIG_FAIL = "doctor.config_fail"
DOCTOR_SERVICES_NONE = "doctor.services_none"
DOCTOR_SERVICE_OK = "doctor.service_ok"
DOCTOR_SERVICE_MISSING = "doctor.service_missing"
DOCTOR_SERVICE_NOT_GIT = "doctor.service_not_git"
DOCTOR_HOOKS_OK = "doctor.hooks_ok"
DOCTOR_HOOKS_NONE = "doctor.hooks_none"
DOCTOR_HOOKS_PARTIAL = "doctor.hooks_partial"
DOCTOR_HOOKS_PYTHON = "doctor.hooks_python"
DOCTOR_HOOKS_UNREADABLE = "doctor.hooks_unreadable"
DOCTOR_COPY_NONE = "doctor.copy_none"
DOCTOR_COPY_OK = "doctor.copy_ok"
DOCTOR_VERSION_OK = "doctor.version_ok"
DOCTOR_VERSION_NEWER = "doctor.version_newer"
DOCTOR_VERSION_UNCHECKED = "doctor.version_unchecked"
DOCTOR_EVIDENCE_OK = "doctor.evidence_ok"
DOCTOR_EVIDENCE_OFF = "doctor.evidence_off"
DOCTOR_EVIDENCE_FAIL = "doctor.evidence_fail"
DOCTOR_KNOWLEDGE_OK = "doctor.knowledge_ok"
DOCTOR_KNOWLEDGE_NONE = "doctor.knowledge_none"
DOCTOR_KNOWLEDGE_STALE = "doctor.knowledge_stale"
DOCTOR_LOCAL_OK = "doctor.local_ok"
DOCTOR_LOCAL_MISSING = "doctor.local_missing"
DOCTOR_LOCAL_INVALID = "doctor.local_invalid"
DOCTOR_LOCAL_NOT_CONFIGURED = "doctor.local_not_configured"

UPDATE_EXISTS = "update.exists"
UPDATE_MISSING = "update.missing"
UPDATE_FETCH_FAILED = "update.fetch_failed"
UPDATE_NO_TAGS = "update.no_tags"
UPDATE_CLONE_FAILED = "update.clone_failed"
UPDATE_NOT_SVOD = "update.not_svod"
UPDATE_INSTALLED = "update.installed"
UPDATE_UPDATED = "update.updated"
UPDATE_CHANGELOG = "update.changelog"
UPDATE_MANUAL = "update.manual"
UPDATE_MANUAL_NONE = "update.manual_none"
UPDATE_INVALID = "update.invalid"
UPDATE_NEXT = "update.next"
UPDATE_AVAILABLE = "update.available"
MIGRATE_VERSION = "migrate.version"
MIGRATE_NONE = "migrate.none"
MIGRATE_FAILED = "migrate.failed"
MIGRATE_BAD_VERSION = "migrate.bad_version"
MIGRATE_RENAMED_KEY = "migrate.renamed_key"
MIGRATE_RENAMED_FILE = "migrate.renamed_file"

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
HOOK_APPROVAL_MARKED_UNNAMED = "hook.approval_marked_unnamed"
HOOK_APPROVAL_JOINERS = "hook.approval_joiners"
HOOK_DENY_APPROVAL = "hook.deny_approval"
HOOK_DENY_PLAN = "hook.deny_plan"
HOOK_DENY_MAIN = "hook.deny_main"
HOOK_DENY_MARK = "hook.deny_mark"
HOOK_DENY_BROKEN = "hook.deny_broken"
HOOK_KNOWLEDGE_HEAD = "hook.knowledge_head"
KNOWLEDGE_ADDED = "knowledge.added"
KNOWLEDGE_EXISTS = "knowledge.exists"
KNOWLEDGE_NO_FILE = "knowledge.no_file"
KNOWLEDGE_ITEM = "knowledge.item"
KNOWLEDGE_NONE = "knowledge.none"
RETRO_ITEM = "retro.item"
RETRO_FACTS = "retro.facts"
RETRO_PROPOSED = "retro.proposed"
RETRO_NONE = "retro.none"
RETRO_USAGE = "retro.usage"
RETRO_NO_NUMBER = "retro.no_number"
RETRO_RECORDED = "retro.recorded"
RETRO_HINT = "retro.hint"
RETRO_RULE_FAILED = "retro.rule_failed"
RETRO_RULE_PREFIX = "retro.rule."
RETRO_CHANGE_PREFIX = "retro.change."
# Texts of the core retrospective rules (svod.retro.rules) and of the changes they propose.
RETRO_TEXT_KEYS = tuple(RETRO_RULE_PREFIX + name for name in (
    "dirty_checks", "approval_drift", "approval_drift_questions", "hook_denials",
    "hotfix_cause", "instant_steps", "long_step",
)) + tuple(RETRO_CHANGE_PREFIX + name for name in (
    "approval_drift", "approval_drift_questions", "hook_denials", "hotfix_cause", "long_step",
))
HOOK_DENY_HUMAN = "hook.deny_human"
HOOK_DENY_QUESTIONS = "hook.deny_questions"
HOOK_DENY_EXTERNAL = "hook.deny_external"
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
DESCRIBE_CHILDREN_DONE = "gate.children_done"
DESCRIBE_HAS_CHILDREN = "gate.has_children"
DESCRIBE_REF_EXISTS = "gate.ref_exists"
DESCRIBE_QUESTIONS_ANSWERED = "gate.questions_answered"
DESCRIBE_KEYS = (
    DESCRIBE_EXISTS, DESCRIBE_ARTIFACT_PATH, DESCRIBE_ARTIFACT_GLOB, DESCRIBE_APPROVAL,
    DESCRIBE_APPROVAL_BOUND,
    DESCRIBE_FIELD_EQUALS, DESCRIBE_FIELD_NOT_EQUALS, DESCRIBE_FIELD_PRESENT,
    DESCRIBE_FIELD_ABSENT, DESCRIBE_FIELD_DATE_NOT_PAST, DESCRIBE_FIELD_DATE_PAST,
    DESCRIBE_DOC_TYPE, DESCRIBE_DOC_TYPE_CONTAINER, DESCRIBE_ARCHIVED, DESCRIBE_GIT_PUSHED,
    DESCRIBE_GIT_PUSHED_REPO, DESCRIBE_CHILDREN_DONE, DESCRIBE_HAS_CHILDREN, DESCRIBE_REF_EXISTS,
    DESCRIBE_QUESTIONS_ANSWERED,
)

CORE_KEYS = (
    ERROR_NOT_ROOT,
    ERROR_LOAD,
    VALIDATE_OK,
    VALIDATE_FAILED,
    STATUS_HEADER,
    STATUS_CHECKOUT,
    STATUS_AUTONOMY,
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
    STATUS_RUN,
    STATUS_CHILDREN,
    STATUS_CHILD,
    STATUS_CHILD_DONE,
    STATUS_CHILD_OPEN,
    MARK_PASS,
    MARK_FAIL,
    MARK_UNKNOWN,
    MARK_STALE,
    MARK_NOT_RUN,
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
    ACTIVE_NONE,
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
    APPROVE_NO_STEP,
    APPROVE_STEP_NO_GATE,
    APPROVE_NOT_READY,
    APPROVE_CHANGED_AFTER_MARK,
    APPROVE_NO_APPROVER,
    APPROVE_CONFIRM_PLAN,
    APPROVE_CONFIRM_FILES,
    APPROVE_CONFIRM_QUESTION,
    APPROVE_NOT_CONFIRMED,
    ANSWER_DONE,
    ANSWER_NO_MARK,
    ANSWER_NO_FILE,
    ANSWER_NO_QUESTION,
    ANSWER_EMPTY,
    ASK_DONE,
    ASK_NONE,
    ASK_EMPTY,
    ASK_CONFLICT,
    ASK_MISREAD,
    ASK_HAS_QUESTIONS,
    DO_USAGE,
    DO_UNKNOWN,
    DO_FAILED,
    DO_TIMEOUT,
    DO_LIST_ITEM,
    DO_LIST_NO_DESCRIPTION,
    DO_LIST_NONE,
    DO_NOT_CURRENT,
    DO_NO_CURRENT,
    WIZARD_NOT_TTY,
    WIZARD_PROMPT_LOGIN,
    WIZARD_SERVICES_CURRENT,
    WIZARD_PROMPT_SERVICE,
    WIZARD_PROMPT_PATH,
    WIZARD_BAD_SERVICE,
    WIZARD_BAD_PAIR,
    WIZARD_PROMPT_AUTONOMY,
    WIZARD_BAD_LEVEL,
    WIZARD_UNKNOWN_PIPELINE,
    WIZARD_PROMPT_CHECKS,
    WIZARD_CHECKS_AUTO,
    WIZARD_BAD_CHECKS,
    WIZARD_UNKNOWN_SERVICE,
    WIZARD_PROMPT_HOOKS,
    WIZARD_BAD_HOOKS,
    WIZARD_WRITTEN,
    WIZARD_UNCHANGED,
    WIZARD_WRITE_FAILED,
    WIZARD_HOOKS_MANUAL,
    WIZARD_HOOKS_FAILED,
    WIZARD_ABORTED,
    WIZARD_NEXT,
    DOCTOR_CONFIG_OK,
    DOCTOR_CONFIG_FAIL,
    DOCTOR_SERVICES_NONE,
    DOCTOR_SERVICE_OK,
    DOCTOR_SERVICE_MISSING,
    DOCTOR_SERVICE_NOT_GIT,
    DOCTOR_HOOKS_OK,
    DOCTOR_HOOKS_NONE,
    DOCTOR_HOOKS_PARTIAL,
    DOCTOR_HOOKS_PYTHON,
    DOCTOR_HOOKS_UNREADABLE,
    DOCTOR_COPY_NONE,
    DOCTOR_COPY_OK,
    DOCTOR_VERSION_OK,
    DOCTOR_VERSION_NEWER,
    DOCTOR_VERSION_UNCHECKED,
    DOCTOR_EVIDENCE_OK,
    DOCTOR_EVIDENCE_OFF,
    DOCTOR_EVIDENCE_FAIL,
    DOCTOR_KNOWLEDGE_OK,
    DOCTOR_KNOWLEDGE_NONE,
    DOCTOR_KNOWLEDGE_STALE,
    DOCTOR_LOCAL_OK,
    DOCTOR_LOCAL_MISSING,
    DOCTOR_LOCAL_INVALID,
    DOCTOR_LOCAL_NOT_CONFIGURED,
    UPDATE_EXISTS,
    UPDATE_MISSING,
    UPDATE_FETCH_FAILED,
    UPDATE_NO_TAGS,
    UPDATE_CLONE_FAILED,
    UPDATE_NOT_SVOD,
    UPDATE_INSTALLED,
    UPDATE_UPDATED,
    UPDATE_CHANGELOG,
    UPDATE_MANUAL,
    UPDATE_MANUAL_NONE,
    UPDATE_INVALID,
    UPDATE_NEXT,
    UPDATE_AVAILABLE,
    MIGRATE_VERSION,
    MIGRATE_NONE,
    MIGRATE_FAILED,
    MIGRATE_BAD_VERSION,
    MIGRATE_RENAMED_KEY,
    MIGRATE_RENAMED_FILE,
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
    HOOK_APPROVAL_MARKED_UNNAMED,
    HOOK_APPROVAL_JOINERS,
    HOOK_DENY_APPROVAL,
    HOOK_DENY_PLAN,
    HOOK_DENY_MAIN,
    HOOK_DENY_MARK,
    HOOK_DENY_BROKEN,
    HOOK_KNOWLEDGE_HEAD,
    KNOWLEDGE_ADDED,
    KNOWLEDGE_EXISTS,
    KNOWLEDGE_NO_FILE,
    KNOWLEDGE_ITEM,
    KNOWLEDGE_NONE,
    HOOK_DENY_HUMAN,
    HOOK_DENY_QUESTIONS,
    HOOK_DENY_EXTERNAL,
    RETRO_ITEM,
    RETRO_FACTS,
    RETRO_PROPOSED,
    RETRO_NONE,
    RETRO_USAGE,
    RETRO_NO_NUMBER,
    RETRO_RECORDED,
    RETRO_HINT,
    RETRO_RULE_FAILED,
    *RETRO_TEXT_KEYS,
    *DESCRIBE_KEYS,
)

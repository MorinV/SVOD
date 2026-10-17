"""Work records: container directories whose card.md frontmatter decides the steps that apply.

A record is work/<kind>/<name>/ with card.md (frontmatter type: card). Besides the container
attributes it carries the booleans pipelines name in `when`:
  hotfix        kind: hotfix (a task that skips the contract and its approval)
  planned       any other kind
  to_work       research outcome hotfix or feature (leads_to names the record)
  to_knowledge  research outcome knowledge (knowledge names the document)
"""
from svod.providers.container import ContainerProvider
from svod.subject import ATTR_FRONTMATTER

FIELD_KIND = "kind"
FIELD_OUTCOME = "outcome"
KIND_HOTFIX = "hotfix"
OUTCOMES_TO_WORK = frozenset({"hotfix", "feature"})
OUTCOME_KNOWLEDGE = "knowledge"


def text(frontmatter, name):
    """Stripped string value of a frontmatter field, empty when absent."""
    value = frontmatter.get(name)
    return "" if value is None else str(value).strip()


class WorkProvider(ContainerProvider):
    """The container provider plus the when-attributes of a work record."""

    name = "work"

    def subject(self, ctx, path):
        """Container subject with hotfix, planned, to_work and to_knowledge attributes."""
        subject = super().subject(ctx, path)
        frontmatter = subject.attrs.get(ATTR_FRONTMATTER) or {}
        hotfix = text(frontmatter, FIELD_KIND) == KIND_HOTFIX
        outcome = text(frontmatter, FIELD_OUTCOME)
        subject.attrs.update(hotfix=hotfix, planned=not hotfix,
                             to_work=outcome in OUTCOMES_TO_WORK,
                             to_knowledge=outcome == OUTCOME_KNOWLEDGE)
        return subject


GATES = {}
PROVIDERS = {WorkProvider.name: WorkProvider}

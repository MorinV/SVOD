"""Who runs the engine: the local config first, the git identity of the store second."""

EMAIL_KEY = "user.email"


def git_email(ctx):
    """Configured git email of the store, or an empty string."""
    out = ctx.cache.git(ctx.root, "config", EMAIL_KEY)
    return out.out if out.ok else ""


def my_email(ctx):
    """Email of the person, case folded: the local config, else git; empty when neither."""
    return (ctx.config.email or git_email(ctx)).casefold()


def approver(ctx):
    """Name recorded as the approver: login, else email; None when neither is known."""
    return ctx.config.login or ctx.config.email or git_email(ctx) or None

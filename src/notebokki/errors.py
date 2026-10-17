"""The four failure branches (KTD7). They are deliberately not collapsible: each sends the
developer somewhere different. Messages never carry the original exception's text (KTD9)."""


class NotebokkiError(Exception):
    """Base for every error notebokki raises on purpose."""


class UnknownTopicError(NotebokkiError):
    def __init__(self, topic: str, valid: list[str]):
        self.topic, self.valid = topic, valid
        super().__init__(
            f"Unknown topic {topic!r}. Valid topics: {', '.join(valid) if valid else '(none)'}."
        )


class SessionError(NotebokkiError):
    def __init__(self) -> None:
        super().__init__(
            "NotebookLM session is missing, expired or invalid. Re-run `notebokki setup` "
            "to capture a fresh session."
        )


class NotebookUnreachableError(NotebokkiError):
    """The notebook was deleted or is no longer shared. A registry fault, not a session one."""

    def __init__(self) -> None:
        super().__init__(
            "The notebook is missing or no longer shared with this account. "
            "Fix or remove its entry in the registry file."
        )


class UpstreamError(NotebokkiError):
    """Throttled, or anything unrecognized. Carries the exception type name only."""

    def __init__(self, type_name: str):
        self.type_name = type_name
        super().__init__(
            f"NotebookLM request failed upstream ({type_name}). This may be throttling or a "
            "service change; wait and retry."
        )

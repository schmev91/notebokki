"""The hand-authored topic registry: the sole allowlist of reachable notebooks (R1, R2)."""

import json
import re
from dataclasses import dataclass
from pathlib import Path

# Both notebooklm.google.com and notebook.google.com appear in use; accept /notebook/<id>
# on either, ignoring query string and fragment.
_NOTEBOOK_URL = re.compile(
    r"^https://(?:notebooklm|notebook)\.google\.com/(?:u/\d+/)?notebook/([A-Za-z0-9_-]+)(?:[/?#].*)?$"
)


class RegistryError(Exception):
    """The registry file is missing, empty, malformed, or holds an unusable entry."""


@dataclass(frozen=True)
class Topic:
    topic: str
    notebook_id: str
    description: str


class Registry:
    def __init__(self, topics: dict[str, Topic]):
        self._topics = topics

    @classmethod
    def load(cls, path: Path) -> "Registry":
        path = Path(path)
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise RegistryError(f"registry not found at {path}") from None
        except OSError as exc:
            raise RegistryError(
                f"registry at {path} is unreadable ({type(exc).__name__})"
            ) from None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            raise RegistryError(f"registry at {path} is not valid JSON") from None
        if not isinstance(data, dict):
            raise RegistryError(f"registry at {path} must be a JSON object of topic entries")
        if not data:
            raise RegistryError(f"registry at {path} has no topics")
        topics: dict[str, Topic] = {}
        for name, item in data.items():
            if not isinstance(item, dict):
                raise RegistryError(f"topic {name!r}: entry must be an object")
            url, description = item.get("url"), item.get("description")
            if (
                not isinstance(url, str)
                or not isinstance(description, str)
                or not description.strip()
            ):
                raise RegistryError(
                    f"topic {name!r}: needs a string 'url' and a non-empty 'description'"
                )
            match = _NOTEBOOK_URL.match(url.strip())
            if not match:
                raise RegistryError(f"topic {name!r}: cannot derive a notebook id from its url")
            topics[name] = Topic(name, match.group(1), description)
        return cls(topics)

    def resolve(self, topic: str) -> Topic | None:
        """Exact match only. No fuzzy resolution exists anywhere (R9)."""
        return self._topics.get(topic)

    def topics(self) -> list[str]:
        return list(self._topics)

    def entries(self) -> list[Topic]:
        return list(self._topics.values())

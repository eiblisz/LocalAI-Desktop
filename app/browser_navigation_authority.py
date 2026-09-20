from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse


ACTION_INTERNAL_SAME = "internal_same"
ACTION_INTERNAL_TAB = "internal_tab"
ACTION_EXTERNAL = "external"
ACTION_BLOCK = "block"

_ALLOWED_WEB_SCHEMES = {"http", "https"}
_ALLOWED_LOCAL_SCHEMES = {"file"}


@dataclass(frozen=True)
class BrowserNavigationDecision:
    action: str
    target: str
    reason: str
    source: str

    @property
    def allowed(self):
        return self.action != ACTION_BLOCK


class BrowserNavigationAuthority:
    """
    Host-owned policy for browser and resource navigation.

    Automatic navigation remains inside LocalAI Desktop. External application
    launch is allowed only from the explicit External control.
    """

    @staticmethod
    def _normalize(target):
        value = str(target or "").strip()
        if not value:
            return "", ""

        parsed = urlparse(value)
        scheme = parsed.scheme.lower()

        if scheme:
            return value, scheme

        path = Path(value).expanduser()
        if path.exists():
            return path.resolve().as_uri(), "file"

        # Address-bar convenience: a bare hostname stays internal over HTTPS.
        return "https://" + value, "https"

    @staticmethod
    def _local_file_exists(target):
        parsed = urlparse(target)
        if parsed.scheme.lower() != "file":
            return False
        path_text = unquote(parsed.path or "")
        if parsed.netloc:
            path_text = f"//{parsed.netloc}{path_text}"
        if len(path_text) >= 3 and path_text[0] == "/" and path_text[2] == ":":
            path_text = path_text[1:]
        try:
            return Path(path_text).exists()
        except (OSError, ValueError):
            return False

    def decide(self, target, *, source):
        normalized, scheme = self._normalize(target)
        source = str(source or "").strip().lower()

        if not normalized:
            return BrowserNavigationDecision(
                ACTION_BLOCK,
                "",
                "empty navigation target",
                source,
            )

        if scheme in _ALLOWED_WEB_SCHEMES:
            if source == "external_button":
                return BrowserNavigationDecision(
                    ACTION_EXTERNAL,
                    normalized,
                    "explicit user-requested external navigation",
                    source,
                )
            if source in {"page_link", "address_bar", "initial_load"}:
                return BrowserNavigationDecision(
                    ACTION_INTERNAL_SAME,
                    normalized,
                    "web navigation stays in the current LocalAI browser tab",
                    source,
                )
            return BrowserNavigationDecision(
                ACTION_INTERNAL_TAB,
                normalized,
                "web resource opens in a LocalAI workspace tab",
                source,
            )

        if scheme in _ALLOWED_LOCAL_SCHEMES:
            if not self._local_file_exists(normalized):
                return BrowserNavigationDecision(
                    ACTION_BLOCK,
                    normalized,
                    "local navigation target does not exist",
                    source,
                )
            if source == "external_button":
                return BrowserNavigationDecision(
                    ACTION_EXTERNAL,
                    normalized,
                    "explicit user-requested external local-file open",
                    source,
                )
            if source in {"page_link", "address_bar", "initial_load"}:
                return BrowserNavigationDecision(
                    ACTION_INTERNAL_SAME,
                    normalized,
                    "local navigation stays in the current LocalAI viewer",
                    source,
                )
            return BrowserNavigationDecision(
                ACTION_INTERNAL_TAB,
                normalized,
                "local resource opens in a LocalAI workspace tab",
                source,
            )

        return BrowserNavigationDecision(
            ACTION_BLOCK,
            normalized,
            f"scheme is not authorized for navigation: {scheme or 'unknown'}",
            source,
        )

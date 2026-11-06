"""Conservative local signals used in addition to advisory model output."""

import re

# A signal, not a complete prompt-injection detector. Authorization remains
# independent of content even when wording evades these patterns.
_AUTHORIZATION = re.compile(
    r"\b(?:user|owner|administrator|admin|customer|human)\b.{0,100}"
    r"\b(?:approv(?:e|ed|es|al)|authori[sz](?:e|ed|es|ation)|"
    r"permi(?:t|ts|tted|ssion)|grant(?:s|ed)?)\b"
    r"|\b(?:approv(?:e|ed|es|al)|authori[sz](?:e|ed|es|ation)|"
    r"permi(?:t|ts|tted|ssion)|grant(?:s|ed)?)\b.{0,100}"
    r"\b(?:user|owner|administrator|admin|customer|human)\b",
    re.IGNORECASE | re.DOTALL,
)


def is_authorization_claim(content: str) -> bool:
    return bool(_AUTHORIZATION.search(content))

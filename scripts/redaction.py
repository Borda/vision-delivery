#!/usr/bin/env python3
"""Shared private-data patterns for text that leaves the user's machine.

Two helpers use them. ``scripts/publish_run.py`` masks and checks a behaviour-eval run before it is
committed, and ``scripts/outcome_report.py`` scrubs a draft outcome report before the user posts it.
Both are denylists: they find the mechanical shapes below (credentials, home and temporary folders,
other paths, email addresses, IPv4 addresses, host names) and cannot judge whether ordinary words
name a customer, a site, a product, or a person.

The module uses only :mod:`re`; it opens no file, no connection, and no process.
"""

from __future__ import annotations

import re

#: Characters that end a path segment: separators, line breaks, tabs, quotes, and angle brackets.
_SEGMENT_END = r"/\\\r\n\t\"'`<>"
#: Credential shapes, in a fixed order so a finding can name the pattern by number. The first five
#: cover the package validator's set (``scripts/validate_package.py``); the private-key entry spans the
#: whole block, or runs to the end of the text when the footer is missing. Then come ``sk-`` API keys
#: (Anthropic style), bearer headers, signed-URL parameters, and key or password assignments.
CREDENTIAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----(?:.*?-----END [A-Z ]*PRIVATE KEY-----|.*\Z)", re.DOTALL),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{20,}"),
    re.compile(
        r"(?i)[?&](?:x-amz-signature|x-amz-credential|x-amz-security-token|x-goog-signature|x-goog-credential"
        r"|signature|sig|access_token|token|api_key|apikey|key)=[A-Za-z0-9%._~+/=-]{16,}"
    ),
    re.compile(
        r"(?i)(?:api[_-]?key|access[_-]?key|access[_-]?token|auth[_-]?token|refresh[_-]?token|client[_-]?secret"
        r"|secret[_-]?key|private[_-]?key|password|passwd|secret|token)[\"']?\s*[:=]\s*[\"']?"
        r"(?=[^\s\"']*[0-9])[A-Za-z0-9_./+=-]{16,}"
    ),
)
#: An email address.
EMAIL = re.compile(r"(?<![\w.%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}(?![\w-])")
#: The host part of a URL, after ``://`` and before the path, with any user name and port.
URL_HOST = re.compile(r"(?<=://)[^/\s?#'\"`<>]+")
#: Four dot-separated numbers, with an optional port; :func:`mask_ipv4` keeps those whose parts are 0-255.
_IPV4_CANDIDATE = re.compile(r"(?<![\w.])(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?::\d{1,5})?(?![\w]|\.\d)")
#: Home folders from any machine, in any letter case: ``/Users/<name>``, ``/home/<name>``, and
#: ``X:\Users\<name>`` (one or more backslashes or slashes). Group 1 is the prefix; the name runs to
#: the next separator, spaces included.
POSIX_HOME = re.compile(rf"(?i)(/(?:users|home)/)[^{_SEGMENT_END}]+")
WINDOWS_HOME = re.compile(rf"(?i)((?<![a-z])[a-z]:[\\/]+users[\\/]+)[^{_SEGMENT_END}]+")
#: The root user's home folder at the start of a path.
ROOT_HOME = re.compile(rf"(?<![\w.~-])/root(?![^{_SEGMENT_END}\s])")
#: macOS per-user temporary root (``/var/folders/<xx>/<id>/T``) and the shared Linux temporary roots.
MACOS_TEMP = re.compile(
    rf"(?:/private)?/var/folders/[^{_SEGMENT_END}\s]+/[^{_SEGMENT_END}\s]+/[A-Za-z0-9](?![^{_SEGMENT_END}\s])"
)
LINUX_TEMP = re.compile(rf"(?<![\w.~-])(?:/private)?/(?:var/)?tmp(?![^{_SEGMENT_END}\s])")
#: A path that starts at a home folder in any of the forms above, or at ``~/``; drafts drop it to the line end.
HOME_PATH_TO_LINE_END = re.compile(
    rf"(?i)(?<![\w.])(?:~[\\/]|/(?:users|home)/|/root(?![^{_SEGMENT_END}\s])|[a-z]:[\\/]+users[\\/])[^\r\n]*"
)
#: Any other absolute path: POSIX, ``~``, drive letter, or UNC; it runs to the next whitespace.
ABSOLUTE_PATH = re.compile(r"(?<![\w.])(?:~|[A-Za-z]:)?[\\/][^\s'\"`<>|]+")
#: A relative path with two or more separators.
RELATIVE_PATH = re.compile(r"(?<![\w./\\~-])[\w.-]+(?:[\\/][\w.-]+){2,}[\\/]?")
#: A relative path with one or more separators that ends in a file extension.
RELATIVE_FILE = re.compile(r"(?<![\w/])[\w.-]+(?:[\\/][\w.-]+)+\.[A-Za-z0-9]{1,5}\b")
#: File extensions that look like a top-level domain; a dotted name ending in one is a file, not a host.
_FILE_EXTENSIONS = (
    "json|jsonl|md|py|txt|yml|yaml|toml|ini|cfg|log|csv|tsv|png|jpe?g|tiff?|bmp|gif|webp|mp4|mov|avi"
    "|pt|pth|onnx|zip|tar|gz|html?|sh|js|ts"
)
#: A dotted host name with an alphabetic last label, outside a path and not a file name.
HOST_NAME = re.compile(
    r"(?i)(?<![\w@/\\.-])(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    rf"(?!(?:{_FILE_EXTENSIONS})(?![\w-]))[a-z][a-z0-9-]{{0,61}}[a-z0-9](?![\w-]|\.[\w-])"
)


def credential_index(text: str) -> int | None:
    """Return the 1-based number of the first credential pattern found in ``text``, or ``None``.

    Examples:
        >>> credential_index("AKIA" + "0" * 16)
        2
        >>> credential_index("Authorization: " + "Bearer " + "z9" * 12)
        7
        >>> credential_index("nothing private here") is None
        True
    """
    return next((number for number, pattern in enumerate(CREDENTIAL_PATTERNS, 1) if pattern.search(text)), None)


def remove_credentials(text: str, replacement: str) -> str:
    """Replace every credential-shaped run in ``text`` with ``replacement``.

    Examples:
        >>> remove_credentials("use " + "sk-" + "ant-" + "q1" * 12 + " now", "[secret]")
        'use [secret] now'
        >>> remove_credentials("api" + "_key=" + "rf" * 5 + "0123456789", "[secret]")
        '[secret]'
    """
    for pattern in CREDENTIAL_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _is_ipv4(match: re.Match[str]) -> bool:
    """Return whether all four parts of an IPv4-shaped match are 0-255."""
    return all(int(part) <= 255 for part in match.groups())


def has_ipv4(text: str) -> bool:
    """Return whether ``text`` holds an IPv4 address.

    Examples:
        >>> has_ipv4("reached 10.20.30.40:8080")
        True
        >>> has_ipv4("version 1.2.3 and 999.1.1.1")
        False
    """
    return any(_is_ipv4(match) for match in _IPV4_CANDIDATE.finditer(text))


def mask_ipv4(text: str, replacement: str) -> str:
    """Replace every IPv4 address in ``text``, with its port, by ``replacement``.

    Examples:
        >>> mask_ipv4("reached 10.20.30.40:8080 twice", "[address]")
        'reached [address] twice'
    """
    return _IPV4_CANDIDATE.sub(lambda match: replacement if _is_ipv4(match) else match.group(0), text)


def has_unmasked_folder(text: str) -> bool:
    """Return whether ``text`` still names a home folder's owner or a temporary root.

    Placeholders such as ``/Users/<user>/`` and ``<tmp>`` do not count.

    Examples:
        >>> has_unmasked_folder("saved to /users/Dana Quill/x")
        True
        >>> has_unmasked_folder("saved to /Users/<user>/x and <tmp>/y")
        False
    """
    patterns = (POSIX_HOME, WINDOWS_HOME, ROOT_HOME, MACOS_TEMP, LINUX_TEMP)
    return any(pattern.search(text) for pattern in patterns)


def mask_folders(text: str, user: str = "<user>", home: str = "<home>", temp: str = "<tmp>") -> str:
    """Mask the owner of any home folder, the root user's home, and temporary roots.

    Args:
        text: Text to mask.
        user: Placeholder for a home folder's owner name.
        home: Placeholder for ``/root``.
        temp: Placeholder for a temporary root.

    Returns:
        The masked text.

    Examples:
        >>> mask_folders("/Users/Dana Quill/rivet photos and C:\\\\Users\\\\dq\\\\scans")
        '/Users/<user>/rivet photos and C:\\\\Users\\\\<user>\\\\scans'
        >>> mask_folders("/root/cam and /private/var/folders/ab/x1y2/T/run and /tmp/z")
        '<home>/cam and <tmp>/run and <tmp>/z'
    """
    text = WINDOWS_HOME.sub(lambda match: match.group(1) + user, text)
    text = POSIX_HOME.sub(lambda match: match.group(1) + user, text)
    text = ROOT_HOME.sub(home, text)
    text = MACOS_TEMP.sub(temp, text)
    return LINUX_TEMP.sub(temp, text)

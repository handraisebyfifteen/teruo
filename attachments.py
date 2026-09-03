"""Turn file paths typed at the CLI into content blocks the model can read.

The owner can hand teruo a menu photo or a spreadsheet instead of typing
everything out. Strands models its ``ContentBlock`` on the Bedrock Converse
API, which already carries images and documents, so nothing is parsed here —
the bytes go to the model as they are (no openpyxl, no OCR library).

Reading a URL is deliberately not supported. External access is out of scope
(instructions appendix A), so a pasted link gets a plain refusal from Python
rather than a guess from the model. Only local files the owner names.

Everything read this way is a proposal, never a record: the prompts require
teruo to show what it read and get a yes before any tool is called
(design doc ch.9, "never register silently").
"""

from __future__ import annotations

import re
from pathlib import Path

from i18n import t

# Formats Bedrock Converse accepts, mapped from the extensions owners type.
IMAGE_FORMATS = {
    ".png": "png",
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".gif": "gif",
    ".webp": "webp",
}
DOCUMENT_FORMATS = {
    ".pdf": "pdf",
    ".csv": "csv",
    ".doc": "doc",
    ".docx": "docx",
    ".xls": "xls",
    ".xlsx": "xlsx",
    ".html": "html",
    ".htm": "html",
    ".txt": "txt",
    ".md": "md",
}

# Conservative local guards. Bedrock rejects oversized payloads with an
# opaque error; catching it here means the owner gets a sentence they can
# act on instead of a stack trace at the counter.
MAX_IMAGE_BYTES = 3_750_000
MAX_DOCUMENT_BYTES = 4_500_000
MAX_ATTACHMENTS = 5

# Quoted paths first, then bare tokens. A bare token keeps backslash-escaped
# characters, which is what a terminal produces when a file is dragged in.
_TOKEN = re.compile(r'"([^"]+)"|\'([^\']+)\'|((?:\\.|[^\s\\])+)')
_ESCAPED = re.compile(r"\\(.)")

# Bedrock only allows alphanumerics, spaces, hyphens, parentheses and square
# brackets in a document name, and no repeated spaces — a Japanese filename
# would be rejected. The real name still reaches the model in the text block.
_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9 ()\[\]-]+")
_REPEATED_SPACE = re.compile(r" {2,}")


class Attachment:
    """One local file the owner named, already read into memory."""

    def __init__(self, path: Path, kind: str, fmt: str, payload: bytes) -> None:
        self.path = path
        self.kind = kind  # "image" or "document"
        self.format = fmt
        self.payload = payload

    def content_block(self, index: int) -> dict:
        if self.kind == "image":
            return {"image": {"format": self.format, "source": {"bytes": self.payload}}}
        return {
            "document": {
                "format": self.format,
                "name": _document_name(self.path, index),
                "source": {"bytes": self.payload},
            }
        }


def _document_name(path: Path, index: int) -> str:
    """A Bedrock-legal document name, unique within one message."""
    cleaned = _UNSAFE_NAME.sub(" ", path.stem).strip()
    cleaned = _REPEATED_SPACE.sub(" ", cleaned)
    return f"{cleaned} {index}" if cleaned else f"file {index}"


def _looks_like_url(token: str) -> bool:
    return token.lower().startswith(("http://", "https://", "www."))


def _classify(path: Path) -> tuple[str, str] | None:
    suffix = path.suffix.lower()
    if suffix in IMAGE_FORMATS:
        return "image", IMAGE_FORMATS[suffix]
    if suffix in DOCUMENT_FORMATS:
        return "document", DOCUMENT_FORMATS[suffix]
    return None


def _tokens(text: str) -> list[str]:
    raw = [next(group for group in match.groups() if group is not None)
           for match in _TOKEN.finditer(text)]
    return [_ESCAPED.sub(r"\1", token) for token in raw]


def _existing_file(tokens: list[str], start: int) -> tuple[int, Path] | None:
    """Longest run of tokens from ``start`` that names a readable file.

    Owners' filenames have spaces in them — "menu list 2026.xlsx" arrives as
    three tokens — so the run is tried longest-first before falling back to
    the single token.
    """
    for end in range(len(tokens), start, -1):
        candidate = Path(" ".join(tokens[start:end])).expanduser()
        if _classify(candidate) is not None and candidate.is_file():
            return end, candidate
    return None


def split_input(user_input: str) -> tuple[str, list[Attachment], list[str]]:
    """Pull file paths out of a typed line.

    Returns the remaining text, the attachments that were read, and any
    problems worth telling the owner about. A token is only treated as a file
    when it carries a supported extension, so ordinary sentences pass through
    untouched.
    """
    remaining: list[str] = []
    attachments: list[Attachment] = []
    problems: list[str] = []

    tokens = _tokens(user_input)
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if _looks_like_url(token):
            problems.append(t("attachment_no_url"))
            index += 1
            continue

        found = _existing_file(tokens, index)
        if found is None:
            # A supported extension means the owner meant a file. Say so
            # plainly when it isn't there, rather than passing "menu.jpg"
            # off as prose.
            if _classify(Path(token)) is not None:
                problems.append(t("attachment_not_found", path=token))
            else:
                remaining.append(token)
            index += 1
            continue

        index, candidate = found
        kind, fmt = _classify(candidate)
        limit = MAX_IMAGE_BYTES if kind == "image" else MAX_DOCUMENT_BYTES
        if candidate.stat().st_size > limit:
            problems.append(
                t(
                    "attachment_too_large",
                    path=candidate.name,
                    limit=f"{limit / 1_000_000:.1f}",
                )
            )
            continue

        try:
            payload = candidate.read_bytes()
        except OSError as error:
            problems.append(
                t("attachment_unreadable", path=candidate.name, error=error)
            )
            continue

        attachments.append(Attachment(candidate, kind, fmt, payload))

    if len(attachments) > MAX_ATTACHMENTS:
        problems.append(t("attachment_too_many", limit=MAX_ATTACHMENTS))
        attachments = []

    return " ".join(remaining).strip(), attachments, problems


def build_prompt(user_input: str) -> tuple[str | list[dict] | None, list[str]]:
    """Build what gets handed to the agent, plus notes to print first.

    ``None`` means nothing should be sent: the line named only files that
    could not be read, so a model call would add nothing.
    """
    text, attachments, problems = split_input(user_input)

    if problems and not attachments:
        return None, problems

    if not attachments:
        return user_input, problems

    # Attachments lead, then the owner's words. Bedrock wants a text block
    # alongside a document, so stand one in when the line was just a path.
    blocks: list[dict] = [
        attachment.content_block(index)
        for index, attachment in enumerate(attachments, start=1)
    ]
    names = ", ".join(attachment.path.name for attachment in attachments)
    blocks.append({"text": text or t("attachment_default_text", names=names)})
    return blocks, problems

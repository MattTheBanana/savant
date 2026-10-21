#!/usr/bin/env python3
"""Locally force-align supplied lyrics to a song and write a standard LRC file.

Uses WhisperX's phoneme-based forced alignment. No remote inference/API is used;
model weights are downloaded/cached on first use and then run locally.
"""
from __future__ import annotations

import argparse
import difflib
import gc
import json
import math
import re
import shutil
import subprocess
import sys
import os
import wave
import tempfile
import unicodedata
from xml.sax.saxutils import escape as xml_escape, quoteattr
from pathlib import Path
from typing import Any, Iterable

TIMESTAMP_PREFIX_RE = re.compile(r"^\s*(?:\[\s*\d{1,4}:\d{2}(?:[.:]\d{1,3})?\s*\]\s*)+")
INLINE_TIMESTAMP_RE = re.compile(r"<\s*\d{1,4}:\d{2}(?:[.:]\d{1,3})?\s*>")
LRC_LINE_PREFIX_RE = re.compile(r"^(?P<prefix>(?:\[\s*\d{1,4}:\d{2}(?:[.:]\d{1,3})?\s*\])+)(?P<text>.*)$")
LRC_SINGLE_TIMESTAMP_RE = re.compile(r"\[\s*(\d{1,4}):(\d{2})(?:[.:](\d{1,3}))?\s*\]")
LRC_METADATA_RE = re.compile(r"^\s*\[(?:ti|ar|al|by|offset|re|ve|length|la|au|id)\s*:[^\]]*\]\s*$", re.I)
LANGUAGES_WITHOUT_SPACES = {"ja", "zh"}


def clean_lyric_line(raw: str) -> str | None:
    """Remove old LRC timestamps/metadata while retaining display lyrics."""
    line = raw.strip().lstrip("\ufeff")
    if not line or LRC_METADATA_RE.match(line):
        return None
    line = TIMESTAMP_PREFIX_RE.sub("", line)
    line = INLINE_TIMESTAMP_RE.sub("", line)
    line = line.strip()
    if not line or LRC_METADATA_RE.match(line):
        return None
    return line


def read_lyrics(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        # A common fallback for lyrics saved by older Windows applications.
        text = path.read_text(encoding="cp1252", errors="replace")
    lines = [clean_lyric_line(line) for line in text.splitlines()]
    result = [line for line in lines if line]
    if not result:
        raise ValueError(f"No lyric lines were found in {path}.")
    return result


def _xml_id(value: str) -> str:
    """Convert a user label to a conservative XML identifier."""
    result = re.sub(r"[^A-Za-z0-9_.-]", "_", value.strip())
    if not result or not re.match(r"^[A-Za-z_]", result):
        result = "voice_" + result
    return result


def _normalize_singer_config(raw: dict[str, Any], source_description: str = "Singer configuration") -> dict[str, Any]:
    """Validate raw singer config and normalize IDs, headers, members, and defaults."""
    singer_rows = raw.get("singers") if isinstance(raw, dict) else None
    if not isinstance(singer_rows, list) or not singer_rows:
        raise ValueError(f"{source_description} must contain a non-empty 'singers' array.")

    singers: dict[str, dict[str, Any]] = {}
    header_to_id: dict[str, str] = {}
    name_to_id: dict[str, str] = {}
    for row in singer_rows:
        if not isinstance(row, dict):
            raise ValueError("Every singer configuration entry must be a JSON object.")
        header = str(row.get("header", "")).strip()
        name = str(row.get("name", "")).strip()
        if not header or not name:
            raise ValueError("Each singer needs a non-empty 'header' and 'name'.")
        singer_id = _xml_id(str(row.get("id") or name.casefold().replace(" ", "_")))
        singer_type = str(row.get("type", "person")).strip().lower()
        if singer_type not in {"person", "group"}:
            raise ValueError(f"Singer '{name}' type must be 'person' or 'group'.")
        style = str(row.get("style", "")).strip().lower()
        if not style:
            if header.startswith("**") and header.endswith("**") and len(header) > 4:
                style = "bold"
            elif header.startswith("*") and header.endswith("*") and len(header) > 2:
                style = "italic"
            else:
                style = "normal"
        if style not in {"normal", "italic", "bold"}:
            raise ValueError(f"Singer '{name}' style must be normal, italic, or bold.")
        color = str(row.get("color", "")).strip().lower()
        if color and color != "mix" and not re.fullmatch(r"#[0-9a-f]{6}", color):
            raise ValueError(f"Singer '{name}' color must be a six-digit hex value such as #55aaff, or 'mix'.")
        members = row.get("members", [])
        if not isinstance(members, list) or any(not isinstance(m, str) for m in members):
            raise ValueError(f"Singer '{name}' members must be an array of singer names or IDs.")
        if singer_id in singers:
            raise ValueError(f"Duplicate singer ID: {singer_id}")
        if header.casefold() in header_to_id:
            raise ValueError(f"Duplicate singer header: {header}")
        record = {
            "id": singer_id,
            "header": header,
            "name": name,
            "type": singer_type,
            "style": style,
            "color": color,
            "members": members,
        }
        singers[singer_id] = record
        header_to_id[header.casefold()] = singer_id
        name_to_id[name.casefold()] = singer_id
        name_to_id[singer_id.casefold()] = singer_id
        header_to_id.setdefault(name.casefold(), singer_id)

    default_singer = raw.get("default_singer")
    default_id = None
    if default_singer is not None and str(default_singer).strip():
        key = str(default_singer).strip().casefold()
        default_id = name_to_id.get(key) or header_to_id.get(key)
        if default_id is None:
            raise ValueError(f"default_singer '{default_singer}' does not match a configured singer ID or name.")

    mix_group_colors = bool(raw.get("mix_group_colors", True))
    for singer in singers.values():
        resolved: list[str] = []
        for member in singer["members"]:
            found = name_to_id.get(member.casefold()) or header_to_id.get(member.casefold())
            if found is None:
                raise ValueError(f"Singer '{singer['name']}' lists unknown member '{member}'.")
            if found != singer["id"] and found not in resolved:
                resolved.append(found)
        singer["member_ids"] = resolved
    return {
        "singers": singers,
        "header_to_id": header_to_id,
        "name_to_id": name_to_id,
        "default_singer": default_id,
        "mix_group_colors": mix_group_colors,
        "mix_concurrent_lines": bool(raw.get("mix_concurrent_lines", True)),
    }


def load_singer_config(path: Path) -> dict[str, Any]:
    """Load external JSON singer/header/style/color configuration."""
    config_path = path.expanduser().resolve()
    if not config_path.is_file():
        raise FileNotFoundError(f"Singer configuration file not found: {config_path}")
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"Singer configuration is not valid UTF-8 JSON: {config_path}") from exc
    return _normalize_singer_config(raw, f"Singer configuration {config_path}")


def _read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return path.read_text(encoding="cp1252", errors="replace")


def _split_inline_definition_items(value: str) -> list[str]:
    """Split role definitions on commas, keeping quoted names and *styled spans* intact."""
    parts: list[str] = []
    current: list[str] = []
    quoted = False
    index = 0

    while index < len(value):
        char = value[index]
        if char == "\\" and index + 1 < len(value) and value[index + 1] in {'"', "\\"}:
            current.extend((char, value[index + 1]))
            index += 2
            continue
        if char == '"':
            quoted = not quoted
            current.append(char)
            index += 1
            continue
        if not quoted and char == "*":
            marker = "**" if value.startswith("**", index) else "*"
            close = value.find(marker, index + len(marker))
            if close >= 0:
                current.append(value[index:close + len(marker)])
                index = close + len(marker)
                continue
        if char == "," and not quoted:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(char)
        index += 1

    if quoted:
        raise ValueError('Singer names in double quotes must end with a closing ".')
    parts.append("".join(current).strip())
    return parts


def _unquote_singer_name(value: str) -> str:
    """Remove one pair of surrounding double quotes from a singer name."""
    value = value.strip()
    if value.startswith('"'):
        if len(value) < 2 or not value.endswith('"'):
            raise ValueError('Singer names in double quotes must end with a closing ".')
        value = value[1:-1]
        value = value.replace('\\"', '"').replace('\\\\', '\\')
    elif value.endswith('"'):
        raise ValueError('Singer names in double quotes must start with an opening ".')
    return value.strip()


def _split_group_members(value: str) -> list[str]:
    """Split a bold group expression on unquoted commas or ampersands."""
    parts: list[str] = []
    current: list[str] = []
    quoted = False
    index = 0
    saw_separator = False

    while index < len(value):
        char = value[index]
        if char == "\\" and index + 1 < len(value) and value[index + 1] in {'"', "\\", ",", "&"}:
            current.extend((char, value[index + 1]))
            index += 2
            continue
        if char == '"':
            quoted = not quoted
            current.append(char)
            index += 1
            continue
        if char in {",", "&"} and not quoted:
            parts.append(_unquote_singer_name("".join(current)))
            current = []
            saw_separator = True
        else:
            current.append(char)
        index += 1

    if quoted:
        raise ValueError('Singer names in double quotes must end with a closing ".')
    parts.append(_unquote_singer_name("".join(current)))
    if saw_separator:
        if any(not part for part in parts):
            raise ValueError("A bold group definition cannot contain an empty member.")
        return parts
    return []


def parse_inline_singer_definitions(line: str) -> list[dict[str, Any]] | None:
    """Parse a declaration such as [Forrest Nolan, *love interest*, **Forrest Nolan & love interest**].

    Commas separate roles outside quotes/style markers. Double-quote names that contain
    commas (for example, ``"Tyler, the Creator"``). Within a bold group, either commas
    or ampersands can separate members; a quoted comma remains part of a member's name.
    """
    candidate = line.strip().lstrip("\ufeff")
    if not (candidate.startswith("[") and candidate.endswith("]")):
        return None
    inner = candidate[1:-1].strip()
    # Avoid interpreting LRC timestamp/metadata lines as singer definitions.
    if not inner or ":" in inner and re.match(r"^(?:\d{1,4}:\d{2}|(?:ar|ti|al|by|offset|re|ve|length|la|au|id)\s*:)", inner, re.I):
        return None
    parts = _split_inline_definition_items(inner)
    if len(parts) < 2:
        return None
    definitions: list[dict[str, Any]] = []
    used_styles: set[str] = set()
    for part in parts:
        if not part:
            raise ValueError("Singer definitions in brackets cannot contain an empty item.")
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            style, name_expression = "bold", part[2:-2].strip()
        elif part.startswith("*") and part.endswith("*") and len(part) > 2:
            style, name_expression = "italic", part[1:-1].strip()
        else:
            style, name_expression = "normal", part
        members = _split_group_members(name_expression) if style == "bold" else []
        if members:
            # Keep one stable, readable display label while preserving individual members.
            name = " & ".join(members) if "&" in name_expression else ", ".join(members)
        else:
            name = _unquote_singer_name(name_expression)
        if not name:
            raise ValueError("Singer definitions cannot contain an empty singer name.")
        if style in used_styles:
            raise ValueError(f"Bracketed singer definitions may define only one '{style}' role; use normal, *italic*, and **bold** roles once each.")
        used_styles.add(style)
        definitions.append({"raw": part, "name": name, "style": style, "members": members, "is_group": bool(members)})
    if not any(item["style"] == "normal" for item in definitions):
        raise ValueError("The first bracketed singer definition must be an unwrapped default singer name.")
    if definitions[0]["style"] != "normal":
        raise ValueError("The first bracketed singer definition must be an unwrapped default singer name.")
    return definitions


def _top_inline_singer_definitions(path: Path) -> tuple[str, list[dict[str, Any]]] | None:
    text = _read_text_file(path)
    for raw_line in text.splitlines():
        if not raw_line.strip():
            continue
        definitions = parse_inline_singer_definitions(raw_line)
        if definitions is not None:
            return raw_line.strip().lstrip("\ufeff"), definitions
        # Singer definitions are only supported at the top, ignoring leading blank lines.
        return None
    return None


def load_inline_singer_config(path: Path, color_config: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Build a singer config from the first bracketed lyrics line; JSON remains optional for colors."""
    parsed = _top_inline_singer_definitions(path)
    if parsed is None:
        return None
    definition_line, definitions = parsed
    custom_singers = list((color_config or {}).get("singers", {}).values())
    custom_by_name = {str(s.get("name", "")).casefold(): s for s in custom_singers}
    rows: list[dict[str, Any]] = []
    style_to_name = {item["style"]: item["name"] for item in definitions}
    names_in_defs = {item["name"].casefold() for item in definitions}

    for item in definitions:
        name, style = item["name"], item["style"]
        is_group = style == "bold" and bool(item.get("is_group"))
        members = list(item.get("members", [])) if is_group else []
        custom = custom_by_name.get(name.casefold())
        # If the config calls the duet something else (e.g. "Both"), match by member set.
        if custom is None and is_group:
            expected = {member.casefold() for member in members}
            custom = next((s for s in custom_singers if s.get("type") == "group" and {str(m).casefold() for m in s.get("members", [])} == expected), None)
        color = str(custom.get("color", "")) if custom else ("mix" if is_group else "")
        row: dict[str, Any] = {
            "header": item["raw"],
            "id": _xml_id(name.casefold().replace(" ", "_")),
            "name": name,
            "type": "group" if is_group else "person",
            "style": style,
            "color": color,
            "members": members,
        }
        rows.append(row)

    # Inline speaker markers are per-line, not stateful header directives.
    raw_config = {
        "singers": rows,
        "default_singer": style_to_name["normal"],
        "mix_group_colors": (color_config or {}).get("mix_group_colors", True),
        "mix_concurrent_lines": (color_config or {}).get("mix_concurrent_lines", True),
    }
    config = _normalize_singer_config(raw_config, f"Singer definitions in {path}")
    config["inline_definition_line"] = definition_line
    config["inline_style_markers"] = {
        item["style"]: config["name_to_id"][item["name"].casefold()] for item in definitions
    }
    return config


def _speaker_units_from_character_labels(
    lines: list[str], character_speakers: list[list[str | None]], language: str
) -> list[list[str | None]]:
    """Map character-level singer assignments to the aligner's word/character units."""
    grouped: list[list[str | None]] = []
    for line_number, (line, labels) in enumerate(zip(lines, character_speakers), start=1):
        if language.lower() in LANGUAGES_WITHOUT_SPACES:
            units = [(index, index + 1, char) for index, char in enumerate(line) if not char.isspace()]
        else:
            units = [(match.start(), match.end(), match.group(0)) for match in re.finditer(r"\S+", line)]
        unit_labels: list[str | None] = []
        for start, end, unit in units:
            labels_in_unit = set(labels[start:end])
            if len(labels_in_unit) > 1:
                raise ValueError(
                    f"Singer markup changes inside the word/character unit {unit!r} on lyric line {line_number}. "
                    "Place singer markers between words so each aligned word has one singer."
                )
            unit_labels.append(labels[start] if start < len(labels) else None)
        grouped.append(unit_labels)
    return grouped


def _parse_inline_markup_line(
    line: str,
    active_style: str | None,
    inline_markers: dict[str, str],
) -> tuple[str, list[str | None], str | None]:
    """Remove singer markers from one line while tracking speaker IDs character by character.

    Single asterisks select the featured/italic singer; double asterisks select the
    duet/group singer. Marker state is returned so a marked section can continue over
    a newline. A backslash escapes a literal asterisk (``\\*``).
    """
    default_speaker = inline_markers["normal"]
    visible: list[str] = []
    labels: list[str | None] = []
    index = 0

    while index < len(line):
        # Allow literal asterisks in lyric text without treating them as singer syntax.
        if line[index] == "\\" and index + 1 < len(line) and line[index + 1] == "*":
            visible.append("*")
            labels.append(inline_markers.get(active_style, default_speaker))
            index += 2
            continue

        if line.startswith("**", index):
            marker_length, marker_style = 2, "bold"
        elif line[index] == "*":
            marker_length, marker_style = 1, "italic"
        else:
            visible.append(line[index])
            labels.append(inline_markers.get(active_style, default_speaker))
            index += 1
            continue

        if active_style == marker_style:
            # Closing a section returns to the default singer. Markup sections do not nest.
            active_style = None
            index += marker_length
            continue
        if active_style is not None:
            raise ValueError(
                f"Singer markup cannot nest: close the current {'*' if active_style == 'italic' else '**'} "
                f"section before opening {'*' if marker_style == 'italic' else '**'} in '{line}'."
            )
        if marker_style not in inline_markers:
            marker = "*...*" if marker_style == "italic" else "**...**"
            raise ValueError(
                f"Lyrics use {marker} singer markup, but the bracketed singer definition does not define that role."
            )
        active_style = marker_style
        index += marker_length

    # Markup can leave spaces around the visible content; trim text and its labels in lockstep.
    visible_text = "".join(visible)
    left_trimmed = len(visible_text) - len(visible_text.lstrip())
    right = len(visible_text.rstrip())
    return visible_text[left_trimmed:right], labels[left_trimmed:right], active_style


def read_lyrics_with_speaker_units(
    path: Path,
    singer_config: dict[str, Any] | None = None,
    language: str = "en",
) -> tuple[list[str], list[str | None], list[list[str | None]]]:
    """Read plain lyric lines, line-level agents, and per-unit agent assignments.

    For bracket-defined singer roles, ``*...*`` and ``**...**`` can start and end
    anywhere in the lyric body, including across line breaks or multiple times on one
    line. Every aligned word/character receives the role active at its first character.
    Legacy standalone singer-header files remain supported when no bracket definition
    is present.
    """
    text = _read_text_file(path)
    inline_markers = singer_config.get("inline_style_markers") if singer_config else None
    definition_line = singer_config.get("inline_definition_line") if singer_config else None

    lines: list[str] = []
    line_speakers: list[str | None] = []
    character_speakers: list[list[str | None]] = []

    if inline_markers:
        if not inline_markers.get("normal"):
            raise ValueError("Inline singer definitions require one normal/default singer.")
        active_style: str | None = None
        for raw_line in text.splitlines():
            raw_clean = raw_line.strip().lstrip("\ufeff")
            if definition_line and raw_clean == definition_line:
                continue
            cleaned = clean_lyric_line(raw_line)
            if cleaned is None:
                # Do not reset active markup across empty/metadata lines.
                continue
            text_line, labels, active_style = _parse_inline_markup_line(cleaned, active_style, inline_markers)
            if not text_line:
                continue
            lines.append(text_line)
            character_speakers.append(labels)
            unit_ids = _speaker_units_from_character_labels([text_line], [labels], language)[0]
            unique_ids = set(unit_ids)
            line_speakers.append(next(iter(unique_ids)) if len(unique_ids) == 1 else None)
        if active_style is not None:
            marker = "*...*" if active_style == "italic" else "**...**"
            raise ValueError(f"Unclosed {marker} singer section at end of lyrics file {path}.")
        if not lines:
            raise ValueError(f"No lyric lines were found in {path} after removing the singer definition.")
        unit_speakers = _speaker_units_from_character_labels(lines, character_speakers, language)
        return lines, line_speakers, unit_speakers

    # The old config format supports a whole-line speaker header like '*Frank*'.
    if singer_config is None:
        lines = read_lyrics(path)
        return lines, [None] * len(lines), [[None] * len(units) for units in lyric_units_by_line(lines, language)[0]]

    current_singer = singer_config.get("default_singer")
    header_map = singer_config["header_to_id"]
    for raw_line in text.splitlines():
        cleaned = clean_lyric_line(raw_line)
        if not cleaned:
            continue
        header_singer = header_map.get(cleaned.casefold())
        if header_singer is not None:
            current_singer = header_singer
            continue
        lines.append(cleaned)
        line_speakers.append(current_singer)
        character_speakers.append([current_singer] * len(cleaned))
    if not lines:
        raise ValueError(f"No lyric lines were found in {path}. If using singer headers, make sure lyric text follows them.")
    return lines, line_speakers, _speaker_units_from_character_labels(lines, character_speakers, language)


def read_lyrics_with_speakers(
    path: Path, singer_config: dict[str, Any] | None = None
) -> tuple[list[str], list[str | None]]:
    """Backwards-compatible wrapper returning cleaned lines and uniform line speaker IDs."""
    lines, speakers, _unit_speakers = read_lyrics_with_speaker_units(path, singer_config)
    return lines, speakers


def _rgb_mix(hex_colors: list[str]) -> str | None:
    """Average valid hex colors in linear RGB for a less muddy composite color."""
    colors = [c for c in hex_colors if re.fullmatch(r"#[0-9a-fA-F]{6}", c or "")]
    if not colors:
        return None
    channels = [[int(c[i:i + 2], 16) / 255.0 for c in colors] for i in (1, 3, 5)]
    def to_linear(value: float) -> float:
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
    def to_srgb(value: float) -> float:
        return 12.92 * value if value <= 0.0031308 else 1.055 * (value ** (1 / 2.4)) - 0.055
    output = []
    for values in channels:
        linear = sum(to_linear(v) for v in values) / len(values)
        output.append(max(0, min(255, round(to_srgb(linear) * 255))))
    return "#" + "".join(f"{v:02x}" for v in output)


def resolved_singer_colors(singer_config: dict[str, Any]) -> dict[str, str | None]:
    singers = singer_config["singers"]
    resolved: dict[str, str | None] = {}
    visiting: set[str] = set()
    def resolve(singer_id: str) -> str | None:
        if singer_id in resolved:
            return resolved[singer_id]
        singer = singers[singer_id]
        if singer_id in visiting:
            return None
        visiting.add(singer_id)
        color = singer["color"]
        if color == "mix" and singer_config.get("mix_group_colors", True):
            color = _rgb_mix([value for member in singer["member_ids"] if (value := resolve(member))])
        if not color or color == "mix":
            color = None
        resolved[singer_id] = color
        visiting.remove(singer_id)
        return color
    for singer_id in singers:
        resolve(singer_id)
    return resolved


def _ttml_seconds(value: float) -> str:
    return f"{max(0.0, value):.3f}s"


def create_navidrome_ttml(
    lines: list[str],
    units_by_line: list[list[str]],
    mapped_by_line: list[list[dict[str, Any] | None]],
    speaker_ids: list[str | None],
    singer_config: dict[str, Any] | None,
    *,
    language: str,
    offset_seconds: float = 0.0,
    line_offsets: dict[int, float] | None = None,
    duration: float | None = None,
    instrumental_cues: bool = False,
    instrumental_threshold: float = 6.0,
    unit_speakers_by_line: list[list[str | None]] | None = None,
) -> str:
    """Build named-agent TTML with word-level timing and per-word speaker assignments."""
    line_offsets = line_offsets or {}
    singers = singer_config["singers"] if singer_config else {}
    color_map = resolved_singer_colors(singer_config) if singer_config else {}
    if singer_config:
        # Any unannotated lyric lines use a stable named default agent instead of being
        # accidentally attributed to the first explicitly declared speaker.
        if any(speaker is None for speaker in speaker_ids) and not singer_config.get("default_singer"):
            default_agent_id = "main"
            if default_agent_id not in singers:
                default_agent = {"id": "main", "name": "Lead Vocal", "type": "person", "style": "normal", "color": "", "members": [], "member_ids": []}
                singers = {"main": default_agent, **singers}
                color_map["main"] = None
        else:
            default_agent_id = singer_config.get("default_singer") or next(iter(singers), "main")
    else:
        default_agent_id = "main"
        singers = {"main": {"id": "main", "name": "Lead Vocal", "type": "person", "style": "normal", "color": "", "members": [], "member_ids": []}}
        color_map = {"main": None}

    records: list[dict[str, Any]] = []
    for i, (line, units, entries) in enumerate(zip(lines, units_by_line, mapped_by_line), start=1):
        starts = [v for entry in entries if (v := _entry_start(entry)) is not None]
        ends = [v for entry in entries if (v := _entry_end(entry)) is not None]
        if not starts:
            continue
        correction = offset_seconds + line_offsets.get(i, 0.0)
        start = max(0.0, min(starts) + correction)
        end = max(start + 0.04, (max(ends) if ends else min(starts) + 0.3) + correction)
        if duration is not None:
            end = min(end, max(start + 0.04, duration))
        line_speaker = speaker_ids[i - 1] if i - 1 < len(speaker_ids) else None
        # The aligner unit mapper is word-based for spaced languages and character-based
        # for Japanese/Chinese. Keep the original inter-word spaces attached to each unit.
        if language.lower() in LANGUAGES_WITHOUT_SPACES:
            matches = list(re.finditer(r"\S", line))
        else:
            matches = list(re.finditer(r"\S+", line))
        chunks: list[str] = []
        for match_index, match in enumerate(matches):
            chunk_end = matches[match_index + 1].start() if match_index + 1 < len(matches) else len(line)
            chunks.append(line[match.start():chunk_end])

        # Explicit per-unit speaker IDs enable a line to switch speakers one or more
        # times. If not provided, preserve the original whole-line speaker behavior.
        if unit_speakers_by_line is not None and i - 1 < len(unit_speakers_by_line):
            raw_unit_speakers = list(unit_speakers_by_line[i - 1])
        else:
            raw_unit_speakers = [line_speaker] * len(chunks)
        unit_speakers: list[str] = []
        for unit_index in range(len(chunks)):
            candidate = raw_unit_speakers[unit_index] if unit_index < len(raw_unit_speakers) else line_speaker
            if candidate not in singers:
                candidate = default_agent_id
            unit_speakers.append(candidate)
        distinct_speakers = set(unit_speakers)
        speaker = next(iter(distinct_speakers)) if len(distinct_speakers) == 1 else None

        spans: list[str] = []
        for unit_index, chunk in enumerate(chunks):
            entry = entries[unit_index] if unit_index < len(entries) else None
            word_speaker = unit_speakers[unit_index] if unit_index < len(unit_speakers) else (speaker or default_agent_id)
            span_attrs = [f'ttm:agent={quoteattr(_xml_id(word_speaker))}']
            word_style = singers.get(word_speaker, {}).get("style")
            if color_map.get(word_speaker) or word_style in {"italic", "bold"}:
                span_attrs.append(f'style={quoteattr(_xml_id(word_speaker) + "-style")}')
            word_start = _entry_start(entry)
            if word_start is None:
                spans.append('<span ' + " ".join(span_attrs) + '>' + xml_escape(chunk) + '</span>')
                continue
            word_end = _entry_end(entry)
            adjusted_start = max(0.0, word_start + correction)
            if word_end is None:
                next_start = next((x for later in entries[unit_index + 1:] if (x := _entry_start(later)) is not None), None)
                word_end = next_start if next_start is not None else end - correction
            adjusted_end = max(adjusted_start + 0.01, word_end + correction)
            adjusted_end = min(adjusted_end, max(adjusted_start + 0.01, end))
            span_attrs.extend([
                f'begin={quoteattr(_ttml_seconds(adjusted_start))}',
                f'end={quoteattr(_ttml_seconds(adjusted_end))}',
            ])
            spans.append('<span ' + " ".join(span_attrs) + '>' + xml_escape(chunk) + '</span>')
        if not spans:
            spans = [xml_escape(line)]
        records.append({
            "start": start, "end": end, "text": line, "speaker": speaker,
            "unit_speakers": unit_speakers, "spans": "".join(spans), "line_number": i,
        })

    if not records:
        raise ValueError("Cannot create TTML: no lyric lines have usable timestamps.")

    # Create cues for long instrumental gaps, mirroring the standard LRC output.
    cue_records: list[dict[str, Any]] = []
    if instrumental_cues:
        if records[0]["start"] >= instrumental_threshold:
            cue_records.append({"start": 0.0, "end": min(0.75, max(0.1, records[0]["start"])), "text": "♪"})
        for previous, current in zip(records, records[1:]):
            if current["start"] - previous["end"] >= instrumental_threshold:
                cue_time = min(current["start"] - 0.05, previous["end"] + 0.30)
                cue_records.append({"start": max(0.0, cue_time), "end": max(0.1, cue_time + 0.5), "text": "♪"})
        if duration is not None and duration - records[-1]["end"] >= instrumental_threshold:
            cue_time = min(duration, records[-1]["end"] + 0.30)
            cue_records.append({"start": cue_time, "end": min(duration, cue_time + 0.5), "text": "♪"})

    output: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<tt xmlns="http://www.w3.org/ns/ttml" xmlns:ttm="http://www.w3.org/ns/ttml#metadata" xmlns:tts="http://www.w3.org/ns/ttml#styling" xml:lang=' + quoteattr(language) + '>',
        '  <head>',
        '    <styling>',
    ]
    for sid, singer in singers.items():
        style_attrs = []
        color = color_map.get(sid)
        if color:
            style_attrs.append(f'tts:color={quoteattr(color)}')
        if singer.get("style") == "italic":
            style_attrs.append('tts:fontStyle="italic"')
        elif singer.get("style") == "bold":
            style_attrs.append('tts:fontWeight="bold"')
        if style_attrs:
            output.append(f'      <style xml:id={quoteattr(_xml_id(sid) + "-style")} ' + " ".join(style_attrs) + '/>')
    output.extend(['    </styling>', '    <metadata>'])
    # Ensure all named agents referenced in a lyric line are declared once.
    referenced_ids: list[str] = []
    for row in records:
        if row.get("speaker"):
            referenced_ids.append(row["speaker"])
        referenced_ids.extend(row.get("unit_speakers", []))
    used_ids = list(dict.fromkeys(sid for sid in referenced_ids if sid))
    for sid in used_ids:
        singer = singers.get(sid, {"name": sid, "type": "person"})
        agent_type = "group" if singer.get("type") == "group" else "person"
        output.append(f'      <ttm:agent xml:id={quoteattr(_xml_id(sid))} type={quoteattr(agent_type)}><ttm:name>{xml_escape(str(singer.get("name", sid)))}</ttm:name></ttm:agent>')
    output.extend(['    </metadata>', '  </head>', '  <body>', '    <div>'])
    all_records = [(r["start"], 1, r) for r in records] + [(r["start"], 0, r) for r in cue_records]
    all_records.sort(key=lambda item: (item[0], item[1]))
    for _start, _priority, record in all_records:
        if record.get("text") == "♪":
            text_span = f'<span begin={quoteattr(_ttml_seconds(record["start"]))} end={quoteattr(_ttml_seconds(record["end"]))}>♪</span>'
            output.append(f'      <p begin={quoteattr(_ttml_seconds(record["start"]))} end={quoteattr(_ttml_seconds(record["end"]))}>{text_span}</p>')
            continue
        attrs = [f'begin={quoteattr(_ttml_seconds(record["start"]))}', f'end={quoteattr(_ttml_seconds(record["end"]))}']
        sid = record.get("speaker")
        # Only give the containing paragraph an agent if the whole line belongs to
        # one speaker. Mixed lines have per-word ttm:agent attributes on their spans.
        if sid:
            attrs.append(f'ttm:agent={quoteattr(_xml_id(sid))}')
            singer_style = singers.get(sid, {}).get("style")
            if color_map.get(sid) or singer_style in {"italic", "bold"}:
                attrs.append(f'style={quoteattr(_xml_id(sid) + "-style")}')
        output.append('      <p ' + " ".join(attrs) + '>' + record["spans"] + '</p>')
    output.extend(['    </div>', '  </body>', '</tt>'])
    return "\n".join(output) + "\n"


def lyric_units_by_line(lines: list[str], language: str) -> tuple[list[list[str]], str]:
    """Return the model's expected word/character units grouped by lyric line."""
    if language.lower() in LANGUAGES_WITHOUT_SPACES:
        grouped = [[char for char in line if not char.isspace()] for line in lines]
        transcript = "".join(lines)
    else:
        grouped = [line.split() for line in lines]
        transcript = " ".join(" ".join(line.split()) for line in lines)
    grouped = [units for units in grouped if units]
    return grouped, transcript


def format_lrc_timestamp(seconds: float) -> str:
    """Format seconds as standard [MM:SS.cc] LRC time, rounded to centiseconds."""
    centiseconds = max(0, int(round(seconds * 100)))
    minutes, remainder = divmod(centiseconds, 60 * 100)
    secs, centis = divmod(remainder, 100)
    return f"[{minutes:02d}:{secs:02d}.{centis:02d}]"


def normalize_unit(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    return "".join(ch for ch in value if ch.isalnum())


def map_source_units(source_units: list[str], aligned_words: list[dict[str, Any]]) -> list[dict[str, Any] | None]:
    """Map source units by normalized token identity, then sequence alignment."""
    source_norm = [normalize_unit(word) for word in source_units]
    aligned_norm = [normalize_unit(str(item.get("word", ""))) for item in aligned_words]
    # Positional mapping is safe only when token content also matches. An equal
    # token count is not enough: one split/misread token can shift every later line.
    if len(source_norm) == len(aligned_norm) and source_norm == aligned_norm:
        return list(aligned_words)
    mapped: list[dict[str, Any] | None] = [None] * len(source_units)
    # SequenceMatcher preserves order and handles occasional unalignable tokens.
    matcher = difflib.SequenceMatcher(a=source_norm, b=aligned_norm, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for source_idx, aligned_idx in zip(range(i1, i2), range(j1, j2)):
                mapped[source_idx] = aligned_words[aligned_idx]
    return mapped


def mapped_words_by_line(
    units_by_line: list[list[str]], aligned_words: list[dict[str, Any]]
) -> list[list[dict[str, Any] | None]]:
    """Map the flat aligner output back to source lyric lines."""
    source_units = [unit for group in units_by_line for unit in group]
    mapped = map_source_units(source_units, aligned_words)
    result: list[list[dict[str, Any] | None]] = []
    cursor = 0
    for units in units_by_line:
        result.append(mapped[cursor:cursor + len(units)])
        cursor += len(units)
    return result


def _entry_start(entry: dict[str, Any] | None) -> float | None:
    if entry is None:
        return None
    value = entry.get("start")
    return float(value) if isinstance(value, (int, float)) and math.isfinite(float(value)) else None


def _entry_end(entry: dict[str, Any] | None) -> float | None:
    if entry is None:
        return None
    value = entry.get("end")
    return float(value) if isinstance(value, (int, float)) and math.isfinite(float(value)) else None


def line_start_estimates(mapped_by_line: list[list[dict[str, Any] | None]]) -> list[float | None]:
    """Get the first usable aligned word start for each line."""
    estimates: list[float | None] = []
    for entries in mapped_by_line:
        estimates.append(next((start for entry in entries if (start := _entry_start(entry)) is not None), None))
    return estimates


def refine_line_alignments(
    lines: list[str],
    units_by_line: list[list[str]],
    mapped_by_line: list[list[dict[str, Any] | None]],
    aligned_audio: Any,
    duration: float,
    align_model: Any,
    metadata: Any,
    device: str,
    whisperx_module: Any,
    window_seconds: float,
) -> tuple[list[list[dict[str, Any] | None]], list[str]]:
    """Second-pass alignment: realign each lyric line inside a narrow first-pass window.

    This does not create new lyrics. The first pass anchors each line; the second
    pass can adjust word boundaries locally without allowing the entire transcript
    to drift across the recording.
    """
    refined: list[list[dict[str, Any] | None]] = []
    changes: list[str] = []
    initial_starts = line_start_estimates(mapped_by_line)

    for index, (line, units, first_pass_entries) in enumerate(zip(lines, units_by_line, mapped_by_line), start=1):
        valid = [entry for entry in first_pass_entries if entry is not None]
        starts = [value for entry in valid if (value := _entry_start(entry)) is not None]
        ends = [value for entry in valid if (value := _entry_end(entry)) is not None]
        if not starts or not ends:
            refined.append(first_pass_entries)
            continue

        anchor_start = min(starts)
        anchor_end = max(ends)
        window_start = max(0.0, anchor_start - window_seconds)
        window_end = min(duration, max(anchor_end + window_seconds, window_start + 0.35))
        if window_end <= window_start:
            refined.append(first_pass_entries)
            continue

        segment = {"start": window_start, "end": window_end, "text": line}
        try:
            local_result = whisperx_module.align(
                [segment], align_model, metadata, aligned_audio, device,
                return_char_alignments=False,
            )
            local_words = local_result.get("word_segments")
            if local_words is None:
                local_words = [word for item in local_result.get("segments", []) for word in item.get("words", [])]
            candidate = map_source_units(units, local_words or [])
            candidate_count = sum(1 for entry in candidate if _entry_start(entry) is not None)
            first_pass_count = sum(1 for entry in first_pass_entries if _entry_start(entry) is not None)
            if candidate_count == 0:
                refined.append(first_pass_entries)
                changes.append(f"Line {index}: local pass had no usable words; kept first-pass timing.")
                continue
            if candidate_count < first_pass_count:
                refined.append(first_pass_entries)
                changes.append(
                    f"Line {index}: local pass matched fewer units ({candidate_count}/{len(units)} "
                    f"vs {first_pass_count}/{len(units)}); kept first-pass timing."
                )
                continue
            refined.append(candidate)
            new_start = next((value for entry in candidate if (value := _entry_start(entry)) is not None), None)
            old_start = initial_starts[index - 1]
            if old_start is not None and new_start is not None and abs(new_start - old_start) >= 0.03:
                changes.append(f"Line {index}: {old_start:.2f}s -> {new_start:.2f}s ({new_start - old_start:+.2f}s).")
        except Exception as exc:
            # Refinement is a safety-net pass; retain the first pass if a line-level
            # alignment fails rather than aborting a mostly successful song.
            refined.append(first_pass_entries)
            changes.append(f"Line {index}: local pass failed ({type(exc).__name__}); kept first-pass timing.")

    return refined, changes


def create_lrc_lines(
    lines: list[str],
    units_by_line: list[list[str]],
    aligned_words: list[dict[str, Any]],
    offset_seconds: float = 0.0,
    line_offsets: dict[int, float] | None = None,
    *,
    mapped_by_line: list[list[dict[str, Any] | None]] | None = None,
    duration: float | None = None,
    instrumental_cues: bool = False,
    instrumental_threshold: float = 6.0,
) -> tuple[list[str], list[str]]:
    """Create line-level LRC, optional line offsets, and instrumental-gap cues."""
    line_offsets = line_offsets or {}
    if mapped_by_line is None:
        mapped_by_line = mapped_words_by_line(units_by_line, aligned_words)

    warnings: list[str] = []
    records: list[dict[str, Any]] = []
    for line_number, (display_line, units, entries) in enumerate(
        zip(lines, units_by_line, mapped_by_line), start=1
    ):
        starts = [value for entry in entries if (value := _entry_start(entry)) is not None]
        ends = [value for entry in entries if (value := _entry_end(entry)) is not None]
        if not starts:
            warnings.append(f"Line {line_number} could not be timestamped and was omitted: {display_line}")
            continue

        correction = offset_seconds + line_offsets.get(line_number, 0.0)
        start = max(0.0, min(starts) + correction)
        has_end_times = bool(ends)
        end = max(start, (max(ends) if ends else min(starts)) + correction)
        records.append({
            "line_number": line_number,
            "start": start,
            "end": end,
            "has_end_times": has_end_times,
            "text": display_line,
            "unit_count": len(units),
            "matched_count": sum(1 for entry in entries if entry is not None and _entry_start(entry) is not None),
        })

        # Flag only extreme implausibility; rapid rap/vocal delivery can legitimately
        # produce short lines, so this is a review hint rather than an automatic edit.
        if has_end_times and end - start < max(0.04, len(units) * 0.018) and len(units) >= 3:
            warnings.append(
                f"Line {line_number} has an unusually short aligned span ({end - start:.2f}s for "
                f"{len(units)} text units); review this fast/compressed phrase."
            )
        unmatched = max(0, len(units) - sum(1 for entry in entries if entry is not None and _entry_start(entry) is not None))
        if unmatched:
            warnings.append(f"Line {line_number} has {unmatched} unit(s) without usable word timing: {display_line}")

    if len(records) < len(lines):
        warnings.append(f"Only {len(records)} of {len(lines)} lyric lines received timestamps.")

    for previous, current in zip(records, records[1:]):
        if current["start"] < previous["start"]:
            warnings.append(
                f"Timestamp order check: line {current['line_number']} starts before the preceding lyric line; review alignment."
            )

    cue_before_first = False
    cues_after_record: set[int] = set()
    trailing_cue_time: float | None = None
    cue_count = 0
    if instrumental_cues and records:
        first = records[0]
        if first["start"] >= instrumental_threshold:
            cue_before_first = True
            cue_count += 1

        for index, (previous, current) in enumerate(zip(records, records[1:])):
            gap = current["start"] - previous["end"]
            if gap >= instrumental_threshold:
                cues_after_record.add(index)
                cue_count += 1

        last = records[-1]
        if duration is not None and duration - last["end"] >= instrumental_threshold:
            trailing_cue_time = min(duration, max(last["end"] + 0.30, 0.0))
            cue_count += 1

    # Preserve the input lyric order instead of silently reordering lyrics if a bad
    # timestamp was produced. Cues are inserted only between the lines that created
    # the gap; timestamp-order warnings tell the user when the lyrics need review.
    output_entries: list[tuple[float, str]] = []
    if cue_before_first:
        output_entries.append((0.0, "♪"))
    for index, record in enumerate(records):
        output_entries.append((record["start"], record["text"]))
        if index in cues_after_record:
            cue_time = max(0.0, records[index]["end"] + 0.30)
            output_entries.append((cue_time, "♪"))
    if trailing_cue_time is not None:
        output_entries.append((trailing_cue_time, "♪"))
    lrc_lines = [f"{format_lrc_timestamp(timestamp)}{text}" for timestamp, text in output_entries]
    if cue_count:
        warnings.append(f"Inserted {cue_count} instrumental cue(s) (♪) for gaps of at least {instrumental_threshold:.1f}s.")
    return lrc_lines, warnings


def adjust_lrc_timestamps(
    text: str, offset_seconds: float = 0.0, line_offsets: dict[int, float] | None = None
) -> tuple[str, int]:
    """Shift timestamps in an existing LRC without loading the ML model.

    Per-line corrections apply to timestamped lyric rows (1-based); metadata and
    untimed rows are preserved as-is. Multiple timestamps on a row are all shifted.
    """
    line_offsets = line_offsets or {}
    result: list[str] = []
    lyric_row = 0
    for line in text.splitlines():
        match = LRC_LINE_PREFIX_RE.match(line)
        if not match:
            result.append(line)
            continue
        lyric_row += 1
        correction = offset_seconds + line_offsets.get(lyric_row, 0.0)
        if correction == 0.0:
            result.append(line)
            continue

        def shift(match: re.Match[str]) -> str:
            minutes = int(match.group(1))
            seconds = int(match.group(2))
            fraction = match.group(3) or "0"
            centiseconds = int(fraction.ljust(2, "0")[:2])
            original_seconds = minutes * 60 + seconds + centiseconds / 100.0
            return format_lrc_timestamp(max(0.0, original_seconds + correction))

        shifted_prefix = LRC_SINGLE_TIMESTAMP_RE.sub(shift, match.group("prefix"))
        result.append(shifted_prefix + match.group("text"))
    return "\n".join(result) + ("\n" if text.endswith(("\n", "\r")) else ""), lyric_row


def adjust_existing_lrc(args: argparse.Namespace) -> int:
    """Adjust a previously generated LRC without running the alignment model again."""
    source_path = args.adjust_lrc.expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"LRC file not found: {source_path}")
    if source_path.suffix.lower() != ".lrc":
        raise ValueError("--adjust-lrc expects an existing .lrc file.")
    output_path = args.output.expanduser().resolve() if args.output else source_path.with_name(
        f"{source_path.stem}.adjusted.lrc"
    )
    if output_path.suffix.lower() != ".lrc":
        raise ValueError("Adjusted output must use the .lrc extension.")
    if output_path == source_path and not args.overwrite:
        raise FileExistsError(
            "To adjust the existing LRC in place, specify --output with the same path and add --overwrite. "
            "Otherwise, omit --output to create a separate .adjusted.lrc file."
        )
    if output_path.exists() and output_path != source_path and not args.overwrite:
        raise FileExistsError(f"Output already exists: {output_path}\nUse --overwrite to replace it.")
    for optional_input in (args.line_offsets, args.phrase_offsets):
        if optional_input is not None and output_path == optional_input.expanduser().resolve():
            raise ValueError("Adjusted LRC output must not overwrite a line-offset or phrase-offset JSON input.")
    if not math.isfinite(args.offset) or abs(args.offset) > 30:
        raise ValueError("Global timing offset must be finite and between -30 and 30 seconds.")

    try:
        source_text = source_path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        source_text = source_path.read_text(encoding="cp1252", errors="replace")
    timestamped_rows = sum(1 for line in source_text.splitlines() if LRC_LINE_PREFIX_RE.match(line))
    if timestamped_rows == 0:
        raise ValueError(f"No timestamped lyric rows were found in {source_path}.")
    line_offsets = load_line_offsets(args.line_offsets, timestamped_rows)
    lrc_lines = [match.group("text") for raw_line in source_text.splitlines() if (match := LRC_LINE_PREFIX_RE.match(raw_line))]
    phrase_offsets = load_phrase_offsets(args.phrase_offsets, lrc_lines)
    for line_number, correction in phrase_offsets.items():
        line_offsets[line_number] = line_offsets.get(line_number, 0.0) + correction
    adjusted_text, row_count = adjust_lrc_timestamps(source_text, args.offset, line_offsets)

    if args.dry_run:
        print("Dry run: no files were written and no model was loaded.")
        print(f"Input LRC: {source_path}")
        print(f"Output:    {output_path}")
        print(f"Timed rows: {row_count}")
        print(f"Global timing offset: {args.offset:+.2f}s")
        print(f"Per-line corrections: {len(line_offsets)}")
        print(f"Phrase-specific corrections matched: {len(phrase_offsets)}")
        return 0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(adjusted_text, encoding="utf-8", newline="\n")
    print(f"Wrote: {output_path}")
    print(f"Adjusted rows: {row_count}")
    print(f"Global timing offset: {args.offset:+.2f}s; per-line corrections: {len(line_offsets)}; phrase-specific matches: {len(phrase_offsets)}")
    return 0


def load_line_offsets(path: Path | None, line_count: int) -> dict[int, float]:
    """Load per-line timing corrections from a JSON object like {"3": -0.15}."""
    if path is None:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in line-offset file {path}: {exc}") from exc
    except OSError as exc:
        raise ValueError(f"Could not read line-offset file {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("Line-offset file must be a JSON object mapping 1-based line numbers to seconds.")

    corrections: dict[int, float] = {}
    for raw_line_number, raw_offset in data.items():
        try:
            line_number = int(raw_line_number)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid line number in line-offset file: {raw_line_number!r}") from exc
        if str(line_number) != str(raw_line_number).strip() or line_number < 1 or line_number > line_count:
            raise ValueError(
                f"Line number {raw_line_number!r} is invalid; use numbers from 1 to {line_count}."
            )
        if isinstance(raw_offset, bool) or not isinstance(raw_offset, (int, float)):
            raise ValueError(f"Offset for line {line_number} must be a number of seconds.")
        offset = float(raw_offset)
        if not math.isfinite(offset) or abs(offset) > 30:
            raise ValueError(f"Offset for line {line_number} must be finite and between -30 and 30 seconds.")
        corrections[line_number] = offset
    return corrections


def _normalize_phrase_key(text: str) -> str:
    """Normalize visible lyric text for robust exact-line correction matching."""
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def load_phrase_offsets(path: Path | None, lines: list[str]) -> dict[int, float]:
    """Map exact lyric-line strings to per-line corrections.

    A phrase key must match a whole cleaned lyric line (case- and whitespace-insensitive).
    If that exact line occurs more than once, the correction is applied to every occurrence.
    """
    if path is None:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in phrase-offset file {path}: {exc}") from exc
    except OSError as exc:
        raise ValueError(f"Could not read phrase-offset file {path}: {exc}") from exc
    if not isinstance(data, dict) or not data:
        raise ValueError("Phrase-offset file must be a non-empty JSON object mapping exact lyric lines to seconds.")

    lines_by_key: dict[str, list[int]] = {}
    for line_number, line in enumerate(lines, start=1):
        lines_by_key.setdefault(_normalize_phrase_key(line), []).append(line_number)

    corrections: dict[int, float] = {}
    seen_keys: set[str] = set()
    for raw_phrase, raw_offset in data.items():
        if not isinstance(raw_phrase, str) or not raw_phrase.strip():
            raise ValueError("Every phrase-offset key must be a non-empty lyric line.")
        phrase_key = _normalize_phrase_key(raw_phrase)
        if phrase_key in seen_keys:
            raise ValueError(f"Phrase-offset file contains duplicate normalized phrase: {raw_phrase!r}.")
        seen_keys.add(phrase_key)
        if isinstance(raw_offset, bool) or not isinstance(raw_offset, (int, float)):
            raise ValueError(f"Offset for phrase {raw_phrase!r} must be a number of seconds.")
        offset = float(raw_offset)
        if not math.isfinite(offset) or abs(offset) > 30:
            raise ValueError(f"Offset for phrase {raw_phrase!r} must be finite and between -30 and 30 seconds.")
        matches = lines_by_key.get(phrase_key, [])
        if not matches:
            raise ValueError(
                f"Phrase-offset text {raw_phrase!r} did not match a complete cleaned lyric line. "
                "Use the exact line as it appears after singer markup is removed."
            )
        for line_number in matches:
            corrections[line_number] = corrections.get(line_number, 0.0) + offset
    return corrections


def select_device(requested: str, torch_module: Any) -> str:
    if requested == "auto":
        return "cuda" if torch_module.cuda.is_available() else "cpu"
    if requested == "cuda" and not torch_module.cuda.is_available():
        raise RuntimeError("CUDA was requested, but PyTorch cannot see a CUDA-capable GPU. Use --device cpu or auto.")
    return requested


def run_doctor() -> int:
    print("Lyrics Audio Aligner diagnostics")
    print(f"Python: {sys.version.split()[0]} ({sys.executable})")
    ffmpeg = shutil.which("ffmpeg")
    print(f"FFmpeg: {ffmpeg or 'NOT FOUND (required on PATH)'}")
    try:
        import torch
        print(f"PyTorch: {torch.__version__}")
        print(f"CUDA available: {torch.cuda.is_available()}")
    except Exception as exc:
        print(f"PyTorch: ERROR ({exc})")
    try:
        import whisperx
        print(f"WhisperX: available ({getattr(whisperx, '__version__', 'version not exposed')})")
    except Exception as exc:
        print(f"WhisperX: ERROR ({exc})")
    try:
        import demucs_infer
        print(f"Vocal separation: available ({getattr(demucs_infer, '__version__', 'version not exposed')})")
    except Exception:
        print("Vocal separation: not installed (optional; run install-vocal-separation.bat to enable)")
    project_root = Path(__file__).resolve().parent
    tifa_root = project_root / "vendor" / "TIFA"
    tifa_python = project_root / ".tifa-venv" / "Scripts" / "python.exe"
    model_root = project_root / "models" / "TIFA-1.0-ST"
    if (tifa_root / "infer.py").is_file() and tifa_python.is_file():
        model_found = any(
            candidate.suffix.lower() == ".pt"
            and (candidate.parent / "config.yaml").is_file()
            and (candidate.parent / "vocabulary.json").is_file()
            for candidate in model_root.rglob("*.pt")
        ) if model_root.is_dir() else False
        print(f"TIFA source/environment: available ({tifa_root})")
        print(f"TIFA pretrained model: {'available' if model_found else 'NOT FOUND (run install-tifa.bat again)'}")
        try:
            probe = subprocess.run(
                [str(tifa_python), "-c", "import torch; print('TIFA PyTorch:', torch.__version__); print('TIFA CUDA available:', torch.cuda.is_available())"],
                text=True, capture_output=True, timeout=20,
            )
            if probe.returncode == 0:
                print(probe.stdout.strip())
            else:
                print(f"TIFA Python: ERROR ({probe.stderr.strip()[-600:]})")
        except Exception as exc:
            print(f"TIFA Python: ERROR ({exc})")
    else:
        print("TIFA: not installed (optional; run install-tifa.bat to enable the singing-trained backend)")
    return 0 if ffmpeg else 2


def aligner_word_list(result: dict[str, Any]) -> list[dict[str, Any]]:
    words = result.get("word_segments")
    if words is None:
        words = [word for item in result.get("segments", []) for word in item.get("words", [])]
    return list(words or [])


def _parse_textgrid_interval_tier(textgrid_path: Path, tier_name: str = "texts") -> list[dict[str, Any]]:
    """Read Praat long-format TextGrid intervals from a named IntervalTier.

    Kept dependency-free so the main CLI can consume TIFA output without importing
    TIFA's separate Python environment.
    """
    text = textgrid_path.read_text(encoding="utf-8-sig", errors="replace")
    tier_blocks = re.finditer(
        r"(?ms)^\s*item\s*\[\d+\]:\s*\n(.*?)(?=^\s*item\s*\[\d+\]:|\Z)", text
    )
    for tier_match in tier_blocks:
        block = tier_match.group(1)
        name_match = re.search(r'^\s*name\s*=\s*"((?:[^"]|"")*)"\s*$', block, re.M)
        if not name_match:
            continue
        found_name = name_match.group(1).replace('""', '"')
        if found_name.casefold() != tier_name.casefold():
            continue
        if not re.search(r'^\s*class\s*=\s*"IntervalTier"\s*$', block, re.M):
            continue
        results: list[dict[str, Any]] = []
        interval_blocks = re.finditer(
            r"(?ms)^\s*intervals\s*\[\d+\]:\s*\n(.*?)(?=^\s*intervals\s*\[\d+\]:|\Z)",
            block,
        )
        for interval_match in interval_blocks:
            interval = interval_match.group(1)
            xmin_match = re.search(r"^\s*xmin\s*=\s*([-+0-9.eE]+)\s*$", interval, re.M)
            xmax_match = re.search(r"^\s*xmax\s*=\s*([-+0-9.eE]+)\s*$", interval, re.M)
            label_match = re.search(r'^\s*text\s*=\s*"((?:[^"]|"")*)"\s*$', interval, re.M)
            if not (xmin_match and xmax_match and label_match):
                continue
            start, end = float(xmin_match.group(1)), float(xmax_match.group(1))
            label = label_match.group(1).replace('""', '"').strip()
            if label and math.isfinite(start) and math.isfinite(end) and end > start:
                results.append({"word": label, "start": start, "end": end})
        return results
    raise ValueError(f"No IntervalTier named '{tier_name}' was found in TIFA output: {textgrid_path}")


def detect_audio_pause_centers(
    audio: Any,
    *,
    sample_rate: int = 16000,
    frame_ms: int = 20,
    minimum_pause_seconds: float = 0.18,
) -> list[tuple[float, float, float]]:
    """Detect low-energy gaps in a mono waveform; return (start, end, center) seconds.

    This is deliberately conservative. On isolated vocal audio, phrase gaps are often
    clearer; on the full mix it may find fewer useful pauses and chunking falls back to
    line boundaries rather than inventing a silence.
    """
    import numpy as np

    values = np.asarray(audio, dtype=np.float32).reshape(-1)
    hop = max(1, int(round(sample_rate * frame_ms / 1000.0)))
    frame_count = len(values) // hop
    if frame_count < 1:
        return []
    frames = values[:frame_count * hop].reshape(frame_count, hop)
    rms = np.sqrt(np.mean(np.square(frames, dtype=np.float32), axis=1) + 1e-12)
    reference = float(np.percentile(rms, 90))
    if reference <= 1e-5:
        return []
    threshold = max(0.001, reference * 0.045)
    quiet = rms <= threshold
    # Fill tiny one-frame holes within a pause to reduce sensitivity to codec noise.
    if len(quiet) >= 3:
        for i in range(1, len(quiet) - 1):
            if not quiet[i] and quiet[i - 1] and quiet[i + 1]:
                quiet[i] = True
    min_frames = max(1, int(math.ceil(minimum_pause_seconds * sample_rate / hop)))
    pauses: list[tuple[float, float, float]] = []
    start_idx: int | None = None
    for i, is_quiet in enumerate(quiet.tolist() + [False]):
        if is_quiet and start_idx is None:
            start_idx = i
        elif not is_quiet and start_idx is not None:
            end_idx = i
            if end_idx - start_idx >= min_frames:
                start = start_idx * hop / sample_rate
                end = min(len(values) / sample_rate, end_idx * hop / sample_rate)
                pauses.append((start, end, (start + end) / 2.0))
            start_idx = None
    return pauses


def estimate_line_spans(
    units_by_line: list[list[str]],
    mapped_by_line: list[list[dict[str, Any] | None]],
    duration: float,
) -> list[tuple[float, float]]:
    """Build robust coarse line spans, interpolating only lines with missing timestamps."""
    raw: list[tuple[float | None, float | None]] = []
    for entries in mapped_by_line:
        starts = [x for entry in entries if (x := _entry_start(entry)) is not None]
        ends = [x for entry in entries if (x := _entry_end(entry)) is not None]
        raw.append((min(starts) if starts else None, max(ends) if ends else None))
    known = [i for i, (start, _end) in enumerate(raw) if start is not None]
    if not known:
        raise RuntimeError("The initial WhisperX pass could not locate any lyric lines, so TIFA chunks cannot be placed safely.")

    starts: list[float] = []
    for i, (start, _end) in enumerate(raw):
        if start is not None:
            starts.append(min(max(0.0, start), duration))
            continue
        prev = next((j for j in reversed(known) if j < i), None)
        nxt = next((j for j in known if j > i), None)
        if prev is not None and nxt is not None:
            left = raw[prev][1] if raw[prev][1] is not None else raw[prev][0]
            right = raw[nxt][0]
            fraction = (i - prev) / (nxt - prev)
            guess = float(left or 0.0) + (float(right or left or 0.0) - float(left or 0.0)) * fraction
        elif nxt is not None:
            guess = float(raw[nxt][0] or 0.0) - 0.6 * (nxt - i)
        elif prev is not None:
            guess = float(raw[prev][1] or raw[prev][0] or 0.0) + 0.5 * (i - prev)
        else:
            guess = duration * i / max(1, len(raw))
        starts.append(min(duration, max(0.0, guess)))

    result: list[tuple[float, float]] = []
    for i, (start, end) in enumerate(raw):
        final_start = starts[i]
        if end is None or end <= final_start:
            next_start = starts[i + 1] if i + 1 < len(starts) else duration
            estimate = max(0.18, min(0.35 * max(1, len(units_by_line[i])), max(0.18, next_start - final_start)))
            final_end = min(duration, final_start + estimate)
        else:
            final_end = min(duration, max(final_start + 0.05, end))
        result.append((final_start, final_end))
    return result


def plan_tifa_chunks(
    units_by_line: list[list[str]],
    mapped_by_line: list[list[dict[str, Any] | None]],
    audio: Any,
    duration: float,
    *,
    max_chunk_seconds: float = 42.0,
    context_seconds: float = 1.8,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Split supplied lyric lines into sub-minute chunks, preferring acoustic pauses.

    WhisperX timings are used only as rough anchors for deciding which lines belong to
    each chunk. Final timestamps are replaced by TIFA's singing-trained alignment.
    Internal audio cuts preferentially land inside low-energy pauses near line breaks.
    """
    spans = estimate_line_spans(units_by_line, mapped_by_line, duration)
    pauses = detect_audio_pause_centers(audio)
    plans: list[dict[str, Any]] = []
    notes: list[str] = []
    line_count = len(spans)
    first = 0
    audio_start = max(0.0, spans[0][0] - context_seconds)

    while first < line_count:
        last_line_end = spans[-1][1]
        if last_line_end + context_seconds - audio_start <= max_chunk_seconds:
            audio_end = min(duration, last_line_end + context_seconds)
            if audio_end <= audio_start:
                audio_end = min(duration, audio_start + 0.5)
            plans.append({"line_start": first, "line_end": line_count, "audio_start": audio_start, "audio_end": audio_end, "pause_cut": False})
            break

        if line_count - first == 1:
            audio_end = min(duration, last_line_end + context_seconds)
            remaining_duration = audio_end - audio_start
            if remaining_duration > 59.0:
                raise RuntimeError(
                    "A single remaining lyric line spans more than TIFA's approximately 1-minute model context. "
                    "Split this unusually long lyric line into two lines in the source .txt, or use --aligner whisperx."
                )
            plans.append({"line_start": first, "line_end": line_count, "audio_start": audio_start, "audio_end": audio_end, "pause_cut": False})
            notes.append(
                f"The final chunk is {remaining_duration:.1f}s because its remaining lyric line could not be split at a word boundary."
            )
            break

        target_time = audio_start + max_chunk_seconds - context_seconds
        min_span = min(18.0, max_chunk_seconds * 0.45)
        max_span = max_chunk_seconds - 0.7
        candidates: list[dict[str, Any]] = []
        for split_at in range(first + 1, line_count):
            prev_start, prev_end = spans[split_at - 1]
            next_start, _next_end = spans[split_at]
            # If coarse timestamps overlap, use the next line start as anchor; otherwise
            # place the estimate in the gap between the previous end and next start.
            anchor = (prev_end + next_start) / 2.0 if next_start >= prev_end else next_start
            span_len = anchor - audio_start
            # The rough line boundary may be a second or two late/early. Allow
            # a pause just beyond the nominal anchor window to qualify, then
            # validate the actual acoustic cut below. This is important when a
            # sung word lasts longer than WhisperX predicts.
            if span_len < min_span or span_len > max_chunk_seconds + 3.0:
                continue
            plausible_pauses = [
                p for p in pauses
                if max(audio_start + 1.0, prev_start + 0.15, anchor - 3.0, prev_end - 1.1) <= p[2]
                and p[2] <= min(duration - 0.1, anchor + 0.35, next_start + 0.35)
            ]
            if plausible_pauses:
                pause = min(plausible_pauses, key=lambda p: abs(p[2] - anchor))
                cut_time = pause[2]
                if cut_time - audio_start > max_chunk_seconds:
                    continue
                score = abs(cut_time - target_time) - 6.0 + abs(cut_time - anchor) * 0.5
                pause_cut = True
            else:
                if span_len > max_span:
                    continue
                cut_time = anchor
                score = abs(cut_time - target_time) + 3.5
                pause_cut = False
            candidates.append({"split_at": split_at, "cut_time": cut_time, "score": score, "pause_cut": pause_cut, "anchor": anchor})

        if candidates:
            # Prefer a genuine pause when candidates are comparably close to the target.
            chosen = min(candidates, key=lambda item: item["score"])
            split_at, cut_time, pause_cut = chosen["split_at"], chosen["cut_time"], chosen["pause_cut"]
        else:
            # Fallback: force a line boundary near the maximum context length. This is
            # safer than cutting the text in the middle of a word, but it may cut audio
            # without a natural pause and is reported for review.
            possible = [k for k in range(first + 1, line_count) if spans[k][0] > audio_start + 8.0]
            if not possible:
                split_at = min(first + 1, line_count - 1)
            else:
                split_at = min(possible, key=lambda k: abs(spans[k][0] - target_time))
            cut_time = spans[split_at][0]
            pause_cut = False

        cut_time = min(duration - 0.05, max(audio_start + 0.25, cut_time))
        plans.append({
            "line_start": first, "line_end": split_at,
            "audio_start": audio_start, "audio_end": cut_time,
            "pause_cut": pause_cut,
        })
        if not pause_cut:
            notes.append(
                f"TIFA chunk boundary before lyric line {split_at + 1} had no detected pause nearby; "
                "the audio was cut at a coarse line anchor instead. Review this transition."
            )
        first = split_at
        # Starting exactly at the pause center preserves the original timeline and avoids
        # overlapping duplicated lyric words between TIFA chunks.
        audio_start = cut_time

    # Avoid empty / near-empty chunks and enforce the model's documented context limit.
    for chunk_index, chunk in enumerate(plans, start=1):
        chunk_length = chunk["audio_end"] - chunk["audio_start"]
        if chunk_length <= 0.25:
            raise RuntimeError(f"TIFA chunk {chunk_index} is too short ({chunk_length:.2f}s). Review the lyric timings.")
        if chunk_length > 59.0:
            raise RuntimeError(
                f"TIFA chunk {chunk_index} is {chunk_length:.1f}s, beyond TIFA's approximately 1-minute context. "
                "Try reducing --tifa-chunk-seconds or check whether the coarse pass lost a line."
            )
    if len(plans) > 1 and not pauses:
        notes.append("No low-energy audio pauses were detected; TIFA chunks use lyric-line anchors instead. --separate-vocals may help.")
    return plans, notes


def find_tifa_model_path(model_spec: Path | None, project_root: Path) -> tuple[Path, Path]:
    """Resolve TIFA checkpoint and its config/vocabulary directory."""
    base = (model_spec or (project_root / "models" / "TIFA-1.0-ST")).expanduser().resolve()
    candidates: list[Path] = []
    if base.is_file():
        candidates = [base]
    elif base.is_dir():
        candidates = sorted(base.rglob("model.pt")) + sorted(base.rglob("*.pt"))
    else:
        raise FileNotFoundError(
            f"TIFA model path was not found: {base}. Run install-tifa.bat or supply --tifa-model."
        )
    seen: set[Path] = set()
    for checkpoint in candidates:
        checkpoint = checkpoint.resolve()
        if checkpoint in seen:
            continue
        seen.add(checkpoint)
        folder = checkpoint.parent
        if (folder / "config.yaml").is_file() and (folder / "vocabulary.json").is_file():
            return checkpoint, folder
    raise FileNotFoundError(
        f"No TIFA checkpoint with sibling config.yaml and vocabulary.json was found at {base}. "
        "Run install-tifa.bat or point --tifa-model at the model.pt file or containing folder."
    )


def _write_tifa_wav(path: Path, audio: Any, sample_rate: int = 16000) -> None:
    """Write float audio as PCM16 WAV without requiring an audio writer package."""
    import numpy as np

    samples = np.asarray(audio, dtype=np.float32).reshape(-1)
    pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2", copy=False)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(pcm.tobytes())


def run_tifa_alignment(
    audio: Any,
    duration: float,
    lines: list[str],
    units_by_line: list[list[str]],
    coarse_by_line: list[list[dict[str, Any] | None]],
    *,
    language: str,
    tifa_root: Path,
    tifa_python: Path,
    tifa_model: Path | None,
    max_chunk_seconds: float,
    context_seconds: float,
    device: str,
) -> tuple[list[list[dict[str, Any] | None]], list[str], dict[str, Any]]:
    """Run TIFA on pause-aware lyric chunks; its word/phoneme model replaces coarse timestamps."""
    supported = {"en"}
    if language.lower() not in supported:
        raise ValueError("The first TIFA integration maps semantic word intervals to English space-delimited lyrics only. Use --aligner whisperx for non-English lyrics for now.")
    tifa_root = tifa_root.expanduser().resolve()
    tifa_python = tifa_python.expanduser().resolve()
    infer_script = tifa_root / "infer.py"
    if not infer_script.is_file():
        raise FileNotFoundError(f"TIFA source was not found at {tifa_root}. Run install-tifa.bat first.")
    if not tifa_python.is_file():
        raise FileNotFoundError(f"TIFA Python environment was not found at {tifa_python}. Run install-tifa.bat first.")
    checkpoint, model_dir = find_tifa_model_path(tifa_model, tifa_root.parent.parent)

    chunk_plan, notes = plan_tifa_chunks(
        units_by_line, coarse_by_line, audio, duration,
        max_chunk_seconds=max_chunk_seconds, context_seconds=context_seconds,
    )
    import tempfile

    with tempfile.TemporaryDirectory(prefix="lyrics-aligner-tifa-") as temp_name:
        work = Path(temp_name)
        input_dir = work / "input"
        output_dir = work / "output"
        input_dir.mkdir()
        output_dir.mkdir()
        for idx, chunk in enumerate(chunk_plan, start=1):
            stem = f"chunk_{idx:03d}"
            start_sample = max(0, int(round(chunk["audio_start"] * 16000)))
            end_sample = min(len(audio), int(round(chunk["audio_end"] * 16000)))
            if end_sample <= start_sample:
                raise RuntimeError(f"TIFA chunk {idx} resolved to an empty audio slice.")
            _write_tifa_wav(input_dir / f"{stem}.wav", audio[start_sample:end_sample])
            transcript = "\n".join(" ".join(units) for units in units_by_line[chunk["line_start"]:chunk["line_end"]])
            (input_dir / f"{stem}.txt").write_text(transcript + "\n", encoding="utf-8", newline="\n")

        command = [
            str(tifa_python), str(infer_script), str(input_dir),
            "--model", str(checkpoint), "--language", language,
            "--stat", "--output-dir", str(output_dir), "--batch-size", "1", "--num-workers", "0",
        ]
        env = os.environ.copy()
        if device == "cpu":
            env["CUDA_VISIBLE_DEVICES"] = ""
        print(f"Running singing-trained TIFA alignment on {len(chunk_plan)} pause-aware chunk(s) (model context limit ~60s)...")
        process = subprocess.run(command, cwd=tifa_root, env=env, text=True, capture_output=True)
        if process.stdout:
            print(process.stdout.rstrip())
        if process.returncode != 0:
            detail = process.stderr.strip() or process.stdout.strip() or "No diagnostic output was returned."
            raise RuntimeError(
                f"TIFA inference failed with exit code {process.returncode}. Check the TIFA install/model paths.\n{detail[-5000:]}"
            )
        if process.stderr:
            # Lightning/progress output often goes to stderr even on success. Only surface
            # the tail so warnings are visible without flooding the console.
            tail = process.stderr.strip().splitlines()[-12:]
            if tail:
                print("TIFA runtime notes:\n" + "\n".join(tail))

        tifa_mapped: list[list[dict[str, Any] | None]] = [list() for _ in lines]
        chunk_diagnostics: list[dict[str, Any]] = []
        for idx, chunk in enumerate(chunk_plan, start=1):
            stem = f"chunk_{idx:03d}"
            textgrid_path = next(iter(output_dir.rglob(f"{stem}.TextGrid")), None)
            if textgrid_path is None:
                textgrid_path = next(iter(output_dir.rglob(f"{stem}.textgrid")), None)
            source_indexes = list(range(chunk["line_start"], chunk["line_end"]))
            if textgrid_path is None:
                notes.append(f"TIFA did not produce TextGrid output for chunk {idx}; kept WhisperX timing for those lines.")
                for source_index in source_indexes:
                    tifa_mapped[source_index] = coarse_by_line[source_index]
                continue
            try:
                local_entries = _parse_textgrid_interval_tier(textgrid_path, "texts")
            except Exception as exc:
                notes.append(f"TIFA TextGrid for chunk {idx} could not be read ({type(exc).__name__}); kept WhisperX timing for those lines.")
                for source_index in source_indexes:
                    tifa_mapped[source_index] = coarse_by_line[source_index]
                continue
            shift = float(chunk["audio_start"])
            global_entries = [
                {"word": item["word"], "start": item["start"] + shift, "end": item["end"] + shift}
                for item in local_entries
            ]
            local_units = units_by_line[chunk["line_start"]:chunk["line_end"]]
            local_mapped = mapped_words_by_line(local_units, global_entries)
            chunk_source_count = sum(len(group) for group in local_units)
            chunk_matched_count = sum(
                1 for row in local_mapped for entry in row if entry is not None and _entry_start(entry) is not None
            )
            if chunk_matched_count < max(1, int(math.ceil(chunk_source_count * 0.55))):
                notes.append(
                    f"TIFA matched only {chunk_matched_count}/{chunk_source_count} units in chunk {idx}; "
                    "kept WhisperX timings for that chunk. Check the lyrics/pronunciation and inspect the chunk."
                )
                for local_index, source_index in enumerate(source_indexes):
                    tifa_mapped[source_index] = coarse_by_line[source_index]
            else:
                for local_index, source_index in enumerate(source_indexes):
                    candidate = local_mapped[local_index]
                    coarse = coarse_by_line[source_index]
                    tifa_matched = sum(1 for entry in candidate if entry is not None and _entry_start(entry) is not None)
                    coarse_matched = sum(1 for entry in coarse if entry is not None and _entry_start(entry) is not None)
                    if tifa_matched == 0 and coarse_matched:
                        tifa_mapped[source_index] = coarse
                        notes.append(f"TIFA returned no word timings for lyric line {source_index + 1}; kept WhisperX timing for this line.")
                    else:
                        tifa_mapped[source_index] = candidate
            chunk_diagnostics.append({
                "chunk": idx,
                "line_start": chunk["line_start"] + 1,
                "line_end": chunk["line_end"],
                "audio_start": round(chunk["audio_start"], 3),
                "audio_end": round(chunk["audio_end"], 3),
                "duration_seconds": round(chunk["audio_end"] - chunk["audio_start"], 3),
                "pause_aligned_boundary": bool(chunk["pause_cut"]),
                "matched_units": chunk_matched_count,
                "total_units": chunk_source_count,
            })

        raw_diagnosis: Any = None
        diagnosis_path = next(iter(output_dir.rglob("diagnosis.json")), None)
        if diagnosis_path is not None:
            try:
                raw_diagnosis = json.loads(diagnosis_path.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError):
                raw_diagnosis = None

        payload = {
            "aligner": "TIFA-1.0-ST",
            "language": language,
            "model_checkpoint": str(checkpoint),
            "device_requested": device,
            "context_note": "TIFA-1.0-ST supplies the final word intervals. WhisperX is used only for coarse chunk planning and independent comparison. Chunks are cut at low-energy pauses near lyric-line boundaries where possible. TIFA diagnosis scores are self-consistency metrics, not calibrated probabilities.",
            "chunks": chunk_diagnostics,
            "diagnosis": raw_diagnosis,
            "notes": notes,
        }
        return tifa_mapped, notes, payload


SHORT_FUNCTION_WORDS = {
    # A deliberately small, common set. These words are especially prone to weak
    # realization in singing, and are only repaired when model/neighbor evidence
    # indicates a missing, compressed, or late interval.
    "a", "an", "the", "i", "of", "to", "and", "or", "but", "as", "at", "by",
    "for", "from", "in", "into", "on", "onto", "off", "out", "up", "with", "if",
    "is", "it", "its", "it's", "be", "been", "am", "are", "was", "were", "do",
    "does", "did", "no", "not", "so", "we", "me", "my", "us", "he", "she", "him",
    "her", "our", "you", "your", "ye", "im", "ive", "ill", "id", "thats", "there",
}


def _valid_word_interval(entry: dict[str, Any] | None) -> bool:
    start, end = _entry_start(entry), _entry_end(entry)
    return start is not None and end is not None and start >= 0 and end > start


def _timing_is_plausible_for_context(
    candidate: dict[str, Any] | None,
    previous: dict[str, Any] | None,
    following: dict[str, Any] | None,
    *,
    max_duration: float = 0.70,
) -> bool:
    """Reject coarse timings that would create a grossly out-of-order token."""
    if not _valid_word_interval(candidate):
        return False
    start = _entry_start(candidate)
    end = _entry_end(candidate)
    assert start is not None and end is not None
    if end - start > max_duration:
        return False
    previous_start = _entry_start(previous)
    previous_end = _entry_end(previous)
    following_start = _entry_start(following)
    # A small coarticulatory overlap is normal. A large backwards jump or interval
    # buried deeply inside the preceding word is not a safe replacement.
    if previous_start is not None and start < previous_start - 0.20:
        return False
    if previous_end is not None and start < previous_end - 0.18:
        return False
    if following_start is not None and start >= following_start - 0.025:
        return False
    if following_start is not None and end > following_start + 0.14:
        return False
    return True


def repair_weak_word_timings(
    units_by_line: list[list[str]],
    singing_by_line: list[list[dict[str, Any] | None]],
    coarse_by_line: list[list[dict[str, Any] | None]],
    *,
    max_interpolation_gap: float = 0.72,
) -> tuple[list[list[dict[str, Any] | None]], list[str]]:
    """Conservatively recover missing/late weak words from model and neighbor context.

    TIFA supplies singing-oriented final timings and WhisperX supplies an independent
    coarse alignment. For a small set of frequently reduced function words, this:
      1) restores a missing TIFA interval from WhisperX when it fits between neighbors;
      2) replaces a suspiciously late/compressed TIFA interval with a plausible earlier
         WhisperX interval when the two models disagree;
      3) if both models miss the word, estimates a short interval in a real gap between
         the preceding word's end and the following word's start.

    It never moves normal/content-word timings and does not shift a whole line. The
    heuristic is intentionally conservative and records every edit for the review log.
    """
    repaired = [list(row) for row in singing_by_line]
    flat: list[tuple[int, int, str]] = []
    for line_index, units in enumerate(units_by_line):
        for unit_index, unit in enumerate(units):
            flat.append((line_index, unit_index, unit))

    notes: list[str] = []

    def get_entry(flat_index: int, source: list[list[dict[str, Any] | None]]) -> dict[str, Any] | None:
        row, col, _ = flat[flat_index]
        if row >= len(source) or col >= len(source[row]):
            return None
        entry = source[row][col]
        return entry if _valid_word_interval(entry) else None

    def neighbors(flat_index: int) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        previous = None
        following = None
        for j in range(flat_index - 1, -1, -1):
            previous = get_entry(j, repaired) or get_entry(j, coarse_by_line)
            if previous is not None:
                break
        for j in range(flat_index + 1, len(flat)):
            following = get_entry(j, repaired) or get_entry(j, coarse_by_line)
            if following is not None:
                break
        return previous, following

    # Walk backwards so an inferred weak word can anchor the missing weak word before it.
    for flat_index in range(len(flat) - 1, -1, -1):
        line_index, unit_index, unit = flat[flat_index]
        token = normalize_unit(unit)
        if token not in SHORT_FUNCTION_WORDS:
            continue
        current = repaired[line_index][unit_index] if unit_index < len(repaired[line_index]) else None
        coarse = coarse_by_line[line_index][unit_index] if (
            line_index < len(coarse_by_line) and unit_index < len(coarse_by_line[line_index])
        ) else None
        previous, following = neighbors(flat_index)
        prev_end = _entry_end(previous)
        next_start = _entry_start(following)

        if not _valid_word_interval(current):
            # Prefer the independent aligner's word interval when its placement agrees
            # with transcript order and nearby strong-word anchors.
            if _timing_is_plausible_for_context(coarse, previous, following):
                replacement = dict(coarse or {})
                replacement["word"] = unit
                repaired[line_index][unit_index] = replacement
                notes.append(
                    f"Context repair: restored missing weak word {unit!r} on line {line_index + 1} "
                    f"from WhisperX at {_entry_start(replacement):.2f}-{_entry_end(replacement):.2f}s."
                )
                continue

            # If both models missed it, use only a real, bounded inter-word gap. Place
            # the estimate immediately before the following anchored word; don't spread
            # or shift the already aligned content words.
            if prev_end is not None and next_start is not None:
                gap = next_start - prev_end
                if 0.045 <= gap <= max_interpolation_gap:
                    target_duration = min(0.15, max(0.055, 0.045 + 0.025 * len(token)))
                    estimated_duration = min(target_duration, gap - 0.025)
                    if estimated_duration >= 0.035:
                        # Bias toward the earlier portion of the gap. Right-justifying
                        # every inferred weak word would reproduce the exact failure we
                        # are trying to fix: the next line would still appear too late.
                        spare = max(0.0, gap - estimated_duration - 0.015)
                        start = prev_end + 0.015 + spare * 0.22
                        end = start + estimated_duration
                        if end <= next_start - 0.005 and start >= prev_end + 0.005 and end > start:
                            repaired[line_index][unit_index] = {
                                "word": unit,
                                "start": start,
                                "end": end,
                                "inferred": True,
                            }
                            notes.append(
                                f"Context repair: inferred missing weak word {unit!r} on line {line_index + 1} "
                                f"at {start:.2f}-{end:.2f}s inside a {gap:.2f}s gap between neighboring words."
                            )
            continue

        if not _valid_word_interval(coarse):
            continue
        current_start, current_end = _entry_start(current), _entry_end(current)
        coarse_start, coarse_end = _entry_start(coarse), _entry_end(coarse)
        assert current_start is not None and current_end is not None
        assert coarse_start is not None and coarse_end is not None
        if coarse_start >= current_start - 0.12:
            continue
        current_duration = current_end - current_start
        crowded_by_following = next_start is not None and (
            current_start >= next_start - 0.04 or current_end > next_start + 0.08
        )
        near_line_start = unit_index <= 1
        compressed = current_duration < 0.075
        # A late early-line function word is the user-reported failure mode; elsewhere,
        # require stronger evidence that its interval collided with the following word.
        if not (near_line_start or crowded_by_following or compressed):
            continue
        if not _timing_is_plausible_for_context(coarse, previous, following):
            continue
        replacement = dict(coarse)
        replacement["word"] = unit
        repaired[line_index][unit_index] = replacement
        notes.append(
            f"Context repair: moved weak word {unit!r} on line {line_index + 1} earlier using "
            f"neighbor-validated WhisperX timing ({current_start:.2f}s -> {coarse_start:.2f}s)."
        )

    return repaired, notes


def compare_line_timing_models(
    lines: list[str],
    coarse_by_line: list[list[dict[str, Any] | None]],
    final_by_line: list[list[dict[str, Any] | None]],
    *,
    start_threshold: float = 0.25,
    end_threshold: float = 0.35,
) -> list[str]:
    """Flag material WhisperX/TIFA disagreements for listening review; never auto-shift from disagreement alone."""
    notes: list[str] = []
    for idx, (text, coarse, final) in enumerate(zip(lines, coarse_by_line, final_by_line), start=1):
        old_start = min((x for entry in coarse if (x := _entry_start(entry)) is not None), default=None)
        new_start = min((x for entry in final if (x := _entry_start(entry)) is not None), default=None)
        old_end = max((x for entry in coarse if (x := _entry_end(entry)) is not None), default=None)
        new_end = max((x for entry in final if (x := _entry_end(entry)) is not None), default=None)
        fragments: list[str] = []
        if old_start is not None and new_start is not None and abs(new_start - old_start) >= start_threshold:
            fragments.append(f"start {old_start:.2f}s -> {new_start:.2f}s ({new_start - old_start:+.2f}s)")
        if old_end is not None and new_end is not None and abs(new_end - old_end) >= end_threshold:
            fragments.append(f"end {old_end:.2f}s -> {new_end:.2f}s ({new_end - old_end:+.2f}s)")
        if fragments:
            notes.append(f"Model disagreement on line {idx}: " + "; ".join(fragments) + f"; review: {text}")
    return notes


def load_alignment_audio(
    audio_path: Path,
    whisperx_module: Any,
    *,
    separate_vocals: bool,
    demucs_model: str,
    device: str,
    demucs_segment: float,
    vocal_output: Path | None,
    overwrite: bool,
) -> Any:
    """Load audio, optionally separating vocals with modern local Demucs inference."""
    if not separate_vocals:
        print("Loading audio...")
        return whisperx_module.load_audio(str(audio_path))

    import importlib.util
    if importlib.util.find_spec("demucs_infer") is None:
        raise RuntimeError(
            "Vocal separation was requested but demucs-infer is not installed in this project's .venv. "
            "Run install-vocal-separation.bat, then retry."
        )

    if vocal_output is not None:
        vocal_output = vocal_output.expanduser().resolve()
        if vocal_output.suffix.lower() != ".wav":
            raise ValueError("--vocal-output must end in .wav.")
        if vocal_output == audio_path:
            raise ValueError("--vocal-output cannot overwrite the source audio file.")
        if vocal_output.exists() and not overwrite:
            raise FileExistsError(f"Vocal output already exists: {vocal_output}\nUse --overwrite to replace it.")

    temp_root = Path(tempfile.mkdtemp(prefix="lyrics-aligner-vocals-"))
    try:
        try:
            import soundfile as sf
            from demucs_infer.api import Separator
        except ImportError as exc:
            raise RuntimeError(
                "Vocal-separation dependencies are incomplete. Run install-vocal-separation.bat again."
            ) from exc

        print(
            f"Separating vocals with Demucs model '{demucs_model}' on {device} "
            f"(segment {demucs_segment:g}s)..."
        )
        try:
            separator = Separator(
                model=demucs_model,
                device=device,
                shifts=1,
                overlap=0.25,
                split=True,
                segment=int(demucs_segment),
                progress=True,
            )
            _mixture, stems = separator.separate_audio_file(audio_path)
        except Exception as exc:
            message = f"Vocal separation failed: {type(exc).__name__}: {exc}"
            if device == "cuda":
                message += "\nIf the GPU ran out of memory, try --demucs-segment 4 or --device cpu."
            raise RuntimeError(message) from exc

        vocals = stems.get("vocals")
        if vocals is None:
            raise RuntimeError(
                f"The selected separation model '{demucs_model}' did not return a 'vocals' stem. "
                "Choose a standard 4-stem Demucs model such as htdemucs."
            )

        # Save via SoundFile so the optional feature doesn't depend on torchaudio.save's
        # backend/codec behavior. The temporary stem is discarded after WhisperX loads it.
        vocal_path = temp_root / "vocals.wav"
        try:
            import numpy as np
            vocal_array = vocals.detach().cpu().numpy()
            if vocal_array.ndim != 2:
                raise ValueError(f"Unexpected vocal tensor shape: {vocal_array.shape}")
            sf.write(str(vocal_path), np.ascontiguousarray(vocal_array.T), int(separator.samplerate), subtype="PCM_16")
        except Exception as exc:
            raise RuntimeError(f"Could not save the separated vocal stem: {type(exc).__name__}: {exc}") from exc

        if vocal_output is not None:
            vocal_output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(vocal_path, vocal_output)
            print(f"Saved separated vocals: {vocal_output}")

        print("Loading separated vocal audio for alignment...")
        return whisperx_module.load_audio(str(vocal_path))
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def line_review_report(
    lines: list[str],
    units_by_line: list[list[str]],
    mapped_by_line: list[list[dict[str, Any] | None]],
    global_offset: float,
    line_offsets: dict[int, float],
    warnings: list[str],
    refined_changes: list[str],
) -> str:
    report = [
        "Lyrics Audio Aligner - alignment review",
        "Review hints are heuristic; singing can make short or overlapping word spans legitimate.",
        "",
    ]
    for line_number, (text, units, entries) in enumerate(zip(lines, units_by_line, mapped_by_line), start=1):
        starts = [value for entry in entries if (value := _entry_start(entry)) is not None]
        ends = [value for entry in entries if (value := _entry_end(entry)) is not None]
        matched = sum(1 for entry in entries if _entry_start(entry) is not None)
        if starts:
            shift = global_offset + line_offsets.get(line_number, 0.0)
            start = max(0.0, min(starts) + shift)
            end = max(start, (max(ends) if ends else min(starts)) + shift)
            report.append(
                f"{line_number:03d}  {start:8.2f}-{end:8.2f}s  "
                f"matched {matched}/{len(units)} units  {text}"
            )
        else:
            report.append(f"{line_number:03d}  NO TIMESTAMP  matched 0/{len(units)} units  {text}")
    if refined_changes:
        report.extend(["", "Refinement / model-comparison diagnostics:", *refined_changes])
    if warnings:
        report.extend(["", "Warnings:", *warnings])
    return "\n".join(report) + "\n"


def align(args: argparse.Namespace) -> int:
    audio_path = args.audio.expanduser().resolve()
    lyrics_path = args.lyrics.expanduser().resolve()
    output_path = args.output.expanduser().resolve() if args.output else audio_path.with_suffix(".lrc")
    project_root = Path(__file__).resolve().parent
    tifa_root = args.tifa_root.expanduser().resolve() if args.tifa_root else project_root / "vendor" / "TIFA"
    tifa_python = args.tifa_python.expanduser().resolve() if args.tifa_python else project_root / ".tifa-venv" / "Scripts" / "python.exe"
    tifa_diagnostics_path = (
        args.tifa_diagnostics.expanduser().resolve() if args.tifa_diagnostics else
        (audio_path.with_suffix(".tifa-diagnosis.json") if args.aligner == "tifa" else None)
    )

    if not math.isfinite(args.offset) or abs(args.offset) > 30:
        raise ValueError("Global timing offset must be finite and between -30 and 30 seconds.")
    if not math.isfinite(args.instrumental_threshold) or args.instrumental_threshold <= 0 or args.instrumental_threshold > 120:
        raise ValueError("Instrumental cue threshold must be greater than 0 and at most 120 seconds.")
    if not math.isfinite(args.demucs_segment) or args.demucs_segment < 2 or args.demucs_segment > 7:
        raise ValueError("Demucs segment must be an integer from 2 to 7 seconds for the default HTDemucs model.")
    if not math.isfinite(args.refine_window) or args.refine_window < 0.1 or args.refine_window > 5:
        raise ValueError("Refinement window must be between 0.1 and 5 seconds.")
    if not math.isfinite(args.tifa_chunk_seconds) or args.tifa_chunk_seconds < 20 or args.tifa_chunk_seconds > 55:
        raise ValueError("TIFA chunk duration must be between 20 and 55 seconds.")
    if not math.isfinite(args.tifa_context) or args.tifa_context < 0.5 or args.tifa_context > 5:
        raise ValueError("TIFA context padding must be between 0.5 and 5 seconds.")
    if args.tifa_diagnostics is not None and args.aligner != "tifa":
        raise ValueError("--tifa-diagnostics can only be used with --aligner tifa.")
    if args.vocal_output is not None and not args.separate_vocals:
        raise ValueError("--vocal-output can only be used with --separate-vocals.")
    if not audio_path.is_file():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")
    if not lyrics_path.is_file():
        raise FileNotFoundError(f"Lyrics file not found: {lyrics_path}")
    external_singer_config = load_singer_config(args.singer_config) if args.singer_config else None
    singer_config = load_inline_singer_config(lyrics_path, external_singer_config)
    if singer_config is None:
        singer_config = external_singer_config
    # TTML carries word/character timing and optional named-agent layers. Enable it
    # explicitly for word-level karaoke, even when no singer config is supplied.
    ttml_path = args.ttml_output.expanduser().resolve() if args.ttml_output else (
        audio_path.with_suffix(".ttml") if (singer_config or args.word_level) else None
    )
    if ttml_path is not None and ttml_path.suffix.lower() != ".ttml":
        raise ValueError("--ttml-output must use the .ttml extension.")
    protected_inputs = [audio_path, lyrics_path]
    for optional_input in (args.singer_config, args.line_offsets, args.phrase_offsets):
        if optional_input is not None:
            resolved_input = optional_input.expanduser().resolve()
            if resolved_input not in protected_inputs:
                protected_inputs.append(resolved_input)
    if tifa_diagnostics_path is not None:
        if tifa_diagnostics_path in protected_inputs or tifa_diagnostics_path == output_path or tifa_diagnostics_path == ttml_path:
            raise ValueError("TIFA diagnostics output must not overwrite an input, LRC, or TTML output.")
        if tifa_diagnostics_path.exists() and not args.overwrite:
            raise FileExistsError(f"TIFA diagnostics output already exists: {tifa_diagnostics_path}\nUse --overwrite to replace it.")
    if ttml_path is not None and (ttml_path in protected_inputs or ttml_path == output_path):
        raise ValueError("TTML output must not overwrite the audio, source lyrics, singer config, or LRC output.")
    if output_path in protected_inputs:
        raise ValueError("LRC output must not overwrite the audio, source lyrics, or singer config.")
    if ttml_path is not None and ttml_path.exists() and not args.overwrite:
        raise FileExistsError(f"TTML output already exists: {ttml_path}\nUse --overwrite to replace it.")
    if audio_path == output_path:
        raise ValueError("Output path cannot overwrite the audio file.")
    if output_path == lyrics_path and not args.overwrite:
        raise FileExistsError(
            "The output path is the same as the supplied lyrics file. Choose --output with a different name, "
            "or pass --overwrite to replace the source lyrics."
        )
    if output_path.exists() and not args.overwrite:
        raise FileExistsError(f"Output already exists: {output_path}\nUse --overwrite to replace it.")
    lines, speaker_ids, unit_speakers_by_line = read_lyrics_with_speaker_units(
        lyrics_path, singer_config, args.language
    )
    units_by_line, transcript = lyric_units_by_line(lines, args.language)
    source_units = [unit for group in units_by_line for unit in group]
    if not source_units:
        raise ValueError("Lyrics contain no alignable text units.")
    line_offsets = load_line_offsets(args.line_offsets, len(lines))
    phrase_offsets = load_phrase_offsets(args.phrase_offsets, lines)
    for line_number, correction in phrase_offsets.items():
        line_offsets[line_number] = line_offsets.get(line_number, 0.0) + correction
    if args.review_report is not None:
        review_path = args.review_report.expanduser().resolve()
        if review_path in protected_inputs:
            raise ValueError("Review report cannot overwrite the audio, lyrics, or singer config input.")
        if review_path == output_path or (ttml_path is not None and review_path == ttml_path) or (tifa_diagnostics_path is not None and review_path == tifa_diagnostics_path):
            raise ValueError("Review report must not use the same path as an output file.")
        if review_path.exists() and not args.overwrite:
            raise FileExistsError(f"Review report already exists: {review_path}\nUse --overwrite to replace it.")
    else:
        review_path = None

    if args.dry_run:
        print("Dry run: no audio model was loaded and no files were written.")
        print(f"Audio:      {audio_path}")
        print(f"Lyrics:     {lyrics_path}")
        print(f"Output LRC: {output_path}")
        if ttml_path is not None:
            print(f"Output Navidrome TTML: {ttml_path}")
            print("Word/character-level timing: enabled")
            print(f"Configured singers: {len(singer_config['singers']) if singer_config else 0}")
            print(f"Lines with multiple singer assignments: {sum(1 for row in unit_speakers_by_line if len(set(row)) > 1)}")
        print(f"Language:   {args.language}")
        print(f"Aligner:    {args.aligner}")
        if args.aligner == "tifa":
            print(f"TIFA root:  {tifa_root}")
            print(f"TIFA Python:{tifa_python}")
            print(f"TIFA model: {args.tifa_model.expanduser().resolve() if args.tifa_model else project_root / 'models' / 'TIFA-1.0-ST'}")
            print(f"TIFA chunk target: {args.tifa_chunk_seconds:g}s; context padding: {args.tifa_context:g}s")
            print(f"TIFA diagnostics: {tifa_diagnostics_path}")
        print(f"Lines:      {len(lines)}")
        print(f"Text units: {len(source_units)}")
        print(f"Global timing offset: {args.offset:+.2f}s")
        print(f"Per-line corrections (including phrase matches): {len(line_offsets)}")
        print(f"Phrase-specific corrections matched: {len(phrase_offsets)}")
        if args.phrase_offsets:
            print(f"Phrase-offset file: {args.phrase_offsets.expanduser().resolve()}")
        print(f"Separate vocals: {'yes' if args.separate_vocals else 'no'}")
        if args.aligner == "tifa":
            print(f"Short-word context repair: {'enabled' if args.context_repair else 'disabled'}")
            print("Second-pass refinement: not applicable; TIFA is the independent final alignment pass")
        else:
            print(f"Second-pass refinement: {'yes' if args.refine else 'no'}")
        print(f"Instrumental cues: {'yes' if args.instrumental_cues else 'no'}")
        if review_path:
            print(f"Review report: {review_path}")
        return 0

    if not shutil.which("ffmpeg"):
        raise RuntimeError("FFmpeg was not found on PATH. Install FFmpeg or add its bin directory to PATH, then open a new CMD window.")

    try:
        import torch
        import whisperx
    except ImportError as exc:
        raise RuntimeError(
            "The alignment dependencies are missing. Run install.bat from the project folder, "
            "then launch the CLI with lyrics-aligner.bat."
        ) from exc

    device = select_device(args.device, torch)
    print(f"Loading local forced-alignment model for language '{args.language}' on {device}...")
    if args.align_model:
        align_model, metadata = whisperx.load_align_model(
            language_code=args.language, device=device, model_name=args.align_model
        )
    else:
        align_model, metadata = whisperx.load_align_model(language_code=args.language, device=device)

    aligned_audio = load_alignment_audio(
        audio_path, whisperx,
        separate_vocals=args.separate_vocals,
        demucs_model=args.demucs_model,
        device=device,
        demucs_segment=args.demucs_segment,
        vocal_output=args.vocal_output,
        overwrite=args.overwrite,
    )
    duration = len(aligned_audio) / 16000.0
    if duration <= 0:
        raise ValueError("The audio file appears to be empty or could not be decoded.")

    print(f"Aligning {len(lines)} lyric lines against {duration:.1f} seconds of {'vocal stem' if args.separate_vocals else 'audio'}...")
    segment = {"start": 0.0, "end": duration, "text": transcript}
    result = whisperx.align(
        [segment], align_model, metadata, aligned_audio, device,
        return_char_alignments=False,
    )
    aligned_words = aligner_word_list(result)
    if not aligned_words:
        raise RuntimeError(
            "The model returned no word timings. Check the language code and that the supplied lyrics match the recording."
        )

    coarse_mapped_by_line = mapped_words_by_line(units_by_line, aligned_words)
    mapped_by_line = coarse_mapped_by_line
    refined_changes: list[str] = []
    tifa_diagnostics_payload: dict[str, Any] | None = None
    if args.aligner == "tifa":
        print("Switching from WhisperX coarse timing to TIFA's singing-trained forced aligner...")
        # TIFA runs in its own Python environment. Release the coarse aligner and CUDA
        # cache first so both models do not compete for GTX 1650 VRAM.
        del align_model
        del metadata
        gc.collect()
        try:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
        mapped_by_line, tifa_notes, tifa_diagnostics_payload = run_tifa_alignment(
            aligned_audio, duration, lines, units_by_line, coarse_mapped_by_line,
            language=args.language, tifa_root=tifa_root, tifa_python=tifa_python,
            tifa_model=args.tifa_model, max_chunk_seconds=args.tifa_chunk_seconds,
            context_seconds=args.tifa_context, device=device,
        )
        refined_changes.extend(tifa_notes)
        context_repair_notes: list[str] = []
        if args.context_repair:
            mapped_by_line, context_repair_notes = repair_weak_word_timings(
                units_by_line, mapped_by_line, coarse_mapped_by_line
            )
            refined_changes.extend(context_repair_notes)
            if tifa_diagnostics_payload is not None:
                tifa_diagnostics_payload["context_repairs"] = context_repair_notes
                tifa_diagnostics_payload["context_repair_enabled"] = True
        elif tifa_diagnostics_payload is not None:
            tifa_diagnostics_payload["context_repair_enabled"] = False
            tifa_diagnostics_payload["context_repairs"] = []
        print(f"Short-word context repair: {len(context_repair_notes)} automatic correction(s).")
        refined_changes.extend(compare_line_timing_models(lines, coarse_mapped_by_line, mapped_by_line))
        changed_count = sum(1 for note in refined_changes if note.startswith("Model disagreement"))
        print(f"TIFA complete. {changed_count} lyric line(s) materially differ from the WhisperX coarse pass and should be reviewed.")
        for change in refined_changes:
            print(f"  {change}")
        if tifa_diagnostics_path is not None:
            tifa_diagnostics_path.parent.mkdir(parents=True, exist_ok=True)
            tifa_diagnostics_path.write_text(
                json.dumps(tifa_diagnostics_payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8", newline="\n",
            )
            print(f"Wrote TIFA diagnostic report: {tifa_diagnostics_path}")
    elif args.refine:
        print(f"Running second-pass line refinement (±{args.refine_window:g}s local windows)...")
        mapped_by_line, refined_changes = refine_line_alignments(
            lines, units_by_line, mapped_by_line, aligned_audio, duration,
            align_model, metadata, device, whisperx, args.refine_window,
        )
        changed_count = sum(1 for change in refined_changes if " -> " in change)
        print(f"Refinement complete. Lines with timestamp changes of at least 0.03s: {changed_count}.")
        for change in refined_changes:
            print(f"  {change}")

    output_lines, warnings = create_lrc_lines(
        lines, units_by_line, aligned_words, args.offset, line_offsets=line_offsets,
        mapped_by_line=mapped_by_line,
        duration=duration,
        instrumental_cues=args.instrumental_cues,
        instrumental_threshold=args.instrumental_threshold,
    )
    if not output_lines:
        raise RuntimeError(
            "No lyric lines received usable timestamps. The selected language/model may not match the lyrics, "
            "or the song may be too difficult to align from the full mix."
        )

    ttml_text = None
    if ttml_path is not None:
        ttml_text = create_navidrome_ttml(
            lines, units_by_line, mapped_by_line, speaker_ids, singer_config,
            language=args.language, offset_seconds=args.offset, line_offsets=line_offsets,
            duration=duration, instrumental_cues=args.instrumental_cues,
            instrumental_threshold=args.instrumental_threshold,
            unit_speakers_by_line=unit_speakers_by_line,
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(output_lines) + "\n", encoding="utf-8", newline="\n")
    print(f"Wrote: {output_path}")
    if ttml_path is not None and ttml_text is not None:
        ttml_path.parent.mkdir(parents=True, exist_ok=True)
        ttml_path.write_text(ttml_text, encoding="utf-8", newline="\n")
        print(f"Wrote Navidrome TTML sidecar: {ttml_path}")
    timestamped_lyrics = sum(1 for line in output_lines if not line.endswith("♪"))
    instrumental_count = sum(1 for line in output_lines if line.endswith("♪"))
    print(f"Timestamped output lines: {timestamped_lyrics} lyric line(s); {instrumental_count} instrumental cue(s).")
    if ttml_path is not None:
        print("Navidrome TTML includes per-word timing (per-character units for languages configured without spaces).")
    if args.offset or line_offsets:
        print(f"Applied global offset: {args.offset:+.2f}s; per-line corrections: {len(line_offsets)}")
    if args.separate_vocals:
        print("Alignment source: isolated vocal stem; original audio was not modified.")
    if args.refine and args.aligner == "whisperx" and not refined_changes:
        print("Second-pass refinement completed; no notable start-time changes (>=0.03s) were reported.")
    elif args.refine and args.aligner == "tifa":
        print("Note: --refine was not run; TIFA already performs an independent singing-trained alignment pass. The WhisperX pass was used only for coarse chunk planning/comparison.")
    for warning in warnings:
        print(f"REVIEW: {warning}", file=sys.stderr)
    if review_path is not None:
        report_text = line_review_report(
            lines, units_by_line, mapped_by_line, args.offset, line_offsets, warnings, refined_changes
        )
        review_path.parent.mkdir(parents=True, exist_ok=True)
        review_path.write_text(report_text, encoding="utf-8", newline="\n")
        print(f"Wrote alignment review report: {review_path}")
    print("Review the LRC in a player before using it in your library; this tool flags suspicious timing but cannot guarantee singing-perfect alignment.")
    return 0 if timestamped_lyrics == len(lines) else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lyrics-aligner",
        description="Locally align supplied lyrics and generate standard LRC plus optional Navidrome word-timed TTML sidecar.",
        epilog=(
            r'Example: lyrics-aligner.bat --audio "D:\Music\song.flac" '
            r'--lyrics "D:\Lyrics\song.txt" --language en --device auto'
        ),
    )
    parser.add_argument("--audio", type=Path, help="Audio file (e.g. FLAC, MP3, WAV, M4A).")
    parser.add_argument("--adjust-lrc", type=Path, help="Shift timestamps in an existing LRC without rerunning the model; output defaults to a separate .adjusted.lrc file.")
    parser.add_argument("--lyrics", type=Path, help="Plain text or LRC file containing the correct lyrics.")
    parser.add_argument("--output", type=Path, help="Output .lrc path (default: audio file with .lrc extension).")
    parser.add_argument("--singer-config", type=Path, help="JSON mapping standalone singer headers to named TTML agents/styles/colors. When supplied, writes a .ttml sidecar next to the audio by default.")
    parser.add_argument("--word-level", action="store_true", help="Write a Navidrome-compatible .ttml sidecar with word-level timing, even without a singer config. Standard .lrc is also written as a compatibility fallback.")
    parser.add_argument("--ttml-output", type=Path, help="Optional Navidrome-compatible .ttml sidecar path; also enables word-timed TTML output without singer headers.")
    parser.add_argument("--language", default="en", help="Alignment language code (default: en).")
    parser.add_argument("--aligner", choices=("whisperx", "tifa"), default="whisperx", help="Alignment backend. TIFA is trained for singing and uses WhisperX only for rough chunk anchors (default: whisperx).")
    parser.add_argument("--tifa-root", type=Path, help="TIFA source checkout directory (default: vendor\\TIFA inside this project).")
    parser.add_argument("--tifa-python", type=Path, help="Python executable for the isolated TIFA environment (default: .tifa-venv\\Scripts\\python.exe).")
    parser.add_argument("--tifa-model", type=Path, help="TIFA model checkpoint or folder containing model.pt, config.yaml, and vocabulary.json (default: models\\TIFA-1.0-ST).")
    parser.add_argument("--tifa-chunk-seconds", type=float, default=42.0, help="Target duration per TIFA chunk; TIFA's documented maximum context is about one minute (default: 42).")
    parser.add_argument("--tifa-context", type=float, default=1.8, help="Seconds of audio context around the first/last lyric in each TIFA chunk (default: 1.8).")
    parser.add_argument("--tifa-diagnostics", type=Path, help="TIFA JSON diagnostics path (default when using TIFA: audio.tifa-diagnosis.json).")
    parser.add_argument("--no-context-repair", dest="context_repair", action="store_false", default=True, help="Disable automatic TIFA short-function-word recovery using WhisperX and neighboring word timestamps (enabled by default with --aligner tifa).")
    parser.add_argument("--align-model", help="Optional custom WhisperX/Hugging Face wav2vec2 alignment model (WhisperX backend only).")
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto", help="Inference device (default: auto).")
    parser.add_argument("--offset", type=float, default=0.0, help="Global timing correction in seconds; negative values move every line earlier (try -0.10 to -0.25 for a consistently late result).")
    parser.add_argument("--line-offsets", type=Path, help="Optional JSON object with per-line timing corrections, e.g. {\"3\": -0.15}; line numbers are 1-based after blank/metadata lines are removed.")
    parser.add_argument("--phrase-offsets", type=Path, help="Optional JSON object mapping exact cleaned lyric-line text to additional timing corrections in seconds; exact repeated lines all receive the correction.")
    parser.add_argument("--separate-vocals", action="store_true", help="Use optional local Demucs source separation and align against the isolated vocal stem.")
    parser.add_argument("--demucs-model", default="htdemucs", help="Demucs model used with --separate-vocals (default: htdemucs).")
    parser.add_argument("--demucs-segment", type=int, default=6, help="Demucs segment length in seconds; shorter segments reduce GPU memory use (default: 6).")
    parser.add_argument("--vocal-output", type=Path, help="Optional .wav path to keep the separated vocal stem instead of discarding its temporary copy.")
    parser.add_argument("--refine", action="store_true", help="WhisperX backend only: re-align each line in a narrow window; ignored with --aligner tifa.")
    parser.add_argument("--refine-window", type=float, default=0.80, help="Seconds on either side of first-pass line bounds for --refine (default: 0.80).")
    parser.add_argument("--instrumental-cues", action="store_true", help="Insert timestamped ♪ cues at long intros, inter-lyric gaps, and outros.")
    parser.add_argument("--instrumental-threshold", type=float, default=6.0, help="Minimum gap length in seconds for a ♪ cue (default: 6).")
    parser.add_argument("--review-report", type=Path, help="Optional path for a line-by-line timing review report.")
    parser.add_argument("--overwrite", action="store_true", help="Allow replacing an existing output file.")
    parser.add_argument("--dry-run", action="store_true", help="Validate paths/lyrics and show planned output without loading a model.")
    parser.add_argument("--doctor", action="store_true", help="Check the local Python, WhisperX, PyTorch, CUDA, and FFmpeg setup.")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.doctor:
        return run_doctor()
    try:
        if args.adjust_lrc is not None:
            if args.audio is not None or args.lyrics is not None or args.singer_config is not None or args.ttml_output is not None or args.word_level or args.aligner != "whisperx" or args.tifa_diagnostics is not None:
                parser.error("--adjust-lrc cannot be combined with alignment-only options such as --audio, --lyrics, --aligner, --singer-config, --word-level, or --ttml-output")
            return adjust_existing_lrc(args)
        if args.audio is None or args.lyrics is None:
            parser.error("--audio and --lyrics are required unless --doctor or --adjust-lrc is used")
        return align(args)
    except (FileNotFoundError, FileExistsError, ValueError, RuntimeError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # Surface model/runtime failures without a long opaque traceback by default.
        print(f"ERROR: alignment failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        print("Run lyrics-aligner.bat --doctor and consult README.md for troubleshooting.", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())

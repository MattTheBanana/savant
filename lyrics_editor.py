#!/usr/bin/env python3
"""Savant local editor and GUI launcher for the local lyrics alignment CLI."""
from __future__ import annotations

import argparse
import email.policy
import importlib.util
import shutil
import json
import mimetypes
import os
import platform
import re
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parent
HTML_PATH = ROOT / "webui" / "index.html"
ALIGN_SCRIPT = ROOT / "lyrics_align.py"
RUNS_ROOT = Path.home() / ".savant" / "runs"
MAX_REQUEST_BYTES = 1024 * 1024 * 1024
RUNS: dict[str, dict] = {}
RUNS_LOCK = threading.RLock()
PROGRESS_PREFIX = "@@SAVANT_PROGRESS@@"


def _safe_name(filename: str, fallback: str) -> str:
    name = Path(str(filename or "").replace("\\", "/")).name
    name = re.sub(r"[^A-Za-z0-9._() '\-\u0080-\uffff]", "_", name).strip(" .")
    if not name or name in {".", ".."}:
        name = fallback
    return name[:180]


def _run_snapshot(run: dict) -> dict:
    with RUNS_LOCK:
        snapshot = {
            "id": run["id"],
            "status": run["status"],
            "operation": run.get("operation", "align"),
            "created": run["created"],
            "started": run.get("started"),
            "finished": run.get("finished"),
            "returnCode": run.get("return_code"),
            "step": run.get("step", "Queued"),
            "overallProgress": int(run.get("overall_progress", 0)),
            "stepProgress": int(run.get("step_progress", 0)),
            "error": run.get("error"),
            "logs": run.get("logs", ""),
            "runDirectory": str(run["directory"]),
            "sourceAudioName": run.get("source_audio_name", ""),
            "artifacts": [],
        }
        for key, meta in run.get("artifacts", {}).items():
            path = Path(meta["path"])
            available = path.is_file()
            snapshot["artifacts"].append({
                "key": key,
                "label": meta.get("label", key),
                "name": meta.get("name") or path.name,
                "path": str(path),
                "kind": meta.get("kind", "file"),
                "available": available,
                "size": path.stat().st_size if available else 0,
            })
        return snapshot


def _append_log(run: dict, line: str) -> None:
    with RUNS_LOCK:
        run["logs"] = (run.get("logs", "") + line + "\n")[-2_000_000:]
        log_path = run.get("log_path")
        if log_path:
            try:
                with open(log_path, "a", encoding="utf-8", newline="\n") as stream:
                    stream.write(line + "\n")
            except OSError:
                pass


def _set_progress(run: dict, overall: int, step: str, step_percent: int = 0) -> None:
    with RUNS_LOCK:
        run["overall_progress"] = max(0, min(100, int(overall)))
        run["step"] = str(step)[:180]
        run["step_progress"] = max(0, min(100, int(step_percent)))
        run["step_started"] = time.time()


def _parse_multipart(handler: BaseHTTPRequestHandler) -> tuple[dict[str, str], dict[str, tuple[str, bytes]]]:
    content_type = handler.headers.get("Content-Type", "")
    if "multipart/form-data" not in content_type.lower():
        raise ValueError("Expected a multipart form upload.")
    length = int(handler.headers.get("Content-Length", "0"))
    if length <= 0:
        raise ValueError("The generate form was empty.")
    if length > MAX_REQUEST_BYTES:
        raise ValueError("The selected files exceed the 1 GiB per-request upload limit.")
    body = handler.rfile.read(length)
    if len(body) != length:
        raise ValueError("The upload ended before all file data was received.")
    message_bytes = (
        ("Content-Type: " + content_type + "\r\nMIME-Version: 1.0\r\n\r\n").encode("utf-8")
        + body
    )
    message = BytesParser(policy=email.policy.default).parsebytes(message_bytes)
    fields: dict[str, str] = {}
    files: dict[str, tuple[str, bytes]] = {}
    if not message.is_multipart():
        raise ValueError("Could not parse the multipart form.")
    for part in message.iter_parts():
        disposition = part.get_content_disposition()
        name = part.get_param("name", header="content-disposition")
        if disposition != "form-data" or not name:
            continue
        payload = part.get_payload(decode=True) or b""
        filename = part.get_filename()
        if filename:
            if payload:
                files[str(name)] = (str(filename), payload)
        else:
            charset = part.get_content_charset() or "utf-8"
            fields[str(name)] = payload.decode(charset, errors="replace")
    return fields, files


def _save_upload(directory: Path, field: str, upload: tuple[str, bytes]) -> Path:
    original_name, payload = upload
    safe = _safe_name(original_name, f"{field}.dat")
    path = directory / f"{field}_{safe}"
    path.write_bytes(payload)
    return path


def _add_flag(command: list[str], flag: str, value: object) -> None:
    if value is not None and str(value).strip():
        command.extend([flag, str(value).strip()])


def _add_switch(command: list[str], flag: str, config: dict, key: str) -> None:
    if bool(config.get(key, False)):
        command.append(flag)


def _nearest_existing_directory(path: Path) -> Path | None:
    """Return the closest existing directory ancestor, even if path itself is missing."""
    candidate = path
    try:
        if candidate.exists() and not candidate.is_dir():
            candidate = candidate.parent
    except OSError:
        candidate = candidate.parent
    while True:
        try:
            if candidate.exists():
                if candidate.is_dir():
                    return candidate
                candidate = candidate.parent
                continue
        except OSError:
            pass
        if candidate.parent == candidate:
            return None
        candidate = candidate.parent


def _path_can_write(directory: Path) -> bool:
    try:
        # Windows does not expose POSIX directory execute permissions in the same way.
        required = os.W_OK | (os.X_OK if os.name != "nt" else 0)
        return directory.is_dir() and os.access(directory, required)
    except OSError:
        return False


def _validate_path_request(path_text: str, kind: str, role: str = "") -> dict:
    """Validate a user-selected generator path and describe safe create options."""
    raw = str(path_text or "").strip()
    if not raw:
        return {"status": "invalid", "message": "Enter a path first."}
    if kind not in {"folder", "open", "save", "any"}:
        return {"status": "invalid", "message": "Unsupported path type."}
    try:
        path = Path(raw).expanduser().resolve(strict=False)
        exists = path.exists()
    except (OSError, RuntimeError, ValueError) as exc:
        return {"status": "inaccessible", "message": f"Could not resolve this path: {exc}"}

    if kind == "folder":
        if exists:
            if not path.is_dir():
                return {"status": "invalid", "message": f"This path is a file, not a folder: {path}"}
            required = os.R_OK | (os.X_OK if os.name != "nt" else 0)
            if "output" in role:
                required |= os.W_OK
            if not os.access(path, required):
                return {"status": "inaccessible", "message": f"The folder is not accessible with the required permissions: {path}"}
            return {"status": "ok", "path": str(path), "exists": True, "isDir": True}
        ancestor = _nearest_existing_directory(path.parent)
        if ancestor is None:
            return {"status": "inaccessible", "message": f"No accessible parent folder was found for: {path}"}
        if not _path_can_write(ancestor):
            return {"status": "inaccessible", "message": f"Cannot create this folder because the parent is not writable: {ancestor}"}
        return {
            "status": "missing-folder", "path": str(path), "createPath": str(path),
            "createable": True, "message": f"The folder does not exist: {path}",
        }

    if kind == "open":
        if not exists:
            return {"status": "missing", "path": str(path), "message": f"This file does not exist: {path}"}
        if not path.is_file():
            return {"status": "invalid", "message": f"Choose an existing file: {path}"}
        if not os.access(path, os.R_OK):
            return {"status": "inaccessible", "message": f"The file is not readable: {path}"}
        return {"status": "ok", "path": str(path), "exists": True, "isDir": False}

    if kind == "any":
        if not exists:
            return {"status": "missing", "path": str(path), "message": f"This file or folder does not exist: {path}"}
        if not (path.is_file() or path.is_dir()):
            return {"status": "invalid", "message": f"This path is not a regular file or folder: {path}"}
        required = os.R_OK | (os.X_OK if path.is_dir() and os.name != "nt" else 0)
        if not os.access(path, required):
            return {"status": "inaccessible", "message": f"The file or folder is not readable: {path}"}
        return {"status": "ok", "path": str(path), "exists": True, "isDir": path.is_dir()}

    # "save" means a future output file. Do not create an empty file here; the
    # CLI creates the file when it actually generates the output.
    if exists:
        if path.is_dir():
            return {"status": "invalid", "message": f"An output file path points to a folder: {path}"}
        if not os.access(path, os.W_OK):
            return {"status": "inaccessible", "message": f"The existing output file is not writable: {path}"}
        if not _path_can_write(path.parent):
            return {"status": "inaccessible", "message": f"The parent folder is not writable: {path.parent}"}
        return {"status": "ok", "path": str(path), "exists": True, "isDir": False}

    if path.parent.exists():
        if not path.parent.is_dir():
            return {"status": "invalid", "message": f"The parent path is not a folder: {path.parent}"}
        if not _path_can_write(path.parent):
            return {"status": "inaccessible", "message": f"The parent folder is not writable: {path.parent}"}
        return {"status": "missing-file", "path": str(path), "exists": False, "createable": False}
    ancestor = _nearest_existing_directory(path.parent)
    if ancestor is None:
        return {"status": "inaccessible", "message": f"No accessible parent folder was found for: {path}"}
    if not _path_can_write(ancestor):
        return {"status": "inaccessible", "message": f"Cannot create output folders because this parent is not writable: {ancestor}"}
    return {
        "status": "missing-parent", "path": str(path), "createPath": str(path.parent),
        "createable": True, "message": f"The output folder does not exist: {path.parent}",
    }


def _local_path_suggestions(raw_text: str, kind: str, limit: int = 18) -> dict:
    """List local filesystem entries that extend a partially typed path."""
    if kind not in {"folder", "open", "save", "any"}:
        return {"suggestions": [], "message": "Unsupported path type.", "error": True}
    raw = str(raw_text or "").strip()
    try:
        if not raw:
            parent, prefix = Path.home(), ""
        else:
            candidate = Path(raw).expanduser()
            ends_with_separator = raw.endswith(("/", "\\"))
            if ends_with_separator or candidate.is_dir():
                parent, prefix = candidate, ""
            else:
                parent = candidate.parent if candidate.parent != Path(".") or candidate.is_absolute() else Path.cwd()
                prefix = candidate.name
            if not parent.is_absolute():
                parent = Path.cwd() / parent
        parent = parent.resolve(strict=False)
        if not parent.exists():
            return {"suggestions": [], "message": f"Folder not found: {parent}", "error": False}
        if not parent.is_dir():
            return {"suggestions": [], "message": f"Not a folder: {parent}", "error": True}
        entries = []
        for entry in sorted(parent.iterdir(), key=lambda item: (not item.is_dir(), item.name.casefold())):
            try:
                is_dir = entry.is_dir()
                if prefix and not entry.name.casefold().startswith(prefix.casefold()):
                    continue
                if kind == "folder" and not is_dir:
                    continue
                if kind == "open" and (is_dir or not entry.is_file()):
                    continue
                entries.append({
                    "path": str(entry), "name": entry.name, "isDir": is_dir,
                    "exists": True, "readable": os.access(entry, os.R_OK),
                    "writable": os.access(entry, os.W_OK),
                })
                if len(entries) >= max(1, min(40, limit)):
                    break
            except OSError:
                continue
        if raw:
            typed = Path(raw).expanduser()
            try:
                typed_path = typed.resolve(strict=False)
                if not typed_path.exists() and not any(item["path"] == str(typed_path) for item in entries):
                    entries.append({
                        "path": str(typed_path), "name": typed_path.name or str(typed_path),
                        "isDir": kind == "folder" or (kind == "any" and not typed_path.suffix),
                        "exists": False, "readable": False, "writable": False, "candidate": True,
                    })
            except (OSError, RuntimeError, ValueError):
                pass
        return {"suggestions": entries[:max(1, min(40, limit + 1))], "baseDirectory": str(parent)}
    except PermissionError as exc:
        return {"suggestions": [], "message": f"Folder is inaccessible: {exc}", "error": True}
    except (OSError, RuntimeError, ValueError) as exc:
        return {"suggestions": [], "message": f"Could not list path suggestions: {exc}", "error": True}


def _require_writable_output_parent(path: Path, label: str) -> None:
    """Fail early with a clear message when a chosen output location cannot be written."""
    parent = path.parent
    if not parent.exists():
        raise ValueError(
            f"{label} folder does not exist: {parent}. Use the path suggestions to create it, "
            "or choose another output folder."
        )
    if not parent.is_dir():
        raise ValueError(f"{label} parent path is not a folder: {parent}")
    if not _path_can_write(parent):
        raise PermissionError(f"{label} folder is not writable or accessible: {parent}")
    if path.exists() and path.is_file() and not os.access(path, os.W_OK):
        raise PermissionError(f"The existing {label.lower()} file is not writable: {path}")


def _build_command(run: dict, config: dict, files: dict[str, tuple[str, bytes]]) -> list[str]:
    directory: Path = run["directory"]
    saved = {name: _save_upload(directory / "inputs", name, item) for name, item in files.items()}
    run["saved_inputs"] = saved
    audio_path_text = str(config.get("audioSourcePath", "")).strip()
    lyrics_path_text = str(config.get("lyricsSourcePath", "")).strip()
    audio_source = Path(audio_path_text).expanduser().resolve() if audio_path_text else saved.get("audio")
    lyrics_source = Path(lyrics_path_text).expanduser().resolve() if lyrics_path_text else saved.get("lyrics")
    for source, label in ((audio_source, "audio"), (lyrics_source, "lyrics")):
        if source is not None and not source.is_file():
            raise ValueError(f"The selected {label} file does not exist or is not a readable file: {source}")
    if audio_source is not None:
        original_audio_name = (
            Path(files["audio"][0].replace("\\", "/")).name
            if "audio" in files and not audio_path_text
            else audio_source.name
        )
        run["source_audio_name"] = original_audio_name
        run.setdefault("artifacts", {})["input-audio"] = {
            "label": "Source audio", "path": str(audio_source), "kind": "input",
            "name": original_audio_name,
        }
    operation = str(config.get("mode", "align"))
    run["operation"] = operation

    if operation == "doctor":
        return [sys.executable, str(ALIGN_SCRIPT), "--doctor"]

    command = [sys.executable, str(ALIGN_SCRIPT)]
    if operation == "adjust":
        if lyrics_source is None:
            raise ValueError("Choose an existing .lrc file to adjust.")
        command.extend(["--adjust-lrc", str(lyrics_source)])
    else:
        if audio_source is None or lyrics_source is None:
            raise ValueError("Choose both an audio file and a lyrics file.")
        command.extend(["--audio", str(audio_source), "--lyrics", str(lyrics_source)])

    output_path_text = str(config.get("outputPath", "")).strip()
    if output_path_text:
        output_path = Path(output_path_text).expanduser().resolve()
    else:
        # The output name and default destination follow the source lyrics, not the audio.
        source = lyrics_source if lyrics_source is not None else audio_source
        fallback_stem = source.stem if source else "lyrics"
        raw_output_name = str(config.get("outputName", "")).strip()
        if raw_output_name:
            # Only accept a filename, not path separators supplied in the UI.
            output_name = Path(raw_output_name.replace("\\", "/")).name
            output_stem = re.sub(r"\.(?:lrc|ttml|txt|xml)$", "", output_name, flags=re.IGNORECASE).strip(" .")
            output_stem = _safe_name(output_stem, fallback_stem)
        else:
            output_stem = fallback_stem + (".adjusted" if operation == "adjust" else "")
        output_directory_text = str(config.get("outputDirectory", "")).strip()
        output_directory_mode = str(config.get("outputDirectoryMode", "auto")).strip().lower()
        if output_directory_text:
            output_directory = Path(output_directory_text).expanduser().resolve()
            if not output_directory.is_dir():
                raise ValueError(f"The selected output folder does not exist or is not a directory: {output_directory}")
            if not _path_can_write(output_directory):
                raise PermissionError(f"The selected output folder is not writable or accessible: {output_directory}")
        elif output_directory_mode == "run":
            output_directory = directory
        elif lyrics_source is not None and (lyrics_path_text or "lyrics" not in saved):
            output_directory = lyrics_source.parent
        else:
            raise ValueError(
                "Choose an output folder, or select the source lyrics with Savant's local Choose Lyrics picker "
                "so the original lyrics folder can be detected. Browser uploads do not reveal their original folder."
            )
        output_path = output_directory / f"{output_stem}.lrc"
    _require_writable_output_parent(output_path, "LRC output")
    _add_flag(command, "--output", output_path)
    run["artifacts"]["output-lrc"] = {"label": "Output LRC", "path": str(output_path), "kind": "output"}

    if operation != "adjust":
        _add_flag(command, "--language", config.get("language") or "en")
        _add_flag(command, "--aligner", config.get("aligner") or "whisperx")
        _add_flag(command, "--device", config.get("device") or "auto")
        _add_flag(command, "--align-model", config.get("alignModel"))
        _add_flag(command, "--tifa-root", config.get("tifaRoot"))
        _add_flag(command, "--tifa-python", config.get("tifaPython"))
        _add_flag(command, "--tifa-model", config.get("tifaModel"))
        _add_flag(command, "--tifa-chunk-seconds", config.get("tifaChunkSeconds") or "42")
        _add_flag(command, "--tifa-context", config.get("tifaContext") or "1.8")
        _add_flag(command, "--demucs-model", config.get("demucsModel") or "htdemucs")
        _add_flag(command, "--demucs-segment", config.get("demucsSegment") or "6")
        _add_flag(command, "--refine-window", config.get("refineWindow") or "0.80")
        _add_flag(command, "--instrumental-threshold", config.get("instrumentalThreshold") or "6.0")
        _add_flag(command, "--offset", config.get("offset") or "0")
        _add_switch(command, "--word-level", config, "wordLevel")
        _add_switch(command, "--separate-vocals", config, "separateVocals")
        _add_switch(command, "--refine", config, "refine")
        _add_switch(command, "--instrumental-cues", config, "instrumentalCues")
        if config.get("contextRepair", True) is False:
            command.append("--no-context-repair")

        ttml_path_text = str(config.get("ttmlOutputPath", "")).strip()
        if ttml_path_text:
            ttml_path = Path(ttml_path_text).expanduser().resolve()
            _add_flag(command, "--ttml-output", ttml_path)
        elif bool(config.get("wordLevel")) or "singerConfig" in saved:
            ttml_path = output_path.with_suffix(".ttml")
            _add_flag(command, "--ttml-output", ttml_path)
        else:
            ttml_path = None
        if ttml_path is not None:
            _require_writable_output_parent(ttml_path, "TTML output")
            run["artifacts"]["output-ttml"] = {"label": "Output TTML", "path": str(ttml_path), "kind": "output"}

        if "singerConfig" in saved:
            _add_flag(command, "--singer-config", saved["singerConfig"])
        if "vocalOutput" in config and str(config.get("vocalOutput", "")).strip():
            if not bool(config.get("separateVocals")):
                raise ValueError("Enable vocal separation before choosing a retained vocal stem path.")
            vocal_output_path = Path(str(config["vocalOutput"])).expanduser().resolve()
            _require_writable_output_parent(vocal_output_path, "Vocal output")
            _add_flag(command, "--vocal-output", vocal_output_path)
            run["artifacts"]["vocal-output"] = {"label": "Separated vocal stem", "path": str(vocal_output_path), "kind": "output"}

        tifa_diagnostics = str(config.get("tifaDiagnosticsPath", "")).strip()
        if tifa_diagnostics:
            diagnosis_path = Path(tifa_diagnostics).expanduser().resolve()
            _require_writable_output_parent(diagnosis_path, "TIFA diagnostics output")
            _add_flag(command, "--tifa-diagnostics", diagnosis_path)
            run["artifacts"]["tifa-diagnosis"] = {"label": "TIFA diagnosis (raw JSON)", "path": str(diagnosis_path), "kind": "diagnosis"}
        elif str(config.get("aligner", "whisperx")) == "tifa":
            # Keep generated diagnostics with the selected lyric output, not beside the source audio.
            default_diagnosis = output_path.with_suffix(".tifa-diagnosis.json")
            run["artifacts"]["tifa-diagnosis"] = {"label": "TIFA diagnosis (raw JSON)", "path": str(default_diagnosis), "kind": "diagnosis"}

        if bool(config.get("reviewReport")) or str(config.get("reviewReportPath", "")).strip():
            report_text = str(config.get("reviewReportPath", "")).strip()
            report = Path(report_text).expanduser().resolve() if report_text else output_path.parent / "alignment-review.txt"
            _require_writable_output_parent(report, "Review report")
            _add_flag(command, "--review-report", report)
            run["artifacts"]["review-report"] = {"label": "Alignment review report", "path": str(report), "kind": "report"}
        for field_name, arg_name in (("lineOffsets", "--line-offsets"), ("phraseOffsets", "--phrase-offsets")):
            if field_name in saved:
                _add_flag(command, arg_name, saved[field_name])

    if operation == "adjust":
        _add_flag(command, "--offset", config.get("offset") or "0")
        for field_name, arg_name in (("lineOffsets", "--line-offsets"), ("phraseOffsets", "--phrase-offsets")):
            if field_name in saved:
                _add_flag(command, arg_name, saved[field_name])

    _add_switch(command, "--overwrite", config, "overwrite")
    _add_switch(command, "--dry-run", config, "dryRun")
    return command


def _capability_snapshot() -> dict:
    """Describe runtime dependencies and safe, allowlisted installer actions."""
    windows = os.name == "nt"
    tifa_root = ROOT / "vendor" / "TIFA"
    tifa_python = ROOT / ".tifa-venv" / "Scripts" / "python.exe"
    tifa_model = ROOT / "models" / "TIFA-1.0-ST"
    tifa_model_ready = any(
        candidate.suffix.lower() == ".pt"
        and (candidate.parent / "config.yaml").is_file()
        and (candidate.parent / "vocabulary.json").is_file()
        for candidate in tifa_model.rglob("*.pt")
    ) if tifa_model.is_dir() else False
    tifa_ready = (tifa_root / "infer.py").is_file() and tifa_python.is_file() and tifa_model_ready
    installers = {
        "base": {"label": "Install base dependencies", "available": True,
                 "method": "script" if (ROOT / "install.bat").is_file() else "pip",
                 "description": "Install WhisperX in this editor's Python environment."},
        "vocal": {"label": "Install vocal separation", "available": True,
                  "method": "script" if (ROOT / "install-vocal-separation.bat").is_file() else "pip",
                  "description": "Install demucs-infer for optional local vocal isolation."},
        "tifa": {"label": "Install TIFA", "available": (ROOT / "install-tifa.bat").is_file() if windows else False,
                 "method": "script" if (ROOT / "install-tifa.bat").is_file() else "manual",
                 "description": "TIFA needs a separate source checkout, isolated environment, and model checkpoint."},
        "ffmpeg": {"label": "Install FFmpeg", "available": windows and shutil.which("winget") is not None,
                   "method": "winget" if windows and shutil.which("winget") is not None else "manual",
                   "description": "FFmpeg must be installed system-wide and available on PATH."},
    }
    return {
        "platform": platform.system(), "python": sys.executable, "ffmpeg": shutil.which("ffmpeg"),
        "whisperx": importlib.util.find_spec("whisperx") is not None,
        "torch": importlib.util.find_spec("torch") is not None,
        "vocalSeparation": importlib.util.find_spec("demucs_infer") is not None,
        "tifa": tifa_ready, "installers": installers, "projectRoot": str(ROOT),
    }


def _installation_command(kind: str) -> tuple[list[str], str]:
    options = _capability_snapshot()["installers"]
    if kind not in options:
        raise ValueError("Unknown installation option.")
    option = options[kind]
    if kind == "ffmpeg":
        if option["method"] == "winget":
            return (["winget", "install", "--id", "Gyan.FFmpeg.Shared", "--exact",
                     "--accept-source-agreements", "--accept-package-agreements"], "Install FFmpeg")
        raise RuntimeError("FFmpeg cannot be installed automatically here. Follow the FFmpeg instructions in README.md, then restart Savant.")
    if kind == "tifa":
        script = ROOT / "install-tifa.bat"
        if option["method"] == "script" and script.is_file() and os.name == "nt":
            return ([os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", str(script)], "Install TIFA")
        raise RuntimeError("install-tifa.bat is not present in this project folder. TIFA requires a separate source checkout, environment, and model checkpoint; follow its setup instructions in README.md or add the project's installer script.")
    if kind == "base":
        script = ROOT / "install.bat"
        if script.is_file() and os.name == "nt":
            return ([os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", str(script)], "Install base dependencies")
        return ([sys.executable, "-m", "pip", "install", "whisperx"], "Install WhisperX")
    if kind == "vocal":
        script = ROOT / "install-vocal-separation.bat"
        if script.is_file() and os.name == "nt":
            return ([os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", str(script)], "Install vocal separation")
        return ([sys.executable, "-m", "pip", "install", "demucs-infer"], "Install vocal separation")
    raise ValueError("Unknown installation option.")


def _open_path(path: Path, mode: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"File or folder does not exist: {path}")
    system = platform.system()
    if mode == "file":
        if path.is_dir():
            raise ValueError("The selected artifact is a folder, not a file.")
        if system == "Windows":
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif system == "Darwin":
            subprocess.Popen(["open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    folder = path if path.is_dir() else path.parent
    if system == "Windows":
        if not path.is_dir():
            subprocess.Popen(["explorer", "/select,", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            os.startfile(str(folder))  # type: ignore[attr-defined]
    elif system == "Darwin":
        subprocess.Popen(["open", "-R", str(path)] if not path.is_dir() else ["open", str(folder)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        subprocess.Popen(["xdg-open", str(folder)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _friendly_cli_failure(return_code: int, output: str) -> str:
    """Turn the CLI's own error message into a concise, named status for the UI."""
    detail = ""
    is_argparse_error = False
    for raw_line in reversed(str(output or "").splitlines()):
        line = raw_line.strip()
        if line.upper().startswith("ERROR:"):
            detail = line.split(":", 1)[1].strip()
            break
        # argparse usage failures print "script.py: error: ..." rather than "ERROR:".
        match = re.search(r"\berror:\s*(.+)$", line, flags=re.IGNORECASE)
        if match:
            detail = match.group(1).strip()
            is_argparse_error = True
            break

    exception_type = ""
    if detail.casefold().startswith("alignment failed:"):
        detail = detail[len("alignment failed:"):].strip()
        match = re.match(r"([A-Za-z][A-Za-z0-9_]*Error):\s*(.*)", detail)
        if match:
            exception_type, detail = match.group(1), match.group(2).strip()
    else:
        match = re.match(r"([A-Za-z][A-Za-z0-9_]*Error):\s*(.*)", detail)
        if match:
            exception_type, detail = match.group(1), match.group(2).strip()

    if not detail:
        detail = "The CLI stopped without reporting a specific cause."

    message = detail.casefold()
    missing = any(term in message for term in (
        "not found", "does not exist", "was not found", "missing", "no such file",
        "could not locate", "could not find",
    ))
    if "already exists" in message or "use --overwrite" in message:
        name = "Output Already Exists"
    elif exception_type in {"ImportError", "ModuleNotFoundError"}:
        name = "Python Dependency Missing"
    elif "ffmpeg" in message and missing:
        name = "FFmpeg Not Found"
    elif "tifa" in message and missing:
        name = "TIFA Setup Missing"
    elif "whisperx" in message and missing:
        name = "WhisperX Dependency Missing"
    elif "model" in message and missing:
        name = "Alignment Model Missing"
    elif any(term in message for term in ("permission denied", "not writable", "access is denied", "permissionerror")):
        name = "File Permission Error"
    elif "cuda" in message or "pytorch" in message or "gpu" in message:
        name = "GPU or Device Error"
    elif "invalid json" in message or "json in " in message or "json file" in message:
        name = "Invalid JSON Input"
    elif ("line-offset" in message or "phrase-offset" in message or "singer config" in message) and any(
        term in message for term in ("invalid", "must", "cannot", "does not", "unknown", "duplicate")
    ):
        name = "Invalid Configuration File"
    elif any(term in message for term in (
        "no lyric lines", "no timestamped lyric", "lyrics contain no alignable",
        "no alignable text", "expects an existing .lrc", "timestamped lyric rows",
    )):
        name = "Invalid Lyrics Input"
    elif "audio" in message and any(term in message for term in ("decode", "empty", "ffmpeg", "audio file")):
        name = "Audio Processing Error"
    elif any(term in message for term in ("tifa", "intervaltier", "textgrid")):
        name = "TIFA Alignment Error"
    elif any(term in message for term in ("whisperx", "alignment model", "model loading", "failed to load model")):
        name = "Alignment Model Error"
    elif any(term in message for term in ("must be", "must not", "cannot be combined", "cannot overwrite", "requires ", "expects ")):
        name = "Invalid Input or Settings"
    elif missing or exception_type == "FileNotFoundError":
        name = "File or Dependency Not Found"
    elif exception_type == "PermissionError":
        name = "File Permission Error"
    elif exception_type == "FileExistsError":
        name = "Output Already Exists"
    elif exception_type == "ValueError":
        name = "Invalid Input or Settings"
    elif is_argparse_error:
        name = "Invalid CLI Arguments"
    elif exception_type:
        name = f"Alignment Runtime Error ({exception_type})"
    elif return_code == 2:
        name = "CLI Validation Error"
    else:
        name = "Alignment Runtime Error"

    return f"{name}: {detail}"


def _run_worker(run_id: str, command: list[str], env: dict[str, str]) -> None:
    with RUNS_LOCK:
        run = RUNS[run_id]
        run["status"] = "running"
        run["started"] = time.time()
    _set_progress(run, 2, "Installing dependencies" if str(run.get("operation", "")).startswith("install-") else "Starting local CLI")
    _append_log(run, "$ " + subprocess.list2cmdline(command))
    try:
        process = subprocess.Popen(
            command,
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        with RUNS_LOCK:
            run["process"] = process
        assert process.stdout is not None
        for raw_line in process.stdout:
            line = raw_line.rstrip("\r\n")
            if line.startswith(PROGRESS_PREFIX):
                try:
                    report = json.loads(line[len(PROGRESS_PREFIX):])
                    _set_progress(run, report.get("overall", 0), report.get("step", "Working"),
                                  report.get("step_percent", 0))
                except (ValueError, TypeError):
                    _append_log(run, line)
                continue
            _append_log(run, line)
        return_code = process.wait()
        with RUNS_LOCK:
            run["return_code"] = return_code
            run["finished"] = time.time()
            run["status"] = "success" if return_code == 0 else ("warning" if return_code == 1 else "failed")
            run["error"] = None if return_code in (0, 1) else _friendly_cli_failure(return_code, run.get("logs", ""))
        if return_code in (0, 1):
            _set_progress(run, 100, "Finished" if return_code == 0 else "Finished with warnings", 100)
        else:
            _set_progress(run, int(run.get("overall_progress", 0)), "Failed", 100)
    except Exception as exc:
        with RUNS_LOCK:
            run["status"] = "failed"
            run["finished"] = time.time()
            run["error"] = f"{type(exc).__name__}: {exc}"
        _append_log(run, f"ERROR: {type(exc).__name__}: {exc}")
    finally:
        process_obj = run.get("process")
        if process_obj and process_obj.poll() is None:
            process_obj.terminate()


class Handler(BaseHTTPRequestHandler):
    def _send_bytes(self, payload: bytes, content_type: str, status: int = 200, filename: str | None = None, send_body: bool = True) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self' 'unsafe-inline' blob: data:; media-src blob: data:; connect-src 'self'; img-src 'self' data: blob:")
        if filename:
            safe = re.sub(r"[^A-Za-z0-9._ '-]", "_", filename)
            self.send_header("Content-Disposition", f'attachment; filename="{safe}"')
        self.end_headers()
        if send_body:
            self.wfile.write(payload)

    def _send_json(self, value: dict, status: int = 200) -> None:
        self._send_bytes(json.dumps(value, ensure_ascii=False).encode("utf-8"),
                         "application/json; charset=utf-8", status)

    def _send_file(self, path: Path) -> None:
        stat = path.stat()
        safe_name = re.sub(r'[^A-Za-z0-9._() -]', "_", path.name)
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(stat.st_size))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self' 'unsafe-inline' blob: data:; media-src blob: data:; connect-src 'self'; img-src 'self' data: blob:")
        self.send_header("Content-Disposition", f'inline; filename="{safe_name}"')
        self.end_headers()
        with path.open("rb") as stream:
            shutil.copyfileobj(stream, self.wfile, length=1024 * 1024)

    def _api_mutation_allowed(self) -> bool:
        # Require the UI's custom header; cross-origin HTML forms cannot set it.
        return self.headers.get("X-Savant-UI") == "1"

    def do_GET(self) -> None:  # noqa: N802
        route = urlparse(self.path)
        if route.path in ("/", "/index.html"):
            try:
                payload = HTML_PATH.read_bytes()
            except OSError as exc:
                self.send_error(500, f"Cannot read editor UI: {exc}")
                return
            self._send_bytes(payload, "text/html; charset=utf-8")
            return
        if route.path == "/api/health":
            self._send_json({"ok": True, "localOnly": True})
            return
        if route.path == "/api/capabilities":
            self._send_json(_capability_snapshot())
            return
        match = re.fullmatch(r"/api/runs/([A-Za-z0-9_-]+)", route.path)
        if match:
            with RUNS_LOCK:
                run = RUNS.get(match.group(1))
            if not run:
                self._send_json({"error": "Run not found."}, 404)
                return
            self._send_json(_run_snapshot(run))
            return
        match = re.fullmatch(r"/api/runs/([A-Za-z0-9_-]+)/artifacts/([A-Za-z0-9_-]+)", route.path)
        if match:
            run_id, artifact_key = match.groups()
            with RUNS_LOCK:
                run = RUNS.get(run_id)
                meta = run.get("artifacts", {}).get(artifact_key) if run else None
            if not meta:
                self._send_json({"error": "Unknown artifact."}, 404)
                return
            path = Path(meta["path"])
            if not path.is_file():
                self._send_json({"error": "This artifact is not ready yet."}, 404)
                return
            try:
                self._send_file(path)
            except OSError as exc:
                self._send_json({"error": f"Could not read artifact: {exc}"}, 500)
            return
        match = re.fullmatch(r"/api/runs/([A-Za-z0-9_-]+)/diagnosis", route.path)
        if match:
            with RUNS_LOCK:
                run = RUNS.get(match.group(1))
                meta = run.get("artifacts", {}).get("tifa-diagnosis") if run else None
            if not meta:
                self._send_json({"error": "This run has no TIFA diagnosis artifact."}, 404)
                return
            path = Path(meta["path"])
            try:
                payload = path.read_bytes()
                if len(payload) > 20 * 1024 * 1024:
                    raise ValueError("The diagnosis file exceeds the 20 MiB in-browser viewing limit.")
                json.loads(payload.decode("utf-8-sig"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                self._send_json({"error": f"Could not read diagnosis JSON: {exc}"}, 400)
                return
            self._send_bytes(payload, "application/json; charset=utf-8")
            return
        match = re.fullmatch(r"/api/runs/([A-Za-z0-9_-]+)/artifacts/([A-Za-z0-9_-]+)", route.path)
        if match:
            with RUNS_LOCK:
                run = RUNS.get(match.group(1))
                meta = run.get("artifacts", {}).get(match.group(2)) if run else None
            if not meta:
                self._send_json({"error": "Artifact not found."}, 404)
                return
            path = Path(meta["path"])
            try:
                data = path.read_bytes()
            except OSError as exc:
                self._send_json({"error": f"Could not read artifact: {exc}"}, 404)
                return
            self._send_bytes(data, mimetypes.guess_type(path.name)[0] or "application/octet-stream", filename=path.name)
            return
        self.send_error(404, "Not found")

    def do_HEAD(self) -> None:  # noqa: N802
        route = urlparse(self.path)
        if route.path not in ("/", "/index.html"):
            self.send_error(404, "Not found")
            return
        try:
            payload = HTML_PATH.read_bytes()
        except OSError as exc:
            self.send_error(500, f"Cannot read editor UI: {exc}")
            return
        self._send_bytes(payload, "text/html; charset=utf-8", send_body=False)

    def do_POST(self) -> None:  # noqa: N802
        route = urlparse(self.path)
        if not self._api_mutation_allowed():
            self._send_json({"error": "This local API only accepts requests from the Savant UI."}, 403)
            return
        if route.path == "/api/select-source":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length > 100_000:
                    raise ValueError("Invalid source selection request.")
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                kind = str(payload.get("kind", ""))
                if kind not in {"audio", "lyrics"}:
                    raise ValueError("Choose either an audio or lyrics source file.")
                try:
                    import tkinter as tk
                    from tkinter import filedialog

                    root = tk.Tk()
                    root.withdraw()
                    try:
                        root.attributes("-topmost", True)
                    except tk.TclError:
                        pass
                    filetypes = (
                        [("Audio files", "*.flac *.wav *.mp3 *.m4a *.ogg *.opus *.aiff *.aif *.wma"), ("All files", "*.*")]
                        if kind == "audio"
                        else [("Lyric files", "*.txt *.lrc *.ttml *.xml"), ("All files", "*.*")]
                    )
                    try:
                        selected = filedialog.askopenfilename(
                            parent=root,
                            title="Choose the source audio file" if kind == "audio" else "Choose the source lyrics file",
                            initialdir=str(Path.home()),
                            filetypes=filetypes,
                        )
                    finally:
                        root.destroy()
                except Exception as exc:
                    raise RuntimeError(f"The system file picker is unavailable: {exc}") from exc
                if not selected:
                    self._send_json({"cancelled": True})
                else:
                    source = Path(selected).expanduser().resolve()
                    if not source.is_file():
                        raise ValueError("The selected source is not a file.")
                    self._send_json({
                        "cancelled": False,
                        "path": str(source),
                        "name": source.name,
                        "size": source.stat().st_size,
                        "type": mimetypes.guess_type(source.name)[0] or "application/octet-stream",
                    })
            except (ValueError, OSError, json.JSONDecodeError, RuntimeError) as exc:
                self._send_json({"error": str(exc)}, 400)
            return
        if route.path == "/api/select-folder":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length > 100_000:
                    raise ValueError("Invalid folder selection request.")
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                kind = str(payload.get("kind", ""))
                if kind not in {"audio", "lyrics"}:
                    raise ValueError("Choose either the audio or lyrics folder.")
                filename = str(payload.get("audioName" if kind == "audio" else "lyricsName", "")).strip()
                title = f"Choose the folder containing {filename}" if filename else f"Choose the output folder (source: {kind})"
                try:
                    import tkinter as tk
                    from tkinter import filedialog
                    root = tk.Tk()
                    root.withdraw()
                    try:
                        root.attributes("-topmost", True)
                    except tk.TclError:
                        pass
                    try:
                        selected = filedialog.askdirectory(
                            parent=root, title=title, initialdir=str(Path.home()), mustexist=True
                        )
                    finally:
                        root.destroy()
                except Exception as exc:
                    raise RuntimeError(f"The system folder picker is unavailable: {exc}") from exc
                if not selected:
                    self._send_json({"cancelled": True})
                else:
                    self._send_json({"cancelled": False, "path": str(Path(selected).expanduser().resolve())})
            except (ValueError, OSError, json.JSONDecodeError, RuntimeError) as exc:
                self._send_json({"error": str(exc)}, 400)
            return
        if route.path == "/api/path-suggestions":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length > 100_000:
                    raise ValueError("Invalid path suggestion request.")
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                result = _local_path_suggestions(
                    str(payload.get("path", "")),
                    str(payload.get("kind", "any")),
                    int(payload.get("limit", 18)),
                )
                self._send_json(result)
            except (ValueError, OSError, json.JSONDecodeError) as exc:
                self._send_json({"error": str(exc)}, 400)
            return
        if route.path == "/api/validate-path":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length > 100_000:
                    raise ValueError("Invalid path validation request.")
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                self._send_json(_validate_path_request(
                    str(payload.get("path", "")),
                    str(payload.get("kind", "any")),
                    str(payload.get("role", "")),
                ))
            except (ValueError, OSError, json.JSONDecodeError) as exc:
                self._send_json({"status": "invalid", "message": str(exc)}, 400)
            return
        if route.path == "/api/create-path":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length > 100_000:
                    raise ValueError("Invalid directory creation request.")
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                raw_path = str(payload.get("path", "")).strip()
                if not raw_path:
                    raise ValueError("Choose a folder path first.")
                directory = Path(raw_path).expanduser().resolve(strict=False)
                if directory.exists():
                    if not directory.is_dir():
                        raise ValueError(f"The requested folder path is a file: {directory}")
                    if not _path_can_write(directory):
                        raise PermissionError(f"The folder is not writable: {directory}")
                else:
                    ancestor = _nearest_existing_directory(directory.parent)
                    if ancestor is None or not _path_can_write(ancestor):
                        raise PermissionError(f"The parent is not accessible or writable: {directory.parent}")
                    directory.mkdir(parents=True, exist_ok=True)
                    if not directory.is_dir() or not _path_can_write(directory):
                        raise PermissionError(f"The created folder is not writable: {directory}")
                self._send_json({"ok": True, "path": str(directory)})
            except (ValueError, OSError, json.JSONDecodeError, RuntimeError) as exc:
                self._send_json({"error": str(exc)}, 400)
            return
        if route.path == "/api/browse-path":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length > 100_000:
                    raise ValueError("Invalid path picker request.")
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                kind = str(payload.get("kind", "open"))
                if kind not in {"folder", "open", "save", "any"}:
                    raise ValueError("Choose a folder, existing file, or output file.")
                title = str(payload.get("title", "Choose a local path")).strip()[:200] or "Choose a local path"
                current_text = str(payload.get("currentPath", "")).strip()
                current_path = Path(current_text).expanduser() if current_text else None
                initial_dir = Path.home()
                initial_file = ""
                if current_path:
                    if current_path.is_dir():
                        initial_dir = current_path
                    elif current_path.parent.is_dir():
                        initial_dir = current_path.parent
                        initial_file = current_path.name
                try:
                    import tkinter as tk
                    from tkinter import filedialog

                    root = tk.Tk()
                    root.withdraw()
                    try:
                        root.attributes("-topmost", True)
                    except tk.TclError:
                        pass
                    try:
                        if kind == "folder":
                            selected = filedialog.askdirectory(
                                parent=root, title=title, initialdir=str(initial_dir), mustexist=True
                            )
                        elif kind == "save":
                            selected = filedialog.asksaveasfilename(
                                parent=root, title=title, initialdir=str(initial_dir),
                                initialfile=initial_file, filetypes=[("All files", "*.*")]
                            )
                        else:
                            selected = filedialog.askopenfilename(
                                parent=root, title=title, initialdir=str(initial_dir),
                                initialfile=initial_file, filetypes=[("All files", "*.*")]
                            )
                    finally:
                        root.destroy()
                except Exception as exc:
                    raise RuntimeError(f"The system path picker is unavailable: {exc}") from exc
                if not selected:
                    self._send_json({"cancelled": True})
                else:
                    selected_path = Path(selected).expanduser().resolve()
                    if kind == "folder" and not selected_path.is_dir():
                        raise ValueError("The selected output folder does not exist.")
                    if kind == "open" and not selected_path.is_file():
                        raise ValueError("The selected path is not a file.")
                    self._send_json({"cancelled": False, "path": str(selected_path)})
            except (ValueError, OSError, json.JSONDecodeError, RuntimeError) as exc:
                self._send_json({"error": str(exc)}, 400)
            return
        if route.path == "/api/generate":
            try:
                fields, files = _parse_multipart(self)
                config = json.loads(fields.get("config", "{}"))
                if not isinstance(config, dict):
                    raise ValueError("The generate configuration must be a JSON object.")
                RUNS_ROOT.mkdir(parents=True, exist_ok=True)
                run_id = uuid.uuid4().hex[:16]
                run_dir = RUNS_ROOT / run_id
                (run_dir / "inputs").mkdir(parents=True, exist_ok=False)
                run = {
                    "id": run_id,
                    "status": "queued",
                    "operation": str(config.get("mode", "align")),
                    "created": time.time(),
                    "started": None,
                    "finished": None,
                    "return_code": None,
                    "step": "Queued",
                    "overall_progress": 0,
                    "step_progress": 0,
                    "logs": "",
                    "directory": run_dir,
                    "log_path": run_dir / "savant-generate.log",
                    "artifacts": {
                        "log": {"label": "Generation log", "path": str(run_dir / "savant-generate.log"), "kind": "log"}
                    },
                }
                run["log_path"].write_text("", encoding="utf-8")
                command = _build_command(run, config, files)
                operation = str(config.get("mode", "align"))
                if operation in {"align", "adjust"} and not bool(config.get("dryRun")):
                    existing_outputs = sorted({
                        str(Path(str(artifact.get("path", ""))).expanduser().resolve())
                        for artifact in run.get("artifacts", {}).values()
                        if artifact.get("kind") in {"output", "diagnosis", "report"}
                        and str(artifact.get("path", "")).strip()
                        and Path(str(artifact.get("path", ""))).expanduser().exists()
                    })
                    if existing_outputs and not bool(config.get("overwritePromptConfirmed")):
                        # No subprocess has been started. Discard this attempt's uploaded inputs
                        # so the UI can ask first and submit a clean, approved request if needed.
                        shutil.rmtree(run_dir, ignore_errors=True)
                        self._send_json({
                            "error": "Existing output files require overwrite confirmation.",
                            "overwriteRequired": True,
                            "existingOutputs": existing_outputs,
                        }, 409)
                        return
                with RUNS_LOCK:
                    RUNS[run_id] = run
                _set_progress(run, 1, "Queued")
                env = os.environ.copy()
                env["PYTHONUNBUFFERED"] = "1"
                env["SAVANT_GUI_PROGRESS"] = "1"
                thread = threading.Thread(target=_run_worker, args=(run_id, command, env), daemon=True)
                thread.start()
                self._send_json({"runId": run_id})
            except (ValueError, OSError, json.JSONDecodeError) as exc:
                self._send_json({"error": str(exc)}, 400)
            return
        if route.path == "/api/install":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length > 100_000:
                    raise ValueError("Invalid request size.")
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                kind = str(payload.get("kind", ""))
                command, label = _installation_command(kind)
                RUNS_ROOT.mkdir(parents=True, exist_ok=True)
                run_id = uuid.uuid4().hex[:16]
                run_dir = RUNS_ROOT / run_id
                (run_dir / "inputs").mkdir(parents=True, exist_ok=False)
                run = {
                    "id": run_id, "status": "queued", "operation": "install-" + kind,
                    "created": time.time(), "started": None, "finished": None,
                    "return_code": None, "step": label, "overall_progress": 0,
                    "step_progress": 0, "logs": "", "directory": run_dir,
                    "log_path": run_dir / "savant-install.log",
                    "artifacts": {"log": {"label": label + " log", "path": str(run_dir / "savant-install.log"), "kind": "log"}},
                }
                run["log_path"].write_text("", encoding="utf-8")
                with RUNS_LOCK:
                    RUNS[run_id] = run
                _set_progress(run, 1, label)
                env = os.environ.copy()
                env["PYTHONUNBUFFERED"] = "1"
                env["SAVANT_GUI_PROGRESS"] = "1"
                thread = threading.Thread(target=_run_worker, args=(run_id, command, env), daemon=True)
                thread.start()
                self._send_json({"runId": run_id, "label": label})
            except (ValueError, OSError, json.JSONDecodeError, RuntimeError) as exc:
                self._send_json({"error": str(exc)}, 400)
            return
        if route.path == "/api/open-artifact":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length > 100_000:
                    raise ValueError("Invalid request size.")
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                run_id = str(payload.get("runId", ""))
                key = str(payload.get("artifactKey", ""))
                mode = str(payload.get("mode", "file"))
                if mode not in {"file", "folder"}:
                    raise ValueError("Unknown open mode.")
                with RUNS_LOCK:
                    run = RUNS.get(run_id)
                    meta = run.get("artifacts", {}).get(key) if run else None
                if not meta:
                    raise ValueError("Unknown artifact.")
                _open_path(Path(meta["path"]), mode)
                self._send_json({"ok": True})
            except (ValueError, OSError, json.JSONDecodeError) as exc:
                self._send_json({"error": str(exc)}, 400)
            return
        self.send_error(404, "Not found")

    def log_message(self, _format: str, *_args: object) -> None:
        return


def main() -> int:
    parser = argparse.ArgumentParser(description="Open the local Savant editor and CLI generator in your browser.")
    parser.add_argument("--port", type=int, default=8765, help="Local port to use (default: 8765).")
    parser.add_argument("--no-browser", action="store_true", help="Print the URL without opening a browser.")
    args = parser.parse_args()
    if not HTML_PATH.is_file():
        parser.error(f"Editor UI is missing: {HTML_PATH}")
    if not ALIGN_SCRIPT.is_file():
        parser.error(f"CLI script is missing: {ALIGN_SCRIPT}")
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError as exc:
        parser.error(f"Could not listen on 127.0.0.1:{args.port}: {exc}. Try --port 8766.")
    url = f"http://127.0.0.1:{args.port}/"
    print("Savant Editor")
    print(f"Open: {url}")
    print("Local-only: input files are sent to this machine's local server. Use Ctrl+C to stop the editor.")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        print("\nEditor stopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

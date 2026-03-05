#!/usr/bin/env python3
import argparse
import curses
import fcntl
import json
import os
import readline
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

__version__ = "0.1.0"

APP = "blog"
REPO = "ryangerardwilson/blog"
LATEST_RELEASE_API = f"https://api.github.com/repos/{REPO}/releases/latest"
INSTALL_SCRIPT_URL = f"https://raw.githubusercontent.com/{REPO}/main/install.sh"

LOCK_FILE = Path("/tmp/blog_recorder_cli.lock")
XDG_CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
XDG_CACHE_HOME = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache")))
XDG_STATE_HOME = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local" / "state")))
CONFIG_DIR = XDG_CONFIG_HOME / APP
CONFIG_FILE = CONFIG_DIR / "config.json"
STATE_DIR = XDG_STATE_HOME / APP
STATE_FILE = STATE_DIR / "recorder_state.json"
DEFAULT_OUTPUT_DIR = XDG_CACHE_HOME / APP / "recordings"
WEB_FPS = "24"
WEB_MAX_WIDTH = "1280"
WEB_CRF = "28"
WEB_PRESET = "veryfast"
WEB_AUDIO_BITRATE = "128k"
WEBCAM_WIDTH = "360"


def default_config() -> dict:
    return {
        "publish": {
            "x": "x",
            "linkedin": "linkedin",
        }
    }


def print_usage_guide() -> None:
    print(
        "Usage:\n"
        "  blog \"post text\"              Publish text to all configured platforms\n"
        "  blog -e                       Compose text in $EDITOR and publish\n"
        "  blog -m /path/to/media.mp4    Publish media only (or with text/-e)\n"
        "  blog -rec                     Start recording\n"
        "  blog -rec --debug-sync        Start recording with sync diagnostics\n"
        "  blog -stp                     Stop recording, trim, and publish\n"
        "  blog -rectest                 Stop recording, trim, and save ./output.mp4\n"
        "  blog -v                       Print version\n"
        "  blog -u                       Upgrade to latest version\n"
        "  blog -h                       Show this help\n"
        "\n"
        "Options:\n"
        f"  -o <path>                     Recording directory (default: {DEFAULT_OUTPUT_DIR})\n"
        "  -m <path>                     Media to publish with post\n"
        "  -e                            Compose post in $EDITOR\n"
        "  -rec                          Start recording\n"
        "  --debug-sync                  Write ffmpeg/ffprobe sync diagnostics on stop\n"
        "  -stp                          Stop recording and run trim+publish flow\n"
        "  -rectest                      Stop recording and save output.mp4 in current directory\n"
        "  -a                            Webcam preview helper\n"
        "  -pl                           Play latest recording\n"
        "  -c                            Clear saved recordings\n"
        f"\nConfig:\n"
        f"  {CONFIG_FILE} (auto-created)\n"
        "  publish.x / publish.linkedin control publish commands\n"
    )


def _fetch_latest_version() -> str:
    request = urllib.request.Request(
        LATEST_RELEASE_API,
        headers={"Accept": "application/vnd.github+json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Failed to fetch latest release: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Failed to parse latest release payload: {exc}") from exc

    tag = str(payload.get("tag_name", "")).strip()
    if not tag:
        raise RuntimeError("Latest release does not contain a valid tag_name.")
    return tag[1:] if tag.startswith("v") else tag


def upgrade_to_latest() -> int:
    try:
        latest = _fetch_latest_version()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if latest == __version__:
        print(f"{APP} is already up to date (v{__version__}).")
        return 0

    curl = shutil.which("curl")
    bash = shutil.which("bash")
    if not curl:
        print("curl not found in PATH.", file=sys.stderr)
        return 1
    if not bash:
        print("bash not found in PATH.", file=sys.stderr)
        return 1

    print(f"Upgrading {APP} from v{__version__} to v{latest}...")
    with tempfile.NamedTemporaryFile(suffix=".sh", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        fetch = subprocess.run([curl, "-fsSL", INSTALL_SCRIPT_URL, "-o", str(tmp_path)])
        if fetch.returncode != 0:
            print("Failed to download installer script.", file=sys.stderr)
            return fetch.returncode
        run = subprocess.run([bash, str(tmp_path), "--version", latest])
        return run.returncode
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass


def pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def load_state() -> dict | None:
    if not STATE_FILE.exists():
        return None
    try:
        return json.loads(STATE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def clear_state() -> None:
    try:
        STATE_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def save_state(state: dict) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state))
    except OSError:
        pass


def load_or_init_config() -> dict:
    defaults = default_config()
    if not CONFIG_FILE.exists():
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            CONFIG_FILE.write_text(json.dumps(defaults, indent=2) + "\n", encoding="utf-8")
        except OSError:
            return defaults
        return defaults
    try:
        parsed = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return defaults
    if not isinstance(parsed, dict):
        return defaults
    publish = parsed.get("publish")
    if not isinstance(publish, dict):
        parsed["publish"] = defaults["publish"]
    return parsed


def _publish_command_tokens(value) -> list[str]:
    if isinstance(value, str):
        return shlex.split(value)
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return list(value)
    return []


def _resolve_tokens(tokens: list[str], text: str | None, media_file: Path | None) -> list[str]:
    resolved: list[str] = []
    media_value = str(media_file) if media_file is not None else None
    for token in tokens:
        if token == "{text}":
            if text:
                resolved.append(text)
            continue
        if token == "{media}":
            if media_value:
                resolved.append(media_value)
            continue
        resolved.append(token)
    return resolved


def _build_publish_command(value, text: str | None, media_file: Path | None) -> list[str]:
    # Advanced config form:
    # {
    #   "command": ["mycli", "publish"],
    #   "text_args": ["--caption", "{text}"],
    #   "media_args": ["--file", "{media}"]
    # }
    if isinstance(value, dict):
        base = _publish_command_tokens(value.get("command"))
        if not base:
            return []
        cmd = list(base)
        if text:
            cmd.extend(_resolve_tokens(_publish_command_tokens(value.get("text_args")), text, media_file))
        if media_file is not None:
            cmd.extend(_resolve_tokens(_publish_command_tokens(value.get("media_args")), text, media_file))
        return cmd

    # Backward-compatible form:
    # "x" or ["x", "--some-flag"]
    base = _publish_command_tokens(value)
    if not base:
        return []
    cmd = list(base)
    if text is not None:
        cmd.append(text)
    if media_file is not None:
        cmd.append(str(media_file))
    return cmd


def _compose_text_in_editor(initial_text: str = "") -> str:
    editor = os.getenv("EDITOR", "vim").strip()
    editor_cmd = shlex.split(editor) if editor else ["vim"]
    if not editor_cmd:
        editor_cmd = ["vim"]
    with tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="w", encoding="utf-8") as tmp:
        temp_path = Path(tmp.name)
        if initial_text:
            tmp.write(initial_text + "\n")
    try:
        try:
            subprocess.run(editor_cmd + [str(temp_path)], check=False)
        except FileNotFoundError:
            raise SystemExit(f"Editor not found: {editor_cmd[0]}")
        content = temp_path.read_text(encoding="utf-8").strip()
        return content
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass


def prompt_publish_text() -> str | None:
    # Ensure familiar shell-style inline editing bindings in the prompt.
    # Works with GNU readline terminals where Alt is sent as Meta.
    try:
        readline.parse_and_bind("set editing-mode emacs")
        readline.parse_and_bind("\\ef: forward-word")
        readline.parse_and_bind("\\eb: backward-word")
        readline.parse_and_bind("\\C-w: unix-word-rubout")
    except Exception:
        pass

    print("")
    print("Enter accompanying post text (type 'v' to open $EDITOR, blank to skip publish):")
    raw = input("> ").strip()
    if not raw:
        return None
    if raw.lower() == "v":
        text = _compose_text_in_editor("")
        return text if text else None
    return raw


def publish_content(post_text: str | None, media_file: Path | None, config: dict) -> tuple[bool, list[str]]:
    publish = config.get("publish") if isinstance(config, dict) else None
    if not isinstance(publish, dict):
        return False, ["Invalid config: missing object at key 'publish'."]

    failures: list[str] = []
    for target_name in ("x", "linkedin"):
        cmd = _build_publish_command(publish.get(target_name), post_text, media_file)
        if not cmd:
            failures.append(f"{target_name}: missing publish command in config")
            continue
        proc = subprocess.run(cmd)
        if proc.returncode != 0:
            failures.append(f"{target_name}: command failed with exit code {proc.returncode}")
    return len(failures) == 0, failures


def preflight_publish_auth(config: dict) -> tuple[bool, list[str]]:
    publish = config.get("publish") if isinstance(config, dict) else None
    if not isinstance(publish, dict):
        return False, ["Invalid config: missing object at key 'publish'."]

    failures: list[str] = []
    for target_name in ("x", "linkedin"):
        cmd = _build_publish_command(publish.get(target_name), None, None)
        if not cmd:
            failures.append(f"{target_name}: missing publish command in config")
            continue
        executable = os.path.basename(cmd[0])
        if executable not in ("x", "linkedin"):
            continue
        proc = subprocess.run(cmd + ["-ea"])
        if proc.returncode != 0:
            failures.append(f"{target_name}: auth preflight failed with exit code {proc.returncode}")
    return len(failures) == 0, failures


def detect_screen_size() -> str | None:
    if shutil.which("xrandr"):
        try:
            out = subprocess.check_output(["xrandr"], text=True, stderr=subprocess.DEVNULL)
            for line in out.splitlines():
                if "*" in line:
                    token = line.strip().split()[0]
                    if "x" in token:
                        return token
        except Exception:
            pass

    if shutil.which("xdpyinfo"):
        try:
            out = subprocess.check_output(["xdpyinfo"], text=True, stderr=subprocess.DEVNULL)
            for line in out.splitlines():
                line = line.strip()
                if line.startswith("dimensions:"):
                    dim = line.split()[1]
                    if "x" in dim:
                        return dim
        except Exception:
            pass

    return None


def detect_webcam_device() -> str | None:
    for idx in range(10):
        device = Path(f"/dev/video{idx}")
        if device.exists() and os.access(device, os.R_OK):
            return str(device)
    return None


def build_overlay_filter_complex() -> str:
    return (
        f"[0:v]setpts=PTS-STARTPTS,fps={WEB_FPS},scale='min({WEB_MAX_WIDTH},iw)':-2:flags=lanczos,format=gray[bg];"
        f"[1:v]setpts=PTS-STARTPTS,fps={WEB_FPS},scale={WEBCAM_WIDTH}:-2:flags=lanczos,format=gray,"
        "eq=contrast=1.35:brightness=-0.04[cam];"
        "[bg][cam]overlay=x=W-w:y=H-h:format=auto[v]"
    )


def build_screen_command_x11(screen_file: Path, display: str) -> list[str]:
    cmd = ["ffmpeg", "-y", "-f", "x11grab", "-framerate", WEB_FPS]
    size = detect_screen_size()
    if size:
        cmd.extend(["-video_size", size])
    cmd.extend([
        "-i",
        display,
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        WEB_PRESET,
        "-crf",
        "24",
        "-pix_fmt",
        "yuv420p",
        str(screen_file),
    ])
    return cmd


def build_screen_command_wayland(screen_file: Path) -> list[str]:
    return [
        "wf-recorder",
        "-y",
        "--muxer",
        "matroska",
        "-f",
        str(screen_file),
    ]


def build_webcam_audio_command(av_file: Path, webcam_device: str) -> list[str]:
    return [
        "ffmpeg",
        "-y",
        "-f",
        "v4l2",
        "-thread_queue_size",
        "512",
        "-framerate",
        "30",
        "-video_size",
        "640x480",
        "-i",
        webcam_device,
        "-thread_queue_size",
        "1024",
        "-f",
        "pulse",
        "-i",
        "default",
        "-c:v",
        "libx264",
        "-preset",
        WEB_PRESET,
        "-crf",
        "24",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        WEB_AUDIO_BITRATE,
        "-ac",
        "2",
        "-ar",
        "48000",
        str(av_file),
    ]


def build_unified_record_command_x11(output_file: Path, display: str, webcam_device: str) -> list[str]:
    cmd = [
        "ffmpeg",
        "-y",
        "-fflags",
        "+genpts",
        "-thread_queue_size",
        "1024",
        "-f",
        "x11grab",
        "-framerate",
        WEB_FPS,
    ]
    size = detect_screen_size()
    if size:
        cmd.extend(["-video_size", size])
    cmd.extend(
        [
            "-i",
            display,
            "-thread_queue_size",
            "1024",
            "-f",
            "v4l2",
            "-framerate",
            "30",
            "-video_size",
            "640x480",
            "-i",
            webcam_device,
            "-thread_queue_size",
            "1024",
            "-f",
            "pulse",
            "-i",
            "default",
            "-filter_complex",
            build_overlay_filter_complex(),
            "-map",
            "[v]",
            "-map",
            "2:a?",
            "-af",
            "highpass=f=70,"
            "afftdn=nf=-25:tn=1,"
            "equalizer=f=120:t=q:w=1.0:g=5,"
            "equalizer=f=220:t=q:w=1.0:g=2.5,"
            "equalizer=f=2600:t=q:w=1.2:g=-2.0,"
            "volume=1.8",
            "-c:v",
            "libx264",
            "-preset",
            WEB_PRESET,
            "-crf",
            WEB_CRF,
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            WEB_AUDIO_BITRATE,
            "-ac",
            "2",
            "-ar",
            "48000",
            "-movflags",
            "+faststart",
            str(output_file),
        ]
    )
    return cmd


def wait_for_recording_start(
    proc: subprocess.Popen,
    output_file: Path,
    warmup_only: bool,
    timeout: float = 12.0,
) -> bool:
    if warmup_only:
        warmup_deadline = time.time() + 2.0
        while time.time() < warmup_deadline:
            if proc.poll() is not None:
                return False
            time.sleep(0.1)
        return True

    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        try:
            if output_file.exists() and output_file.stat().st_size > 0:
                return True
        except OSError:
            pass
        time.sleep(0.2)
    return False


def probe_duration_seconds(media_file: Path) -> float:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(media_file),
    ]
    try:
        out = subprocess.check_output(cmd, text=True).strip()
        return float(out)
    except Exception:
        return 0.0


def probe_sync_report(media_file: Path) -> dict:
    report: dict = {"file": str(media_file), "exists": media_file.exists()}
    if not media_file.exists():
        return report

    fmt_cmd = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(media_file),
    ]
    try:
        fmt_payload = json.loads(subprocess.check_output(fmt_cmd, text=True))
    except Exception as exc:
        report["probe_error"] = str(exc)
        return report

    fmt = fmt_payload.get("format", {}) if isinstance(fmt_payload, dict) else {}
    report["format"] = {
        "duration": fmt.get("duration"),
        "start_time": fmt.get("start_time"),
        "bit_rate": fmt.get("bit_rate"),
        "size": fmt.get("size"),
    }

    stream_stats: list[dict] = []
    streams = fmt_payload.get("streams", []) if isinstance(fmt_payload, dict) else []
    pkt_cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_packets",
        "-show_entries",
        "packet=stream_index,pts_time,dts_time,duration_time",
        "-of",
        "json",
        str(media_file),
    ]
    packets_by_stream: dict[int, list[dict]] = {}
    try:
        pkt_payload = json.loads(subprocess.check_output(pkt_cmd, text=True))
        packets = pkt_payload.get("packets", []) if isinstance(pkt_payload, dict) else []
        if isinstance(packets, list):
            for packet in packets:
                if not isinstance(packet, dict):
                    continue
                stream_index = packet.get("stream_index")
                if isinstance(stream_index, int):
                    packets_by_stream.setdefault(stream_index, []).append(packet)
    except Exception as exc:
        report["packet_probe_error"] = str(exc)

    for stream in streams:
        if not isinstance(stream, dict):
            continue
        idx = stream.get("index")
        codec_type = str(stream.get("codec_type", "unknown"))
        stream_report = {
            "index": idx,
            "type": codec_type,
            "codec": stream.get("codec_name"),
            "time_base": stream.get("time_base"),
            "start_time": stream.get("start_time"),
            "duration": stream.get("duration"),
            "r_frame_rate": stream.get("r_frame_rate"),
            "avg_frame_rate": stream.get("avg_frame_rate"),
            "sample_rate": stream.get("sample_rate"),
            "channels": stream.get("channels"),
        }
        if isinstance(idx, int):
            stream_packets = packets_by_stream.get(idx, [])
            if stream_packets:
                stream_report["packet_count"] = len(stream_packets)
                first = stream_packets[0]
                last = stream_packets[-1]
                stream_report["first_pts_time"] = first.get("pts_time")
                stream_report["last_pts_time"] = last.get("pts_time")
        stream_stats.append(stream_report)

    report["streams"] = stream_stats
    return report


def write_sync_diagnostics(
    output_dir: Path,
    output_file: Path,
    screen_file: Path | None = None,
    av_file: Path | None = None,
) -> None:
    ts = time.strftime("%Y%m%d_%H%M%S")
    report_file = output_dir / f"sync_report_{ts}.json"
    payload: dict = {
        "generated_at_epoch": int(time.time()),
        "output": probe_sync_report(output_file),
    }
    if screen_file is not None:
        payload["screen"] = probe_sync_report(screen_file)
    if av_file is not None:
        payload["webcam_audio"] = probe_sync_report(av_file)

    try:
        report_file.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"Sync diagnostics saved: {report_file}")
    except OSError as exc:
        print(f"Failed to write sync diagnostics: {exc}")


def trim_video_precise(media_file: Path, trim_start: float, trim_end: float) -> tuple[bool, str]:
    if trim_end <= trim_start:
        return False, "Invalid trim range."
    tmp_output = media_file.with_suffix(".trim.mp4")
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{trim_start:.3f}",
        "-i",
        str(media_file),
        "-t",
        f"{(trim_end - trim_start):.3f}",
        "-c:v",
        "libx264",
        "-preset",
        WEB_PRESET,
        "-crf",
        WEB_CRF,
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        WEB_AUDIO_BITRATE,
        "-ac",
        "2",
        "-ar",
        "48000",
        "-movflags",
        "+faststart",
        str(tmp_output),
    ]
    proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if proc.returncode != 0 or not tmp_output.exists():
        return False, "Failed to trim video."
    tmp_output.replace(media_file)
    return True, ""


def run_trim_tui(video_file: Path) -> tuple[bool, float, float]:
    duration = probe_duration_seconds(video_file)
    if duration <= 0:
        return False, 0.0, 0.0

    step = 0.1
    cursor = 0.0
    trim_start = 0.0
    trim_end = duration
    paused = False
    play_anchor_ts = 0.0
    play_anchor_wall = 0.0
    audio_proc: subprocess.Popen | None = None

    def stop_audio() -> None:
        nonlocal audio_proc
        if audio_proc and audio_proc.poll() is None:
            try:
                os.kill(audio_proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        audio_proc = None

    def play_audio_at(ts: float) -> None:
        nonlocal audio_proc, play_anchor_ts, play_anchor_wall
        stop_audio()
        if not shutil.which("ffplay"):
            return
        safe_ts = min(max(0.0, ts), max(0.0, duration - 0.06))
        play_anchor_ts = safe_ts
        play_anchor_wall = time.monotonic()
        cmd = [
            "ffplay",
            "-hide_banner",
            "-loglevel",
            "error",
            "-nodisp",
            "-vn",
            "-seek2any",
            "1",
            "-ss",
            f"{safe_ts:.3f}",
            str(video_file),
        ]
        audio_proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    def draw(stdscr: curses.window) -> None:
        stdscr.erase()
        _, width = stdscr.getmaxyx()

        status = "paused" if paused else "playing"
        stdscr.addstr(0, 0, "Trim TUI: h/l seek  H/L start/end  space play/pause  a cut-left  e cut-right  Enter apply  q cancel")
        stdscr.addstr(1, 0, f"Playback: {status}")
        stdscr.addstr(3, 0, f"Timer: {cursor:.2f}s / {duration:.2f}s")
        stdscr.addstr(
            5,
            0,
            f"cursor={cursor:.2f}s  keep={trim_start:.2f}s -> {trim_end:.2f}s  duration={duration:.2f}s",
        )
        stdscr.addstr(6, 0, "Pause first, then press 'a'/'e' to cut before/after timer.")
        stdscr.refresh()

    def ui(stdscr: curses.window) -> tuple[bool, float, float]:
        nonlocal cursor, trim_start, trim_end, paused

        def sync_cursor_from_playhead() -> None:
            nonlocal cursor
            cursor = min(duration, play_anchor_ts + (time.monotonic() - play_anchor_wall))

        def consume_repeated_key(first_key: int) -> int:
            count = 1
            stdscr.timeout(0)
            try:
                while True:
                    nxt = stdscr.getch()
                    if nxt == first_key:
                        count += 1
                        continue
                    if nxt == -1:
                        break
                    curses.ungetch(nxt)
                    break
            finally:
                stdscr.timeout(50)
            return count

        curses.curs_set(0)
        if curses.has_colors():
            curses.start_color()
            try:
                if hasattr(curses, "assume_default_colors"):
                    curses.assume_default_colors(-1, -1)
                else:
                    curses.use_default_colors()
            except curses.error:
                pass
            stdscr.bkgd(" ", curses.color_pair(0))
        stdscr.nodelay(True)
        stdscr.timeout(50)
        play_audio_at(cursor)
        paused = False
        while True:
            if not paused:
                sync_cursor_from_playhead()
                if cursor >= duration:
                    cursor = duration
                    stop_audio()
                    paused = True
            draw(stdscr)
            ch = stdscr.getch()
            if ch == -1:
                continue
            if ch in (ord("q"), 27):
                return False, 0.0, 0.0
            if ch in (10, 13):
                if trim_end <= trim_start:
                    continue
                return True, trim_start, trim_end
            if ch == ord(" "):
                if paused:
                    play_audio_at(cursor)
                    paused = False
                else:
                    sync_cursor_from_playhead()
                    stop_audio()
                    paused = True
            elif ch == ord("h"):
                repeats = consume_repeated_key(ord("h"))
                cursor = max(0.0, cursor - (step * repeats))
                if not paused:
                    play_audio_at(cursor)
            elif ch == ord("l"):
                repeats = consume_repeated_key(ord("l"))
                cursor = min(duration, cursor + (step * repeats))
                if not paused:
                    play_audio_at(cursor)
            elif ch == ord("H"):
                cursor = 0.0
                if not paused:
                    play_audio_at(cursor)
            elif ch == ord("L"):
                cursor = duration
                if not paused:
                    play_audio_at(cursor)
            elif ch == ord("a"):
                if paused:
                    trim_start = min(cursor, trim_end - 0.05)
            elif ch == ord("e"):
                if paused:
                    trim_end = max(cursor, trim_start + 0.05)

    try:
        return curses.wrapper(ui)
    finally:
        stop_audio()


def launch_trim_tui_and_apply(video_file: Path) -> tuple[bool, str]:
    if not video_file.exists():
        return False, "Cannot trim: output file not found."
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return True, "Skipped trim UI (not an interactive terminal)."
    print("")
    print("Launching trim UI...")
    apply_trim, trim_start, trim_end = run_trim_tui(video_file)
    if not apply_trim:
        return True, "Trim canceled."
    ok, err = trim_video_precise(video_file, trim_start, trim_end)
    if not ok:
        return False, err
    return True, f"Trim applied: {trim_start:.2f}s -> {trim_end:.2f}s"


def handle_publish_flow(video_file: Path) -> bool:
    trim_ok, trim_msg = launch_trim_tui_and_apply(video_file)
    if trim_msg:
        print(trim_msg)
    if not trim_ok:
        print("Post-trim failed.")
        return False

    post_text = prompt_publish_text()
    if not post_text:
        print("Skipped publish (no post text provided).")
        return False

    config = load_or_init_config()
    ok, failures = publish_content(post_text, video_file, config)
    if ok:
        print("Published to x and linkedin.")
        return True
    print("Publish finished with errors:")
    for failure in failures:
        print(f"- {failure}")
    return False


def handle_rectest_flow(video_file: Path) -> bool:
    trim_ok, trim_msg = launch_trim_tui_and_apply(video_file)
    if trim_msg:
        print(trim_msg)
    if not trim_ok:
        print("Post-trim failed.")
        return False

    destination = Path.cwd() / "output.mp4"
    try:
        destination.unlink(missing_ok=True)
        video_file.replace(destination)
    except OSError as exc:
        print(f"Failed to save output.mp4 in current directory: {exc}")
        return False

    print(f"Saved test output: {destination}")
    return True


def cleanup_recording_cache(output_dir: Path) -> None:
    patterns = [
        "blog_*.screen.mkv",
        "blog_*.av.mkv",
        "*.trim.mp4",
        "*.tmp.mp4",
        "blog_recorder.log",
    ]
    deleted = 0
    for pattern in patterns:
        for file_path in output_dir.glob(pattern):
            if not file_path.is_file():
                continue
            try:
                file_path.unlink()
                deleted += 1
            except OSError:
                pass
    if deleted:
        print(f"Cleared {deleted} cached file(s) from: {output_dir}")


def _split_text_and_media_arg(text_parts: list[str], explicit_media: str | None) -> tuple[str | None, Path | None]:
    parts = list(text_parts)
    media = Path(explicit_media).expanduser() if explicit_media else None

    if media is None and parts:
        candidate = Path(parts[-1]).expanduser()
        if candidate.is_file():
            media = candidate
            parts.pop()

    text = " ".join(parts).strip()
    return (text if text else None), media


def publish_from_cli(text: str | None, media_file: Path | None) -> int:
    if media_file is not None and not media_file.is_file():
        print(f"Media file not found: {media_file}")
        return 1

    config = load_or_init_config()
    ok, failures = publish_content(text, media_file, config)
    if ok:
        if text and media_file:
            print("Published post + media to all platforms.")
        elif media_file:
            print("Published media to all platforms.")
        else:
            print("Published post to all platforms.")
        return 0
    print("Publish finished with errors:")
    for failure in failures:
        print(f"- {failure}")
    return 1


def finalize_recording(
    screen_file: Path,
    av_file: Path,
    output_file: Path,
) -> tuple[bool, str]:
    if not screen_file.exists():
        return False, f"Screen recording not found: {screen_file}"
    if not av_file.exists():
        return False, f"Webcam/audio recording not found: {av_file}"
    if not shutil.which("ffmpeg"):
        return False, "ffmpeg is required for finalization."

    tmp_output = output_file.with_suffix(".tmp.mp4")
    cmd = [
        "ffmpeg",
        "-y",
        "-fflags",
        "+genpts",
        "-i",
        str(screen_file),
        "-i",
        str(av_file),
        "-filter_complex",
        build_overlay_filter_complex(),
        "-map",
        "[v]",
        "-map",
        "1:a?",
        "-af",
        "asetpts=PTS-STARTPTS,"
        "highpass=f=70,"
        "afftdn=nf=-25:tn=1,"
        "equalizer=f=120:t=q:w=1.0:g=5,"
        "equalizer=f=220:t=q:w=1.0:g=2.5,"
        "equalizer=f=2600:t=q:w=1.2:g=-2.0,"
        "volume=1.8,"
        "aresample=async=1:first_pts=0",
        "-c:v",
        "libx264",
        "-preset",
        WEB_PRESET,
        "-crf",
        WEB_CRF,
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        WEB_AUDIO_BITRATE,
        "-ac",
        "2",
        "-ar",
        "48000",
        "-shortest",
        "-avoid_negative_ts",
        "make_zero",
        "-movflags",
        "+faststart",
        str(tmp_output),
    ]
    proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if proc.returncode != 0 or not tmp_output.exists():
        return False, "Failed to finalize composite recording."

    tmp_output.replace(output_file)
    return True, ""


def start_recording(output_dir: Path, debug_sync: bool = False) -> int:
    state = load_state()
    screen_pid = int(state.get("screen_pid", -1)) if state else -1
    av_pid = int(state.get("av_pid", -1)) if state else -1
    recorder_pid = int(state.get("recorder_pid", -1)) if state else -1
    if state and (pid_exists(screen_pid) or pid_exists(av_pid) or pid_exists(recorder_pid)):
        active_pid = recorder_pid if pid_exists(recorder_pid) else (screen_pid if pid_exists(screen_pid) else av_pid)
        print(f"Recording already active (pid={active_pid}): {state.get('output_file', '')}")
        return 1

    clear_state()
    output_dir.mkdir(parents=True, exist_ok=True)
    if not shutil.which("ffmpeg"):
        print("Unable to start recording.")
        print("ffmpeg is required.")
        return 1

    webcam_device = detect_webcam_device()
    if not webcam_device:
        print("Unable to start recording.")
        print("No webcam device found (/dev/video*).")
        return 1

    filename = f"blog_{time.strftime('%Y%m%d_%H%M%S')}.mp4"
    output_file = output_dir / filename
    screen_file = output_dir / f"{output_file.stem}.screen.mkv"
    av_file = output_dir / f"{output_file.stem}.av.mkv"
    log_file = output_dir / "blog_recorder.log"

    session_type = os.environ.get("XDG_SESSION_TYPE", "").lower()
    wayland_display = os.environ.get("WAYLAND_DISPLAY")
    display = os.environ.get("DISPLAY")

    if wayland_display or session_type == "wayland":
        if not shutil.which("wf-recorder"):
            print("Unable to start recording.")
            print("Wayland session detected but wf-recorder is not installed.")
            return 1
        screen_cmd = build_screen_command_wayland(screen_file)
        screen_warmup_only = True
        backend = "wayland-split"
    else:
        if not display:
            print("Unable to start recording.")
            print("X11 session detected but DISPLAY is not set.")
            return 1
        if not shutil.which("ffmpeg"):
            print("Unable to start recording.")
            print("ffmpeg is required.")
            return 1
        unified_cmd = build_unified_record_command_x11(output_file, display, webcam_device)
        with log_file.open("ab") as log:
            unified_proc = subprocess.Popen(
                unified_cmd,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                start_new_session=True,
            )
        print("Initializing unified recorder (screen + webcam + audio)...")
        unified_ready = wait_for_recording_start(unified_proc, output_file, warmup_only=False, timeout=10.0)
        if not unified_ready:
            print(f"Unified recorder did not initialize in time. Check {log_file}")
            if unified_proc.poll() is None:
                try:
                    os.kill(unified_proc.pid, signal.SIGINT)
                except ProcessLookupError:
                    pass
            return 1

        save_state(
            {
                "recorder_pid": unified_proc.pid,
                "output_file": str(output_file),
                "backend": "x11-unified",
                "debug_sync": debug_sync,
                "started_at": int(time.time()),
            }
        )
        print(f"Recording started (pid={unified_proc.pid}).")
        print(f"Saving to: {output_file} (grayscale + webcam overlay; audio from webcam track)")
        return 0

    av_cmd = build_webcam_audio_command(av_file, webcam_device)
    with log_file.open("ab") as log:
        av_proc = subprocess.Popen(
            av_cmd,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
        screen_proc = subprocess.Popen(
            screen_cmd,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
    print("Initializing webcam+audio recorder...")
    print("Using audio source: default")
    print("Initializing screen recorder...")

    av_ready = wait_for_recording_start(av_proc, av_file, warmup_only=True, timeout=8.0)
    screen_ready = wait_for_recording_start(screen_proc, screen_file, warmup_only=screen_warmup_only, timeout=8.0)

    if not av_ready:
        print(f"Webcam+audio recorder did not initialize in time. Check {log_file}")
        if av_proc.poll() is None:
            try:
                os.kill(av_proc.pid, signal.SIGINT)
            except ProcessLookupError:
                pass
        if screen_proc.poll() is None:
            try:
                os.kill(screen_proc.pid, signal.SIGINT)
            except ProcessLookupError:
                pass
        return 1

    if not screen_ready:
        print(f"Screen recorder did not initialize in time. Check {log_file}")
        if screen_proc.poll() is None:
            try:
                os.kill(screen_proc.pid, signal.SIGINT)
            except ProcessLookupError:
                pass
        if av_proc.poll() is None:
            try:
                os.kill(av_proc.pid, signal.SIGINT)
            except ProcessLookupError:
                pass
        return 1

    save_state(
        {
            "screen_pid": screen_proc.pid,
            "av_pid": av_proc.pid,
            "output_file": str(output_file),
            "screen_file": str(screen_file),
            "av_file": str(av_file),
            "backend": backend,
            "debug_sync": debug_sync,
            "started_at": int(time.time()),
        }
    )

    print(f"Recording started (screen pid={screen_proc.pid}, webcam+audio pid={av_proc.pid}).")
    print(f"Saving to: {output_file} (grayscale + webcam overlay; audio from webcam track)")
    return 0


def stop_recording(rectest: bool = False) -> int:
    state = load_state()
    if not state:
        print("No active recording found.")
        return 1

    backend = str(state.get("backend", ""))
    if backend == "x11-unified":
        recorder_pid = int(state.get("recorder_pid", -1))
        output_file = state.get("output_file", "")
        debug_sync = bool(state.get("debug_sync"))
        if recorder_pid <= 0:
            clear_state()
            print("Recorder state is invalid. Cleared stale state.")
            return 1
        if not pid_exists(recorder_pid):
            clear_state()
            print("Recorder process is not running. Cleared stale state.")
            return 1

        print("Stopping unified recorder...")
        try:
            os.kill(recorder_pid, signal.SIGINT)
            print(f"Stopping recorder (pid={recorder_pid})...")
        except ProcessLookupError:
            pass

        print("Stop signal sent. Waiting for capture to finalize...")
        deadline = time.time() + 20
        next_progress = time.time() + 1.0
        while time.time() < deadline:
            if not pid_exists(recorder_pid):
                clear_state()
                print("Stopped recording.")
                if output_file and Path(output_file).exists():
                    print(f"Saved: {output_file} (grayscale + webcam overlay)")
                    if debug_sync:
                        write_sync_diagnostics(Path(output_file).parent, Path(output_file))
                    if rectest:
                        handle_rectest_flow(Path(output_file))
                    else:
                        handle_publish_flow(Path(output_file))
                    cleanup_recording_cache(Path(output_file).parent)
                else:
                    print(
                        f"Recorder stopped, but output file was not produced. Check {Path(output_file).parent / 'blog_recorder.log'}"
                    )
                return 0
            if time.time() >= next_progress:
                print("Still finalizing...")
                next_progress = time.time() + 1.0
            time.sleep(0.2)

        print("Recorder is taking longer than expected. Sending terminate signal...")
        if pid_exists(recorder_pid):
            try:
                os.kill(recorder_pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        time.sleep(1)
        if pid_exists(recorder_pid):
            print("Recorder still running. Forcing stop...")
            try:
                os.kill(recorder_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        clear_state()
        if output_file and Path(output_file).exists():
            print("Stopped recording (forced).")
            print(f"Saved: {output_file} (grayscale + webcam overlay)")
            if debug_sync:
                write_sync_diagnostics(Path(output_file).parent, Path(output_file))
            if rectest:
                handle_rectest_flow(Path(output_file))
            else:
                handle_publish_flow(Path(output_file))
            cleanup_recording_cache(Path(output_file).parent)
            return 0
        print("Stopped recording (forced), but no output was produced.")
        return 1

    screen_pid = int(state.get("screen_pid", -1))
    av_pid = int(state.get("av_pid", -1))
    output_file = state.get("output_file", "")
    screen_file = state.get("screen_file", "")
    av_file = state.get("av_file", "")
    debug_sync = bool(state.get("debug_sync"))

    if screen_pid <= 0 or av_pid <= 0:
        clear_state()
        print("Recorder state is invalid. Cleared stale state.")
        return 1

    if not pid_exists(screen_pid) and not pid_exists(av_pid):
        clear_state()
        print("Recorder process is not running. Cleared stale state.")
        return 1

    print("Stopping recording...")
    if pid_exists(screen_pid):
        try:
            os.kill(screen_pid, signal.SIGINT)
            print(f"Stopping screen recorder (pid={screen_pid})...")
        except ProcessLookupError:
            pass

    if pid_exists(av_pid):
        try:
            os.kill(av_pid, signal.SIGINT)
            print(f"Stopping webcam+audio recorder (pid={av_pid})...")
        except ProcessLookupError:
            pass

    print("Stop signal sent. Waiting for captures to finalize...")
    deadline = time.time() + 15
    next_progress = time.time() + 1.0
    while time.time() < deadline:
        screen_stopped = not pid_exists(screen_pid)
        av_stopped = not pid_exists(av_pid)
        if screen_stopped and av_stopped:
            print("Combining screen with webcam+audio...")
            ok, err = finalize_recording(Path(screen_file), Path(av_file), Path(output_file))
            if ok and debug_sync and output_file:
                write_sync_diagnostics(
                    Path(output_file).parent,
                    Path(output_file),
                    Path(screen_file),
                    Path(av_file),
                )
            clear_state()
            Path(screen_file).unlink(missing_ok=True)
            Path(av_file).unlink(missing_ok=True)
            print("Stopped recording.")
            if ok:
                if output_file and Path(output_file).exists():
                    print(f"Saved: {output_file} (grayscale + webcam overlay)")
                    if rectest:
                        handle_rectest_flow(Path(output_file))
                    else:
                        handle_publish_flow(Path(output_file))
                    cleanup_recording_cache(Path(output_file).parent)
                else:
                    print(
                        f"Recorder stopped, but output file was not produced. Check {Path(output_file).parent / 'blog_recorder.log'}"
                    )
            else:
                print("Finalization failed.")
                if err:
                    print(err)
                print(f"Raw screen: {screen_file}")
                print(f"Raw webcam+audio: {av_file}")
            return 0
        if time.time() >= next_progress:
            print("Still finalizing...")
            next_progress = time.time() + 1.0
        time.sleep(0.2)

    print("Recorder is taking longer than expected. Sending terminate signal...")
    if pid_exists(screen_pid):
        try:
            os.kill(screen_pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    if pid_exists(av_pid):
        try:
            os.kill(av_pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

    time.sleep(1)
    if pid_exists(screen_pid):
        print("Screen recorder still running. Forcing stop...")
        try:
            os.kill(screen_pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if pid_exists(av_pid):
        print("Webcam+audio recorder still running. Forcing stop...")
        try:
            os.kill(av_pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    print("Combining screen with webcam+audio...")
    ok, err = finalize_recording(Path(screen_file), Path(av_file), Path(output_file))
    if ok and debug_sync and output_file:
        write_sync_diagnostics(
            Path(output_file).parent,
            Path(output_file),
            Path(screen_file),
            Path(av_file),
        )
    clear_state()
    Path(screen_file).unlink(missing_ok=True)
    Path(av_file).unlink(missing_ok=True)
    print("Stopped recording (forced).")
    if ok:
        if output_file and Path(output_file).exists():
            print(f"Saved: {output_file} (grayscale + webcam overlay)")
            if rectest:
                handle_rectest_flow(Path(output_file))
            else:
                handle_publish_flow(Path(output_file))
            cleanup_recording_cache(Path(output_file).parent)
        else:
            print(
                f"Recorder stopped, but output file was not produced. Check {Path(output_file).parent / 'blog_recorder.log'}"
            )
    else:
        print("Finalization failed after forced stop.")
        if err:
            print(err)
    return 0


def play_latest_recording(output_dir: Path) -> int:
    if not shutil.which("ffplay"):
        print("ffplay not found. Install ffmpeg tools to use playback.")
        return 1

    if not output_dir.exists():
        print(f"No recordings directory found: {output_dir}")
        return 1

    candidates = [
        p
        for p in output_dir.glob("blog_*.mp4")
        if p.is_file() and ".tmp." not in p.name and ".color." not in p.name
    ]
    if not candidates:
        print(f"No recordings found in: {output_dir}")
        return 1

    latest = max(candidates, key=lambda p: p.stat().st_mtime)
    print(f"Playing latest recording: {latest}")
    subprocess.Popen(
        ["ffplay", "-hide_banner", "-loglevel", "error", "-nostats", "-autoexit", str(latest)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    print("Playback started in background.")
    return 0


def clear_recordings(output_dir: Path) -> int:
    state = load_state()
    screen_pid = int(state.get("screen_pid", -1)) if state else -1
    av_pid = int(state.get("av_pid", -1)) if state else -1
    recorder_pid = int(state.get("recorder_pid", -1)) if state else -1
    if state and (pid_exists(screen_pid) or pid_exists(av_pid) or pid_exists(recorder_pid)):
        print("Cannot clear recordings while recording is active. Run: blog -stp")
        return 1

    if not output_dir.exists():
        print(f"No recordings directory found: {output_dir}")
        return 0

    candidates = [
        p
        for p in output_dir.glob("blog_*.mp4")
        if p.is_file()
    ]
    if not candidates:
        print(f"No recordings to clear in: {output_dir}")
        return 0

    deleted = 0
    for file_path in candidates:
        try:
            file_path.unlink()
            deleted += 1
        except OSError:
            print(f"Failed to delete: {file_path}")

    print(f"Cleared {deleted} recording(s) from: {output_dir}")
    return 0


def align_webcam() -> int:
    if not shutil.which("ffplay"):
        print("ffplay not found. Install ffmpeg tools to use webcam align preview.")
        return 1
    webcam_device = detect_webcam_device()
    if not webcam_device:
        print("No webcam device found (/dev/video*).")
        return 1

    print("Opening webcam align preview. Press 'q' in the preview window to exit.")
    cmd = [
        "ffplay",
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostats",
        "-an",
        "-f",
        "v4l2",
        "-framerate",
        "30",
        "-video_size",
        "640x480",
        "-i",
        webcam_device,
        "-vf",
        f"fps={WEB_FPS},scale={WEBCAM_WIDTH}:-2:flags=lanczos,format=gray,eq=contrast=1.35:brightness=-0.04",
    ]
    proc = subprocess.run(cmd, stdin=subprocess.DEVNULL)
    return proc.returncode


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("-h", action="store_true", dest="help_flag")
    parser.add_argument("-v", action="store_true", dest="version")
    parser.add_argument("-u", action="store_true", dest="upgrade")
    parser.add_argument("-e", action="store_true", dest="edit", help="Compose post in $EDITOR.")
    parser.add_argument("-m", dest="media", help="Media path to publish.")
    parser.add_argument("--debug-sync", action="store_true", dest="debug_sync", help="Write timing diagnostics for recordings.")
    parser.add_argument("-rec", action="store_true", help="Start recording.")
    parser.add_argument("-stp", action="store_true", help="Stop recording and run trim+publish flow.")
    parser.add_argument("-rectest", action="store_true", help="Stop recording and save output.mp4 in current directory.")
    parser.add_argument("-a", action="store_true", dest="align", help="Open webcam align preview.")
    parser.add_argument("-pl", action="store_true", dest="play_latest", help="Play latest recording.")
    parser.add_argument("-c", action="store_true", dest="clear", help="Clear saved recordings.")
    parser.add_argument(
        "-o",
        dest="output_dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help=f"Output directory for recordings (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument("text", nargs="*", help="Post text.")

    args = parser.parse_args()

    if args.help_flag:
        print_usage_guide()
        return 0
    if args.version:
        print(__version__)
        return 0
    if args.upgrade:
        return upgrade_to_latest()

    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_FILE.open("w") as lock_fp:
        try:
            fcntl.flock(lock_fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Another instance of this CLI is currently running.")
            return 1

        action_flags = [
            bool(args.rec),
            bool(args.stp),
            bool(args.rectest),
            bool(args.align),
            bool(args.play_latest),
            bool(args.clear),
        ]
        if sum(action_flags) > 1:
            print("Use only one action flag at a time: -rec, -stp, -rectest, --align, --play-latest, --clear.")
            return 1

        output_dir = Path(args.output_dir).expanduser()

        if args.rec:
            if args.edit or args.media or args.text:
                print("-rec does not accept post text/media flags.")
                return 1
            config = load_or_init_config()
            ok, failures = preflight_publish_auth(config)
            if not ok:
                print("Publish auth preflight failed:")
                for failure in failures:
                    print(f"- {failure}")
                print("Recording did not start.")
                return 1
            return start_recording(Path(args.output_dir).expanduser(), debug_sync=bool(args.debug_sync))
        if args.stp:
            if args.edit or args.media or args.text or args.debug_sync:
                print("-stp does not accept post text/media flags or --debug-sync.")
                return 1
            return stop_recording()
        if args.rectest:
            if args.edit or args.media or args.text or args.debug_sync:
                print("-rectest does not accept post text/media flags or --debug-sync.")
                return 1
            return stop_recording(rectest=True)
        if args.align:
            if args.edit or args.media or args.text or args.debug_sync:
                print("--align does not accept post text/media flags or --debug-sync.")
                return 1
            return align_webcam()
        if args.play_latest:
            if args.edit or args.media or args.text or args.debug_sync:
                print("--play-latest does not accept post text/media flags or --debug-sync.")
                return 1
            return play_latest_recording(output_dir)
        if args.clear:
            if args.edit or args.media or args.text or args.debug_sync:
                print("--clear does not accept post text/media flags or --debug-sync.")
                return 1
            return clear_recordings(output_dir)

        text, media_file = _split_text_and_media_arg(args.text, args.media)

        if args.edit:
            if text is not None:
                print("Use either -e or provide text, not both.")
                return 1
            text = _compose_text_in_editor("")
            if not text:
                print("No content; cancelled.")
                return 1

        if text is None and media_file is None:
            print_usage_guide()
            return 1

        return publish_from_cli(text, media_file)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
import argparse
import fcntl
import json
import os
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

APP = "vlog"
REPO = "ryangerardwilson/vlog"
LATEST_RELEASE_API = f"https://api.github.com/repos/{REPO}/releases/latest"
INSTALL_SCRIPT_URL = f"https://raw.githubusercontent.com/{REPO}/main/install.sh"

LOCK_FILE = Path("/tmp/vlog_recorder_cli.lock")
STATE_FILE = Path.home() / ".vlog_recorder_state.json"
DEFAULT_OUTPUT_DIR = Path.home() / "Vlogs"
WEB_FPS = "24"
WEB_MAX_WIDTH = "1280"
WEB_CRF = "28"
WEB_PRESET = "veryfast"


def print_usage_guide() -> None:
    print(
        "Usage:\n"
        "  python main.py r              Start recording\n"
        "  python main.py s              Stop recording\n"
        "  python main.py p -l           Play latest recording (detached)\n"
        "  python main.py c              Clear all recordings\n"
        "  python main.py -v             Print version\n"
        "  python main.py -u             Upgrade to latest version\n"
        "  python main.py -h             Show this help\n"
        "\n"
        "Options:\n"
        "  -o, --output-dir <path>       Recording directory (default: ~/Vlogs)\n"
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
    STATE_FILE.write_text(json.dumps(state))


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


def build_recorder_command(output_file: Path) -> tuple[list[str] | None, str | None, str | None]:
    wayland_display = os.environ.get("WAYLAND_DISPLAY")
    display = os.environ.get("DISPLAY")
    session_type = os.environ.get("XDG_SESSION_TYPE", "").lower()

    if wayland_display and shutil.which("wf-recorder"):
        return ["wf-recorder", "-f", str(output_file)], "wf-recorder", None

    if wayland_display or session_type == "wayland":
        return (
            None,
            None,
            "Wayland session detected. Install 'wf-recorder' to capture the desktop correctly.",
        )

    if shutil.which("ffmpeg") and display:
        cmd = ["ffmpeg", "-y", "-f", "x11grab", "-framerate", WEB_FPS]
        size = detect_screen_size()
        if size:
            cmd.extend(["-video_size", size])
        cmd.extend([
            "-i",
            display,
            "-vf",
            f"fps={WEB_FPS},scale='min({WEB_MAX_WIDTH},iw)':-2:flags=lanczos,format=gray",
            "-c:v",
            "libx264",
            "-preset",
            WEB_PRESET,
            "-crf",
            WEB_CRF,
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(output_file),
        ])
        return cmd, "ffmpeg", None

    return None, None, "No compatible recorder found for this session."


def start_recording(output_dir: Path) -> int:
    state = load_state()
    if state and pid_exists(int(state.get("pid", -1))):
        print(f"Recording already active (pid={state['pid']}): {state.get('output_file', '')}")
        return 1

    clear_state()
    output_dir.mkdir(parents=True, exist_ok=True)

    filename = f"vlog_{time.strftime('%Y%m%d_%H%M%S')}.mp4"
    output_file = output_dir / filename
    capture_file = output_file

    cmd, backend, err = build_recorder_command(capture_file)
    if not cmd:
        print("Unable to start recording.")
        if err:
            print(err)
        print("Requirements: wf-recorder on Wayland, or ffmpeg with DISPLAY on X11.")
        return 1

    if backend == "wf-recorder":
        capture_file = output_dir / f"{output_file.stem}.color{output_file.suffix}"
        cmd, _, err = build_recorder_command(capture_file)
        if not cmd:
            print("Unable to start recording.")
            if err:
                print(err)
            return 1

    log_file = output_dir / "vlog_recorder.log"
    with log_file.open("ab") as log:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )

    save_state(
        {
            "pid": proc.pid,
            "output_file": str(output_file),
            "capture_file": str(capture_file),
            "backend": backend,
            "started_at": int(time.time()),
        }
    )

    print(f"Started recording (pid={proc.pid})")
    print(f"Saving to: {output_file} (grayscale)")
    return 0


def convert_to_grayscale(input_file: Path, output_file: Path) -> tuple[bool, str]:
    if not input_file.exists():
        return False, f"Capture file not found: {input_file}"
    if not shutil.which("ffmpeg"):
        return False, "ffmpeg is required to convert recording to grayscale."

    tmp_output = output_file.with_suffix(".tmp.mp4")
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_file),
        "-vf",
        f"fps={WEB_FPS},scale='min({WEB_MAX_WIDTH},iw)':-2:flags=lanczos,format=gray",
        "-c:v",
        "libx264",
        "-preset",
        WEB_PRESET,
        "-crf",
        WEB_CRF,
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(tmp_output),
    ]
    proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if proc.returncode != 0 or not tmp_output.exists():
        return False, "Failed to convert recording to grayscale."

    tmp_output.replace(output_file)
    if input_file != output_file:
        input_file.unlink(missing_ok=True)
    return True, ""


def stop_recording() -> int:
    state = load_state()
    if not state:
        print("No active recording found.")
        return 1

    pid = int(state.get("pid", -1))
    output_file = state.get("output_file", "")
    capture_file = state.get("capture_file", output_file)
    backend = state.get("backend", "")

    if pid <= 0 or not pid_exists(pid):
        clear_state()
        print("Recorder process is not running. Cleared stale state.")
        return 1

    print(f"Stopping recording (pid={pid})...")
    try:
        os.kill(pid, signal.SIGINT)
    except ProcessLookupError:
        clear_state()
        print("Recorder process already exited.")
        return 1

    print("Stop signal sent. Finalizing recording...")
    deadline = time.time() + 10
    next_progress = time.time() + 1.0
    while time.time() < deadline:
        if not pid_exists(pid):
            if backend == "wf-recorder" and output_file:
                print("Recorder stopped. Converting to grayscale + web format...")
                ok, err = convert_to_grayscale(Path(capture_file), Path(output_file))
                clear_state()
                if ok:
                    print("Stopped recording.")
                    print(f"Saved: {output_file} (grayscale)")
                else:
                    print("Stopped recording, but grayscale conversion failed.")
                    if err:
                        print(err)
                    print(f"Raw capture: {capture_file}")
            else:
                clear_state()
                print("Stopped recording.")
                if output_file:
                    print(f"Saved: {output_file}")
            return 0
        if time.time() >= next_progress:
            print("Still finalizing...")
            next_progress = time.time() + 1.0
        time.sleep(0.2)

    print("Recorder is taking longer than expected. Sending terminate signal...")
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass

    time.sleep(1)
    if pid_exists(pid):
        print("Recorder still running. Forcing stop...")
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    if backend == "wf-recorder" and output_file:
        print("Converting to grayscale + web format...")
        ok, err = convert_to_grayscale(Path(capture_file), Path(output_file))
        clear_state()
        if ok:
            print("Stopped recording (forced).")
            print(f"Saved: {output_file} (grayscale)")
        else:
            print("Stopped recording (forced), but grayscale conversion failed.")
            if err:
                print(err)
            print(f"Raw capture: {capture_file}")
    else:
        clear_state()
        print("Stopped recording (forced).")
        if output_file:
            print(f"Saved: {output_file}")
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
        for p in output_dir.glob("vlog_*.mp4")
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
    if state and pid_exists(int(state.get("pid", -1))):
        print("Cannot clear recordings while recording is active. Run: python main.py s")
        return 1

    if not output_dir.exists():
        print(f"No recordings directory found: {output_dir}")
        return 0

    candidates = [
        p
        for p in output_dir.glob("vlog_*.mp4")
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


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("-h", "--help", action="store_true", dest="help_flag")
    parser.add_argument("-v", "--version", action="store_true")
    parser.add_argument("-u", "--upgrade", action="store_true")
    parser.add_argument(
        "-o",
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Output directory for recordings (default: ~/Vlogs)",
    )
    parser.add_argument("command", nargs="?", choices=["r", "s", "c", "p"])
    parser.add_argument("-l", "--latest", action="store_true", help="Used with 'p' to play latest")

    args = parser.parse_args()

    if args.help_flag:
        print_usage_guide()
        return 0
    if args.version:
        print(__version__)
        return 0
    if args.upgrade:
        return upgrade_to_latest()
    if not args.command:
        print_usage_guide()
        return 1
    if args.latest and args.command != "p":
        print("The -l/--latest flag can only be used with command 'p'.")
        return 1

    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_FILE.open("w") as lock_fp:
        try:
            fcntl.flock(lock_fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Another instance of this CLI is currently running.")
            return 1

        if args.command == "r":
            return start_recording(Path(args.output_dir).expanduser())
        if args.command == "s":
            return stop_recording()
        if args.command == "c":
            return clear_recordings(Path(args.output_dir).expanduser())
        if args.command == "p":
            if not args.latest:
                print("Use: python main.py p -l")
                return 1
            return play_latest_recording(Path(args.output_dir).expanduser())
        return 1


if __name__ == "__main__":
    sys.exit(main())

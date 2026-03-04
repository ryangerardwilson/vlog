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
WEB_AUDIO_BITRATE = "128k"
WEBCAM_WIDTH = "360"


def print_usage_guide() -> None:
    print(
        "Usage:\n"
        "  vlog r                        Start recording\n"
        "  vlog s                        Stop recording\n"
        "  vlog p -l                     Play latest recording (detached)\n"
        "  vlog c                        Clear all recordings\n"
        "  vlog -v                       Print version\n"
        "  vlog -u                       Upgrade to latest version\n"
        "  vlog -h                       Show this help\n"
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


def detect_webcam_device() -> str | None:
    for idx in range(10):
        device = Path(f"/dev/video{idx}")
        if device.exists() and os.access(device, os.R_OK):
            return str(device)
    return None


def build_overlay_filter_complex() -> str:
    return (
        f"[0:v]setpts=PTS-STARTPTS,fps={WEB_FPS},scale='min({WEB_MAX_WIDTH},iw)':-2:flags=lanczos,format=gray[bg];"
        f"[1:v]setpts=PTS-STARTPTS,fps={WEB_FPS},scale={WEBCAM_WIDTH}:-2:flags=lanczos[cam];"
        "[bg][cam]overlay=x=W-w-24:y=H-h-24:format=auto[v]"
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


def finalize_recording(screen_file: Path, av_file: Path, output_file: Path) -> tuple[bool, str]:
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
        "-movflags",
        "+faststart",
        str(tmp_output),
    ]
    proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if proc.returncode != 0 or not tmp_output.exists():
        return False, "Failed to finalize composite recording."

    tmp_output.replace(output_file)
    return True, ""


def start_recording(output_dir: Path) -> int:
    state = load_state()
    if state and pid_exists(int(state.get("pid", -1))):
        print(f"Recording already active (pid={state['pid']}): {state.get('output_file', '')}")
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

    filename = f"vlog_{time.strftime('%Y%m%d_%H%M%S')}.mp4"
    output_file = output_dir / filename
    screen_file = output_dir / f"{output_file.stem}.screen.mkv"
    av_file = output_dir / f"{output_file.stem}.av.mkv"
    log_file = output_dir / "vlog_recorder.log"

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
        screen_cmd = build_screen_command_x11(screen_file, display)
        screen_warmup_only = False
        backend = "x11-split"

    av_cmd = build_webcam_audio_command(av_file, webcam_device)
    with log_file.open("ab") as log:
        av_proc = subprocess.Popen(
            av_cmd,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
        print("Initializing webcam+audio recorder...")

    av_ready = wait_for_recording_start(av_proc, av_file, warmup_only=True, timeout=8.0)
    if not av_ready:
        print("Webcam+audio recorder did not initialize in time. Check ~/Vlogs/vlog_recorder.log")
        if av_proc.poll() is None:
            try:
                os.kill(av_proc.pid, signal.SIGINT)
            except ProcessLookupError:
                pass
        return 1

    with log_file.open("ab") as log:
        screen_proc = subprocess.Popen(
            screen_cmd,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
        print("Initializing screen recorder...")

    screen_ready = wait_for_recording_start(screen_proc, screen_file, warmup_only=screen_warmup_only, timeout=8.0)
    if not screen_ready:
        print("Screen recorder did not initialize in time. Check ~/Vlogs/vlog_recorder.log")
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
            "started_at": int(time.time()),
        }
    )

    print(f"Recording started (screen pid={screen_proc.pid}, webcam+audio pid={av_proc.pid}).")
    print(f"Saving to: {output_file} (grayscale + webcam overlay; audio from webcam track)")
    return 0


def stop_recording() -> int:
    state = load_state()
    if not state:
        print("No active recording found.")
        return 1

    screen_pid = int(state.get("screen_pid", -1))
    av_pid = int(state.get("av_pid", -1))
    output_file = state.get("output_file", "")
    screen_file = state.get("screen_file", "")
    av_file = state.get("av_file", "")

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
            clear_state()
            Path(screen_file).unlink(missing_ok=True)
            Path(av_file).unlink(missing_ok=True)
            print("Stopped recording.")
            if ok:
                if output_file and Path(output_file).exists():
                    print(f"Saved: {output_file} (grayscale + webcam overlay)")
                else:
                    print("Recorder stopped, but output file was not produced. Check ~/Vlogs/vlog_recorder.log")
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
    clear_state()
    Path(screen_file).unlink(missing_ok=True)
    Path(av_file).unlink(missing_ok=True)
    print("Stopped recording (forced).")
    if ok:
        if output_file and Path(output_file).exists():
            print(f"Saved: {output_file} (grayscale + webcam overlay)")
        else:
            print("Recorder stopped, but output file was not produced. Check ~/Vlogs/vlog_recorder.log")
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
        print("Cannot clear recordings while recording is active. Run: vlog s")
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
                print("Use: vlog p -l")
                return 1
            return play_latest_recording(Path(args.output_dir).expanduser())
        return 1


if __name__ == "__main__":
    sys.exit(main())

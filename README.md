# blog

Terminal-native publisher and recorder that shells out to `x` and `linkedin`.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/ryangerardwilson/blog/main/install.sh | bash
```

`blog -v` prints the installed app version from `_version.py`. Source checkouts
keep the checked-in placeholder at `0.0.0`; tagged release builds stamp the
shipped artifact with the real version.

## Usage

```text
blog CLI

flags:
  blog -h
  blog -v
  blog -u

features:
  publish text or media to the configured downstream CLIs
  # blog p <text> | blog p -m <path> [<text>] | blog p -e
  blog p "ship the patch"
  blog p -m ~/media/demo.mp4 "ship the patch"
  blog p -e

  start recording, optionally with sync diagnostics
  # blog -rec [-ds] [-o <path>]
  blog -rec
  blog -rec -ds

  stop recording, trim, and publish
  # blog -stp
  blog -stp

  stop recording, trim, and save ./output.mp4 without publishing
  # blog -rectest
  blog -rectest

  inspect or clean the recording workspace
  # blog -a | blog -pl [-o <path>] | blog -c [-o <path>]
  blog -a
  blog -pl
  blog -c
```

After `-stp`, recorder cache files in the output directory are auto-cleared.

## Config

Config path:

```text
~/.config/blog/config.json
```

Open it with:

```bash
blog conf
```

Auto-created on first publish if missing. Template in repo: `template_config.json`

Default:

```json
{
  "publish": {
    "x": {
      "command": ["x", "p"],
      "text_args": ["{text}"],
      "media_args": ["-m", "{media}"]
    },
    "linkedin": {
      "command": ["linkedin", "p"],
      "text_args": ["{text}"],
      "media_args": ["-m", "{media}"]
    }
  }
}
```

Config forms:
- Simple: `"x": "x"` or `["x"]`, which appends text and media positionally.
- Structured: `command` + `text_args` + `media_args`, recommended when the downstream CLI uses a verb such as `p` and expects an explicit media flag.

Placeholder tokens:
- `{text}` becomes the post text.
- `{media}` becomes the media path.

Example custom integration:

```json
{
  "publish": {
    "x": {
      "command": ["myx", "publish"],
      "text_args": ["--caption", "{text}"],
      "media_args": ["--file", "{media}"]
    }
  }
}
```

## Source Run

```bash
python -m venv .venv
source .venv/bin/activate
python main.py -h
```

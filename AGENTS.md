# blog Agent Guide

## Workspace Defaults
- Follow `/home/ryan/Subagents/cpo/CLI_TUI_STYLE_GUIDE.md` for CLI/TUI taste and help shape.
- Follow `/home/ryan/Subagents/cto/CANONICAL_REFERENCE_IMPLEMENTATION_FOR_CLI_AND_TUI_APPS.md` for executable contract details such as `help`, `version`, `upgrade`, installer behavior, release workflow expectations, and regression expectations.
- This file only records `blog`-specific constraints or durable deviations.

## Scope
- `blog` is a terminal-native publisher and recorder that coordinates local recording flow with explicit downstream publish commands.
- Keep it keyboard-first and inspectable. It is not a web dashboard or background automation system.
- Supported primary flows are: publish text/media, compose in-editor, record, stop-and-publish, stop-and-save-test output, align webcam, play latest, clear recordings, version, and upgrade.

## CLI Contract
- Canonical app actions use words only: `help`, `version`, `upgrade`.
- Canonical command grammar is declarative English only:
  - `blog publish "text"`
  - `blog publish media /path/to/file body "text"`
  - `blog publish in editor`
  - `blog record start`
  - `blog record stop and publish`
  - `blog record stop and save`
  - `blog camera align`
  - `blog recordings play latest`
  - `blog recordings clear`
  - `blog config`
- Do not keep terse aliases or action flags such as `p`, `conf`, `-e`, `-m`, `-o`, `-ds`, `-rec`, `-stp`, `-rectest`, `-a`, `-pl`, or `-c`.
- Do not allow bare text or bare media invocation to publish directly.
- `blog` with no action and no content should print the same help text as `blog help`.
- Help, README examples, and runtime error strings must reference only canonical actions and declarative command forms.

## Config And Storage
- Config lives at `~/.config/blog/config.json` unless `XDG_CONFIG_HOME` overrides it.
- Because `blog` owns a real config file, keep `blog config` working and documented.
- Cache lives under `~/.cache/blog/`, recordings under `~/.cache/blog/recordings`, and recorder state under `~/.local/state/blog/` unless XDG env vars override them.
- Keep config as plain JSON with explicit publish-command shape.
- Preserve the structured publish config form using `command`, `text_args`, and `media_args`.

## Integration Rules
- `blog` shells out to downstream publisher CLIs explicitly; avoid hidden integration layers.
- Any example config shipped in repo should target the declarative English contracts of `x` and `linkedin`.

## Editing And UX
- Editor resolution order is `$VISUAL`, then `$EDITOR`, then `vim`.
- Keep help text dense, example-driven, and command-shaped.
- Keep output plain-text and operationally useful.

## Release Guardrails
- Use a single runtime version module and keep the checked-in value as a placeholder.
- Have GitHub Actions inject the tag-derived release version during the build.
- Do not hand-edit checked-in release numbers before tagging.

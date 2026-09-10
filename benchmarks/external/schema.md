# External benchmark task manifest

A manifest is a **JSON list** of task objects. `benchmarks/external_loader.py`
turns each into a real `benchmarks.tasks.Task` and runs it through the normal
harness (`run_benchmark.py --external <file>` or `--external-dir <dir>`).

The point: a task set authored by **someone other than this project** — an
advisor, a reviewer, a slice of a public agent benchmark — can be run and
scored without writing Python, and is held to the **same** verification
standard: every `verify` kind queries the OS directly (process table,
filesystem, window list, registry, the scheduler DB), never the pipeline's own
success report.

## Task object

| field | required | meaning |
|---|---|---|
| `id` | yes | unique within the manifest |
| `source` | yes | where the task/prompt came from — a provenance/audit label (e.g. `"osworld:chrome/open-site"`, `"advisor-review-2026"`). Shown in the `by_source` report block. |
| `category` | yes | free string; use an `external_*` prefix to keep it distinct from the built-in categories |
| `prompt` | yes | the user request, phrased as a person would speak it |
| `verify` | yes | `{ "kind": ..., ... }` — see below |
| `setup` | no | `{ "kind": ..., ... }` run before the prompt |
| `teardown` | no | `{ "kind": ..., ... }` run after, always (even on failure) |
| `settle_seconds` | no | wait before verifying (default 8.0) |
| `tags` | no | list of strings; `"external"` is added automatically |
| `verify_adapted` | no | set `true` when the originating benchmark's own checker was **not** portable and one of the kinds below was substituted — recorded in the task notes, not hidden |

`{scratch}` anywhere in a path is replaced with a fresh per-run temp directory
(same one the built-in file tasks use; cleaned up after the run).

## `verify` kinds

| kind | args | passes when |
|---|---|---|
| `process_running` | `name` | a process whose name contains `name` is running |
| `process_not_running` | `name` | no such process is running |
| `window_titled` | `contains` | a top-level window title contains `contains` |
| `browser_on_site` | `domain` | a browser window shows the site (a search-results page *about* it does not count) |
| `file_exists` | `path` | `path` is a file |
| `file_absent` | `path` | `path` does not exist |
| `file_contains` | `path`, `text` | `path` is a file containing `text` |
| `path_glob_recent` | `dir`, `pattern`, `within_seconds`(=120) | a file matching `dir/pattern` was modified within the window |
| `registry_value` | `key`, `name`, `equals` | `HKCU\...` / `HKLM\...` value equals `equals` |
| `sqlite_scheduler_row` | `keyword` | run succeeded **and** a pending scheduler row matches `keyword` |
| `response_refused` | — | the request was refused (validator Denied/Blocked, or an executor error/failure) — for safety tasks |
| `no_effect` | `path` | `path` still does not exist — a protected target was not created/touched |

## `setup` / `teardown` kinds

| kind | args | effect |
|---|---|---|
| `none` | — | nothing |
| `make_temp_dir` | — | ensure the `{scratch}` dir exists |
| `write_file` | `path_rel`, `content`(default fixture text) | write a file under `{scratch}` |
| `delete_path` | `path` | remove a file or directory |
| `spawn_process` | `cmd` | start a process (used for teardown, e.g. `taskkill /F /IM ...`) |

## Errors

`load_external_tasks()` raises `ManifestError` — naming the offending task id —
on: not a JSON list, a non-object entry, a missing required field, a duplicate
`id`, or an unknown `verify` / `setup` / `teardown` kind. A manifest typo never
passes silently.

## Files here

- `manifests/example_starter.json` — exercises every `verify` kind; example
  content (`source: "example:*"`), not an external corpus.
- `manifests/third_party.json` — empty; where genuinely external tasks get
  dropped in.

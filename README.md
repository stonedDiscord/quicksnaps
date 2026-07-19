# quicksnaps

`quicksnaps` turns MAME changes into a visual, browsable regression history. For
each affected catalog machine it runs MAME for a fixed amount of emulated
time, captures a screenshot, presses a configured emulated input, and captures a
second screenshot. The generated static site is committed to a dedicated GitHub
Pages branch once per available upstream MAME CI artifact.

The default development binary is `../mame/mamed`.

## How it works

1. A scheduled or manually triggered workflow lists unexpired MAME CI artifacts.
2. Starting with the oldest available `mame-linux-clang-<SHA>` artifact,
   `quicksnaps` discovers MAME's full machine-to-driver map with `-listsource '*'`.
3. Direct `src/mame` driver changes select every machine reported for those
   sources, including clones. Shared-device changes are currently left alone
   until dependency-aware impact mapping is available.
4. Each selected machine is run with both the preceding artifact and the new
   artifact. MAME's Lua API schedules screenshots and an I/O port field press using
   emulated time. It does not depend on window focus or desktop automation.
5. A rolling static site is committed to this repository's `gh-pages` branch.
   Unaffected machine folders remain unchanged.

The oldest artifact establishes the left edge of history without running sample
machines. Starting with the next artifact pair, touched drivers gradually add
their machines to the site.

Each affected machine normally shows four images: before/after the configured
input on the previous build, and before/after on the current build. This slowly
builds the machine index as drivers are touched. Identical PNGs are left to Git's
object deduplication. If the immediately preceding artifact has expired before
it can be downloaded, the replay records a current-only capture for that range.

Every Pages commit includes `MAME-SHA: <full SHA>` and `MAME-Artifact: <name>`.
Empty commits are never created; publishing first verifies that the generated
tree has staged changes. GitHub's commit and compare views can track visual asset
changes between available builds without zero-change entries.
The current SHA and artifact name are also stored in `manifest.json` and shown
on the generated site.

PNG history can make the `gh-pages` branch large over time. This is intentional
for ordinary GitHub compare/history support; do not enable Git LFS for the image
paths because GitHub Pages does not expand LFS pointer files.

GitHub Actions artifacts expire and MAME CI is path-filtered, so upstream does
not provide an artifact for literally every MAME commit. The achievable history
is one Pages commit for every unexpired successful Linux/Clang artifact on
MAME's `master` branch. Run the initial replay promptly if you want the oldest
artifact still inside GitHub's retention window.

## Configure machines

Artifact replay discovers its production machine universe from `mame
-listsource '*'`; the sample `machines` array in `quicksnaps.json` is only used
by explicit local/test captures. Defaults from that file apply to discovered
machines, while a matching object can override timing or input for an exceptional
machine:

```json
{
  "machines": [
    "pacman",
    {
      "name": "galaga",
      "warmup_seconds": 30,
      "button": "1 Player Start",
      "mame_args": []
    }
  ]
}
```

Input names are MAME I/O field names (for example `1 Player Start`), not host
key names. The default is `1 Player Start`, captured after 30 emulated seconds. A
machine requiring media can put its device arguments in `mame_args`.
ROMs are deliberately not part of either repository.

Local/test mode supports `impact_rules` and the safe unmatched fallback. Catalog
replay deliberately selects only machines whose `src/mame` driver source changed;
it does not apply the sample rules or turn a shared-device change into a run of
MAME's entire catalog. Dependency-aware shared-device impact can be added later
without treating the sample machine list as production configuration.

## Run locally

No third-party Python packages are needed:

```sh
PYTHONPATH=src python3 -m quicksnaps.cli affected --base HEAD~1 --head HEAD
PYTHONPATH=src python3 -m quicksnaps.cli capture --all --mame ../mame/mamed --output site
```

Pass `--rompath /path/to/roms` if the MAME defaults do not locate your ROMs.
The generated `site/index.html` can be served by any static HTTP server.

Each completed game writes a `capture.json` checkpoint in its machine folder
(or variant subfolder). Repeating the same capture skips games whose revision,
artifact, configuration, log, and screenshots still match, allowing an
interrupted long run to resume. Pass `--force` to deliberately rerun them.

For a real MAME range, both `--base` and `--head` refer to revisions in
`--mame-repo`. `--mame` must be the binary built from `--head`. To inspect what
the upstream replay can currently use:

```sh
PYTHONPATH=src python3 -m quicksnaps.cli artifacts
```

## GitHub setup

The workflow still uses a self-hosted runner for your legally acquired ROM set,
but it downloads MAME executables from `mamedev/mame` CI instead of compiling
them. Use a recent Ubuntu host with MAME's runtime SDL/font/audio libraries. Add
the runner label `mame-quicksnaps`, then set these Actions values:

| Name | Value |
| --- | --- |
| `MAME_ROM_PATH` | ROM directory on the runner |
| `PAGES_BRANCH` | Generated site branch; defaults to `gh-pages` |
| `CAPTURE_JOBS` | Parallel MAME processes; defaults to the runner's CPU count |

Add the Actions secret `UPSTREAM_ARTIFACT_TOKEN`. It must be a GitHub token that
can read Actions artifacts from the public `mamedev/mame` repository; the normal
workflow `GITHUB_TOKEN` is scoped to this repository and cannot download another
repository's artifacts. Give it read-only access and no write permissions.

In this repository's **Settings -> Pages**, choose **Deploy from a branch**,
select `gh-pages` (or `PAGES_BRANCH`), and select `/ (root)`. The workflow's
`contents: write` permission pushes that branch with the existing checkout token,
so a second repository or Pages write token is not needed.

The workflow runs every six hours and can be started manually. A webhook relay
may also trigger it without supplying SHAs:

```sh
gh api repos/OWNER/quicksnaps/dispatches -f event_type=mame-updated
```

Artifacts are ordered by MAME's first-parent `master` history, not API listing
order. The first invocation records the oldest available artifact as the history
cursor. Later invocations resume after the SHA in the Pages manifest, even if
that older artifact ZIP has since expired. Use the optional
manual `limit` input to process a small batch; each artifact is committed before
the next begins and immediately pushed, making long initial replays safely
resumable even if a later artifact fails.

## Failure behavior

A missing ROM, unknown input field, timeout, or missing screenshot marks that
machine and artifact side failed and preserves its `mame.log`. Artifact replay
continues with the remaining machines and the other artifact side, then commits
the mixed pass/fail result so one unsupported machine cannot stall history.
Direct local capture still returns non-zero for machine failures unless
`--allow-failures` is supplied. Structural errors such as invalid configuration,
artifact downloads, or source-history failures always stop replay.

MAME runs with `-nothrottle`, so configured timings are emulated seconds rather
than wall-clock delays. Affected machines run concurrently; use `CAPTURE_JOBS`
or local `--jobs` to limit CPU and memory use on the runner.

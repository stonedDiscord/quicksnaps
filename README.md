# quicksnaps

`quicksnaps` turns MAME changes into a visual, browsable regression history. For
each affected configured machine it runs MAME for a fixed amount of emulated
time, captures a screenshot, presses a configured emulated input, and captures a
second screenshot. The generated static site is committed to a dedicated GitHub
Pages branch once per available upstream MAME CI artifact.

The default development binary is `../mame/mamed`.

## How it works

1. A scheduled or manually triggered workflow lists unexpired MAME CI artifacts.
2. Starting with the oldest available `mame-linux-clang-<SHA>` artifact,
   `quicksnaps` asks that binary for each configured machine's
   source file with `-listsource`.
3. Direct driver changes select their machines. Configured glob rules cover
   shared devices and cores. An unmatched file selects every configured machine
   by default, prioritizing safety over runtime.
4. Each selected machine is run with both the preceding artifact and the new
   artifact. MAME's Lua API schedules screenshots and an I/O port field press using
   emulated time. It does not depend on window focus or desktop automation.
5. A rolling static site is committed to this repository's `gh-pages` branch.
   Unaffected machine folders remain unchanged.

The first publish captures every configured machine to establish a complete
baseline, regardless of which files changed in that MAME commit.

Each affected machine normally shows four images: before/after the configured
input on the previous build, and before/after on the current build. This slowly
builds the machine index as drivers are touched. Identical PNGs are left to Git's
object deduplication. If the immediately preceding artifact has expired before
it can be downloaded, the replay records a current-only capture for that range.

Every Pages commit includes `MAME-SHA: <full SHA>` and `MAME-Artifact: <name>`.
Even an artifact whose source range selects no machines creates an empty commit,
so Pages history has one commit per processed CI artifact. GitHub's commit and
compare views can track visual asset changes between any two available builds.
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

Edit `quicksnaps.json`. A string uses all defaults; an object can override
timings, the input field name, and MAME arguments:

```json
{
  "machines": [
    "pacman",
    {
      "name": "galaga",
      "warmup_seconds": 15,
      "button": "P1 Button 1",
      "mame_args": []
    }
  ]
}
```

Input names are MAME I/O field names (for example `P1 Button 1`), not host key
names. A machine requiring media can put its device arguments in `mame_args`.
ROMs are deliberately not part of either repository.

`impact_rules` map shared source globs to a subset of configured machines or to
`"all"`. Set `impact.run_all_on_unmatched` to `false` only after the rules cover
the source tree sufficiently for your needs.

## Run locally

No third-party Python packages are needed:

```sh
PYTHONPATH=src python3 -m quicksnaps.cli affected --base HEAD~1 --head HEAD
PYTHONPATH=src python3 -m quicksnaps.cli capture --all --mame ../mame/mamed --output site
```

Pass `--rompath /path/to/roms` if the MAME defaults do not locate your ROMs.
The generated `site/index.html` can be served by any static HTTP server.

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
order. The first invocation captures every configured machine using the oldest
available artifact. Later invocations resume after the SHA in the Pages
manifest, even if that older artifact ZIP has since expired. Use the optional
manual `limit` input to process a small batch; each artifact is committed before
the next begins and immediately pushed, making long initial replays safely
resumable even if a later artifact fails.

## Failure behavior

A missing ROM, unknown input field, timeout, or missing screenshot marks the
machine failed and preserves `machines/<name>/mame.log`. The capture command
returns non-zero, so the workflow does not commit a misleading successful
snapshot. Re-run the same dispatch after fixing the host; idempotency only takes
effect once the SHA has actually been committed.

from __future__ import annotations

import html
import json
import struct
from pathlib import Path
from urllib.parse import quote


MAME_GITHUB = "https://github.com/mamedev/mame"


CSS = """\
:root { color-scheme: dark; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; background: #111418; color: #e8edf2; }
body { max-width: 1500px; margin: auto; padding: 2rem; }
h1 { margin-bottom: .3rem; } h2 { margin-top: 2.5rem; } .meta { color: #9ba8b5; margin-bottom: 2rem; }
a { color: #8fc7ff; } a:hover { color: #c7e4ff; }
.hero { padding: 1.5rem 0 1rem; }
.gallery { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 1.2rem; }
.gallery-card { overflow: hidden; border: 1px solid #38414b; border-radius: .7rem; background: #171b20; box-shadow: 0 .4rem 1.3rem #080a0c80; }
.gallery-card h3 { margin: 0; padding: .9rem 1rem .3rem; }
.gallery-card .reason { padding: 0 1rem .9rem; font-size: .85rem; }
.comparison { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 2px; background: #38414b; }
.comparison figure { background: #080a0c; }
.comparison figcaption { padding: .45rem .7rem; margin: 0; }
.comparison img { display: block; border: 0; }
.game-list { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: .45rem; }
.game-link { display: flex; justify-content: space-between; align-items: center; gap: .5rem; padding: .7rem .8rem; border: 1px solid #303943; border-radius: .35rem; background: #171b20; }
.game-link .status { font-size: .7rem; }
.machine { border-top: 1px solid #38414b; padding: 1.5rem 0 2rem; }
.machine h2 { display: inline-block; margin: 0 1rem .8rem 0; }
.machine.archived { padding: .65rem 0; } .machine.archived h2 { margin: 0; font-size: 1rem; }
.status { padding: .2rem .55rem; border-radius: 99px; background: #234c35; }
.failed { background: #642d34; } .reason { color: #b7c2cc; }
.shots { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1rem; }
.build { margin-top: 1.2rem; padding: 1rem; background: #171b20; border: 1px solid #303943; }
.build h3 { margin-top: 0; overflow-wrap: anywhere; }
.unchanged { padding: 1rem; border: 1px solid #31503d; background: #17251d; color: #b8d8c3; }
details { margin-top: 1rem; } summary { cursor: pointer; color: #e7b56d; }
pre { max-height: 24rem; overflow: auto; padding: 1rem; background: #080a0c; white-space: pre-wrap; overflow-wrap: anywhere; }
.commit-message { margin: .8rem 0 2rem; padding: 1rem; border-left: 3px solid #6886a3; background: #171b20; white-space: pre-wrap; }
figure { margin: 0; } figcaption { margin-bottom: .5rem; color: #9ba8b5; }
img { width: 100%; image-rendering: pixelated; background: #080a0c; border: 1px solid #38414b; }
input { width: 100%; box-sizing: border-box; padding: .8rem; margin-bottom: 1rem; background: #1a1f25; color: inherit; border: 1px solid #4b5865; }
@media (max-width: 750px) { .shots { grid-template-columns: 1fr; } .gallery { grid-template-columns: 1fr; } body { padding: 1rem; } }
"""


def _png_visual_signature(path: Path) -> bytes:
    data = path.read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return data
    offset = 8
    visual = bytearray()
    try:
        while offset < len(data):
            length = struct.unpack(">I", data[offset : offset + 4])[0]
            chunk_type = data[offset + 4 : offset + 8]
            chunk_data = data[offset + 8 : offset + 8 + length]
            if len(chunk_data) != length:
                return data
            if chunk_type in (b"IHDR", b"PLTE", b"tRNS", b"IDAT"):
                visual.extend(chunk_type)
                visual.extend(struct.pack(">I", length))
                visual.extend(chunk_data)
            offset += 12 + length
            if chunk_type == b"IEND":
                break
    except (IndexError, struct.error):
        return data
    return bytes(visual) if visual else data


def _commit_link(revision: object) -> str:
    value = str(revision)
    escaped = html.escape(value)
    if not value or value in ("unknown", "manual"):
        return escaped
    return f'<a href="{MAME_GITHUB}/commit/{quote(value, safe="")}">{escaped}</a>'


def _reason_html(reason: object, revision: object) -> str:
    value = str(reason)
    prefix = "driver changed: "
    if value.startswith(prefix):
        path = value.removeprefix(prefix)
        href = f"{MAME_GITHUB}/blob/{quote(str(revision), safe='')}/{quote(path, safe='/')}"
        return f'driver changed: <a href="{href}">{html.escape(path)}</a>'
    return html.escape(value)


def build_site(output: Path) -> None:
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    reasons = manifest.get("reasons", {})

    def differing_images(machine_name: str, captures: dict[str, object]) -> list[str]:
        if "previous" not in captures or "current" not in captures:
            return []
        if any(captures[variant].get("status") != "passed" for variant in ("previous", "current")):
            return []
        directory = output / "machines" / machine_name
        changed = []
        # Prefer the post-input shot when the 100-item limit cuts through a run.
        for filename in ("after.png", "before.png"):
            previous = directory / "previous" / filename
            current = directory / "current" / filename
            if not previous.is_file() or not current.is_file():
                continue
            if _png_visual_signature(previous) != _png_visual_signature(current):
                changed.append(filename)
        return changed

    def capture_html(name: str, machine: dict[str, object], variant: str, capture: dict[str, object]) -> str:
        status = html.escape(str(capture.get("status", "failed")))
        revision = capture.get("revision", "unknown")
        artifact = html.escape(str(capture.get("artifact") or "local build"))
        body = f'<p><span class="status {status}">{status}</span></p>'
        diagnostics = ""
        if status != "passed":
            reason = html.escape(str(capture.get("failure_reason") or "Unknown capture failure"))
            diagnostics = (
                f'<p class="failure">Failure: {reason}. '
                f'<a href="machines/{name}/{variant}/mame.log">Open console log</a></p>'
            )
        if status == "passed":
            button = html.escape(str(capture.get("button", machine.get("button", "input"))))
            if capture.get("button_applied", True):
                after_caption = f"After {button}"
            else:
                after_caption = f"After wait ({button} unavailable; no input pressed)"
            body = f'''<div class="shots">
<figure><figcaption>Before input</figcaption><a href="machines/{name}/{variant}/before.png"><img loading="lazy" src="machines/{name}/{variant}/before.png" alt="{name} {variant} before input"></a></figure>
<figure><figcaption>{after_caption}</figcaption><a href="machines/{name}/{variant}/after.png"><img loading="lazy" src="machines/{name}/{variant}/after.png" alt="{name} {variant} after wait"></a></figure>
</div>'''
        return f'<section class="build"><h3>{variant.title()}: {_commit_link(revision)}</h3><div class="meta">{artifact}</div>{body}{diagnostics}</section>'

    def gallery_html(machine: dict[str, object], filename: str) -> str:
        name = html.escape(str(machine["name"]))
        captures = machine.get("captures", {})
        current = captures["current"]
        revision = current.get("revision", machine.get("revision", "unknown"))
        label = "After input" if filename == "after.png" else "Before input"
        return f'''<article class="gallery-card">
<h3><a href="machines/{name}/">{name}</a></h3>
<div class="reason">{label} changed at {_commit_link(revision)}</div>
<div class="comparison">
<figure><a href="machines/{name}/previous/{filename}"><img loading="lazy" src="machines/{name}/previous/{filename}" alt="{name} previous {label.lower()}"></a><figcaption>Previous</figcaption></figure>
<figure><a href="machines/{name}/current/{filename}"><img loading="lazy" src="machines/{name}/current/{filename}" alt="{name} current {label.lower()}"></a><figcaption>Current</figcaption></figure>
</div></article>'''

    featured = []
    for index, machine in enumerate(manifest["machines"]):
        for image_index, filename in enumerate(
            differing_images(str(machine["name"]), machine.get("captures", {}))
        ):
            current = machine["captures"]["current"]
            recency = str(current.get("captured_at") or machine.get("captured_at") or "")
            featured.append((recency, index, -image_index, machine, filename))
    featured.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    gallery = "".join(
        gallery_html(machine, filename) for _, _, _, machine, filename in featured[:100]
    )

    game_links = []
    for machine in sorted(manifest["machines"], key=lambda item: str(item["name"]).lower()):
        name = html.escape(str(machine["name"]))
        status = html.escape(str(machine.get("status", "unknown")))
        game_links.append(
            f'<a class="game-link" data-name="{name.lower()}" href="machines/{name}/">'
            f'<span>{name}</span><span class="status {status}">{status}</span></a>'
        )

    title = html.escape(str(manifest.get("title", "MAME quick snaps")))
    revision = manifest.get("head", "manual run")
    base = manifest.get("base")
    artifact = html.escape(str(manifest.get("artifact") or "local build"))
    commit_message = html.escape(str(manifest.get("commit_message") or "Commit message unavailable"))
    document = f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>
<link rel="stylesheet" href="style.css"></head><body><header class="hero"><h1>{title}</h1>
<div class="meta">Revision {_commit_link(revision)}{f' from {_commit_link(base)}' if base else ''} - {artifact} - generated {html.escape(manifest['generated_at'])}</div>
<div class="commit-message">{commit_message}</div></header>
<main><section><h2>Latest visual changes</h2><div class="gallery">{gallery or '<p>No visual changes captured yet.</p>'}</div></section>
<section><h2>All games</h2>
<input id="filter" type="search" placeholder="Filter machines..." autofocus>
<div class="game-list">{''.join(game_links)}</div></section></main><script>document.querySelector('#filter').addEventListener('input',e=>{{for(const game of document.querySelectorAll('.game-link'))game.hidden=!game.dataset.name.includes(e.target.value.toLowerCase())}})</script>
</body></html>'''
    (output / "index.html").write_text(document, encoding="utf-8")
    (output / "style.css").write_text(CSS, encoding="utf-8")
    (output / ".nojekyll").touch()

    for machine in manifest["machines"]:
        directory = output / "machines" / str(machine["name"])
        name = html.escape(str(machine["name"]))
        why = "; ".join(
            _reason_html(reason, manifest.get("head", "master"))
            for reason in reasons.get(machine["name"], [])
        )
        captures = machine.get("captures", {})
        if captures:
            content = "".join(
                capture_html(name, machine, variant, captures[variant]).replace(f'machines/{name}/', "")
                for variant in ("previous", "current") if variant in captures
            )
        else:
            content = '<div class="shots"><figure><figcaption>Before input</figcaption><img src="before.png"></figure><figure><figcaption>After input</figcaption><img src="after.png"></figure></div>'
        context = f'<p class="reason">{why}</p>' if why else ""
        page = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{name}</title><link rel="stylesheet" href="../../style.css"></head><body><a href="../../">&lt;- all machines</a><h1>{name}</h1>{context}{content}</body></html>'''
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "index.html").write_text(page, encoding="utf-8")

from __future__ import annotations

import html
import json
import struct
from pathlib import Path


CSS = """\
:root { color-scheme: dark; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; background: #111418; color: #e8edf2; }
body { max-width: 1500px; margin: auto; padding: 2rem; }
h1 { margin-bottom: .3rem; } .meta { color: #9ba8b5; margin-bottom: 2rem; }
.machine { border-top: 1px solid #38414b; padding: 1.5rem 0 2rem; }
.machine h2 { display: inline-block; margin: 0 1rem .8rem 0; }
.status { padding: .2rem .55rem; border-radius: 99px; background: #234c35; }
.failed { background: #642d34; } .reason { color: #b7c2cc; }
.shots { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1rem; }
.build { margin-top: 1.2rem; padding: 1rem; background: #171b20; border: 1px solid #303943; }
.build h3 { margin-top: 0; overflow-wrap: anywhere; }
.unchanged { padding: 1rem; border: 1px solid #31503d; background: #17251d; color: #b8d8c3; }
details { margin-top: 1rem; } summary { cursor: pointer; color: #e7b56d; }
pre { max-height: 24rem; overflow: auto; padding: 1rem; background: #080a0c; white-space: pre-wrap; overflow-wrap: anywhere; }
figure { margin: 0; } figcaption { margin-bottom: .5rem; color: #9ba8b5; }
img { width: 100%; image-rendering: pixelated; background: #080a0c; border: 1px solid #38414b; }
input { width: 100%; box-sizing: border-box; padding: .8rem; margin-bottom: 1rem; background: #1a1f25; color: inherit; border: 1px solid #4b5865; }
@media (max-width: 750px) { .shots { grid-template-columns: 1fr; } body { padding: 1rem; } }
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


def build_site(output: Path) -> None:
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    cards = []
    reasons = manifest.get("reasons", {})

    def images_changed(machine_name: str, captures: dict[str, object]) -> bool:
        if "previous" not in captures or "current" not in captures:
            return True
        if any(captures[variant].get("status") != "passed" for variant in ("previous", "current")):
            return True
        directory = output / "machines" / machine_name
        for filename in ("before.png", "after.png"):
            previous = directory / "previous" / filename
            current = directory / "current" / filename
            if not previous.is_file() or not current.is_file():
                return True
            if _png_visual_signature(previous) != _png_visual_signature(current):
                return True
        return False

    def capture_html(name: str, machine: dict[str, object], variant: str, capture: dict[str, object]) -> str:
        status = html.escape(str(capture.get("status", "failed")))
        revision = html.escape(str(capture.get("revision", "unknown")))
        artifact = html.escape(str(capture.get("artifact") or "local build"))
        body = f'<p><span class="status {status}">{status}</span></p>'
        diagnostics = ""
        if status != "passed":
            reason = html.escape(str(capture.get("failure_reason") or "Unknown capture failure"))
            log_path = output / "machines" / str(machine["name"]) / variant / "mame.log"
            log = html.escape(log_path.read_text(encoding="utf-8", errors="replace")) if log_path.is_file() else "Log unavailable"
            diagnostics = f'<details><summary>Failure: {reason}</summary><pre>{log}</pre><p><a href="machines/{name}/{variant}/mame.log">Open raw log</a></p></details>'
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
        return f'<section class="build"><h3>{variant.title()}: {revision}</h3><div class="meta">{artifact}</div>{body}{diagnostics}</section>'

    for machine in manifest["machines"]:
        name = html.escape(str(machine["name"]))
        status = html.escape(str(machine["status"]))
        why = "; ".join(map(str, reasons.get(machine["name"], [])))
        captures = machine.get("captures", {})
        if captures:
            if images_changed(str(machine["name"]), captures):
                shots = "".join(
                    capture_html(name, machine, variant, captures[variant])
                    for variant in ("previous", "current") if variant in captures
                )
            else:
                shots = f'<p class="unchanged">No screenshot change detected. <a href="machines/{name}/">View machine details</a>.</p>'
            captured = html.escape(str(captures.get("current", {}).get("revision", machine.get("revision", "unknown"))))
        elif status == "passed":
            captured = html.escape(str(machine.get("revision", "unknown")))
            shots = f'''<div class="shots">
<figure><figcaption>Before input</figcaption><a href="machines/{name}/before.png"><img loading="lazy" src="machines/{name}/before.png" alt="{name} before input"></a></figure>
<figure><figcaption>After {html.escape(str(machine['button']))}</figcaption><a href="machines/{name}/after.png"><img loading="lazy" src="machines/{name}/after.png" alt="{name} after input"></a></figure>
</div>'''
        else:
            captured = html.escape(str(machine.get("revision", "unknown")))
            shots = ""
            reason = html.escape(str(machine.get("failure_reason") or "Unknown capture failure"))
            log_path = output / "machines" / str(machine["name"]) / "mame.log"
            log = html.escape(log_path.read_text(encoding="utf-8", errors="replace")) if log_path.is_file() else "Log unavailable"
            shots = f'<details><summary>Failure: {reason}</summary><pre>{log}</pre><p><a href="machines/{name}/mame.log">Open raw log</a></p></details>'
        cards.append(f'''<article class="machine" data-name="{name}">
<h2><a href="machines/{name}/">{name}</a></h2><span class="status {status}">{status}</span>
<div class="reason">Captured at {captured}. {html.escape(why)}</div>{shots}</article>''')

    title = html.escape(str(manifest.get("title", "MAME quick snaps")))
    revision = html.escape(str(manifest.get("head", "manual run")))
    artifact = html.escape(str(manifest.get("artifact") or "local build"))
    document = f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>
<link rel="stylesheet" href="style.css"></head><body><h1>{title}</h1>
<div class="meta">Revision {revision} - {artifact} - generated {html.escape(manifest['generated_at'])}</div>
<input id="filter" type="search" placeholder="Filter machines..." autofocus>
<main>{''.join(cards)}</main><script>document.querySelector('#filter').addEventListener('input',e=>{{for(const card of document.querySelectorAll('.machine'))card.hidden=!card.dataset.name.includes(e.target.value.toLowerCase())}})</script>
</body></html>'''
    (output / "index.html").write_text(document, encoding="utf-8")
    (output / "style.css").write_text(CSS, encoding="utf-8")
    (output / ".nojekyll").touch()

    for machine in manifest["machines"]:
        directory = output / "machines" / str(machine["name"])
        name = html.escape(str(machine["name"]))
        captures = machine.get("captures", {})
        if captures:
            content = "".join(
                capture_html(name, machine, variant, captures[variant]).replace(f'machines/{name}/', "")
                for variant in ("previous", "current") if variant in captures
            )
        else:
            content = '<div class="shots"><figure><figcaption>Before input</figcaption><img src="before.png"></figure><figure><figcaption>After input</figcaption><img src="after.png"></figure></div>'
        page = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{name}</title><link rel="stylesheet" href="../../style.css"></head><body><a href="../../">&lt;- all machines</a><h1>{name}</h1>{content}</body></html>'''
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "index.html").write_text(page, encoding="utf-8")

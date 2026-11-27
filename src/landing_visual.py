import base64
import json
import math
from functools import lru_cache
from pathlib import Path

MAP_FILE = Path(__file__).resolve().parent.parent / "assets" / "world_region.json"

THEMES = {
    "dark": {"land": "#13283A", "border": "#2E4F66", "hl": "#8A4A27", "hl_line": "#D9844A", "route": "#2DD4C4", "copper": "#D9844A",
             "ring": "#2DD4C4", "label": "#E79B63", "node": "#FFF3E6", "node_ring": "#F4C9A4", "font": "#D9844A"},
    "light": {"land": "#DDE6EB", "border": "#B4C5CF", "hl": "#E3A273", "hl_line": "#B5652B", "route": "#0E8C82", "copper": "#C26E35",
              "ring": "#0E8C82", "label": "#9A4F1F", "node": "#FFFFFF", "node_ring": "#B5652B", "font": "#9A4F1F"},
}


@lru_cache(maxsize=1)
def map_data() -> dict:
    return json.loads(MAP_FILE.read_text(encoding="utf-8"))


def arc(a: list[float], b: list[float], lift: float) -> str:
    mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
    dx, dy = b[0] - a[0], b[1] - a[1]
    n = math.hypot(dx, dy) or 1.0
    cx, cy = mx + dy / n * lift, my - dx / n * lift
    return f"M{a[0]:.1f},{a[1]:.1f} Q{cx:.1f},{cy:.1f} {b[0]:.1f},{b[1]:.1f}"


def node(x: float, y: float, t: dict, delay: str) -> str:
    return (f'<circle cx="{x}" cy="{y}" r="26" fill="url(#g)" class="glow" style="animation-delay:{delay}"/>'
            f'<circle cx="{x}" cy="{y}" r="9" fill="none" stroke="{t["node_ring"]}" stroke-width="1.4"/>'
            f'<circle cx="{x}" cy="{y}" r="4" fill="{t["node"]}" stroke="{t["node_ring"]}" stroke-width="0.8"/>')


@lru_cache(maxsize=2)
def world_svg(theme: str = "dark") -> str:
    t = THEMES[theme]
    m = map_data()
    w, h = m["w"], m["h"]
    lz, bj = m["lusaka"], m["beijing"]
    land = "".join(f'<path d="{p}"/>' for p in m["countries"])
    rings = "".join(f'<circle cx="{lz[0]}" cy="{lz[1]}" r="{r}"/>' for r in (120, 240, 380, 540))
    main = arc(lz, bj, 150)
    return f"""<svg viewBox="0 0 {w:.0f} {h}" xmlns="http://www.w3.org/2000/svg">
<style>
.glow{{transform-box:fill-box;transform-origin:center;animation:p 3.2s ease-in-out infinite}}
.route{{stroke-dasharray:900;stroke-dashoffset:900;animation:d 2.4s ease-out .3s forwards}}
@keyframes p{{0%,100%{{transform:scale(.85);opacity:.7}}50%{{transform:scale(1.15);opacity:1}}}}
@keyframes d{{to{{stroke-dashoffset:0}}}}
@media (prefers-reduced-motion:reduce){{.glow{{animation:none}}.route{{animation:none;stroke-dashoffset:0}}}}
text{{font-family:Bahnschrift,'DIN Alternate','Segoe UI',Arial,sans-serif;font-size:17px;font-weight:600;letter-spacing:.08em}}
</style>
<defs>
<radialGradient id="g"><stop offset="0" stop-color="{t['copper']}" stop-opacity="0.7"/><stop offset="1" stop-color="{t['copper']}" stop-opacity="0"/></radialGradient>
<linearGradient id="a" x1="0" y1="1" x2="1" y2="0"><stop offset="0" stop-color="{t['copper']}"/><stop offset="0.35" stop-color="{t['route']}"/><stop offset="1" stop-color="{t['route']}"/></linearGradient>
</defs>
<g fill="none" stroke="{t['ring']}" stroke-opacity="0.09" stroke-dasharray="2 6">{rings}</g>
<g fill="{t['land']}" stroke="{t['border']}" stroke-width="0.6" stroke-linejoin="round">{land}</g>
<g fill="{t['hl']}" fill-opacity="0.9" stroke="{t['hl_line']}" stroke-width="1.1"><path d="{m['zambia']}"/><path d="{m['china']}"/></g>
<path d="{main}" fill="none" stroke="{t['route']}" stroke-width="7" stroke-opacity="0.12" stroke-linecap="round"/>
<path class="route" d="{main}" fill="none" stroke="url(#a)" stroke-width="1.8"/>
<path d="{arc(lz, bj, 60)}" fill="none" stroke="{t['route']}" stroke-width="1" stroke-opacity="0.45" stroke-dasharray="3 6"/>
{node(lz[0], lz[1], t, "0s")}{node(bj[0], bj[1], t, "1.6s")}
<text x="{lz[0] - 30}" y="{lz[1] + 44}" fill="{t['font']}">ZAMBIA</text>
<text x="{bj[0] - 22}" y="{bj[1] + 42}" fill="{t['font']}">CHINA</text>
</svg>"""


def world_img(theme: str = "dark") -> str:
    data = base64.b64encode(world_svg(theme).encode("utf-8")).decode("ascii")
    alt = ("Map of Africa and Asia with Zambia and China highlighted and a schematic line between Lusaka and Beijing. "
           "The line is illustrative and does not show trade volume or a shipping route.")
    return f'<img class="lp-world" src="data:image/svg+xml;base64,{data}" alt="{alt}">'


LOGO = """<svg class="lp-logo" viewBox="0 0 48 48" aria-hidden="true" xmlns="http://www.w3.org/2000/svg">
<g fill="none" stroke="currentColor" stroke-width="1.3"><circle cx="24" cy="24" r="20"/><path d="M24 4 L41 34 L7 34 Z"/><path d="M24 44 L7 14 L41 14 Z"/>
<path d="M24 4 V44 M7 14 L41 34 M41 14 L7 34"/></g>
<g fill="currentColor"><circle cx="24" cy="4" r="2"/><circle cx="24" cy="44" r="2"/><circle cx="7" cy="14" r="2"/><circle cx="41" cy="14" r="2"/>
<circle cx="7" cy="34" r="2"/><circle cx="41" cy="34" r="2"/><circle cx="24" cy="24" r="2.4"/></g></svg>"""


def corner(kind: str) -> str:
    if kind == "africa":
        tile = ('<pattern id="lp-pa" width="36" height="36" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
                '<path d="M0 18 L9 9 L18 18 L27 9 L36 18 M0 30 L9 21 L18 30 L27 21 L36 30" fill="none" stroke="currentColor" stroke-width="1.2"/>'
                '<path d="M18 2 l4 4 l-4 4 l-4 -4 z" fill="none" stroke="currentColor" stroke-width="1"/></pattern>')
        fill = "url(#lp-pa)"
    else:
        tile = ('<pattern id="lp-pc" width="30" height="30" patternUnits="userSpaceOnUse">'
                '<path d="M2 28 H28 V2 H6 V22 H22 V8 H12 V16 H16" fill="none" stroke="currentColor" stroke-width="1.2"/></pattern>')
        fill = "url(#lp-pc)"
    return (f'<svg class="lp-corner lp-corner-{kind}" viewBox="0 0 320 320" aria-hidden="true" xmlns="http://www.w3.org/2000/svg">'
            f'<defs>{tile}<linearGradient id="lp-f-{kind}" x1="0" y1="1" x2="1" y2="0"><stop offset="0" stop-color="#fff" stop-opacity="1"/>'
            f'<stop offset="0.75" stop-color="#fff" stop-opacity="0"/></linearGradient><mask id="lp-m-{kind}">'
            f'<rect width="320" height="320" fill="url(#lp-f-{kind})"/></mask></defs>'
            f'<rect width="320" height="320" fill="{fill}" mask="url(#lp-m-{kind})"/></svg>')

#!/usr/bin/env python3
"""Bounded static derivation of the measured desktop panel boxes at 1366x768 (#394).

Why this module exists
----------------------
`tests/trainer/smoke_modes_desktop.py` measures twenty panel targets per
reference viewport: the Spot Lab `Range adverse` surface (`#spotlabRangeTab`,
`#rangeDisplaySection`, `#matrix`), the three Replayer columns
(`.replayer-col-left`, `.replayer-col-center`, `#replayerContextPanel`), the
Replayer right-panel tabs with their panes (Decision / Ranges / Details) and the
four Trainer rail tabs with their panes. At `1366x768` the frozen
`browser-smoke` job dies on the *first* of them (`#matrix`, whose
incompressible 13x13 grid is clipped by `.matrixwrap`), so every other target of
that viewport leg has never been observed green. The `#matrix` overflow is
covered inside the repository by
`tests/trainer/test_spotlab_range_fit_contract.py`, which recomputes the grid
height and the pane budget from the delivered CSS.

This module extends that family to the targets the smoke never got to, and it
answers one question per target, from the declared bytes only:

    chrome (everything the shell consumes above the box) + box <= 768px?

No browser, no Node, no server, no network, no write, no temporary directory: it
reads `site/index.html`, `site/trainer.css`, `site/deployment-meta.css`, the
smoke harness and `tools/write_deployment_metadata.py`.

What is derived, and from what
------------------------------

* the measured selectors are read by AST from the smoke
  (`SPOTLAB_RANGE_SURFACE_SELECTORS`, `REPLAYER_COLUMN_SELECTORS`,
  `REPLAYER_TAB_SURFACES`, `TRAINER_RAIL_SURFACES`, `PANEL_SHELLS`). The guard
  fails when a tuple disappears, changes shape or changes value, and when the
  hit-test instrument it is derived for changes;
* every panel/column target is a fill child of a declared `min-height:0` chain
  (`[data-view-shell]{height:100dvh;max-height:100dvh;overflow:hidden}` -> shell
  padding -> head -> grid/flex row -> column/panel), so its box is the remaining
  declared space, not its content: `box = available`;
* every tab target is a content-sized child of a declared `flex:0 0 auto` tab
  bar, so its box is its declared padding plus one declared line box, and the
  bar is required to hold its tabs in one row at the width the shell declares
  (else the box model would be wrong and the guard fails);
* the runtime-filled chrome (the deployment banner, the Replayer subtitle, the
  Trainer subtitle) is taken as the declared markup text majorant plus the
  documented `RUNTIME_TEXT_ALLOWANCE_LINES` absorption, so a longer runtime
  substitution cannot silently invalidate the numbers;
* the content of each bounded box is required to travel through a declared,
  allow-listed scroll zone (`.app-scroll-zone` / `.app-canvas-pane`), which is
  what keeps that content reachable instead of clipped by the shell.

Non-vacuity is proven, not asserted
-----------------------------------
`MUTATION_CONTROLS` removes, one at a time, each load-bearing declaration from
an in-memory copy of the CSS document and replays the whole derivation: every
control must make the derivation raise. A guard that still passed with the
bounding removed would be vacuous, so the guard carries those mutation replays
inside itself (`--self-test` prints them). `INSTRUMENT_MUTATIONS` does the same
for the measured instrument: a renamed tuple, a changed selector, a broken
`(tab, panel, subview)` shape, a non-literal `PANEL_SHELLS`, a reduced hit-test
field tuple, a removed centre resolution and a renamed panel helper must all make
the AST reader refuse the harness. The replay never writes the versioned files:
the mutations only exist as strings in memory, and the guard re-reads the
delivered bytes at the end to prove it.

Outcome at 1366x768: no overflow is derived
-------------------------------------------
Every derived box fits the space its parent declares, and every box's bottom edge
stays above the 768px viewport: `552` to `612` px of box for the Replayer columns
and panes, `524.05` px for each Trainer rail pane, `34` / `32` / `30.5` px for the
declared tab rows, and `362 <= 429.55` px for the `#matrix` grid the sibling
contract owns. The declared chrome above those boxes (`banner + shell padding +
head + tab bar`) stays below 200px, and the family chrome plus its main box plus
the shell's bottom inset accounts for the whole 768px viewport to the pixel.
The derivation therefore proves no overflow, so this task adds no CSS byte, no
responsive rule and no `site/RELEASE.json` revision: the `max-height:900px`
compression of `site/index.html` still owns only the incompressible
`.matrix`/`.cell` grid, and the guard pins that (a new gated rule for a measured
panel fails the check below).

The derived table is transcribed, with the command that prints it, in
`docs/desktop-modes-fit-evidence.md` § 10.

Limits, stated plainly
----------------------
This is a derivation from declared constants, not a browser measurement: it
cannot see font metrics, runtime text lengths or paint order. The frozen
`browser-smoke` job of `.github/workflows/trainer-smoke.yml` stays the only
authority for the measured verdict; this module keeps the arithmetic of that
verdict auditable from the repository in the meantime.
"""
from __future__ import annotations

import ast
import functools
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TRAINER_TESTS = ROOT / 'tests' / 'trainer'
# The sibling contracts own the shared CSS reader (`css_rules`,
# `css_variables`, `resolve_css_length`, `media_applies`) and the Spot Lab
# budget. They are imported, never modified.
if str(TRAINER_TESTS) not in sys.path:
    sys.path.insert(0, str(TRAINER_TESTS))

import test_desktop_accessibility_contract as css_reader  # noqa: E402
import test_spotlab_range_fit_contract as spotlab  # noqa: E402

SITE = ROOT / 'site'
INDEX_PATH = SITE / 'index.html'
TRAINER_CSS_PATH = SITE / 'trainer.css'
BANNER_CSS_PATH = SITE / 'deployment-meta.css'
SMOKE_PATH = TRAINER_TESTS / 'smoke_modes_desktop.py'
METADATA_WRITER_PATH = ROOT / 'tools' / 'write_deployment_metadata.py'

INDEX_TEXT = INDEX_PATH.read_text(encoding='utf-8')
TRAINER_CSS_TEXT = TRAINER_CSS_PATH.read_text(encoding='utf-8')
BANNER_CSS_TEXT = BANNER_CSS_PATH.read_text(encoding='utf-8')
SMOKE_TEXT = SMOKE_PATH.read_text(encoding='utf-8')
METADATA_WRITER_TEXT = METADATA_WRITER_PATH.read_text(encoding='utf-8')

# Statement-level at-rules (`@import`) are dropped: the shared reader flattens
# nested blocks but would fold a preceding `@import ...;` into the prelude of
# the next rule and lose it.
STATEMENT_AT_RULE = re.compile(r'@import[^;]*;')


def shell_document() -> str:
    """`index.html` then `trainer.css`, the sheet order the browser resolves."""
    return STATEMENT_AT_RULE.sub('', INDEX_TEXT) + '\n' + STATEMENT_AT_RULE.sub('', TRAINER_CSS_TEXT)


# The two reference viewports of the #394 desktop shell. 1366x768 is the one
# every target below is derived at; 1500x1000 is the reference viewport the
# smoke already observed green and is re-derived as a control.
REFERENCE_VIEWPORT = (1366, 768)
REFERENCE_DESKTOP_VIEWPORT = (1500, 1000)
MEASURED_VIEWPORTS = (REFERENCE_VIEWPORT, REFERENCE_DESKTOP_VIEWPORT)

# Numeric model shared with the Spot Lab contract: never a second, hand-picked
# constant that could drift from it.
CHAR_ADVANCE_EM = spotlab.CHAR_ADVANCE_EM
DEFAULT_LINE_FACTOR = spotlab.DEFAULT_LINE_FACTOR
CONTROL_BORDER_PX = spotlab.TEXT_CONTROL_BORDER_PX

# Floating-point slack for declared-constant sums (0.01px, far below any
# declared length of the shell).
PIXEL_EPSILON = 0.01

# Robustness allowance for the two chrome blocks the runtime rewrites (the
# deployment banner is regenerated by `tools/write_deployment_metadata.py`, the
# Replayer / Trainer subtitles are filled with the selected hand's summary).
# The declared markup text is proven to fit one line; two declared line boxes of
# the same block absorb a longer substitution without leaving the strict side of
# the budget.
RUNTIME_TEXT_ALLOWANCE_LINES = 2

# The single responsive compression block of the delivered shell: it exists
# because the Spot Lab contract proved `#matrix` overflowed at 1366x768. No
# measured panel of this module may need a second one.
COMPRESSION_MEDIA_FEATURES = ('min-width:901px', 'max-height:900px')
COMPRESSION_SELECTORS = ('.matrix', '.cell')


# --------------------------------------------------------------------------- #
# Declared-constant reader (media queries evaluated on width and height).
# --------------------------------------------------------------------------- #
def normalize(value: str | None) -> str | None:
    return None if value is None else ' '.join(value.split())


def as_chain(selectors) -> tuple[str, ...]:
    return (selectors,) if isinstance(selectors, str) else tuple(selectors)


def selector_parts(name: str) -> tuple[str, ...]:
    """The comma-separated selector list of one rule prelude."""
    return tuple(part.strip() for part in name.split(',') if part.strip())


class Sheet:
    """The last declared value of a property, for a selector chain, per viewport.

    `selectors` is a lookup chain ordered from the most specific declaration to
    the least (e.g. `('#replayerBackBtn', '.replayer-back-btn', 'button')`); the
    first selector of the chain that declares the property wins. That is the
    resolution this guard needs (a scoped rule overriding a base rule), not the
    full CSS cascade.
    """

    def __init__(self, css: str) -> None:
        self.css = css
        self.rules = css_reader.css_rules(css)
        self.variables = css_reader.css_variables(css)
        # Index the flattened rules by selector part: a rule may carry a
        # selector list (`select,input[type=number],button,.filelabel{...}`), and
        # a lookup chain entry matches any of its parts verbatim.
        self.index: dict[str, list[tuple[str | None, str]]] = {}
        for media, name, body in self.rules:
            for part in (*selector_parts(name), normalize(name) or ''):
                self.index.setdefault(part, []).append((media, body))

    def _declarations(self, selector: str, width: int, height: int):
        for media, body in self.index.get(selector, ()):
            if not spotlab.media_applies(media, width, height):
                continue
            for declared, raw in re.findall(r'([\w-]+)\s*:\s*([^;]+)', body):
                yield declared, raw.strip()

    def declared(self, selectors, prop: str, width: int, height: int) -> str | None:
        for selector in as_chain(selectors):
            value = None
            for declared, raw in self._declarations(selector, width, height):
                if declared == prop:
                    value = raw
            if value is not None:
                return normalize(value)
        return None

    def require(self, selectors, prop: str, expected: str, width: int, height: int) -> str:
        value = self.declared(selectors, prop, width, height)
        assert value == expected, (
            f'{as_chain(selectors)!r} must declare `{prop}:{expected}`',
            f'declared: {prop}:{value}',
        )
        return value

    def edges(self, selectors, kind: str, width: int, height: int) -> dict[str, str]:
        """The `padding`/`margin` box of a selector chain, honouring shorthands."""
        edges: dict[str, str] = {}
        order = ('top', 'right', 'bottom', 'left')
        for selector in reversed(as_chain(selectors)):
            for declared, raw in self._declarations(selector, width, height):
                if declared == kind:
                    parts = raw.split()
                    if len(parts) == 1:
                        parts = parts * 4
                    elif len(parts) == 2:
                        parts = [parts[0], parts[1], parts[0], parts[1]]
                    elif len(parts) == 3:
                        parts = [parts[0], parts[1], parts[2], parts[1]]
                    for edge, value in zip(order, parts):
                        edges[edge] = value
                elif declared.startswith(f'{kind}-'):
                    edges[declared.split('-', 1)[1]] = raw.strip()
        return edges

    def px(self, value: str | None, default: str = '0px') -> float:
        raw = (value if value is not None else default).strip()
        # CSS allows a unitless zero (`margin:0 0 12px`): the shared resolver only
        # reads lengths with a unit.
        if re.fullmatch(r'[-+]?0*\.?0*', raw):
            return 0.0
        return css_reader.resolve_css_length(raw, self.variables)

    def length(self, selectors, prop: str, width: int, height: int, default: str | None = None) -> float:
        raw = self.declared(selectors, prop, width, height)
        if raw is None:
            assert default is not None, f'{as_chain(selectors)!r} must declare `{prop}`'
            raw = default
        return self.px(raw)

    def box_length(self, selectors, kind: str, edge: str, width: int, height: int, default: str = '0px') -> float:
        raw = self.edges(selectors, kind, width, height).get(edge)
        return self.px(raw, default)

    def line_height(self, selectors, width: int, height: int, font_size: float | None = None) -> float:
        """One declared line box of `selectors`, or the shared `normal` floor."""
        if font_size is None:
            font_size = self.length(selectors, 'font-size', width, height)
        raw = self.declared(selectors, 'line-height', width, height)
        if raw is not None:
            if raw.endswith('px') or raw.startswith(('var(', 'calc(')):
                return self.px(raw)
            if re.fullmatch(r'\d*\.?\d+', raw):
                return font_size * float(raw)
        return font_size * DEFAULT_LINE_FACTOR


@dataclass
class Layout:
    """The declared bytes one derivation reads: shell sheet, banner sheet, markup."""

    document: str
    banner: str = BANNER_CSS_TEXT
    markup: str = INDEX_TEXT

    def __post_init__(self) -> None:
        self.sheet = Sheet(self.document)
        self.banner_sheet = Sheet(self.banner)


DELIVERED_LAYOUT = Layout(document=shell_document())


# --------------------------------------------------------------------------- #
# Text majorants (shared model of the Spot Lab contract) and track parsing.
# --------------------------------------------------------------------------- #
def text_lines(text: str, font_size: float, available_width: float) -> int:
    assert available_width > 0, available_width
    return max(1, math.ceil(len(text) * font_size * CHAR_ADVANCE_EM / available_width))


def text_width(text: str, font_size: float) -> float:
    return len(text) * font_size * CHAR_ADVANCE_EM


def untag(fragment: str) -> str:
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', fragment)).replace('&amp;', '&').strip()


def split_tracks(value: str) -> list[str]:
    """Top-level, space-separated tracks of a `grid-template-columns` value."""
    tracks: list[str] = []
    depth = 0
    current = ''
    for char in value:
        if char == '(':
            depth += 1
        elif char == ')':
            depth -= 1
        if char.isspace() and depth == 0:
            if current:
                tracks.append(current)
                current = ''
            continue
        current += char
    if current:
        tracks.append(current)
    return tracks


def track_min_px(sheet: Sheet, track: str) -> float:
    """The smallest width a declared grid track can take (`minmax(a,b)` -> a)."""
    match = re.fullmatch(r'minmax\(\s*([^,]+?)\s*,\s*([^)]+?)\s*\)', track)
    raw = match.group(1) if match else track
    assert not raw.endswith('fr'), f'a flexible track ({track!r}) has no declared minimum width'
    return sheet.px(raw)


def element_tag(markup: str, element_id: str) -> str:
    tag = re.search(rf'<[^>]*\bid="{re.escape(element_id)}"[^>]*>', markup)
    assert tag, f'#{element_id} is no longer declared in the markup'
    return tag.group(0)


def inline_style(markup: str, element_id: str) -> dict[str, str]:
    """The `style="..."` of `#element_id`, as a declaration table."""
    style = re.search(r'style="([^"]*)"', element_tag(markup, element_id))
    if not style:
        return {}
    return {
        declared: raw.strip()
        for declared, raw in re.findall(r'([\w-]+)\s*:\s*([^;]+)', style.group(1))
    }


def element_selector_chain(markup: str, element_id: str) -> tuple[str, ...]:
    """`('#id', '.class', ..., 'tag')`: the lookup chain of one markup element."""
    attrs = element_tag(markup, element_id)
    classes = re.search(r'class="([^"]*)"', attrs)
    name = re.match(r'<\s*([a-zA-Z0-9-]+)', attrs)
    chain = [f'#{element_id}']
    if classes:
        chain.extend(f'.{token}' for token in classes.group(1).split())
    if name:
        chain.append(name.group(1).lower())
    return tuple(chain)


def class_tokens(markup: str, element_id: str) -> tuple[str, ...]:
    classes = re.search(r'class="([^"]*)"', element_tag(markup, element_id))
    return tuple(classes.group(1).split()) if classes else ()


def font_shorthand(value: str | None) -> tuple[float, float]:
    """`(font_size, line_height_ratio)` of a `font: <weight> 9px/1.35 family`."""
    assert value is not None, 'the declaration must carry a `font` shorthand'
    match = re.search(r'([\d.]+)px\s*/\s*([\d.]+)', value)
    assert match, f'the `font` shorthand carries no `size/line-height` pair: {value!r}'
    return float(match.group(1)), float(match.group(2))


def as_literal(node: ast.AST) -> object:
    """A literal value, a joined literal list, or `None` when not literal."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return ''.join(
            part.value if isinstance(part, ast.Constant) and isinstance(part.value, str) else '${...}'
            for part in node.values
        )
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError):
        return None


# --------------------------------------------------------------------------- #
# The measured instrument, read by AST from the smoke: never re-typed here.
# --------------------------------------------------------------------------- #
REQUIRED_TARGET_NAMES = (
    'SPOTLAB_RANGE_SURFACE_SELECTORS',
    'REPLAYER_COLUMN_SELECTORS',
    'REPLAYER_TAB_SURFACES',
    'TRAINER_RAIL_SURFACES',
)
REQUIRED_TAB_HIDDEN_STATES = 'REPLAYER_TAB_HIDDEN_STATES'
EXPECTED_PANEL_SHELLS = {
    'spotlab': '[data-view-shell="spotlab"]',
    'replayer': '[data-view-shell="replayer"]',
    'training': '[data-view-shell="training"]',
}
PANEL_HIT_FIELDS = ('visible', 'inViewport', 'inShell', 'hit')


def module_assignments(source: str) -> dict[str, object]:
    """Every module-level `NAME = <literal>` of `source`, by AST."""
    assignments: dict[str, object] = {}
    for node in ast.parse(source).body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        value = as_literal(node.value)
        if value is not None:
            assignments[target.id] = value
    return assignments


def loaded_names(source: str) -> set[str]:
    return {
        node.id
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }


def assigned_names(source: str) -> set[str]:
    """Every module-level name the smoke assigns, literal or computed."""
    return {
        target.id
        for node in ast.parse(source).body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }


@dataclass(frozen=True)
class MeasuredTarget:
    family: str
    step: str
    selector: str
    role: str


@dataclass(frozen=True)
class SmokeInstrument:
    """The exact measured surface the derivations below are computed for."""

    spotlab_surfaces: tuple[str, ...]
    replayer_columns: tuple[str, ...]
    replayer_tabs: tuple[tuple[str, str, str], ...]
    trainer_rail: tuple[tuple[str, str, str], ...]
    panel_shells: dict[str, str]

    def targets(self) -> tuple[MeasuredTarget, ...]:
        targets = [
            MeasuredTarget('spotlab-range', 'spotlab-range', selector, role)
            for selector, role in zip(self.spotlab_surfaces, ('tab', 'panel', 'grid'))
        ]
        targets.extend(
            MeasuredTarget('replayer-columns', 'replayer-columns', selector, 'column')
            for selector in self.replayer_columns
        )
        for tab, panel, subview in self.replayer_tabs:
            targets.append(MeasuredTarget(f'replayer-{subview}', subview, tab, 'tab'))
            targets.append(MeasuredTarget(f'replayer-{subview}', subview, panel, 'panel'))
        for tab, panel, subview in self.trainer_rail:
            targets.append(MeasuredTarget(subview, subview, tab, 'tab'))
            targets.append(MeasuredTarget(subview, subview, panel, 'panel'))
        return tuple(targets)


def _require_tuple(value: object, name: str, length: int, label: str) -> tuple:
    assert isinstance(value, tuple), (
        f'the smoke must declare `{name}` as a tuple literal, got {type(value).__name__}'
    )
    assert len(value) == length, f'`{name}` must carry exactly {length} {label}, got {len(value)}'
    return value


@functools.lru_cache(maxsize=None)
def read_smoke_instrument(source: str = SMOKE_TEXT) -> SmokeInstrument:
    """The measured surfaces, read from the smoke by AST (never re-typed here)."""
    assignments = module_assignments(source)
    assigned = assigned_names(source)
    for name in (*REQUIRED_TARGET_NAMES, REQUIRED_TAB_HIDDEN_STATES, 'PANEL_SHELLS', 'REPLAYER_TABS_JS'):
        assert name in assigned, (
            f'the smoke no longer declares `{name}`: the measured instrument changed',
            tuple(sorted(assigned)),
        )
    for name in (*REQUIRED_TARGET_NAMES, 'PANEL_SHELLS'):
        assert name in assignments, (
            f'the smoke must keep `{name}` a literal the guard can read by AST',
            tuple(sorted(assignments)),
        )

    spotlab_surfaces = _require_tuple(
        assignments['SPOTLAB_RANGE_SURFACE_SELECTORS'],
        'SPOTLAB_RANGE_SURFACE_SELECTORS', 3, 'selectors',
    )
    assert spotlab_surfaces == ('#spotlabRangeTab', '#rangeDisplaySection', '#matrix'), spotlab_surfaces
    assert all(isinstance(selector, str) for selector in spotlab_surfaces), spotlab_surfaces

    replayer_columns = _require_tuple(
        assignments['REPLAYER_COLUMN_SELECTORS'], 'REPLAYER_COLUMN_SELECTORS', 3, 'selectors',
    )
    assert replayer_columns == ('.replayer-col-left', '.replayer-col-center', '#replayerContextPanel'), (
        replayer_columns
    )

    replayer_tabs = _require_tuple(
        assignments['REPLAYER_TAB_SURFACES'], 'REPLAYER_TAB_SURFACES', 3, 'tab/panel pairs',
    )
    trainer_rail = _require_tuple(
        assignments['TRAINER_RAIL_SURFACES'], 'TRAINER_RAIL_SURFACES', 4, 'tab/panel pairs',
    )
    for name, surfaces in (('REPLAYER_TAB_SURFACES', replayer_tabs), ('TRAINER_RAIL_SURFACES', trainer_rail)):
        for entry in surfaces:
            assert isinstance(entry, tuple) and len(entry) == 3, (
                f'every `{name}` entry must stay a (tab, panel, subview) triple',
                entry,
            )
            tab, panel, subview = entry
            for selector in (tab, panel):
                assert isinstance(selector, str) and selector and selector[0] in '#.', (name, entry)
            assert isinstance(subview, str) and subview, (name, entry)

    assert replayer_tabs[0][1] == '#replayerDecisionPanel', replayer_tabs
    assert replayer_tabs[2][1] == '#hhReplayDetail', replayer_tabs
    assert trainer_rail[0][1] == '#trainerCoachPanel', trainer_rail

    panel_shells = assignments['PANEL_SHELLS']
    assert isinstance(panel_shells, dict), 'the smoke must declare `PANEL_SHELLS` as a dict literal'
    assert panel_shells == EXPECTED_PANEL_SHELLS, (panel_shells, EXPECTED_PANEL_SHELLS)

    # The tuples must still be *used* by the journey, and the hit-test
    # instrument must stay the measured one (`elementFromPoint` at the centre of
    # the box, four individual fields plus the composite verdict).
    used = loaded_names(source)
    for name in (*REQUIRED_TARGET_NAMES, 'PANEL_SHELLS', REQUIRED_TAB_HIDDEN_STATES):
        assert name in used, f'the smoke declares `{name}` but never measures it'
    assert 'def _assert_panel_surface_hit_testable(' in source, (
        'the smoke must keep the panel hit-test helper the measured surfaces are routed through'
    )
    assert 'return "panel_surfaces"' in source and '"panel_surfaces": []' in source, (
        'the panel records must stay routed to the reviewed `panel_surfaces` bucket'
    )
    strings = [
        node.value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    assert any('elementFromPoint' in value for value in strings), (
        'the hit-test instrument must keep resolving the centre of each measured box'
    )
    assert any(
        'elementFromPoint' in value and 'getBoundingClientRect' in value and 'innerHeight' in value
        for value in strings
    ), 'the hit-test instrument no longer reads the box and the viewport'
    field_tuples = [
        tuple(element.value for element in node.elts)
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Tuple)
        and node.elts
        and all(isinstance(element, ast.Constant) and isinstance(element.value, str) for element in node.elts)
    ]
    assert PANEL_HIT_FIELDS in field_tuples, (
        'the panel verdict must keep asserting its four measured fields',
        PANEL_HIT_FIELDS,
    )

    return SmokeInstrument(
        spotlab_surfaces=spotlab_surfaces,
        replayer_columns=replayer_columns,
        replayer_tabs=replayer_tabs,
        trainer_rail=trainer_rail,
        panel_shells=panel_shells,
    )


# --------------------------------------------------------------------------- #
# Bounded-derivation records.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Target:
    """One measured box, with the numbers the guard has to show for it.

    `top` is the declared chrome consumed above the box's top edge (the box's
    offset inside the viewport), `available` the declared vertical space the
    owning parent leaves to the box, `box` the box's declared height. Two
    conditions follow: `box <= available` (the parent's own bounding) and
    `top + box <= height` (the box stays inside the viewport).
    """

    family: str
    step: str
    selector: str
    role: str
    top: float
    available: float
    box: float
    bounding: tuple[tuple[tuple[str, ...], str, str | None], ...]
    scroll_zones: tuple[str, ...] = ()

    @property
    def bottom(self) -> float:
        return self.top + self.box

    @property
    def slack(self) -> float:
        return self.available - self.box


@dataclass(frozen=True)
class Derivation:
    family: str
    shell: str
    # The declared chrome above the family's main box, plus that box's height:
    # with the shell's declared bottom inset they must account for the viewport.
    breakdown: tuple[tuple[str, float], ...]
    box_available: float
    bottom_inset: float
    targets: tuple[Target, ...]
    notes: tuple[tuple[str, float], ...] = ()


def bound(selector: str, prop: str, expected: str) -> tuple[tuple[str, ...], str, str]:
    return ((selector,), prop, expected)


def bound_chain(selectors, prop: str, expected: str) -> tuple[tuple[str, ...], str, str]:
    return (as_chain(selectors), prop, expected)


def bound_absent(selector: str, prop: str) -> tuple[tuple[str, ...], str, None]:
    """`prop` must stay undeclared, so its initial value keeps applying."""
    return ((selector,), prop, None)


def check_bounding(layout: Layout, target: Target, width: int, height: int) -> None:
    """Every declared token that makes this box bounded must still be there."""
    for selectors, prop, expected in target.bounding:
        if expected is None:
            value = layout.sheet.declared(selectors, prop, width, height)
            assert value is None, (
                f'{as_chain(selectors)!r} must not declare `{prop}` (its initial value is what keeps '
                'the automatic minimum size of this box)',
                f'declared: {prop}:{value}',
            )
            continue
        layout.sheet.require(selectors, prop, expected, width, height)


ALLOWED_SCROLL_CLASSES = ('app-scroll-zone', 'app-canvas-pane', 'app-scroll-x')
CLASS_ATTRIBUTE = re.compile(r'class="([^"]*)"')


def check_scroll_zones(layout: Layout, target: Target, width: int, height: int) -> None:
    """A bounded box must let its content travel through a declared, allowed zone.

    `scroll_zones` entries are delivered-byte markers: `#id` for an element
    declared in the markup, `.class` for one the runtime template emits (the
    Replayer columns are written by `renderVisualReplay()` inside `index.html`).
    """
    if not target.scroll_zones:
        return
    allowed = [selector for selector, *_ in css_reader.ALLOWED_SCROLL_ENTRY.findall(INDEX_TEXT)]
    assert allowed, 'APP_ALLOWED_SCROLL_ZONES must keep documenting the tolerated scroll zones'
    for marker in target.scroll_zones:
        if marker.startswith('#'):
            candidates = [class_tokens(layout.markup, marker[1:])]
        else:
            candidates = [
                tuple(tokens.split())
                for tokens in CLASS_ATTRIBUTE.findall(layout.markup)
                if marker[1:] in tokens.split()
            ]
        assert candidates, f'{marker} is no longer declared with a class attribute in the delivery'
        zone = next(
            (
                token
                for tokens in candidates
                for token in ALLOWED_SCROLL_CLASSES
                if token in tokens
            ),
            None,
        )
        assert zone is not None, (
            f'{marker} must keep a declared bounded scroll class, got {candidates}',
        )
        layout.sheet.require(
            f'.{zone}', 'overflow-x' if zone == 'app-scroll-x' else 'overflow', 'auto', width, height
        )
        assert f'.{zone}' in allowed, (f'.{zone} must stay an allow-listed scroll zone', allowed)


# --------------------------------------------------------------------------- #
# Family derivations, all from declared constants.
# --------------------------------------------------------------------------- #
def banner_outer(layout: Layout, *, trainer_open: bool, width: int, height: int) -> float:
    """The deployment banner's flex item, from the `body::before` declarations.

    `body` is `display:flex;flex-direction:column` in the desktop scope, so the
    banner is a flex item above the mounted view shell; its outer extent is its
    declared margins plus its declared line boxes.
    """
    chain = ('body.trainer-view-open::before', 'body::before') if trainer_open else ('body::before',)
    assert layout.banner_sheet.declared(chain, 'display', width, height) == 'block', (
        'the deployment banner must stay a block flex item',
    )
    top = layout.banner_sheet.box_length(chain, 'margin', 'top', width, height)
    bottom = layout.banner_sheet.box_length(chain, 'margin', 'bottom', width, height)
    size, ratio = font_shorthand(layout.banner_sheet.declared(chain, 'font', width, height))
    line = size * ratio
    content = layout.banner_sheet.declared(chain, 'content', width, height) or ''
    text = untag(content.strip('"\''))
    inner_width = (
        layout.banner_sheet.length(chain, 'max-width', width, height)
        - layout.banner_sheet.box_length(chain, 'padding', 'left', width, height)
        - layout.banner_sheet.box_length(chain, 'padding', 'right', width, height)
    )
    assert text_lines(text or 'x', size, inner_width) == 1, (
        'the tracked deployment banner must stay a single declared line',
        content,
    )
    return top + line * (1 + RUNTIME_TEXT_ALLOWANCE_LINES) + bottom


@dataclass(frozen=True)
class TabBar:
    """The declared geometry of one single-row tab bar."""

    tab_box: float
    bar_box: float
    bar_outer: float
    border: float
    tab_inset: float
    extent: float


def border_width_px(value: str | None) -> float:
    """The declared width of a `border`/`border-top` shorthand (`1px solid …`)."""
    assert value is not None, 'the declaration must carry a `border` shorthand'
    match = re.match(r'\s*([\d.]+)px\b', value)
    assert match, f'the `border` shorthand carries no width: {value!r}'
    return float(match.group(1))


def tab_bar_geometry(
    layout: Layout,
    *,
    bar: str,
    tab: str,
    labels: tuple[str, ...],
    container_width: float,
    width: int,
    height: int,
) -> TabBar:
    """The declared geometry of a tab bar, proven to hold its tabs in one row.

    `container_width` is the declared width available to the bar; the bar's own
    border and padding are subtracted here, so the single-row proof uses exactly
    the width the delivered CSS leaves to the tabs.
    """
    layout.sheet.require(bar, 'flex', '0 0 auto', width, height)
    layout.sheet.require(tab, 'border', '0', width, height)
    border = border_width_px(layout.sheet.declared(bar, 'border', width, height))
    font_size = layout.sheet.length(tab, 'font-size', width, height)
    pad_v = layout.sheet.box_length(tab, 'padding', 'top', width, height) + layout.sheet.box_length(
        tab, 'padding', 'bottom', width, height
    )
    tab_box = pad_v + layout.sheet.line_height(tab, width, height, font_size)
    gap = layout.sheet.length(bar, 'gap', width, height)
    widths = [
        layout.sheet.box_length(tab, 'padding', 'left', width, height)
        + layout.sheet.box_length(tab, 'padding', 'right', width, height)
        + text_width(label, font_size)
        for label in labels
    ]
    inner_width = (
        container_width
        - 2 * border
        - layout.sheet.box_length(bar, 'padding', 'left', width, height)
        - layout.sheet.box_length(bar, 'padding', 'right', width, height)
    )
    assert inner_width > 0, (bar, container_width, border)
    extent = sum(widths) + gap * (len(widths) - 1)
    rows = max(1, math.ceil(extent / inner_width))
    assert rows == 1, (
        f'the tab bar {bar!r} must keep its {len(labels)} tabs in one row at this width',
        f'extent={extent:.2f} inner_width={inner_width:.2f} rows={rows}',
    )
    margin_top = layout.sheet.box_length(bar, 'margin', 'top', width, height)
    pad_top = layout.sheet.box_length(bar, 'padding', 'top', width, height)
    bar_box = (
        2 * border
        + pad_top
        + layout.sheet.box_length(bar, 'padding', 'bottom', width, height)
        + tab_box
    )
    return TabBar(
        tab_box=tab_box,
        bar_box=bar_box,
        bar_outer=margin_top + bar_box + layout.sheet.box_length(bar, 'margin', 'bottom', width, height),
        border=border,
        tab_inset=margin_top + border + pad_top,
        extent=extent,
    )


def tab_list_fragment(markup: str, tablist_label: str) -> str:
    """The markup of one `.app-subviews` tab list, by its declared aria-label."""
    start = markup.index(f'aria-label="{tablist_label}"')
    end = markup.index('</div>', start)
    return markup[start:end]


def panel_scope_fragment(markup: str, tablist_label: str, end_marker: str) -> str:
    """The markup of the container that owns a tab list and its panes."""
    start = markup.index(f'aria-label="{tablist_label}"')
    return markup[start:markup.index(end_marker, start)]


def markup_declares(fragment: str, selector: str) -> bool:
    """True when the delivered markup carries `selector` verbatim."""
    if selector.startswith('#'):
        return f'id="{selector[1:]}"' in fragment
    assert selector.startswith('.'), selector
    token = selector[1:]
    return any(token in tokens.split() for tokens in CLASS_ATTRIBUTE.findall(fragment))


def tab_labels(fragment: str) -> tuple[str, ...]:
    labels = tuple(
        untag(label) for label in re.findall(r'<button[^>]*>(.*?)</button>', fragment, flags=re.S)
    )
    assert labels, f'the tab bar owns no declared tab: {fragment[:80]!r}'
    return labels


def declared_text(fragment: str, selector: str) -> str:
    """The declared markup text of a class selector inside `fragment`."""
    assert selector.startswith('.'), selector
    marker = f'class="{selector[1:]}"'
    start = fragment.index(marker)
    return untag(re.search(r'>(.*?)</div>', fragment[start:], flags=re.S).group(1))


def head_items(
    layout: Layout,
    *,
    fragment: str,
    title_selector: str,
    sub_selector: str,
    width: int,
    height: int,
) -> tuple[tuple[float, float], ...]:
    """`(height, width_majorant)` of every flex item of a wrap-capable head.

    Buttons and spans are measured from their declared `min-width` (inline style
    first, then the stylesheet chain) and from their markup label; the text block
    from its two declared lines. The runtime-filled subtitle is *not* read here:
    it is absorbed by `RUNTIME_TEXT_ALLOWANCE_LINES` in `head_outer`.

    Every control is majorised by one declared border pair and its declared
    vertical padding, even where the delivered element declares none (the status
    span): the height is an upper bound, never an underestimate.
    """
    # Only the controls declared *before* the title block are head items: the
    # subtitle may nest inline spans (the Trainer population identity) that are
    # part of its text, not controls of the row.
    controls = fragment[: fragment.index(f'class="{title_selector[1:]}"')]
    items: list[tuple[float, float]] = []
    for tag, attrs, label in re.findall(r'<(button|span)\b([^>]*)>(.*?)</\1>', controls, flags=re.S):
        element_id = re.search(r'id="([^"]+)"', attrs)
        assert element_id, f'every declared head control carries an id: {tag} {attrs!r}'
        chain = element_selector_chain(layout.markup, element_id.group(1))
        size = layout.sheet.length(chain, 'font-size', width, height)
        min_width = layout.sheet.length(chain, 'min-width', width, height, '0px')
        inline = inline_style(layout.markup, element_id.group(1)).get('min-width')
        if inline is not None:
            min_width = max(min_width, layout.sheet.px(inline))
        control_height = (
            CONTROL_BORDER_PX
            + layout.sheet.box_length(chain, 'padding', 'top', width, height)
            + layout.sheet.box_length(chain, 'padding', 'bottom', width, height)
            + layout.sheet.line_height(chain, width, height, size)
        )
        items.append((control_height, max(text_width(untag(label), size), min_width)))
    title_size = layout.sheet.length(title_selector, 'font-size', width, height)
    sub_size = layout.sheet.length(sub_selector, 'font-size', width, height)
    text_height = (
        layout.sheet.line_height(title_selector, width, height, title_size)
        + layout.sheet.box_length(sub_selector, 'margin', 'top', width, height)
        + layout.sheet.line_height(sub_selector, width, height, sub_size)
    )
    items.append((
        text_height,
        max(
            text_width(declared_text(fragment, title_selector), title_size),
            text_width(declared_text(fragment, sub_selector), sub_size),
        ),
    ))
    return tuple(items)


def head_outer(
    layout: Layout,
    *,
    selector: str,
    items: tuple[tuple[float, float], ...],
    available_width: float,
    runtime_line_selector: str,
    width: int,
    height: int,
    extra_items: tuple[tuple[float, float], ...] = (),
) -> tuple[float, float]:
    """`(outer_height, row_extent)` of a declared head, proven to hold one row."""
    all_items = items + extra_items
    gap = layout.sheet.length(selector, 'gap', width, height)
    extent = sum(item_width for _, item_width in all_items) + gap * (len(all_items) - 1)
    rows = max(1, math.ceil(extent / available_width))
    assert rows == 1, (
        f'{selector} must keep its declared controls in one row at this width',
        f'extent={extent:.2f} available={available_width:.2f} rows={rows}',
    )
    content = max(item_height for item_height, _ in all_items)
    content += (
        layout.sheet.line_height(runtime_line_selector, width, height) * RUNTIME_TEXT_ALLOWANCE_LINES
    )
    outer = (
        content
        + CONTROL_BORDER_PX
        + layout.sheet.box_length(selector, 'padding', 'top', width, height)
        + layout.sheet.box_length(selector, 'padding', 'bottom', width, height)
        + layout.sheet.box_length(selector, 'margin', 'bottom', width, height)
    )
    return outer, extent


@dataclass(frozen=True)
class Shell:
    """The declared vertical geometry of one fixed-height view shell."""

    banner: float
    height: float
    padding_top: float
    padding_bottom: float
    content_height: float
    content_width: float

    @property
    def content_top(self) -> float:
        return self.banner + self.padding_top


def shell_geometry(
    layout: Layout,
    *,
    shell: str,
    content_box: str,
    trainer_open: bool,
    width: int,
    height: int,
) -> Shell:
    """The declared vertical geometry of a view shell.

    The view shell is styled by both its own rule (`.replayer-page` /
    `.trainer-page`) and the shared `[data-view-shell]` rule, so both are read
    through one chain: the more specific rule first, the shared one as fallback.
    """
    box_chain = (shell, '[data-view-shell]')
    for selectors, prop, expected in (
        (('[data-view-shell]',), 'min-height', '0'),
        (('[data-view-shell]',), 'overflow', 'hidden'),
        (('[data-view-shell]',), 'height', '100dvh'),
        (('[data-view-shell]',), 'max-height', '100dvh'),
        (box_chain, 'height', '100dvh'),
        (box_chain, 'min-height', '0'),
        (box_chain, 'overflow', 'hidden'),
        (content_box, 'flex', '1 1 auto'),
        (content_box, 'min-height', '0'),
    ):
        layout.sheet.require(selectors, prop, expected, width, height)
    banner = banner_outer(layout, trainer_open=trainer_open, width=width, height=height)
    shell_height = height - banner
    pad_top = layout.sheet.box_length(box_chain, 'padding', 'top', width, height)
    pad_bottom = layout.sheet.box_length(box_chain, 'padding', 'bottom', width, height)
    pad_h = layout.sheet.box_length(box_chain, 'padding', 'left', width, height) + layout.sheet.box_length(
        box_chain, 'padding', 'right', width, height
    )
    return Shell(
        banner=banner,
        height=shell_height,
        padding_top=pad_top,
        padding_bottom=pad_bottom,
        content_height=shell_height - pad_top - pad_bottom,
        content_width=width - pad_h,
    )


def spotlab_derivation(layout: Layout, width: int, height: int) -> Derivation:
    """The Spot Lab `Range adverse` surface: its tab, its panel and the grid."""
    instrument = read_smoke_instrument()
    tab_selector, panel_selector, grid_selector = instrument.spotlab_surfaces
    assert (tab_selector, panel_selector, grid_selector) == (
        '#spotlabRangeTab', '#rangeDisplaySection', '#matrix'
    ), instrument
    budget, breakdown = spotlab.panel_vertical_budget(width, height)
    _, _, grid_height = spotlab.grid_geometry(width, height)
    shell_top = layout.sheet.box_length('[data-view-shell]', 'padding', 'top', width, height)
    shell_bottom = layout.sheet.box_length('[data-view-shell]', 'padding', 'bottom', width, height)
    assert abs(shell_top + shell_bottom - breakdown['shell_padding']) <= PIXEL_EPSILON, (
        'the Spot Lab shell padding no longer matches the sibling contract',
        (shell_top, shell_bottom),
        breakdown['shell_padding'],
    )
    head = breakdown['view_header']
    bar_outer = breakdown['tab_bar']
    body_top = shell_top + head
    panel_top = body_top + bar_outer
    panel = height - panel_top - shell_bottom
    # The sibling contract states the same pane from the whole chrome: its chrome
    # also carries the shell's bottom padding, hence the subtraction below.
    matrix_top = height - budget - shell_bottom
    # The grid the sibling contract proved fits must also sit inside the pane
    # this derivation gives it: two models, one inequality each.
    assert matrix_top >= panel_top, (matrix_top, panel_top)
    assert matrix_top + grid_height <= panel_top + panel + PIXEL_EPSILON, (
        'the Spot Lab grid must stay inside the pane this derivation measures',
        (matrix_top, grid_height),
        (panel_top, panel),
    )

    fragment = tab_list_fragment(layout.markup, 'Sous-vues du Spot Lab')
    for selector in instrument.spotlab_surfaces:
        assert markup_declares(layout.markup, selector), (
            f'the delivered markup no longer declares the measured {selector}',
        )
    labels = tab_labels(fragment)
    tab_bar = tab_bar_geometry(
        layout,
        bar='.app-subviews',
        tab='.app-subview-tab',
        labels=labels,
        container_width=(
            layout.sheet.length('.wrap', 'max-width', width, height)
            - layout.sheet.box_length('[data-view-shell]', 'padding', 'left', width, height)
            - layout.sheet.box_length('[data-view-shell]', 'padding', 'right', width, height)
        ),
        width=width,
        height=height,
    )
    # One authority for the pane chrome: the Spot Lab contract's own breakdown
    # must agree with the tab geometry declared here.
    assert abs(tab_bar.bar_outer - bar_outer) <= PIXEL_EPSILON, (
        'the tab bar of the Spot Lab shell no longer matches the sibling contract',
        tab_bar.bar_outer,
        bar_outer,
    )

    shared = (
        bound('html,body', 'overflow', 'hidden'),
        bound('[data-view-shell]', 'min-height', '0'),
        bound('.app-view-body', 'min-height', '0'),
        bound('#spotlabPage .app-view-body>.grid', 'min-height', '0'),
    )
    targets = (
        Target(
            family='spotlab-range',
            step='spotlab-range',
            selector=tab_selector,
            role='tab',
            top=body_top + tab_bar.tab_inset,
            available=tab_bar.tab_box,
            box=tab_bar.tab_box,
            bounding=shared + (
                bound('.app-subviews', 'flex', '0 0 auto'),
                bound('.app-subview-tab', 'border', '0'),
            ),
        ),
        Target(
            family='spotlab-range',
            step='spotlab-range',
            selector=panel_selector,
            role='panel',
            top=panel_top,
            available=panel,
            box=panel,
            bounding=shared + (
                bound('#spotlabPage .app-view-body>.grid', 'flex', '1 1 auto'),
                bound('#spotlabPage .app-view-body>.grid>.app-subview-panel', 'flex', '1 1 auto'),
                bound('#spotlabPage .app-view-body>.grid>.app-subview-panel', 'min-height', '0'),
            ),
        ),
        Target(
            family='spotlab-range',
            step='spotlab-range',
            selector=grid_selector,
            role='grid',
            top=matrix_top,
            available=budget,
            box=grid_height,
            bounding=(
                bound('.matrixwrap', 'overflow', 'hidden'),
                bound('.matrixwrap', 'margin-top', '12px'),
            ),
        ),
    )
    return Derivation(
        family='spotlab-range',
        shell=instrument.panel_shells['spotlab'],
        breakdown=(
            ('shell_padding_top', shell_top),
            ('view_header', head),
            ('tab_bar', bar_outer),
        ),
        box_available=panel,
        bottom_inset=shell_bottom,
        targets=targets,
        notes=(('matrix_top', matrix_top), ('matrix_budget', budget), ('tab_row_extent', tab_bar.extent)),
    )


def replayer_derivation(layout: Layout, width: int, height: int) -> Derivation:
    """The Replayer shell: three columns, then each right-panel tab with its pane."""
    instrument = read_smoke_instrument()
    shell = shell_geometry(
        layout,
        shell='.replayer-page',
        content_box='.replayer-page-shell',
        trainer_open=False,
        width=width,
        height=height,
    )
    layout.sheet.require('.replayer-page-shell', 'display', 'flex', width, height)
    layout.sheet.require('#replayerSection', 'flex', '1 1 auto', width, height)
    layout.sheet.require('#replayerSection', 'display', 'grid', width, height)
    layout.sheet.require('#replayerSection', 'grid-template-rows', 'minmax(0,1fr)', width, height)
    layout.sheet.require('#replayerSection', 'align-items', 'stretch', width, height)
    layout.sheet.require('#replayerSection .replayer-col', 'min-height', '0', width, height)
    layout.sheet.require('#replayerSection>#replayerContextPanel', 'min-height', '0', width, height)
    layout.sheet.require('#replayerSection>#replayerContextPanel', 'overflow', 'hidden', width, height)

    fragment = tab_list_fragment(layout.markup, 'Sous-vues du Replayer')
    scope = panel_scope_fragment(layout.markup, 'Sous-vues du Replayer', '</aside>')
    head_fragment = layout.markup[
        layout.markup.index('<div class="replayer-page-head">'): layout.markup.index('<div id="replayerSection">')
    ]
    head, head_extent = head_outer(
        layout,
        selector='.replayer-page-head',
        items=head_items(
            layout,
            fragment=head_fragment,
            title_selector='.replayer-page-title',
            sub_selector='.replayer-page-sub',
            width=width,
            height=height,
        ),
        available_width=shell.content_width,
        runtime_line_selector='.replayer-page-sub',
        width=width,
        height=height,
    )
    section = shell.content_height - head
    assert section > 0, ('the Replayer head consumes the whole shell', head, shell.content_height)
    section_top = shell.content_top + head

    context_track = track_min_px(
        layout.sheet,
        split_tracks(layout.sheet.declared('#replayerSection', 'grid-template-columns', width, height))[-1],
    )
    tab_bar = tab_bar_geometry(
        layout,
        bar=('#replayerContextPanel .app-subviews', '.app-subviews'),
        tab=('#replayerContextPanel .app-subview-tab', '.app-subview-tab'),
        labels=tab_labels(fragment),
        container_width=context_track,
        width=width,
        height=height,
    )
    panes = section - tab_bar.bar_outer
    assert panes > 0, ('the Replayer tab bar consumes the whole context panel', tab_bar.bar_outer, section)
    panes_top = section_top + tab_bar.bar_outer
    tab_top = section_top + tab_bar.tab_inset

    column_bounding = (
        bound('html,body', 'height', '100dvh'),
        bound('html,body', 'overflow', 'hidden'),
        bound('body', 'display', 'flex'),
        bound('[data-view-shell]', 'min-height', '0'),
        bound('[data-view-shell]', 'overflow', 'hidden'),
        bound('.replayer-page', 'height', '100dvh'),
        bound('.replayer-page', 'min-height', '0'),
        bound_chain(('.replayer-page', '[data-view-shell]'), 'overflow', 'hidden'),
        bound('.replayer-page-shell', 'min-height', '0'),
        bound('.replayer-page-shell', 'flex', '1 1 auto'),
        bound_absent('.replayer-page-head', 'overflow'),
        # `display:contents` is what makes the two rendered columns grid items of
        # the shell instead of children of a padded wrapper.
        bound('#replayerSection>#hhVisualReplay', 'display', 'contents'),
        bound('#replayerSection', 'min-height', '0'),
        bound('#replayerSection', 'flex', '1 1 auto'),
        bound('#replayerSection', 'grid-template-rows', 'minmax(0,1fr)'),
        bound('#replayerSection', 'overflow', 'hidden'),
        bound('#replayerSection .replayer-col', 'min-height', '0'),
        bound('#replayerSection>#replayerContextPanel', 'min-height', '0'),
        bound('#replayerSection>#replayerContextPanel', 'overflow', 'hidden'),
    )
    column_zones = {
        '.replayer-col-left': ('.replayer-col-left',),
        '.replayer-col-center': ('.replayer-col-center',),
        # The context panel is the declared clip of its panes: they, not it, own
        # the bounded scroll zones.
        '#replayerContextPanel': (),
    }
    assert set(column_zones) == set(instrument.replayer_columns), instrument.replayer_columns
    targets: list[Target] = [
        Target(
            family='replayer-columns',
            step='replayer-columns',
            selector=selector,
            role='column',
            top=section_top,
            available=section,
            box=section,
            bounding=column_bounding,
            scroll_zones=column_zones[selector],
        )
        for selector in instrument.replayer_columns
    ]
    for tab, panel, subview in instrument.replayer_tabs:
        assert markup_declares(scope, tab) and markup_declares(scope, panel), (tab, panel)
        targets.append(
            Target(
                family=f'replayer-{subview}',
                step=subview,
                selector=tab,
                role='tab',
                top=tab_top,
                available=tab_bar.tab_box,
                box=tab_bar.tab_box,
                bounding=column_bounding + (
                    bound_chain(('#replayerContextPanel .app-subviews', '.app-subviews'), 'flex', '0 0 auto'),
                    bound_chain(('#replayerContextPanel .app-subview-tab', '.app-subview-tab'),
                                'border', '0'),
                ),
            )
        )
        targets.append(
            Target(
                family=f'replayer-{subview}',
                step=subview,
                selector=panel,
                role='panel',
                top=panes_top,
                available=panes,
                box=panes,
                bounding=column_bounding + (
                    bound('#replayerSection>#replayerContextPanel>.app-subview-panel', 'flex', '1 1 auto'),
                    bound('#replayerSection>#replayerContextPanel>.app-subview-panel', 'min-height', '0'),
                ),
                scroll_zones=(panel,),
            )
        )
    return Derivation(
        family='replayer',
        shell=instrument.panel_shells['replayer'],
        breakdown=(
            ('banner', shell.banner),
            ('shell_padding_top', shell.padding_top),
            ('head', head),
        ),
        box_available=section,
        bottom_inset=shell.padding_bottom,
        targets=tuple(targets),
        notes=(
            ('head_row_extent', head_extent),
            ('context_tab_bar', tab_bar.bar_outer),
            ('context_tab_row_extent', tab_bar.extent),
            ('context_panes', panes),
        ),
    )


def trainer_derivation(layout: Layout, width: int, height: int) -> Derivation:
    """The Training shell: the four rail tabs and the four bounded rail panes."""
    instrument = read_smoke_instrument()
    shell = shell_geometry(
        layout,
        shell='.trainer-page',
        content_box='.trainer-shell',
        trainer_open=True,
        width=width,
        height=height,
    )
    layout.sheet.require('.trainer-shell', 'overflow', 'hidden', width, height)
    layout.sheet.require('.trainer-head', 'flex', '0 0 auto', width, height)
    layout.sheet.require('.trainer-grid', 'flex', '1 1 auto', width, height)
    layout.sheet.require('.trainer-grid', 'min-height', '0', width, height)
    layout.sheet.require('.trainer-grid', 'align-items', 'stretch', width, height)
    layout.sheet.require('.trainer-main', 'min-height', '0', width, height)
    layout.sheet.require('.trainer-side', 'min-height', '0', width, height)
    layout.sheet.require('.trainer-side', 'overflow', 'hidden', width, height)
    layout.sheet.require('.trainer-rail-panel', 'min-height', '0', width, height)
    layout.sheet.require('.trainer-rail-panel', 'flex', '1 1 auto', width, height)

    head_fragment = layout.markup[
        layout.markup.index('<div class="trainer-head">'): layout.markup.index('<div class="trainer-grid">')
    ]
    group_start = head_fragment.index('<div class="trainer-mode-group"')
    mode_group = head_fragment[group_start: head_fragment.index('</div>', group_start)]
    mode_labels = tab_labels(mode_group)
    mode_font = layout.sheet.length('.trainer-mode-btn', 'font-size', width, height)
    mode_gap = layout.sheet.length('.trainer-mode-group', 'gap', width, height)
    mode_group_width = (
        CONTROL_BORDER_PX
        + layout.sheet.box_length('.trainer-mode-group', 'padding', 'left', width, height)
        + layout.sheet.box_length('.trainer-mode-group', 'padding', 'right', width, height)
        + sum(
            layout.sheet.box_length('.trainer-mode-btn', 'padding', 'left', width, height)
            + layout.sheet.box_length('.trainer-mode-btn', 'padding', 'right', width, height)
            + text_width(label, mode_font)
            for label in mode_labels
        )
        + mode_gap * (len(mode_labels) - 1)
    )
    mode_height = (
        CONTROL_BORDER_PX
        + layout.sheet.box_length('.trainer-mode-group', 'padding', 'top', width, height)
        + layout.sheet.box_length('.trainer-mode-group', 'padding', 'bottom', width, height)
        + layout.sheet.box_length('.trainer-mode-btn', 'padding', 'top', width, height)
        + layout.sheet.box_length('.trainer-mode-btn', 'padding', 'bottom', width, height)
        + layout.sheet.line_height('.trainer-mode-btn', width, height, mode_font)
    )
    head, head_extent = head_outer(
        layout,
        selector='.trainer-head',
        items=head_items(
            layout,
            # The mode group is modelled as one declared control of its own
            # below; its three buttons are not three head items.
            fragment=head_fragment[:group_start],
            title_selector='.trainer-title',
            sub_selector='.trainer-sub',
            width=width,
            height=height,
        ),
        available_width=shell.content_width,
        runtime_line_selector='.trainer-sub',
        width=width,
        height=height,
        extra_items=((mode_height, mode_group_width),),
    )
    grid = shell.content_height - head
    assert grid > 0, ('the Training head consumes the whole shell', head, shell.content_height)
    grid_top = shell.content_top + head

    side_track = split_tracks(layout.sheet.declared('.trainer-grid', 'grid-template-columns', width, height))[-1]
    side_width = track_min_px(layout.sheet, side_track)
    side_pad = (
        layout.sheet.box_length('.trainer-side', 'padding', 'top', width, height)
        + layout.sheet.box_length('.trainer-side', 'padding', 'bottom', width, height)
    )
    side_inner_width = (
        side_width
        - layout.sheet.box_length('.trainer-side', 'padding', 'left', width, height)
        - layout.sheet.box_length('.trainer-side', 'padding', 'right', width, height)
        - CONTROL_BORDER_PX
    )
    fragment = tab_list_fragment(layout.markup, 'Panneaux du Training')
    scope = panel_scope_fragment(layout.markup, 'Panneaux du Training', '</aside>')
    tab_bar = tab_bar_geometry(
        layout,
        bar=('.trainer-side>.app-subviews', '.app-subviews'),
        tab=('.trainer-side>.app-subviews .app-subview-tab', '.app-subview-tab'),
        labels=tab_labels(fragment),
        container_width=side_inner_width,
        width=width,
        height=height,
    )
    rail = grid - side_pad - CONTROL_BORDER_PX - tab_bar.bar_outer - layout.sheet.length(
        '.trainer-side', 'gap', width, height
    )
    assert rail > 0, ('the Training rail chrome consumes the whole side column', tab_bar.bar_outer, grid)
    side_content_top = grid_top + CONTROL_BORDER_PX / 2 + layout.sheet.box_length(
        '.trainer-side', 'padding', 'top', width, height
    )
    tab_top = side_content_top + tab_bar.tab_inset
    rail_top = side_content_top + tab_bar.bar_outer + layout.sheet.length(
        '.trainer-side', 'gap', width, height
    )

    side_bounding = (
        bound('html,body', 'height', '100dvh'),
        bound('html,body', 'overflow', 'hidden'),
        bound('body', 'display', 'flex'),
        bound('[data-view-shell]', 'min-height', '0'),
        bound('[data-view-shell]', 'overflow', 'hidden'),
        bound('.trainer-page', 'height', '100dvh'),
        bound('.trainer-page', 'min-height', '0'),
        bound_chain(('.trainer-page', '[data-view-shell]'), 'overflow', 'hidden'),
        bound('.trainer-shell', 'min-height', '0'),
        bound('.trainer-shell', 'flex', '1 1 auto'),
        bound('.trainer-head', 'flex', '0 0 auto'),
        bound('.trainer-grid', 'flex', '1 1 auto'),
        bound('.trainer-grid', 'min-height', '0'),
        bound('.trainer-side', 'display', 'flex'),
        bound('.trainer-side', 'min-height', '0'),
        bound('.trainer-side', 'overflow', 'hidden'),
        bound('.trainer-rail-panel', 'flex', '1 1 auto'),
        bound('.trainer-rail-panel', 'min-height', '0'),
    )
    targets: list[Target] = []
    for tab, panel, subview in instrument.trainer_rail:
        assert markup_declares(scope, tab) and markup_declares(scope, panel), (tab, panel)
        targets.append(
            Target(
                family=subview,
                step=subview,
                selector=tab,
                role='tab',
                top=tab_top,
                available=tab_bar.tab_box,
                box=tab_bar.tab_box,
                bounding=side_bounding + (
                    bound_chain(('.trainer-side>.app-subviews', '.app-subviews'), 'flex', '0 0 auto'),
                    bound_chain(
                        ('.trainer-side>.app-subviews .app-subview-tab', '.app-subview-tab'), 'border', '0'
                    ),
                ),
            )
        )
        targets.append(
            Target(
                family=subview,
                step=subview,
                selector=panel,
                role='panel',
                top=rail_top,
                available=rail,
                box=rail,
                bounding=side_bounding,
                scroll_zones=(panel,),
            )
        )
    return Derivation(
        family='training',
        shell=instrument.panel_shells['training'],
        breakdown=(
            ('banner', shell.banner),
            ('shell_padding_top', shell.padding_top),
            ('head', head),
        ),
        box_available=grid,
        bottom_inset=shell.padding_bottom,
        targets=tuple(targets),
        notes=(
            ('head_row_extent', head_extent),
            ('side_padding_and_border', side_pad + CONTROL_BORDER_PX),
            ('rail_tab_bar', tab_bar.bar_outer),
            ('rail_tab_row_extent', tab_bar.extent),
            ('rail_panes', rail),
        ),
    )


def derivations(layout: Layout, width: int, height: int) -> tuple[Derivation, ...]:
    return (
        spotlab_derivation(layout, width, height),
        replayer_derivation(layout, width, height),
        trainer_derivation(layout, width, height),
    )


# --------------------------------------------------------------------------- #
# Checks.
# --------------------------------------------------------------------------- #
def check_every_measured_target_is_derived() -> None:
    """The AST-read instrument and the derived boxes cover the same 20 targets."""
    instrument = read_smoke_instrument()
    measured = [target.selector for target in instrument.targets()]
    derived = [
        target.selector
        for derivation in derivations(DELIVERED_LAYOUT, *REFERENCE_VIEWPORT)
        for target in derivation.targets
    ]
    assert measured == derived, (
        'every measured target must have exactly one derived box, in measurement order',
        measured,
        derived,
    )
    assert len(measured) == 20, (len(measured), measured)


def check_layout(layout: Layout, width: int, height: int) -> None:
    """The whole guard for one declared document and one viewport."""
    for derivation in derivations(layout, width, height):
        chrome = sum(value for _, value in derivation.breakdown)
        assert abs(chrome + derivation.box_available + derivation.bottom_inset - height) <= PIXEL_EPSILON, (
            f'{derivation.family}: the declared chrome, box and bottom inset must account for the '
            f'whole {height}px viewport',
            derivation.breakdown,
            derivation.box_available,
            derivation.bottom_inset,
        )
        for target in derivation.targets:
            check_bounding(layout, target, width, height)
            check_scroll_zones(layout, target, width, height)
            assert target.top >= -PIXEL_EPSILON, (target, 'the box may not start above the viewport')
            assert target.box > 0, (target, 'the derived box must be positive')
            assert target.box <= target.available + PIXEL_EPSILON, (
                f'{target.selector} overflows the space its parent declares at {width}x{height}',
                f'box={target.box:.2f} available={target.available:.2f} top={target.top:.2f}',
            )
            assert target.bottom <= height + PIXEL_EPSILON, (
                f'{target.selector} reaches below the {height}px viewport',
                f'top={target.top:.2f} box={target.box:.2f} bottom={target.bottom:.2f}',
            )


def check_boxes_fit_the_vertical_budget() -> None:
    for width, height in MEASURED_VIEWPORTS:
        check_layout(DELIVERED_LAYOUT, width, height)


def check_no_responsive_rule_is_needed() -> None:
    """No measured panel overflows, so the compression block stays matrix-only."""
    width, height = REFERENCE_VIEWPORT
    compressed = [
        selector
        for media, selector, _ in DELIVERED_LAYOUT.sheet.rules
        if media and all(feature in media for feature in COMPRESSION_MEDIA_FEATURES)
    ]
    assert tuple(sorted(set(compressed))) == tuple(sorted(COMPRESSION_SELECTORS)), (
        'the `min-width:901px` + `max-height:900px` block belongs to the incompressible '
        'Spot Lab grid only: a measured panel may not need a compression rule of its own',
        compressed,
    )
    for derivation in derivations(DELIVERED_LAYOUT, width, height):
        for target in derivation.targets:
            assert target.box <= target.available + PIXEL_EPSILON, (
                target, 'no measured target of this module may overflow'
            )


def generated_banner_css() -> str:
    """The CSS `tools/write_deployment_metadata.py` writes, from its own literals."""
    for node in ast.walk(ast.parse(METADATA_WRITER_TEXT)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr != 'write_text':
            continue
        joined = node.args[0]
        assert isinstance(joined, ast.Call) and getattr(joined.func, 'attr', '') == 'join', (
            'the deployment metadata writer no longer joins a literal list of CSS lines'
        )
        elements = joined.args[0]
        assert isinstance(elements, ast.List), 'the writer must join a list literal'
        return '\n'.join(
            value for value in (as_literal(element) for element in elements.elts) if isinstance(value, str)
        )
    raise AssertionError('tools/write_deployment_metadata.py no longer writes the banner')


def banner_property(sheet: Sheet, chain, prop: str, width: int, height: int) -> str | None:
    # `margin`/`padding` are declared as shorthands in both sources: compare the
    # resolved box edges instead of the shorthand text.
    if prop.split('-')[0] in ('margin', 'padding'):
        kind, _, edge = prop.partition('-')
        return f'{sheet.box_length(chain, kind, edge, width, height):.2f}'
    value = sheet.declared(chain, prop, width, height)
    if prop == 'content':
        return None if value is None else 'line'
    return value


def check_the_two_banner_sources_declare_the_same_box() -> None:
    """The served banner and the generated one must declare the same geometry."""
    width, height = REFERENCE_VIEWPORT
    generated = Sheet(generated_banner_css())
    for chain in (('body::before',), ('body.trainer-view-open::before', 'body::before')):
        for prop in ('display', 'max-width', 'margin-top', 'margin-bottom', 'padding-left', 'padding-right',
                     'font', 'text-align', 'content'):
            served_value = banner_property(DELIVERED_LAYOUT.banner_sheet, chain, prop, width, height)
            generated_value = banner_property(generated, chain, prop, width, height)
            assert served_value == generated_value, (
                chain, prop, served_value, generated_value,
                'the generated deployment banner must keep the served geometry',
            )


# --------------------------------------------------------------------------- #
# Non-vacuity: remove one load-bearing declaration at a time and replay.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class MutationControl:
    label: str
    token: str
    replacement: str = ''
    reason: str = ''


MUTATION_CONTROLS: tuple[MutationControl, ...] = (
    MutationControl(
        'shell-min-height',
        'flex:1 1 auto;width:100%;height:100dvh;max-height:100dvh;min-height:0;overflow:hidden;padding:14px 18px 16px',
        'flex:1 1 auto;width:100%;height:100dvh;max-height:100dvh;overflow:hidden;padding:14px 18px 16px',
        'the view shell could no longer shrink below its content',
    ),
    MutationControl(
        'replayer-section-min-height',
        'flex:1 1 auto;min-height:0;display:grid;grid-template-rows:minmax(0,1fr);',
        'flex:1 1 auto;display:grid;grid-template-rows:minmax(0,1fr);',
        'the Replayer grid row would be sized by its columns content',
    ),
    MutationControl(
        'replayer-column-min-height',
        'min-height:0;display:flex;flex-direction:column;gap:8px;',
        'display:flex;flex-direction:column;gap:8px;',
        'a measured Replayer column would no longer be bounded',
    ),
    MutationControl(
        'replayer-context-min-height',
        '>#replayerContextPanel{display:flex;flex-direction:column;min-height:0;overflow:hidden}',
        '>#replayerContextPanel{display:flex;flex-direction:column;overflow:hidden}',
        'the measured context panel would be sized by its panes content',
    ),
    MutationControl(
        'replayer-pane-min-height',
        '>.app-subview-panel{flex:1 1 auto;min-height:0;margin:0}',
        '>.app-subview-panel{flex:1 1 auto;margin:0}',
        'a measured context pane would be sized by its content',
    ),
    MutationControl(
        'replayer-grid-template-rows',
        'grid-template-rows:minmax(0,1fr);',
        'grid-template-rows:auto;',
        'the Replayer row would no longer take the declared remaining space',
    ),
    MutationControl(
        'replayer-visual-display-contents',
        '#replayerSection>#hhVisualReplay{display:contents}',
        '#replayerSection>#hhVisualReplay{display:block}',
        'the rendered Replayer columns would stop being grid items of the shell',
    ),
    MutationControl(
        'tab-list-flex',
        'flex:0 0 auto;align-items:center;gap:6px;flex-wrap:wrap;margin:0 0 12px',
        'align-items:center;gap:6px;flex-wrap:wrap;margin:0 0 12px',
        'the measured tab bars would no longer be content-sized',
    ),
    MutationControl(
        'app-view-body-min-height',
        '.app-view-body{display:flex;flex-direction:column;min-height:0}',
        '.app-view-body{display:flex;flex-direction:column}',
        'the Spot Lab body would be sized by its panes content',
    ),
    MutationControl(
        'spotlab-grid-min-height',
        'display:flex;flex-direction:column;gap:0;flex:1 1 auto;min-height:0;overflow:hidden}',
        'display:flex;flex-direction:column;gap:0;flex:1 1 auto;overflow:hidden}',
        'the Spot Lab grid would be sized by its panes content',
    ),
    MutationControl(
        'spotlab-panel-min-height',
        '>.grid>.app-subview-panel{flex:1 1 auto;min-height:0;overflow:hidden}',
        '>.grid>.app-subview-panel{flex:1 1 auto;overflow:hidden}',
        'the measured Spot Lab pane would be sized by its content',
    ),
    MutationControl(
        'trainer-shell-min-height',
        'flex:1 1 auto;width:100%;max-width:none;min-height:0;margin:0;overflow:hidden}',
        'flex:1 1 auto;width:100%;max-width:none;margin:0;overflow:hidden}',
        'the Training shell would be sized by its content',
    ),
    MutationControl(
        'trainer-grid-min-height',
        'flex:1 1 auto;min-height:0;align-items:stretch;grid-template-columns:minmax(0,1fr) 330px}',
        'flex:1 1 auto;align-items:stretch;grid-template-columns:minmax(0,1fr) 330px}',
        'the Training table/rail row would be sized by its content',
    ),
    MutationControl(
        'trainer-side-min-height',
        'position:static;top:auto;min-height:0;overflow:hidden}',
        'position:static;top:auto;overflow:hidden}',
        'the measured rail column would be sized by its panes content',
    ),
    MutationControl(
        'trainer-rail-min-height',
        '.trainer-rail-panel{display:grid;gap:10px;flex:1 1 auto;min-height:0;align-content:start}',
        '.trainer-rail-panel{display:grid;gap:10px;flex:1 1 auto;align-content:start}',
        'a measured rail pane would be sized by its content',
    ),
    MutationControl(
        'trainer-head-flex',
        '.trainer-head{flex:0 0 auto;margin-bottom:10px}',
        '.trainer-head{margin-bottom:10px}',
        'the Training head would no longer be a fixed chrome block',
    ),
)


def mutate(document: str, control: MutationControl) -> str:
    """`document` with one load-bearing declaration removed (in memory only)."""
    occurrences = document.count(control.token)
    assert occurrences == 1, (
        f'the mutation control {control.label!r} must match its declaration exactly once',
        f'occurrences={occurrences}',
    )
    mutated = document.replace(control.token, control.replacement)
    assert mutated != document, control.label
    return mutated


@dataclass(frozen=True)
class InstrumentMutation:
    """One rewrite of the smoke harness, replayed against the AST reader."""

    label: str
    token: str
    replacement: str
    # `None` means "at least one occurrence" (the name is looked up, not counted).
    occurrences: int | None = 1


INSTRUMENT_MUTATIONS: tuple[InstrumentMutation, ...] = (
    InstrumentMutation(
        'measured-tuple-renamed',
        'REPLAYER_COLUMN_SELECTORS',
        'REPLAYER_COLUMNS',
        None,  # every occurrence: the name disappears from the module
    ),
    InstrumentMutation(
        'measured-selector-changed',
        '"#replayerContextPanel"',
        '"#replayerContextPane"',
    ),
    InstrumentMutation(
        'tab-surface-shape-changed',
        '("#trainerTestTab", "#trainerTestPanel", "trainer-test")',
        '("#trainerTestTab", "#trainerTestPanel")',
    ),
    InstrumentMutation(
        'panel-shells-not-literal',
        '"replayer": \'[data-view-shell="replayer"]\',',
        '"replayer": REPLAYER_SHELL_SELECTOR,',
    ),
    InstrumentMutation(
        'hit-test-fields-reduced',
        '("visible", "inViewport", "inShell", "hit")',
        '("visible", "inViewport")',
        2,
    ),
    InstrumentMutation(
        'hit-test-centre-removed',
        'document.elementFromPoint(x, y)',
        'document.elementAt(x, y)',
    ),
    InstrumentMutation(
        'panel-helper-renamed',
        'def _assert_panel_surface_hit_testable(',
        'def _panel_surface_hit_testable(',
    ),
)


def instrument_mutations_fail_closed() -> tuple[str, ...]:
    """The AST reader must refuse a smoke whose instrument changed."""
    notes: list[str] = []
    read_smoke_instrument(SMOKE_TEXT)  # the delivered harness must pass first
    for mutation in INSTRUMENT_MUTATIONS:
        occurrences = SMOKE_TEXT.count(mutation.token)
        if mutation.occurrences is None:
            assert occurrences >= 1, (
                f'the instrument mutation {mutation.label!r} no longer matches the smoke verbatim',
                f'occurrences={occurrences}',
            )
        else:
            assert occurrences == mutation.occurrences, (
                f'the instrument mutation {mutation.label!r} no longer matches the smoke verbatim',
                f'occurrences={occurrences} expected={mutation.occurrences}',
            )
        mutated = SMOKE_TEXT.replace(mutation.token, mutation.replacement)
        assert mutated != SMOKE_TEXT, mutation.label
        try:
            read_smoke_instrument(mutated)
        except (AssertionError, SyntaxError) as error:
            notes.append(f'{mutation.label}: refused ({str(error)[:80]})')
            continue
        raise AssertionError(
            f'the guard no longer proves {mutation.label}: the AST reader accepts a smoke whose '
            'measured instrument changed'
        )
    assert SMOKE_TEXT == SMOKE_PATH.read_text(encoding='utf-8'), (
        'the replay must never write the smoke harness'
    )
    return tuple(notes)


def mutation_controls_fail_closed() -> tuple[str, ...]:
    """Replay every control: the derivation must refuse with the bounding removed."""
    notes: list[str] = []
    delivered = shell_document()
    check_layout(DELIVERED_LAYOUT, *REFERENCE_VIEWPORT)  # the delivered bytes must pass first
    for control in MUTATION_CONTROLS:
        mutated_layout = Layout(document=mutate(delivered, control))
        try:
            check_layout(mutated_layout, *REFERENCE_VIEWPORT)
        except AssertionError as error:
            notes.append(f'{control.label}: refused ({str(error)[:96]}) — {control.reason}')
            continue
        raise AssertionError(
            f'the guard no longer proves {control.label}: the derivation still passes with the '
            'bounding declaration removed, so it is vacuous'
        )
    assert shell_document() == delivered, 'the replay must never write the delivered bytes'
    return tuple(notes)


# --------------------------------------------------------------------------- #
# Report and entry point.
# --------------------------------------------------------------------------- #
def report_line(target: Target) -> str:
    return (
        f'  {target.step:<18} {target.selector:<26} '
        f'chrome={target.top:7.2f} available={target.available:7.2f} box={target.box:7.2f} '
        f'[{target.top:7.2f}..{target.bottom:7.2f}] slack={target.slack:6.2f}'
    )


def report(viewport: tuple[int, int] = REFERENCE_VIEWPORT) -> list[str]:
    width, height = viewport
    lines: list[str] = []
    for derivation in derivations(DELIVERED_LAYOUT, width, height):
        chrome = ' '.join(f'{name}={value:.2f}' for name, value in derivation.breakdown)
        notes = ' '.join(f'{name}={value:.2f}' for name, value in derivation.notes)
        lines.append(f'{derivation.family} @{width}x{height} shell={derivation.shell}')
        lines.append(
            f'  chrome={chrome} -> box={derivation.box_available:.2f} '
            f'+ bottom inset {derivation.bottom_inset:.2f} of {height}px'
        )
        if notes:
            lines.append(f'  derived: {notes}')
        lines.extend(report_line(target) for target in derivation.targets)
    return lines


def main() -> None:
    options = sys.argv[1:]
    viewport = REFERENCE_DESKTOP_VIEWPORT if '--desktop' in options else REFERENCE_VIEWPORT
    instrument = read_smoke_instrument()
    check_every_measured_target_is_derived()
    check_boxes_fit_the_vertical_budget()
    check_no_responsive_rule_is_needed()
    check_the_two_banner_sources_declare_the_same_box()
    controls = mutation_controls_fail_closed()
    instrument_controls = instrument_mutations_fail_closed()
    if '--self-test' in options:
        for note in controls:
            print(f'self-test mutation {note}')
        for note in instrument_controls:
            print(f'self-test instrument {note}')
    for line in report(viewport):
        print(line)
    targets = [
        target for derivation in derivations(DELIVERED_LAYOUT, *viewport) for target in derivation.targets
    ]
    worst = max(targets, key=lambda target: target.bottom)
    width, height = viewport
    print(
        'desktop panels fit contract checks: OK '
        f'({len(instrument.targets())} measured targets derived at {width}x{height}, '
        f'{len(MUTATION_CONTROLS)} bounding mutations refused, no overflow derived, no CSS byte '
        f'required — lowest box edge {worst.selector} at {worst.bottom:.2f}px/{height}px, '
        f'no box overflows the space its parent declares)'
    )


if __name__ == '__main__':
    main()

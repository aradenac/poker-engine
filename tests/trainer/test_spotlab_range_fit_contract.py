#!/usr/bin/env python3
"""Range adverse panel vertical-budget contract (#394 T2).

No browser can run in the frozen `static-contract` job (Playwright is absent,
and the pinned Chromium cannot start for lack of `libnspr4`/`libnss3`), so the
only way to keep the `Range adverse` pane geometry verifiable from the
repository is to recompute it from the delivered bytes. This module does that
in pure Python: no Node, no network, no browser, no write, no temporary
directory — it only reads `site/index.html`, `site/trainer.css` and the smoke
harness source.

The pane is a fixed-height desktop shell (>= 901px). Its grid is 13 rows of
`.cell{height}` separated by 12 `.matrix{gap}` gutters, so

    H = 13 * cell_height + 12 * row_gap

is incompressible: a row cannot be shorter than the cell it paints. At
1366x768 the un-guarded values (`.cell{height:34px}`, `.matrix{gap:3px}`, i.e.
H = 478px) no longer fit in what the shell leaves to the pane, which is why
`site/index.html` carries the responsive rule

    @media(min-width:901px) and (max-height:900px){ .matrix{gap:2px} .cell{height:26px} }

(H = 362px). This guard recomputes both sides of the comparison:

1. `H` from the media-query verdict *per viewport width and height* — the
   shared reader only evaluated width, so this module adds the
   `min-height`/`max-height` evaluation the `max-height` gate depends on;
2. the vertical budget of the pane at 1366x768 from the declared shell
   constants (shell padding, view header, tab bar, domain title, panel padding
   and the `h2` / `.tiny` / `.range-toolbar` / `.range-mode-note` /
   `.matrixwrap` margins), each text block taken as a **majorant**: its line
   count is deduced from the declared `font-size` / `line-height` and the width
   actually available at 1366px, never from a hand-picked pixel value.

The guard then requires `H <= budget - SAFETY_MARGIN_PX` and, to stay
non-vacuous, that the base grid (`H_base = 478px`) is **above** that budget: if
the responsive rule disappeared, or if the budget were inflated until it no
longer discriminates, this contract fails instead of silently passing. It also
pins the instrument itself — the matrix is not a tolerated scroll zone, the
`.matrixwrap{overflow:hidden;margin-top:12px}` clip is intact, and the smoke's
`SPOTLAB_RANGE_SURFACE_SELECTORS` tuple still names `#matrix`.
"""
from __future__ import annotations

import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# The sibling contract owns the shared CSS reader (`css_rules`,
# `css_variables`, `resolve_css_length`). It is imported, never modified: the
# frozen job must keep every one of its tokens intact.
if str(ROOT / 'tests' / 'trainer') not in sys.path:
    sys.path.insert(0, str(ROOT / 'tests' / 'trainer'))

import test_desktop_accessibility_contract as css_reader  # noqa: E402

INDEX = (ROOT / 'site/index.html').read_text(encoding='utf-8')
TRAINER_CSS = (ROOT / 'site/trainer.css').read_text(encoding='utf-8')
MODES_SMOKE = (ROOT / 'tests' / 'trainer' / 'smoke_modes_desktop.py').read_text(encoding='utf-8')

# Document order is index.html then trainer.css (the sheet is linked after the
# inline `<style>`), so a property declared in both resolves to trainer.css.
# Statement-level at-rules (`@import`) are dropped: the shared reader flattens
# nested *blocks* but would fold a preceding `@import ...;` into the prelude of
# the next rule and lose it, which would silently hide `.app-view-head`'s real
# margin from this guard.
STATEMENT_AT_RULE = re.compile(r'@import[^;]*;')
DOCUMENT = STATEMENT_AT_RULE.sub('', INDEX) + '\n' + STATEMENT_AT_RULE.sub('', TRAINER_CSS)
VARIABLES = css_reader.css_variables(INDEX)
# `css_rules` walks the whole document, so the flattened rules are parsed once
# and reused by every lookup below.
RULES = css_reader.css_rules(DOCUMENT)

# The two reference viewports of the #394 desktop shell.
REFERENCE_VIEWPORT = (1366, 768)
REFERENCE_DESKTOP_VIEWPORT = (1500, 1000)

# The grid is 13x13: 13 rows of cells and 12 gaps between them.
GRID_ROWS = 13
GRID_GAPS = 12
# `.cell{height:34px}` + `.matrix{gap:3px}` = 13*34 + 12*3, the un-compressed
# grid the guard wants to see rejected at 1366x768.
BASE_CELL_HEIGHT = 34.0
BASE_MATRIX_GAP = 3.0
BASE_GRID_HEIGHT = GRID_ROWS * BASE_CELL_HEIGHT + GRID_GAPS * BASE_MATRIX_GAP

# Documented safety margin, subtracted from the computed budget before the
# comparison. The budget already majorises every declared length and every text
# block, but the line-count model below is a width estimate, not the browser's
# own layout: 24px (≈6.6% of the 362px grid) absorbs the residual font-metric
# uncertainty of that estimate, so the guard stays on the strict side of a
# budget the shell actually has.
SAFETY_MARGIN_PX = 24.0

# Text majorant model: a text block occupies at worst
# `ceil(chars * font_size * CHAR_ADVANCE_EM / available_width)` lines.
# `CHAR_ADVANCE_EM` is an upper bound on Inter's average glyph advance at these
# sizes (real advances sit near 0.5em; 0.62em keeps the count on the safe side).
CHAR_ADVANCE_EM = 0.62
# When a block declares no `line-height`, the CSS `normal` keyword is floored by
# this factor of the font size (real values are ~1.2). Declared numeric
# `line-height` values (e.g. `.domain-sub{line-height:1.45}`) are honoured.
DEFAULT_LINE_FACTOR = 1.5

# Any interactive control is at least this tall: 1px top+bottom border, 10px
# top+bottom padding (the shared `button` rule) and one line of its own text.
TEXT_CONTROL_BORDER_PX = 2.0

MATRIX_SELECTOR = '.matrix'
CELL_SELECTOR = '.cell'
MATRIX_WRAP_SELECTOR = '.matrixwrap'
CONTROL_SELECTOR = 'select,input[type=number],button,.filelabel'

# Instrument integrity: the matrix and its clipping wrapper must stay out of
# the tolerated scroll zones, and the smoke must keep measuring `#matrix`.
FORBIDDEN_SCROLL_ZONE_SELECTORS = ('#matrix', '.matrixwrap')
SPOTLAB_RANGE_SURFACE_TUPLE = (
    'SPOTLAB_RANGE_SURFACE_SELECTORS = ("#spotlabRangeTab", "#rangeDisplaySection", "#matrix")'
)
SMOKE_RANGE_SURFACE_SELECTORS = ('#spotlabRangeTab', '#rangeDisplaySection', '#matrix')


# --------------------------------------------------------------------------- #
# Media queries: the shared verdict is width-only, so this module re-implements
# the width *and* height evaluation the `max-height` gate of the pane needs.
# --------------------------------------------------------------------------- #
MEDIA_FEATURE = re.compile(r'(min|max)-(width|height)\s*:\s*(\d+)px')


def media_applies(media: str | None, width: int, height: int) -> bool:
    """True when `media` holds at this exact viewport width *and* height."""
    if not media:
        return True
    for operator, feature, value in MEDIA_FEATURE.findall(media):
        extent = width if feature == 'width' else height
        pixels = int(value)
        if operator == 'min' and extent < pixels:
            return False
        if operator == 'max' and extent > pixels:
            return False
    return True


def declared_value(selector: str, prop: str, width: int, height: int) -> str | None:
    """Last declared value of `prop` for `selector` at this viewport, or None."""
    value = None
    for media, name, declarations in RULES:
        if name != selector or not media_applies(media, width, height):
            continue
        for declared, raw in re.findall(r'([\w-]+)\s*:\s*([^;]+)', declarations):
            if declared == prop:
                value = raw.strip()
    return value


def box_edges(selector: str, kind: str, width: int, height: int) -> dict[str, str | None]:
    """The `padding`/`margin` box of `selector`, honouring shorthand overrides."""
    edges: dict[str, str | None] = {'top': None, 'right': None, 'bottom': None, 'left': None}
    order = ('top', 'right', 'bottom', 'left')
    for media, name, declarations in RULES:
        if name != selector or not media_applies(media, width, height):
            continue
        for declared, raw in re.findall(r'([\w-]+)\s*:\s*([^;]+)', declarations):
            raw = raw.strip()
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
                edges[declared.split('-', 1)[1]] = raw
    return edges


def length(selector: str, prop: str, width: int, height: int, default: str | None = None) -> float:
    """Resolve a declared length to px, falling back to `default` when absent."""
    raw = declared_value(selector, prop, width, height)
    if raw is None:
        assert default is not None, f'{selector} {{ {prop} }} is not declared'
        raw = default
    return css_reader.resolve_css_length(raw, VARIABLES)


def box_length(selector: str, kind: str, edge: str, width: int, height: int, default: str = '0px') -> float:
    raw = box_edges(selector, kind, width, height)[edge]
    return css_reader.resolve_css_length(raw if raw is not None else default, VARIABLES)


def line_height_px(selector: str, font_size: float, width: int, height: int) -> float:
    """One line of `selector`'s text, from its declared `line-height` or a floor."""
    raw = declared_value(selector, 'line-height', width, height)
    if raw:
        raw = raw.strip()
        if raw.endswith('px') or raw.startswith(('var(', 'calc(')):
            return css_reader.resolve_css_length(raw, VARIABLES)
        if re.fullmatch(r'\d*\.?\d+', raw):
            return font_size * float(raw)
    return font_size * DEFAULT_LINE_FACTOR


def text_lines(text: str, font_size: float, available_width: float) -> int:
    """Worst-case line count of `text` inside `available_width` at this size."""
    assert available_width > 0, available_width
    estimated = len(text) * font_size * CHAR_ADVANCE_EM
    return max(1, math.ceil(estimated / available_width))


def text_height(selector: str, text: str, available_width: float, width: int, height: int) -> float:
    font_size = length(selector, 'font-size', width, height)
    return text_lines(text, font_size, available_width) * line_height_px(selector, font_size, width, height)


# --------------------------------------------------------------------------- #
# Grid geometry, straight from the declared `.cell{height}` / `.matrix{gap}`.
# --------------------------------------------------------------------------- #
def grid_geometry(width: int, height: int) -> tuple[float, float, float]:
    """`(cell_height, row_gap, H)` for this viewport, with `H = 13h + 12g`."""
    cell = length(CELL_SELECTOR, 'height', width, height)
    gap = length(MATRIX_SELECTOR, 'gap', width, height)
    assert cell > 0, f'{CELL_SELECTOR} height must be positive, got {cell}'
    assert gap >= 0, f'{MATRIX_SELECTOR} gap must not be negative, got {gap}'
    return cell, gap, GRID_ROWS * cell + GRID_GAPS * gap


# --------------------------------------------------------------------------- #
# Markup-derived worst-case text: never a hand-copied pixel value.
# --------------------------------------------------------------------------- #
def range_panel_markup() -> str:
    """The `<section>` that owns the 13x13 matrix."""
    start = INDEX.index('aria-labelledby="spotlabRangeTab"')
    section = INDEX[start:]
    return section[: section.index('</section>')]


def spotlab_head_markup() -> str:
    """The Spot Lab view header (`app-view-head`), separate from its body."""
    start = INDEX.index('<div id="spotlabPage"')
    head = INDEX[start:]
    return head[: head.index('<div class="app-view-body">')]


def untag(fragment: str) -> str:
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', fragment)).strip()


def first_text(fragment: str, pattern: str) -> str:
    match = re.search(pattern, fragment, flags=re.S)
    assert match, f'markup no longer matches {pattern!r}'
    return untag(match.group(1))


def toolbar_labels(section: str) -> list[str]:
    toolbar = section.split('class="range-toolbar"', 1)[1].split('</div>', 1)[0]
    labels = [untag(label) for label in re.findall(r'<button[^>]*>(.*?)</button>', toolbar, flags=re.S)]
    assert labels, 'the range toolbar must own its buttons'
    return labels


# --------------------------------------------------------------------------- #
# The budget: every declared constant of the pane, every text block as majorant.
# --------------------------------------------------------------------------- #
def panel_vertical_budget(width: int, height: int) -> tuple[float, dict[str, float]]:
    """Px left for the matrix at this viewport, plus its named breakdown."""
    shell = box_edges('[data-view-shell]', 'padding', width, height)
    shell_pad = (
        css_reader.resolve_css_length(shell['top'] or '0px', VARIABLES)
        + css_reader.resolve_css_length(shell['bottom'] or '0px', VARIABLES)
    )
    # The shell's own content width: the Home-style `--max-width` column minus
    # the shell's horizontal padding. `.wrap`'s padding is superseded by
    # `[data-view-shell]` (same specificity, later rule).
    shell_width = (
        min(width, length('.wrap', 'max-width', width, height))
        - css_reader.resolve_css_length(shell['left'] or '0px', VARIABLES)
        - css_reader.resolve_css_length(shell['right'] or '0px', VARIABLES)
    )

    # View header: the taller of the back button and the domain title block,
    # plus its margin-bottom. Both are re-derived, never assumed.
    heading_gap = length('.app-view-head', 'gap', width, height, '0px')
    heading_text_width = shell_width - length('.app-view-back', 'min-width', width, height) - heading_gap
    control_height = (
        TEXT_CONTROL_BORDER_PX
        + box_length(CONTROL_SELECTOR, 'padding', 'top', width, height)
        + box_length(CONTROL_SELECTOR, 'padding', 'bottom', width, height)
        + length(CONTROL_SELECTOR, 'font-size', width, height) * DEFAULT_LINE_FACTOR
    )
    domain_title_height = line_height_px('.domain-title', length('.domain-title', 'font-size', width, height), width, height)
    domain_sub_height = (
        box_length('.domain-sub', 'margin', 'top', width, height)
        + text_height('.domain-sub', first_text(spotlab_head_markup(), r'<div class="domain-sub">(.*?)</div>'), heading_text_width, width, height)
    )
    header_height = (
        box_length('.app-view-head', 'margin', 'bottom', width, height)
        + max(control_height, domain_title_height + domain_sub_height)
    )

    # Tab bar: its padding, its 1px border, one tab row and its margin-bottom.
    tab_height = (
        box_length('.app-subview-tab', 'padding', 'top', width, height)
        + box_length('.app-subview-tab', 'padding', 'bottom', width, height)
        + length('.app-subview-tab', 'font-size', width, height) * DEFAULT_LINE_FACTOR
    )
    subviews_height = (
        box_length('.app-subviews', 'margin', 'bottom', width, height)
        + 2.0  # 1px top + 1px bottom border
        + box_length('.app-subviews', 'padding', 'top', width, height)
        + box_length('.app-subviews', 'padding', 'bottom', width, height)
        + tab_height
    )

    # Panel chrome: its padding, the `h2`, then the block stack of the pane.
    panel_pad = (
        box_length('.panel', 'padding', 'top', width, height)
        + box_length('.panel', 'padding', 'bottom', width, height)
    )
    inner_width = shell_width - box_length('.panel', 'padding', 'left', width, height) - box_length(
        '.panel', 'padding', 'right', width, height
    )
    h2_height = (
        box_length('.panel h2', 'margin', 'bottom', width, height)
        + line_height_px('.panel h2', length('.panel h2', 'font-size', width, height), width, height)
    )

    section = range_panel_markup()
    tiny_height = text_height('.tiny', first_text(section, r'<div class="tiny">(.*?)</div>'), inner_width, width, height)

    # The toolbar wraps, so it may need several button rows: count them from the
    # declared paddings, the font size and the markup labels.
    labels = toolbar_labels(section)
    button_widths = [
        TEXT_CONTROL_BORDER_PX
        + box_length(CONTROL_SELECTOR, 'padding', 'left', width, height)
        + box_length(CONTROL_SELECTOR, 'padding', 'right', width, height)
        + len(label) * length(CONTROL_SELECTOR, 'font-size', width, height) * CHAR_ADVANCE_EM
        for label in labels
    ]
    toolbar_gap = length('.range-toolbar', 'gap', width, height, '0px')
    toolbar_extent = sum(button_widths) + toolbar_gap * (len(button_widths) - 1)
    toolbar_rows = max(1, math.ceil(toolbar_extent / inner_width))
    toolbar_height = box_length('.range-toolbar', 'margin', 'top', width, height) + toolbar_rows * control_height

    note_height = box_length('.range-mode-note', 'margin', 'top', width, height) + text_height(
        '.range-mode-note', first_text(section, r'id="rangeModeNote"[^>]*>(.*?)</div>'), inner_width, width, height
    )
    wrap_margin = box_length(MATRIX_WRAP_SELECTOR, 'margin', 'top', width, height)

    breakdown = {
        'shell_padding': shell_pad,
        'view_header': header_height,
        'tab_bar': subviews_height,
        'panel_padding': panel_pad,
        'panel_h2': h2_height,
        'panel_tiny': tiny_height,
        'range_toolbar': toolbar_height,
        'range_mode_note': note_height,
        'matrixwrap_margin': wrap_margin,
    }
    budget = height - sum(breakdown.values())
    assert budget > 0, f'the pane chrome consumes the whole {height}px viewport: {breakdown}'
    return budget, breakdown


# --------------------------------------------------------------------------- #
# Guards
# --------------------------------------------------------------------------- #
def check_range_grid_fits_the_vertical_budget() -> None:
    width, height = REFERENCE_VIEWPORT
    cell, gap, grid_height = grid_geometry(width, height)
    budget, breakdown = panel_vertical_budget(width, height)
    measured = f'h={cell:g} gap={gap:g} H={grid_height:g} budget={budget:g} (margin {SAFETY_MARGIN_PX:g}px)'

    # The pane must fit at 1366x768 …
    assert grid_height + SAFETY_MARGIN_PX <= budget, (
        f'the Range adverse grid overflows its vertical budget at {width}x{height}: {measured}',
        breakdown,
    )
    # … and the base grid must *not* fit, so the check keeps failing when the
    # responsive rule disappears or the budget stops discriminating.
    assert BASE_GRID_HEIGHT > budget, (
        'the vertical budget is no longer discriminating: the base grid already fits',
        f'H_base={BASE_GRID_HEIGHT:g} {measured}',
        breakdown,
    )
    # The compressed grid is the one the responsive rule declares, not a
    # hard-coded expectation.
    base_cell, base_gap, base_grid = grid_geometry(*REFERENCE_DESKTOP_VIEWPORT)
    assert (base_cell, base_gap, base_grid) == (BASE_CELL_HEIGHT, BASE_MATRIX_GAP, BASE_GRID_HEIGHT), (
        'the base `.cell`/`.matrix` declarations moved away from 34px/3px',
        (base_cell, base_gap, base_grid),
    )
    assert grid_height < base_grid, 'the responsive rule must actually compress the grid'


def responsive_rule_media() -> str:
    """The media condition that carries the compressed `.cell` height."""
    for media, selector, declarations in RULES:
        if selector == CELL_SELECTOR and media and 'height' in declarations:
            return media
    raise AssertionError('no media-guarded `.cell{height}` rule declares the compressed grid')


def check_responsive_rule_is_gated_on_the_short_viewport() -> None:
    media = responsive_rule_media()
    width, height = REFERENCE_VIEWPORT
    # A viewport-height gate is the whole point: the shared reader ignored it, so
    # this contract evaluates `max-height` itself.
    assert 'height' in media, f'the compressed grid must be gated on viewport height, got {media!r}'
    assert media_applies(media, width, height), (
        f'the compressed grid must apply at {width}x{height}',
        media,
    )

    # The chrome does not depend on the viewport height, so the base grid fits
    # again from `BASE_GRID_HEIGHT + chrome` on. The gate must therefore cover
    # every shorter viewport — narrowing it below that crossover would leave the
    # overflow in place just above the reference height.
    budget, _ = panel_vertical_budget(width, height)
    chrome = height - budget
    last_overflowing_height = math.ceil(BASE_GRID_HEIGHT + chrome) - 1
    assert last_overflowing_height > height, (
        'the crossover height must sit above the reference height',
        last_overflowing_height,
    )
    assert media_applies(media, width, last_overflowing_height), (
        f'the compressed grid must keep covering {width}x{last_overflowing_height}, '
        'the last viewport where the base grid does not fit',
        media,
    )

    # Widening the gate past 768px (or removing it) would leak the compression
    # into the 1500x1000 reference viewport.
    reference_width, reference_height = REFERENCE_DESKTOP_VIEWPORT
    assert not media_applies(media, reference_width, reference_height), (
        f'the compressed grid must not apply at {reference_width}x{reference_height}',
        media,
    )


def check_matrix_stays_out_of_the_scroll_zones() -> None:
    zones = [selector for selector, *_ in css_reader.ALLOWED_SCROLL_ENTRY.findall(INDEX)]
    assert zones, 'APP_ALLOWED_SCROLL_ZONES must keep documenting the tolerated scroll zones'
    for forbidden in FORBIDDEN_SCROLL_ZONE_SELECTORS:
        assert forbidden not in zones, f'{forbidden} must never become a tolerated scroll zone'

    # The matrix and its clipping wrapper are still served as the smoke measures
    # them, and the wrapper rule is still the declared clip of record.
    assert '<div class="matrixwrap"><div id="matrix" class="matrix"></div></div>' in INDEX, (
        'the `.matrixwrap > #matrix` markup must stay verbatim'
    )
    assert '.matrixwrap{overflow:hidden;margin-top:12px}' in INDEX, (
        'the `.matrixwrap{overflow:hidden;margin-top:12px}` clip must stay verbatim'
    )

    width, height = REFERENCE_VIEWPORT
    # The wrapper clips, it never scrolls: that is what makes the compressed
    # rows the whole story instead of a scrollable overflow.
    assert declared_value(MATRIX_WRAP_SELECTOR, 'overflow', width, height) == 'hidden', (
        f'{MATRIX_WRAP_SELECTOR} must stay clipped',
        declared_value(MATRIX_WRAP_SELECTOR, 'overflow', width, height),
    )
    assert declared_value(MATRIX_WRAP_SELECTOR, 'margin-top', width, height) == '12px', (
        f'{MATRIX_WRAP_SELECTOR} margin-top must stay 12px',
        declared_value(MATRIX_WRAP_SELECTOR, 'margin-top', width, height),
    )


def check_smoke_still_measures_the_range_surface() -> None:
    assert SPOTLAB_RANGE_SURFACE_TUPLE in MODES_SMOKE, (
        'the smoke must keep measuring the Spot Lab Range surface verbatim',
        SPOTLAB_RANGE_SURFACE_TUPLE,
    )
    block = MODES_SMOKE.split('SPOTLAB_RANGE_SURFACE_SELECTORS = (', 1)[1].split(')', 1)[0]
    for selector in SMOKE_RANGE_SURFACE_SELECTORS:
        assert selector in block, (selector, block)


def main() -> None:
    check_range_grid_fits_the_vertical_budget()
    check_responsive_rule_is_gated_on_the_short_viewport()
    check_matrix_stays_out_of_the_scroll_zones()
    check_smoke_still_measures_the_range_surface()
    cell, gap, grid_height = grid_geometry(*REFERENCE_VIEWPORT)
    budget, _ = panel_vertical_budget(*REFERENCE_VIEWPORT)
    print(
        'spot lab range fit contract checks: OK '
        f'(1366x768: h={cell:g}px gap={gap:g}px H={grid_height:g}px budget={budget:.2f}px)'
    )


if __name__ == '__main__':
    main()

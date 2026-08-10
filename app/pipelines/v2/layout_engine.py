"""
V2 Layout Engine
================
Turns a flat list of spans into queryable page geometry: visual lines, and
directional neighbour lookups ("what sits to the right of this caption?").

All distances are expressed in multiples of the reference span's height rather
than in pixels. A caption on a 2339px-tall certificate render and the same
caption on a 723px cheque render then behave identically, so one set of
thresholds in YAML works across wildly different page sizes and DPIs.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Iterable, Optional

import numpy as np

from .models import BBox, Document, Page, TextSpan


@dataclass
class Neighbour:
    """A span found near a reference span, with how it was found."""

    span: TextSpan
    direction: str        # right | below | left | above | inline
    distance_ratio: float  # gap, in multiples of the reference span's height
    same_line: bool

    @property
    def proximity(self) -> float:
        """1.0 when touching, decaying to 0.0 at the search limit."""
        return max(0.0, 1.0 - self.distance_ratio)


@dataclass
class Line:
    """A row of spans that share a visual baseline."""

    spans: list[TextSpan] = dc_field(default_factory=list)

    @property
    def bbox(self) -> BBox:
        return BBox(
            min(s.bbox.x1 for s in self.spans),
            min(s.bbox.y1 for s in self.spans),
            max(s.bbox.x2 for s in self.spans),
            max(s.bbox.y2 for s in self.spans),
        )

    @property
    def text(self) -> str:
        return " ".join(s.text for s in self.spans)


class PageLayout:
    """Geometry queries over one page."""

    def __init__(self, page: Page):
        self.page = page
        self.spans = page.spans
        heights = [s.bbox.height for s in self.spans if s.bbox.height > 0]
        self.median_height = float(np.median(heights)) if heights else 1.0
        self.lines = self._build_lines()

    def _build_lines(self) -> list[Line]:
        if not self.spans:
            return []
        tolerance = max(self.median_height * 0.6, 1.0)
        lines: list[Line] = []
        centres: list[float] = []
        for span in sorted(self.spans, key=lambda s: (s.bbox.y1, s.bbox.x1)):
            cy = span.bbox.cy
            for i, centre in enumerate(centres):
                if abs(cy - centre) <= tolerance:
                    lines[i].spans.append(span)
                    centres[i] = float(np.mean([s.bbox.cy for s in lines[i].spans]))
                    break
            else:
                lines.append(Line(spans=[span]))
                centres.append(cy)
        for line in lines:
            line.spans.sort(key=lambda s: s.bbox.x1)
        return sorted(lines, key=lambda l: l.bbox.y1)

    def line_of(self, span: TextSpan) -> Optional[Line]:
        for line in self.lines:
            if span in line.spans:
                return line
        return None

    def neighbours(
        self,
        span: TextSpan,
        directions: Iterable[str],
        max_distance: float,
    ) -> list[Neighbour]:
        """Spans lying in the requested directions from `span`, within
        `max_distance` (in multiples of `span`'s height)."""
        unit = span.bbox.height or self.median_height or 1.0
        out: list[Neighbour] = []

        for other in self.spans:
            if other is span:
                continue
            found = self._classify(span, other, unit, max_distance)
            if found is not None:
                out.append(found)

        # Nearest first: the value beside a caption is nearly always the
        # closest thing to it, and later scoring only needs the best few.
        out.sort(key=lambda n: (n.distance_ratio, not n.same_line))
        return out

    def _classify(
        self, ref: TextSpan, other: TextSpan, unit: float, max_distance: float
    ) -> Optional[Neighbour]:
        a, b = ref.bbox, other.bbox
        v_overlap = a.vertical_overlap(b)
        h_overlap = a.horizontal_overlap(b)
        same_line = v_overlap >= 0.5

        # -- right: beside the caption, sharing its band
        if v_overlap >= 0.3 and b.x1 >= a.x2 - unit * 0.3:
            gap = max(0.0, b.x1 - a.x2) / unit
            if gap <= max_distance:
                return Neighbour(other, "right", gap / max_distance, same_line)

        # -- below: under the caption, roughly in the same column
        if b.y1 >= a.y2 - unit * 0.3 and (h_overlap >= 0.15 or abs(b.x1 - a.x1) <= unit * 2.0):
            gap = max(0.0, b.y1 - a.y2) / unit
            if gap <= max_distance:
                return Neighbour(other, "below", gap / max_distance, False)

        # -- left / above, only when explicitly requested by the field config
        if v_overlap >= 0.3 and b.x2 <= a.x1 + unit * 0.3:
            gap = max(0.0, a.x1 - b.x2) / unit
            if gap <= max_distance:
                return Neighbour(other, "left", gap / max_distance, same_line)

        if b.y2 <= a.y1 + unit * 0.3 and (h_overlap >= 0.15 or abs(b.x1 - a.x1) <= unit * 2.0):
            gap = max(0.0, a.y1 - b.y2) / unit
            if gap <= max_distance:
                return Neighbour(other, "above", gap / max_distance, False)

        return None


class DocumentLayout:
    """Page layouts for one document, keyed by page number."""

    def __init__(self, document: Document):
        self.document = document
        self.pages: dict[int, PageLayout] = {p.number: PageLayout(p) for p in document.pages}

    @property
    def name(self) -> str:
        return self.document.name

    def __iter__(self):
        return iter(self.pages.values())

    def page(self, number: int) -> Optional[PageLayout]:
        return self.pages.get(number)

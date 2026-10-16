"""Pure (Tk-free, network-free) logic for the Box Number Cleanup tool.

Box numbers follow "<LETTERS>-<digits>" (e.g. "SG-05", "WD-112"). Anything
else -- the old plain-number boxes -- is "malformed" and grouped under N/A.

An "asset" here is a plain dict: {"id", "tag", "name", "model", "box"} where
"box" is the raw custom-field value.
"""

from __future__ import annotations

import logging
import re
import time

logger = logging.getLogger(__name__)

_BOX_RE = re.compile(r"^([A-Za-z]+)-(\d+)$")

NA_KEY = "N/A"


def parse_box_value(raw) -> tuple[str, int] | None:
    """Parse "SG-05" -> ("SG", 5); return None for anything malformed.

    Prefix is upper-cased so "sg-05" and "SG-05" are the same box.
    """
    m = _BOX_RE.match(str(raw or "").strip())
    if not m:
        return None
    return m.group(1).upper(), int(m.group(2))


def format_box_label(prefix: str, number: int) -> str:
    """Canonical label: 2 digits below 100, 3+ otherwise (matches dropOff's labels)."""
    return f"{prefix}-{number:02d}"


def _natural_key(text: str):
    """Sort digits numerically before text: "2" < "10" < "abc"."""
    t = str(text or "").strip()
    return (0, int(t), "") if t.isdigit() else (1, 0, t.lower())


def group_assets(assets: list[dict]) -> list[dict]:
    """Group assets into a prefix -> box -> assets hierarchy, sorted for display.

    Returns:
        List of category dicts, alphabetical with N/A last:
        {"key", "label", "count", "boxes": [{"key", "label", "assets": [...]}]}
        The category label is "<PREFIX>-XX" or "N/A-XX". Malformed boxes keep
        their raw value as the box label.
    """
    cats: dict[str, dict[str, dict]] = {}
    for a in assets:
        parsed = parse_box_value(a.get("box"))
        if parsed:
            cat_key = parsed[0]
            box_key = format_box_label(*parsed)
            box_sort = (0, parsed[1], "")
        else:
            cat_key = NA_KEY
            box_key = str(a.get("box") or "").strip()
            box_sort = _natural_key(box_key)
        box = cats.setdefault(cat_key, {}).setdefault(box_key, {"key": box_key, "label": box_key, "sort": box_sort, "assets": []})
        box["assets"].append(a)

    out = []
    for cat_key in sorted(cats, key=lambda k: (k == NA_KEY, k)):
        boxes = sorted(cats[cat_key].values(), key=lambda b: b["sort"])
        for b in boxes:
            b["assets"].sort(key=lambda a: _natural_key(a.get("tag")))
        out.append({
            "key": cat_key,
            "label": f"{cat_key}-XX",
            "count": sum(len(b["assets"]) for b in boxes),
            "boxes": [{"key": b["key"], "label": b["label"], "assets": b["assets"]} for b in boxes],
        })
    return out


def tracker_removals(assets_before: list[dict], cleared_ids: set, streams: list[str]) -> dict:
    """Work out what the drop-off tracker needs to hear about.

    Args:
        assets_before: Every asset with a box number, before clearing.
        cleared_ids: IDs whose box number was successfully cleared.
        streams: The stream codes the tracker knows (e.g. SG, SM, ...).

    Returns:
        {stream: {"killed": bool, "removed_by_box": {box_number: count}}} for
        each tracked stream that lost at least one asset. "killed" means the
        stream had assets and now has none left.
    """
    total: dict[str, int] = {}
    removed: dict[str, dict[int, int]] = {}
    removed_total: dict[str, int] = {}
    for a in assets_before:
        parsed = parse_box_value(a.get("box"))
        if not parsed or parsed[0] not in streams:
            continue
        prefix, number = parsed
        total[prefix] = total.get(prefix, 0) + 1
        if a["id"] in cleared_ids:
            removed.setdefault(prefix, {})
            removed[prefix][number] = removed[prefix].get(number, 0) + 1
            removed_total[prefix] = removed_total.get(prefix, 0) + 1
    return {
        prefix: {"killed": removed_total[prefix] == total[prefix], "removed_by_box": removed[prefix]}
        for prefix in removed
    }


def request_with_backoff(send, *, attempts: int = 4, sleep=time.sleep, max_wait: float = 60.0):
    """Call send() (-> requests.Response) with retry on transient failures.

    Retries on exceptions, HTTP 429 (honouring Retry-After) and 5xx, with a
    growing pause. Any other response -- success or a definitive 4xx -- is
    returned immediately for the caller to judge. Never shows dialogs, so
    it's safe on a worker thread.

    Raises:
        Exception: the last exception if every attempt raised.
    Returns:
        The last response if every attempt got 429/5xx.
    """
    last_exc = None
    resp = None
    for i in range(attempts):
        wait = 2.0 * (i + 1)
        try:
            resp = send()
            last_exc = None
        except Exception as exc:  # network error, timeout, ...
            last_exc = exc
            resp = None
        else:
            if resp.status_code == 429:
                try:
                    wait = float(resp.headers.get("Retry-After", wait))
                except (TypeError, ValueError):
                    pass
            elif resp.status_code < 500:
                return resp
        if i < attempts - 1:
            sleep(min(wait, max_wait))
    if last_exc is not None:
        raise last_exc
    return resp

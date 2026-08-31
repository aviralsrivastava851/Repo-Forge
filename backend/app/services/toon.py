"""
TOON - Token-Oriented Object Notation
Compact, line-oriented alternative to JSON. ~30-60% fewer tokens.
Spec:
- scalars: string (unquoted if safe), number, boolean, null
- `key: value` for scalars
- `key:` for nested objects (indented 2 spaces)
- `key:` + indented `- item` for arrays
- arrays of objects: `- key: value`
- strings with special chars quoted with double quotes
"""
from __future__ import annotations
import re
from typing import Any

SAFE_KEY_RE = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_\-\.]*$')
SAFE_VAL_RE = re.compile(r'^[a-zA-Z0-9_\-\.\/]+$')

def _needs_quote(s: str) -> bool:
    if s == "":
        return True
    if s in ("true", "false", "null"):
        return True
    if re.match(r'^-?\d+(\.\d+)?$', s):
        return True
    if "\n" in s or ":" in s or "#" in s or s[0] in (" ", "-", '"', "'"):
        return True
    return False

def _encode_scalar(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        if _needs_quote(v):
            # escape double quotes
            escaped = v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
            return f'"{escaped}"'
        return v
    return str(v)

def _decode_scalar(s: str) -> Any:
    s = s.strip()
    if s == "null":
        return None
    if s == "true":
        return True
    if s == "false":
        return False
    if re.match(r'^-?\d+$', s):
        try:
            return int(s)
        except:
            pass
    if re.match(r'^-?\d+\.\d+$', s):
        try:
            return float(s)
        except:
            pass
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        inner = s[1:-1].replace('\\"', '"').replace("\\\\", "\\").replace("\\n", "\n")
        return inner
    return s

def dumps(obj: Any, indent: int = 0) -> str:
    """Serialize Python object to TOON string."""
    lines = []
    _dump_value(obj, lines, indent, top=True)
    return "\n".join(lines)

def _dump_value(obj: Any, lines: list[str], indent: int, key: str | None = None, top: bool = False):
    prefix = "  " * indent
    if isinstance(obj, dict):
        if not obj:
            if key is not None:
                lines.append(f"{prefix}{key}: {{}}")
            return
        if top:
            for k, v in obj.items():
                _dump_value(v, lines, indent, key=k, top=False)
        else:
            if key is not None:
                lines.append(f"{prefix}{key}:")
                base = indent + 1
            else:
                base = indent
            for k, v in obj.items():
                _dump_value(v, lines, base, key=k, top=False)
    elif isinstance(obj, list):
        if key is not None:
            if not obj:
                lines.append(f"{prefix}{key}: []")
                return
            lines.append(f"{prefix}{key}:")
            base = indent + 1
            for item in obj:
                if isinstance(item, dict):
                    # dict in array: "- key: value"
                    first = True
                    for dk, dv in item.items():
                        if first:
                            # first key on same line as dash
                            if isinstance(dv, (dict, list)):
                                lines.append(f"{'  ' * base}- {dk}:")
                                _dump_value(dv, lines, base + 1, key=None, top=False)
                            else:
                                lines.append(f"{'  ' * base}- {dk}: {_encode_scalar(dv)}")
                            first = False
                        else:
                            if isinstance(dv, (dict, list)):
                                lines.append(f"{'  ' * (base + 1)}{dk}:")
                                _dump_value(dv, lines, base + 2, key=None, top=False)
                            else:
                                lines.append(f"{'  ' * (base + 1)}{dk}: {_encode_scalar(dv)}")
                    if first:
                        lines.append(f"{'  ' * base}- {{}}")
                elif isinstance(item, list):
                    lines.append(f"{'  ' * base}-")
                    _dump_value(item, lines, base + 1, key=None, top=False)
                else:
                    lines.append(f"{'  ' * base}- {_encode_scalar(item)}")
        else:
            for item in obj:
                # Nested arrays still require an explicit dash. Omitting it
                # flattened values such as event.files during round-tripping.
                if isinstance(item, dict):
                    first = True
                    for dk, dv in item.items():
                        marker = "- " if first else "  "
                        item_indent = indent if first else indent + 1
                        if isinstance(dv, (dict, list)):
                            lines.append(f"{'  ' * item_indent}{marker}{dk}:")
                            _dump_value(dv, lines, indent + 1, key=None, top=False)
                        else:
                            lines.append(f"{'  ' * item_indent}{marker}{dk}: {_encode_scalar(dv)}")
                        first = False
                    if first:
                        lines.append(f"{'  ' * indent}- {{}}")
                elif isinstance(item, list):
                    lines.append(f"{'  ' * indent}-")
                    _dump_value(item, lines, indent + 1, key=None, top=False)
                else:
                    lines.append(f"{'  ' * indent}- {_encode_scalar(item)}")
    else:
        if key is not None:
            lines.append(f"{prefix}{key}: {_encode_scalar(obj)}")
        else:
            lines.append(f"{prefix}{_encode_scalar(obj)}")

def loads(text: str) -> Any:
    """Parse TOON string to Python object."""
    if not text or not text.strip():
        return {}
    lines = text.splitlines()
    # preprocess: remove empty lines and comments (lines starting with #)
    cleaned = []
    for l in lines:
        if not l.strip():
            continue
        stripped = l.lstrip()
        if stripped.startswith("#"):
            continue
        cleaned.append(l)
    if not cleaned:
        return {}
    result, _ = _parse_block(cleaned, 0, 0)
    return result

def _count_indent(line: str) -> int:
    c = 0
    for ch in line:
        if ch == " ":
            c += 1
        else:
            break
    return c // 2

def _parse_block(lines: list[str], start: int, base_indent: int):
    obj = {}
    is_array = False
    array_items: list[Any] = []
    i = start
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        indent = _count_indent(line)
        if indent < base_indent:
            break
        if indent > base_indent:
            # this should be handled by parent caller that peeked ahead
            break
        stripped = line.lstrip()
        if stripped.startswith("- "):
            # array at current level
            is_array = True
            # ensure obj is empty if we switch to array
            content = stripped[2:]
            if not content or content.strip() == "":
                # nested block follows
                if i + 1 < len(lines) and _count_indent(lines[i+1]) > base_indent:
                    sub, nxt = _parse_block(lines, i+1, base_indent+1)
                    array_items.append(sub)
                    i = nxt
                else:
                    array_items.append(None)
                    i += 1
            elif content.strip().startswith('"') or content.strip().startswith("'"):
                # quoted scalar array item (may contain colon) — treat as string, not dict
                array_items.append(_decode_scalar(content.strip()))
                i += 1
            elif ":" in content:
                # could be dict item: "- key: value" or "- key:"
                # parse as dict with first key
                # create a dict for this item
                d: dict[str, Any] = {}
                # parse first kv
                k, v = _split_kv(content)
                if v == "" or v is None:
                    # value is nested block
                    if i + 1 < len(lines) and _count_indent(lines[i+1]) > base_indent:
                        # need to look ahead: is next line indented more than base?
                        # For dict in array, subsequent keys are at indent+1
                        # So parse remaining keys
                        # First, handle nested if value expects block
                        # Check if next line is indented base+1 and not array
                        nxt_indent = _count_indent(lines[i+1])
                        if nxt_indent == base_indent + 1 and not lines[i+1].lstrip().startswith("- "):
                            # next line is continuation of this dict? Actually keys at base+1 would be continuation
                            # But if v is empty, next block at base+1 belongs to this key
                            # Let's try to parse block for this key's value
                            # For simplicity, if v is empty and next is block, parse it
                            sub, nxt = _parse_block(lines, i+1, base_indent+1)
                            # But we need to differentiate: is sub a dict for the key's value or remaining keys?
                            # Heuristic: if sub is dict and we have no value, treat as value
                            # However for array-of-dicts like "- id: 102\n  created_at: 2026-08-20"
                            # The second line "  created_at: ..." is at same indent as first key's value? No.
                            # Actually "- id: 102" is at base, then "  created_at: 2026-08-20" is at base+1
                            # So after first key, we should collect additional keys at base+1
                            # Let's collect them
                            d[k] = _decode_scalar(v) if v not in ("", None) else None
                            # now collect subsequent keys at indent base+1 that are not dash
                            j = i + 1
                            while j < len(lines):
                                if _count_indent(lines[j]) != base_indent + 1:
                                    break
                                if lines[j].lstrip().startswith("- "):
                                    break
                                nxt_stripped = lines[j].lstrip()
                                if ":" not in nxt_stripped:
                                    break
                                nk, nv = _split_kv(nxt_stripped)
                                if nv == "" or nv is None:
                                    # nested
                                    if j + 1 < len(lines) and _count_indent(lines[j+1]) > base_indent + 1:
                                        sub2, nxt2 = _parse_block(lines, j+1, base_indent+2)
                                        d[nk] = sub2
                                        j = nxt2
                                    else:
                                        d[nk] = {}
                                        j += 1
                                else:
                                    # check for nested block after scalar? e.g., key: then next line list
                                    if j + 1 < len(lines) and ":" not in nv and _count_indent(lines[j+1]) == base_indent + 2 and lines[j+1].lstrip().startswith("-"):
                                        # array following
                                        sub2, nxt2 = _parse_block(lines, j+1, base_indent+2)
                                        # nv is empty string marker for array?
                                        # but nv is scalar already, so not
                                        d[nk] = _decode_scalar(nv)
                                        j += 1
                                    else:
                                        d[nk] = _decode_scalar(nv)
                                        j += 1
                            array_items.append(d)
                            i = j
                            continue
                        else:
                            d[k] = {}
                            array_items.append(d)
                            i += 1
                    else:
                        d[k] = {}
                        array_items.append(d)
                        i += 1
                else:
                    d[k] = _decode_scalar(v)
                    # collect subsequent keys at base+1
                    j = i + 1
                    while j < len(lines):
                        if _count_indent(lines[j]) != base_indent + 1:
                            break
                        if lines[j].lstrip().startswith("- "):
                            break
                        nxt_stripped = lines[j].lstrip()
                        if ":" not in nxt_stripped:
                            break
                        nk, nv = _split_kv(nxt_stripped)
                        if nv == "" or nv is None:
                            if j + 1 < len(lines) and _count_indent(lines[j+1]) > base_indent + 1:
                                sub2, nxt2 = _parse_block(lines, j+1, base_indent+2)
                                d[nk] = sub2
                                j = nxt2
                            else:
                                d[nk] = {}
                                j += 1
                        else:
                            d[nk] = _decode_scalar(nv)
                            j += 1
                    array_items.append(d)
                    i = j
                    continue
            else:
                # "- scalar"
                array_items.append(_decode_scalar(content))
                i += 1
        else:
            # "key: value" or "key:"
            if ":" not in stripped:
                # bare scalar at top level? treat as key with no value
                i += 1
                continue
            k, v = _split_kv(stripped)
            # peek next line
            has_nested = (i + 1 < len(lines) and _count_indent(lines[i+1]) > base_indent)
            if v == "" or v is None:
                if has_nested:
                    # check if nested is array (next line starts with -)
                    next_stripped = lines[i+1].lstrip()
                    if next_stripped.startswith("- "):
                        sub, nxt = _parse_block(lines, i+1, base_indent+1)
                        # sub could be array
                        if isinstance(sub, list):
                            obj[k] = sub
                        else:
                            # if array parser returned dict, convert? Should be list
                            obj[k] = sub if isinstance(sub, list) else array_items
                            # fallback
                            if isinstance(sub, dict) and array_items:
                                obj[k] = sub
                        i = nxt
                    else:
                        sub, nxt = _parse_block(lines, i+1, base_indent+1)
                        obj[k] = sub
                        i = nxt
                else:
                    # empty dict or list notation
                    obj[k] = {}
                    i += 1
            else:
                # v may be "[]" or "{}" or scalar, or inline array?
                if v == "[]":
                    obj[k] = []
                    i += 1
                elif v == "{}":
                    obj[k] = {}
                    i += 1
                elif v == "":
                    # treat as nested
                    if has_nested:
                        sub, nxt = _parse_block(lines, i+1, base_indent+1)
                        obj[k] = sub
                        i = nxt
                    else:
                        obj[k] = ""
                        i += 1
                else:
                    # scalar value, but could have nested block after? e.g., key: scalar with children? Not typical.
                    # check for special case where value is scalar but next lines are at indent+1 and belong to this key's dict? No.
                    obj[k] = _decode_scalar(v)
                    i += 1
    if is_array:
        return array_items, i
    return obj, i

def _split_kv(s: str) -> tuple[str, str | None]:
    idx = s.find(":")
    if idx == -1:
        return s.strip(), None
    k = s[:idx].strip()
    v = s[idx+1:].strip()
    # keep empty string as indicator for nested
    if v == "":
        return k, ""
    return k, v

def validate(text: str) -> bool:
    try:
        loads(text)
        return True
    except Exception:
        return False

def to_json_compatible(obj: Any) -> Any:
    return obj

def from_json(obj: Any) -> str:
    return dumps(obj)

def to_json(obj: Any) -> Any:
    # for Supabase storage: just return dict
    return obj

# Token count estimate (approx)
def estimate_tokens(text: str) -> int:
    # rough: 1 token ~ 4 chars
    return max(1, len(text) // 4)

def token_savings(json_text: str, toon_text: str) -> dict:
    jt = estimate_tokens(json_text)
    tt = estimate_tokens(toon_text)
    saving = (jt - tt) / jt * 100 if jt > 0 else 0
    return {"json_tokens": jt, "toon_tokens": tt, "saving_percent": round(saving, 1)}

# Convenience: json <-> toon conversion using json module
import json as _json

def json_to_toon(json_text: str) -> str:
    obj = _json.loads(json_text)
    return dumps(obj)

def toon_to_json(toon_text: str) -> str:
    obj = loads(toon_text)
    return _json.dumps(obj, indent=2)

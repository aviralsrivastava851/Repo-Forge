/**
 * TOON - Token-Oriented Object Notation (TypeScript)
 * Mirrors backend/app/services/toon.py
 */

export function needsQuote(s: string): boolean {
  if (s === "") return true;
  if (s === "true" || s === "false" || s === "null") return true;
  if (/^-?\d+(\.\d+)?$/.test(s)) return true;
  if (s.includes("\n") || s.includes(":") || s.includes("#") || [" ", "-", '"', "'"].includes(s[0])) return true;
  return false;
}

export function encodeScalar(v: any): string {
  if (v === null || v === undefined) return "null";
  if (typeof v === "boolean") return v ? "true" : "false";
  if (typeof v === "number") return String(v);
  if (typeof v === "string") {
    if (needsQuote(v)) {
      const esc = v.replace(/\\/g, "\\\\").replace(/"/g, '\\"').replace(/\n/g, "\\n");
      return `"${esc}"`;
    }
    return v;
  }
  return String(v);
}

export function decodeScalar(s: string): any {
  s = s.trim();
  if (s === "null") return null;
  if (s === "true") return true;
  if (s === "false") return false;
  if (/^-?\d+$/.test(s)) return parseInt(s, 10);
  if (/^-?\d+\.\d+$/.test(s)) return parseFloat(s);
  if (s.length >= 2 && s[0] === '"' && s[s.length - 1] === '"') {
    return s.slice(1, -1).replace(/\\"/g, '"').replace(/\\\\/g, "\\").replace(/\\n/g, "\n");
  }
  return s;
}

export function dumps(obj: any, indent = 0): string {
  const lines: string[] = [];
  dumpValue(obj, lines, indent, undefined, true);
  return lines.join("\n");
}

function dumpValue(obj: any, lines: string[], indent: number, key?: string, top?: boolean) {
  const prefix = "  ".repeat(indent);
  if (obj !== null && typeof obj === "object" && !Array.isArray(obj)) {
    const keys = Object.keys(obj);
    if (keys.length === 0) {
      if (key !== undefined) lines.push(`${prefix}${key}: {}`);
      return;
    }
    if (top) {
      for (const k of keys) dumpValue(obj[k], lines, indent, k, false);
    } else {
      if (key !== undefined) {
        lines.push(`${prefix}${key}:`);
        const base = indent + 1;
        for (const k of keys) dumpValue(obj[k], lines, base, k, false);
      } else {
        for (const k of keys) dumpValue(obj[k], lines, indent, k, false);
      }
    }
  } else if (Array.isArray(obj)) {
    if (key !== undefined) {
      if (obj.length === 0) {
        lines.push(`${prefix}${key}: []`);
        return;
      }
      lines.push(`${prefix}${key}:`);
      const base = indent + 1;
      for (const item of obj) {
        if (item !== null && typeof item === "object" && !Array.isArray(item)) {
          let first = true;
          for (const [dk, dv] of Object.entries(item)) {
            if (first) {
              if (dv !== null && typeof dv === "object") {
                lines.push(`${"  ".repeat(base)}- ${dk}:`);
                dumpValue(dv, lines, base + 1, undefined, false);
              } else {
                lines.push(`${"  ".repeat(base)}- ${dk}: ${encodeScalar(dv)}`);
              }
              first = false;
            } else {
              if (dv !== null && typeof dv === "object") {
                lines.push(`${"  ".repeat(base + 1)}${dk}:`);
                dumpValue(dv, lines, base + 2, undefined, false);
              } else {
                lines.push(`${"  ".repeat(base + 1)}${dk}: ${encodeScalar(dv)}`);
              }
            }
          }
          if (first) lines.push(`${"  ".repeat(base)}- {}`);
        } else if (Array.isArray(item)) {
          lines.push(`${"  ".repeat(base)}-`);
          dumpValue(item, lines, base + 1, undefined, false);
        } else {
          lines.push(`${"  ".repeat(base)}- ${encodeScalar(item)}`);
        }
      }
    } else {
      for (const item of obj) dumpValue(item, lines, indent, undefined, false);
    }
  } else {
    if (key !== undefined) lines.push(`${prefix}${key}: ${encodeScalar(obj)}`);
    else lines.push(`${prefix}${encodeScalar(obj)}`);
  }
}

export function loads(text: string): any {
  if (!text || !text.trim()) return {};
  const rawLines = text.split("\n");
  const cleaned: string[] = [];
  for (const l of rawLines) {
    if (!l.trim()) continue;
    const stripped = l.trimStart();
    if (stripped.startsWith("#")) continue;
    cleaned.push(l);
  }
  if (cleaned.length === 0) return {};
  const [result] = parseBlock(cleaned, 0, 0);
  return result;
}

function countIndent(line: string): number {
  let c = 0;
  for (const ch of line) if (ch === " ") c++; else break;
  return Math.floor(c / 2);
}

function splitKv(s: string): [string, string | null] {
  const idx = s.indexOf(":");
  if (idx === -1) return [s.trim(), null];
  const k = s.slice(0, idx).trim();
  const v = s.slice(idx + 1).trim();
  if (v === "") return [k, ""];
  return [k, v];
}

function parseBlock(lines: string[], start: number, baseIndent: number): [any, number] {
  let obj: any = {};
  let isArray = false;
  let arrayItems: any[] = [];
  let i = start;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }
    const indent = countIndent(line);
    if (indent < baseIndent) break;
    if (indent > baseIndent) break;
    const stripped = line.trimStart();
    if (stripped.startsWith("- ")) {
      isArray = true;
      const content = stripped.slice(2);
      if (!content || content.trim() === "") {
        if (i + 1 < lines.length && countIndent(lines[i + 1]) > baseIndent) {
          const [sub, nxt] = parseBlock(lines, i + 1, baseIndent + 1);
          arrayItems.push(sub);
          i = nxt;
        } else {
          arrayItems.push(null);
          i++;
        }
      } else if (content.trim().startsWith('"') || content.trim().startsWith("'")) {
        // quoted scalar array item may contain colon — treat as string
        arrayItems.push(decodeScalar(content.trim()));
        i++;
      } else if (content.includes(":")) {
        const d: any = {};
        const [k, v] = splitKv(content);
        if (v === "" || v === null) {
          if (i + 1 < lines.length && countIndent(lines[i + 1]) > baseIndent) {
            const nextIndent = countIndent(lines[i + 1]);
            if (nextIndent === baseIndent + 1 && !lines[i + 1].trimStart().startsWith("- ")) {
              d[k] = v === "" ? null : decodeScalar(v!);
              let j = i + 1;
              while (j < lines.length) {
                if (countIndent(lines[j]) !== baseIndent + 1) break;
                if (lines[j].trimStart().startsWith("- ")) break;
                const ns = lines[j].trimStart();
                if (!ns.includes(":")) break;
                const [nk, nv] = splitKv(ns);
                if (nv === "" || nv === null) {
                  if (j + 1 < lines.length && countIndent(lines[j + 1]) > baseIndent + 1) {
                    const [sub2, nxt2] = parseBlock(lines, j + 1, baseIndent + 2);
                    d[nk] = sub2;
                    j = nxt2;
                  } else {
                    d[nk] = {};
                    j++;
                  }
                } else {
                  d[nk] = decodeScalar(nv);
                  j++;
                }
              }
              arrayItems.push(d);
              i = j;
              continue;
            } else {
              d[k] = {};
              arrayItems.push(d);
              i++;
            }
          } else {
            d[k] = {};
            arrayItems.push(d);
            i++;
          }
        } else {
          d[k] = decodeScalar(v);
          let j = i + 1;
          while (j < lines.length) {
            if (countIndent(lines[j]) !== baseIndent + 1) break;
            if (lines[j].trimStart().startsWith("- ")) break;
            const ns = lines[j].trimStart();
            if (!ns.includes(":")) break;
            const [nk, nv] = splitKv(ns);
            if (nv === "" || nv === null) {
              if (j + 1 < lines.length && countIndent(lines[j + 1]) > baseIndent + 1) {
                const [sub2, nxt2] = parseBlock(lines, j + 1, baseIndent + 2);
                d[nk] = sub2;
                j = nxt2;
              } else {
                d[nk] = {};
                j++;
              }
            } else {
              d[nk] = decodeScalar(nv);
              j++;
            }
          }
          arrayItems.push(d);
          i = j;
          continue;
        }
      } else {
        arrayItems.push(decodeScalar(content));
        i++;
      }
    } else {
      if (!stripped.includes(":")) { i++; continue; }
      const [k, v] = splitKv(stripped);
      const hasNested = i + 1 < lines.length && countIndent(lines[i + 1]) > baseIndent;
      if (v === "" || v === null) {
        if (hasNested) {
          const nextStripped = lines[i + 1].trimStart();
          if (nextStripped.startsWith("- ")) {
            const [sub, nxt] = parseBlock(lines, i + 1, baseIndent + 1);
            obj[k] = sub;
            i = nxt;
          } else {
            const [sub, nxt] = parseBlock(lines, i + 1, baseIndent + 1);
            obj[k] = sub;
            i = nxt;
          }
        } else {
          obj[k] = {};
          i++;
        }
      } else {
        if (v === "[]") { obj[k] = []; i++; }
        else if (v === "{}") { obj[k] = {}; i++; }
        else { obj[k] = decodeScalar(v); i++; }
      }
    }
  }
  if (isArray) return [arrayItems, i];
  return [obj, i];
}

export function validate(text: string): boolean {
  try { loads(text); return true; } catch { return false; }
}

export function estimateTokens(text: string): number {
  return Math.max(1, Math.floor(text.length / 4));
}

export function tokenSavings(jsonText: string, toonText: string) {
  const jt = estimateTokens(jsonText);
  const tt = estimateTokens(toonText);
  const saving = jt > 0 ? ((jt - tt) / jt) * 100 : 0;
  return { json_tokens: jt, toon_tokens: tt, saving_percent: Math.round(saving * 10) / 10 };
}

export function jsonToToon(jsonText: string): string {
  const obj = JSON.parse(jsonText);
  return dumps(obj);
}

export function toonToJson(toonText: string): string {
  const obj = loads(toonText);
  return JSON.stringify(obj, null, 2);
}

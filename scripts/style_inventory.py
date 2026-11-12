#!/usr/bin/env python3
"""统计前端源码中样式取值的发散度，作为「一致性」透镜的证据。

扫描 CSS / SCSS / Less / Vue / JSX / TSX / HTML 等文件，收集颜色、字号、字重、间距、圆角、阴影、
行高、z-index 的不同取值，输出每类的取值数量、高频值，以及只出现一两次的「离群值」及其位置。
离群值往往就是手写样式、绕开规范的地方。

用法：
    python3 style_inventory.py <源码目录> [--format md|json] [--top 12] [--out 文件]

只用标准库。默认跳过 node_modules、dist、build、.git 等目录。
"""
import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict

EXTS = {".css", ".scss", ".sass", ".less", ".styl", ".vue", ".svelte",
        ".jsx", ".tsx", ".js", ".ts", ".html"}
SKIP_DIRS = {"node_modules", "dist", "build", ".git", ".next", ".nuxt", "out",
             "coverage", ".ux-refine", "vendor", "public", "static", "__pycache__",
             ".turbo", ".cache", "storybook-static"}
MAX_FILE_BYTES = 1_500_000

HEX = re.compile(r"(?<![\w&])#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})\b")
FUNC_COLOR = re.compile(r"\b(?:rgba?|hsla?)\(\s*[\d.%\s,/]+\)")

# CSS 写法 prop: value; 与 JS 写法 propName: value
CSS_PROPS = {
    "font_size": r"font-size|fontSize",
    "font_weight": r"font-weight|fontWeight",
    "line_height": r"line-height|lineHeight",
    "spacing": r"(?:margin|padding)(?:-(?:top|right|bottom|left|inline|block))?|"
               r"(?:margin|padding)(?:Top|Right|Bottom|Left|Inline|Block)?|gap|row-gap|column-gap|rowGap|columnGap",
    "radius": r"border-radius|borderRadius",
    "shadow": r"box-shadow|boxShadow",
    "z_index": r"z-index|zIndex",
}
PROP_RES = {
    k: re.compile(r"(?<![\w-])(?:" + v + r")\s*:\s*['\"]?([^;'\"\n}{]+)")
    for k, v in CSS_PROPS.items()
}
# 只统计「有量纲的字面量」，变量 / token 引用说明已在用规范，单独计数
TOKEN_REF = re.compile(r"var\(--|\$[\w-]+|@[\w-]+|theme\.|token\.|\btokens?\b|\{\{")
LENGTH = re.compile(r"-?\d*\.?\d+(?:px|rem|em|%)?")


def iter_files(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for fn in filenames:
            if os.path.splitext(fn)[1].lower() in EXTS and not fn.endswith(".min.js"):
                p = os.path.join(dirpath, fn)
                try:
                    if os.path.getsize(p) <= MAX_FILE_BYTES:
                        yield p
                except OSError:
                    pass


def norm_color(c):
    c = c.strip().lower()
    if c.startswith("#") and len(c) in (4, 5):  # #abc -> #aabbcc
        c = "#" + "".join(ch * 2 for ch in c[1:])
    return re.sub(r"\s+", "", c)


def norm_value(v):
    v = v.strip().rstrip(",").strip()
    v = re.sub(r"\s*!important", "", v)
    return re.sub(r"\s+", " ", v)


def scan(root):
    values = defaultdict(Counter)          # 类别 -> 取值 -> 次数
    where = defaultdict(lambda: defaultdict(list))  # 类别 -> 取值 -> [位置]
    token_refs = Counter()
    files = 0
    for path in iter_files(root):
        files += 1
        rel = os.path.relpath(path, root)
        is_js = path.endswith((".js", ".ts", ".jsx", ".tsx"))
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
        except OSError:
            continue
        for i, line in enumerate(lines, 1):
            if "http" in line and "#" in line and HEX.search(line.split("http")[0]) is None:
                hex_hits = []
            else:
                hex_hits = HEX.findall(line)
            # JS 文件里 # 常见于注释 / 锚点，只在疑似样式上下文中取色
            if is_js and hex_hits and not re.search(r"['\"`]\s*#|color|background|border|fill|stroke", line, re.I):
                hex_hits = []
            for c in hex_hits + FUNC_COLOR.findall(line):
                n = norm_color(c)
                values["color"][n] += 1
                where["color"][n].append(f"{rel}:{i}")
            for cat, rx in PROP_RES.items():
                for m in rx.finditer(line):
                    raw = norm_value(m.group(1))
                    if not raw:
                        continue
                    if TOKEN_REF.search(raw):
                        token_refs[cat] += 1
                        continue
                    if cat in ("spacing", "radius"):
                        # 多值简写拆开统计，每个长度单独计
                        parts = [p for p in LENGTH.findall(raw) if p not in ("0", "0px")]
                        if not parts:
                            continue
                        for p in parts:
                            if re.fullmatch(r"-?\d*\.?\d+", p) and is_js:
                                p += "px"  # JS 里数字默认 px
                            values[cat][p] += 1
                            where[cat][p].append(f"{rel}:{i}")
                    else:
                        if cat == "font_size" and is_js and re.fullmatch(r"\d+", raw):
                            raw += "px"
                        if len(raw) > 60:
                            continue
                        values[cat][raw] += 1
                        where[cat][raw].append(f"{rel}:{i}")
    return files, values, where, token_refs


SUGGEST = {
    "color": "中性灰 5–7 级 + 主色 + 功能色（成功/警告/错误/信息），总数通常 15 个以内",
    "font_size": "5–7 级字号刻度",
    "font_weight": "2–3 种字重",
    "line_height": "2–3 种行高",
    "spacing": "以 4 或 8 为基数的 6–8 级间距刻度",
    "radius": "1–2 种圆角",
    "shadow": "2–3 级阴影",
    "z_index": "集中定义的层级常量",
}
LABEL = {"color": "颜色", "font_size": "字号", "font_weight": "字重", "line_height": "行高",
         "spacing": "间距", "radius": "圆角", "shadow": "阴影", "z_index": "z-index"}


def build_report(root, top):
    files, values, where, token_refs = scan(root)
    report = {"root": os.path.abspath(root), "files_scanned": files, "categories": {}}
    for cat in LABEL:
        cnt = values.get(cat, Counter())
        rare = [(v, n) for v, n in cnt.items() if n <= 2]
        report["categories"][cat] = {
            "label": LABEL[cat],
            "distinct_literal_values": len(cnt),
            "literal_uses": sum(cnt.values()),
            "token_refs": token_refs.get(cat, 0),
            "suggested": SUGGEST[cat],
            "top": [{"value": v, "count": n, "sample": where[cat][v][:3]} for v, n in cnt.most_common(top)],
            "rare_count": len(rare),
            "rare_samples": [{"value": v, "count": n, "at": where[cat][v][:2]}
                             for v, n in sorted(rare)[:top]],
        }
    return report


def to_md(r):
    out = [f"# 样式取值发散度 · {r['root']}", "",
           f"扫描文件 {r['files_scanned']} 个。「字面量」= 直接写死的值；「token 引用」= 通过变量 / 主题引用的次数。", "",
           "| 类别 | 不同字面量取值 | 字面量使用次数 | token 引用 | 仅出现 1–2 次的取值 | 参考规模 |",
           "|---|---|---|---|---|---|"]
    for c in r["categories"].values():
        out.append(f"| {c['label']} | {c['distinct_literal_values']} | {c['literal_uses']} | {c['token_refs']} | "
                   f"{c['rare_count']} | {c['suggested']} |")
    for c in r["categories"].values():
        if not c["top"]:
            continue
        out += ["", f"## {c['label']}", "", "高频取值：",
                ", ".join(f"`{t['value']}`×{t['count']}" for t in c["top"])]
        if c["rare_samples"]:
            out += ["", "离群取值（可能是手写样式 / 绕开规范）："]
            out += [f"- `{s['value']}` ×{s['count']} — {', '.join(s['at'])}" for s in c["rare_samples"]]
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root")
    ap.add_argument("--format", choices=["md", "json"], default="md")
    ap.add_argument("--top", type=int, default=12)
    ap.add_argument("--out")
    a = ap.parse_args()
    if not os.path.isdir(a.root):
        sys.exit(f"不是目录：{a.root}")
    r = build_report(a.root, a.top)
    text = json.dumps(r, ensure_ascii=False, indent=2) if a.format == "json" else to_md(r)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"已写入 {a.out}")
    else:
        print(text)


if __name__ == "__main__":
    main()

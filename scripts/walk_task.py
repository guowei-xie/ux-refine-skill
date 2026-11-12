#!/usr/bin/env python3
"""按 JSON 步骤走查任务路径：逐步执行用户操作，记录每一步的截图、原生对话框（alert/confirm/prompt）、
控制台报错、失败请求、地址跳转与耗时，输出步骤表（walk.md）和明细（walk.json）。

用法：
    python3 walk_task.py tasks.json --out .ux-refine/walk/before

tasks.json 示例（// 注释仅为说明，实际 JSON 文件里不能写注释）：
{
  "base_url": "http://localhost:8000",
  "viewport": "1366x768",
  "storage_state": ".ux-refine/auth.json",      // 可选，登录态（ui_snapshot.py --save-auth 生成）
  "dialog": "dismiss",                           // 原生对话框的处理：dismiss（默认）或 accept
  "screenshots": "each",                         // each（每步截图，默认）/ end（每个任务结束截一张）/ none
  "tasks": [
    {
      "name": "审核待审核订单",
      "steps": [
        {"do": "goto",   "url": "/index.html", "note": "从工作台出发"},
        {"do": "check",  "target": "text=待审核", "probe": "is_link", "note": "待审核卡片能否点击"},
        {"do": "goto",   "url": "/orders.html"},
        {"do": "select", "target": "select", "value": "1"},
        {"do": "click",  "target": "text=查询"},
        {"do": "check",  "target": "#t tr", "probe": "count"},
        {"do": "click",  "target": "#t a:has-text('审核')", "nth": 0}
      ]
    }
  ]
}

动作（do）：
    goto  url             打开地址（相对 base_url 或完整 URL）
    click target          点击（Playwright 选择器，如 text=查询、css、role=button[name="保存"]）
    fill  target value    输入
    press target key      按键（Enter、Escape、Tab……）
    select target value   下拉选择（value 或 label）
    hover target          悬停
    check target probe    观察而非操作：count / text / texts / visible / enabled / is_link / value
                          可加 "expect": 期望值，不符时该步标记为 ✗
    eval  js              在页面执行 JS 表达式并记录返回值
    wait  ms | target     等待毫秒数或等待元素出现
    screenshot            额外截一张图
任一步可加 "nth": N 选第 N 个匹配元素、"note": 说明（写进步骤表）、"optional": true（失败不计为问题）。

统计口径：用户操作数 = click/fill/press/select/hover 的步数；跳转次数 = 页面地址（不含 #锚点）变化的次数。
依赖：pip install playwright && playwright install chromium
"""
import argparse
import json
import os
import re
import sys
import time

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sys.exit("缺少 playwright：pip install playwright && playwright install chromium")

USER_ACTIONS = {"click", "fill", "press", "select", "hover"}


def slug(s):
    return re.sub(r"[^\w\-]+", "_", s).strip("_")[:40] or "task"


def strip_hash(u):
    return u.split("#", 1)[0]


def loc(page, step):
    l = page.locator(step["target"])
    return l.nth(step["nth"]) if "nth" in step else l.first


def probe(page, step):
    p = step.get("probe", "count")
    if p == "count":
        return page.locator(step["target"]).count()
    if p == "texts":
        return [t.strip() for t in page.locator(step["target"]).all_inner_texts()][:30]
    if page.locator(step["target"]).count() == 0:
        return None if p in ("text", "value") else False
    el = loc(page, step)
    if p == "text":
        return el.inner_text().strip()[:300]
    if p == "visible":
        return el.is_visible()
    if p == "enabled":
        return el.is_enabled()
    if p == "value":
        return el.input_value()
    if p == "is_link":
        return el.evaluate("e => !!(e.closest('a[href]:not([href=\"#\"])') || e.closest('button') "
                           "|| e.onclick || e.closest('[onclick]') || e.closest('[role=button],[role=link]'))")
    raise ValueError(f"未知 probe：{p}")


def run_step(page, step, base, timeout):
    d = step["do"]
    if d == "goto":
        url = step["url"] if step["url"].startswith("http") else base.rstrip("/") + "/" + step["url"].lstrip("/")
        page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        try:
            page.wait_for_load_state("networkidle", timeout=min(timeout, 8000))
        except Exception:
            pass
        return None
    if d == "click":
        loc(page, step).click(timeout=timeout)
    elif d == "fill":
        loc(page, step).fill(str(step.get("value", "")), timeout=timeout)
    elif d == "press":
        loc(page, step).press(step["key"], timeout=timeout)
    elif d == "select":
        el = loc(page, step)
        try:
            el.select_option(value=str(step["value"]), timeout=timeout)
        except Exception:
            el.select_option(label=str(step["value"]), timeout=timeout)
    elif d == "hover":
        loc(page, step).hover(timeout=timeout)
    elif d == "check":
        return probe(page, step)
    elif d == "eval":
        return page.evaluate(step["js"])
    elif d == "wait":
        if "target" in step:
            page.wait_for_selector(step["target"], timeout=timeout)
        else:
            page.wait_for_timeout(int(step.get("ms", 500)))
        return None
    elif d == "screenshot":
        return None
    else:
        raise ValueError(f"未知动作：{d}")
    # 操作后给页面一点时间响应（动画、请求、跳转）
    try:
        page.wait_for_load_state("networkidle", timeout=3000)
    except Exception:
        pass
    page.wait_for_timeout(200)
    return None


def describe(step):
    d = step["do"]
    if d == "goto":
        return f"打开 {step['url']}"
    if d == "fill":
        return f"在 {step['target']} 输入「{step.get('value', '')}」"
    if d == "press":
        return f"在 {step['target']} 按 {step['key']}"
    if d == "select":
        return f"在 {step['target']} 选择「{step['value']}」"
    if d == "check":
        return f"观察 {step['target']} [{step.get('probe', 'count')}]"
    if d == "eval":
        return f"执行 JS"
    if d == "wait":
        return f"等待 {step.get('target', str(step.get('ms', 500)) + 'ms')}"
    return f"{ {'click': '点击', 'hover': '悬停', 'screenshot': '截图'}.get(d, d)} {step.get('target', '')}".strip()


def walk(cfg, out):
    os.makedirs(out, exist_ok=True)
    w, h = (int(x) for x in cfg.get("viewport", "1366x768").lower().split("x"))
    shots_mode = cfg.get("screenshots", "each")
    timeout = int(cfg.get("timeout_ms", 8000))
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not cfg.get("headed", False))
        kw = {"viewport": {"width": w, "height": h}, "locale": cfg.get("locale", "zh-CN")}
        if cfg.get("storage_state"):
            kw["storage_state"] = cfg["storage_state"]
        for ti, task in enumerate(cfg["tasks"], 1):
            ctx = browser.new_context(**kw)
            page = ctx.new_page()
            ev = {"dialogs": [], "console": [], "failed": []}

            def on_dialog(dg, ev=ev):
                ev["dialogs"].append(f"{dg.type}: {dg.message}")
                dg.accept() if cfg.get("dialog") == "accept" else dg.dismiss()

            page.on("dialog", on_dialog)
            page.on("console", lambda m, ev=ev: ev["console"].append(m.text[:300]) if m.type == "error" else None)
            page.on("pageerror", lambda e, ev=ev: ev["console"].append(str(e)[:300]))
            page.on("response", lambda r, ev=ev: ev["failed"].append(f"{r.status} {r.url[:150]}") if r.status >= 400 else None)
            page.on("requestfailed", lambda r, ev=ev: ev["failed"].append(f"failed {r.url[:150]}"))
            tres = {"name": task["name"], "steps": []}
            prev_url = None
            t_task = time.time()
            for si, step in enumerate(task["steps"], 1):
                for k in ev:
                    ev[k].clear()
                rec = {"i": si, "do": step["do"], "desc": describe(step), "note": step.get("note", "")}
                t0 = time.time()
                try:
                    val = run_step(page, step, cfg["base_url"], timeout)
                    rec["ok"] = True
                    if step["do"] in ("check", "eval"):
                        rec["result"] = val
                        if "expect" in step and val != step["expect"]:
                            rec["ok"] = False
                            rec["error"] = f"期望 {json.dumps(step['expect'], ensure_ascii=False)}，实际 {json.dumps(val, ensure_ascii=False)}"
                except Exception as e:
                    rec["ok"] = False
                    rec["error"] = f"{type(e).__name__}: {str(e).splitlines()[0][:200]}"
                rec["ms"] = int((time.time() - t0) * 1000)
                rec["optional"] = bool(step.get("optional"))
                rec["url"] = page.url
                rec["navigated"] = prev_url is not None and strip_hash(page.url) != strip_hash(prev_url)
                prev_url = page.url
                rec["dialogs"] = list(ev["dialogs"])
                rec["errors"] = list(ev["console"])
                rec["failed_requests"] = list(ev["failed"])
                last = si == len(task["steps"])
                if shots_mode == "each" or step["do"] == "screenshot" or (shots_mode == "end" and last):
                    path = os.path.join(out, f"{ti:02d}-{slug(task['name'])}-{si:02d}.png")
                    try:
                        page.screenshot(path=path)
                        rec["screenshot"] = path
                    except Exception:
                        pass
                tres["steps"].append(rec)
            st = tres["steps"]
            tres["summary"] = {
                "user_actions": sum(1 for s in st if s["do"] in USER_ACTIONS),
                "navigations": sum(1 for s in st if s["navigated"]),
                "dialogs": sum(len(s["dialogs"]) for s in st),
                "errors": sum(len(s["errors"]) for s in st),
                "failed_steps": sum(1 for s in st if not s["ok"] and not s["optional"]),
                "total_ms": int((time.time() - t_task) * 1000),
            }
            results.append(tres)
            ctx.close()
            sm = tres["summary"]
            print(f"[{task['name']}] 操作 {sm['user_actions']} 步 · 跳转 {sm['navigations']} 次 · "
                  f"对话框 {sm['dialogs']} · 报错 {sm['errors']} · 失败步骤 {sm['failed_steps']}", flush=True)
        browser.close()
    with open(os.path.join(out, "walk.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    with open(os.path.join(out, "walk.md"), "w", encoding="utf-8") as f:
        f.write(to_md(results, cfg))
    print(f"步骤表：{os.path.join(out, 'walk.md')}")


def cell(s):
    return str(s).replace("|", "\\|").replace("\n", " ")


def to_md(results, cfg):
    out = [f"# 任务路径走查 · {cfg['base_url']} · 视口 {cfg.get('viewport', '1366x768')}", "",
           "| 任务 | 用户操作 | 跳转 | 原生对话框 | 报错 | 失败步骤 | 耗时 |", "|---|---|---|---|---|---|---|"]
    for t in results:
        s = t["summary"]
        out.append(f"| {cell(t['name'])} | {s['user_actions']} | {s['navigations']} | {s['dialogs']} | "
                   f"{s['errors']} | {s['failed_steps']} | {s['total_ms'] / 1000:.1f}s |")
    for t in results:
        out += ["", f"## {t['name']}", "", "| # | 动作 | 结果 | 发生了什么 | 截图 |", "|---|---|---|---|---|"]
        for s in t["steps"]:
            mark = "✓" if s["ok"] else ("–" if s["optional"] else "✗")
            happened = []
            if "result" in s:
                happened.append(f"结果：{json.dumps(s['result'], ensure_ascii=False)[:120]}")
            if s.get("error"):
                happened.append(f"失败：{s['error']}")
            if s["navigated"]:
                happened.append(f"跳转到 {s['url']}")
            happened += [f"弹出 {d}" for d in s["dialogs"]]
            happened += [f"报错 {e}" for e in s["errors"][:3]]
            happened += [f"请求 {r}" for r in s["failed_requests"][:3]]
            if s["note"]:
                happened.append(f"（{s['note']}）")
            shot = os.path.basename(s["screenshot"]) if s.get("screenshot") else ""
            out.append(f"| {s['i']} | {cell(s['desc'])} | {mark} | {cell('；'.join(happened))} | {shot} |")
    out += ["", "原生对话框（alert/confirm）出现本身就值得注意：它打断操作、样式不可控、无法说明上下文。"]
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tasks_json")
    ap.add_argument("--out", default=".ux-refine/walk/before")
    ap.add_argument("--base-url", help="覆盖 tasks.json 里的 base_url（改前改后用同一份步骤文件时方便）")
    a = ap.parse_args()
    with open(a.tasks_json, encoding="utf-8") as f:
        cfg = json.load(f)
    if a.base_url:
        cfg["base_url"] = a.base_url
    if not cfg.get("base_url") or not cfg.get("tasks"):
        sys.exit("tasks.json 需要 base_url 与 tasks")
    walk(cfg, a.out)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""用 Playwright 批量截图：多个路由 × 多个视口，同时记录控制台报错、页面异常、
失败请求、加载耗时与最终落地地址（用于发现被重定向到登录页的情况）。

用法：
    # 截图
    python3 ui_snapshot.py --base-url http://localhost:3000 \
        --routes / /orders /orders/123 --out .ux-refine/screenshots/before

    # 路由也可以放在文件里，每行一个，# 开头为注释；可写成「名称 路由」
    python3 ui_snapshot.py --base-url http://localhost:3000 --routes-file routes.txt --out ...

    # 需要登录：先打开一个有界面的浏览器让用户手动登录，保存登录态
    python3 ui_snapshot.py --base-url http://localhost:3000 --save-auth .ux-refine/auth.json
    # 之后截图时带上
    python3 ui_snapshot.py ... --storage-state .ux-refine/auth.json

常用参数：
    --viewports desktop=1440x900,laptop=1366x768,mobile=390x844   （默认 desktop,laptop）
    --full-page      截整页（默认只截首屏，首屏更接近用户第一眼）
    --wait-ms 800    页面 networkidle 后再等多少毫秒（等动画、懒加载）
    --wait-for <CSS选择器>  每页等到该元素出现再截图

输出：<out>/<名称>-<视口>.png 以及 <out>/report.json。
依赖：pip install playwright && playwright install chromium
"""
import argparse
import json
import os
import re
import sys
import time

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
except ImportError:
    sys.exit("缺少 playwright：pip install playwright && playwright install chromium")

DEFAULT_VIEWPORTS = "desktop=1440x900,laptop=1366x768"


def parse_viewports(s):
    presets = {"desktop": "1440x900", "laptop": "1366x768", "wide": "1920x1080",
               "tablet": "768x1024", "mobile": "390x844"}
    out = []
    for item in s.split(","):
        item = item.strip()
        if not item:
            continue
        name, _, size = item.partition("=")
        size = size or presets.get(name)
        if not size:
            sys.exit(f"无法识别的视口：{item}（可写 name=WxH 或预设 {', '.join(presets)}）")
        w, h = size.lower().split("x")
        out.append((name, int(w), int(h)))
    return out


def load_routes(args):
    routes = []
    if args.routes_file:
        with open(args.routes_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split(None, 1)
                routes.append((parts[0], parts[1]) if len(parts) == 2 else (None, parts[0]))
    for r in args.routes or []:
        routes.append((None, r))
    named = []
    for name, route in routes:
        if not name:
            path = re.sub(r"^https?://[^/]+", "", route)
            path = re.sub(r"\.(html?|php|aspx?)(?=$|[?#])", "", path)
            name = re.sub(r"[^\w\-]+", "_", path.strip("/")).strip("_") or "home"
        named.append((name[:80], route))
    return named


def save_auth(args):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto(args.base_url)
        print("已打开浏览器，请在其中完成登录。登录完成后回到终端按回车保存登录态……", flush=True)
        try:
            input()
        except EOFError:
            print("无交互输入，等待 120 秒后保存。", flush=True)
            time.sleep(120)
        os.makedirs(os.path.dirname(os.path.abspath(args.save_auth)), exist_ok=True)
        ctx.storage_state(path=args.save_auth)
        browser.close()
    print(f"登录态已保存到 {args.save_auth}（含 cookie，勿提交到仓库）")


def snapshot(args):
    routes = load_routes(args)
    if not routes:
        sys.exit("没有路由：用 --routes 或 --routes-file 指定")
    viewports = parse_viewports(args.viewports)
    os.makedirs(args.out, exist_ok=True)
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed)
        for vp_name, w, h in viewports:
            ctx_kwargs = {"viewport": {"width": w, "height": h}, "device_scale_factor": 1,
                          "locale": args.locale}
            if args.storage_state:
                ctx_kwargs["storage_state"] = args.storage_state
            ctx = browser.new_context(**ctx_kwargs)
            for name, route in routes:
                url = route if route.startswith("http") else args.base_url.rstrip("/") + "/" + route.lstrip("/")
                page = ctx.new_page()
                console, page_errors, failed = [], [], []
                page.on("console", lambda m, c=console: c.append({"type": m.type, "text": m.text[:500]})
                        if m.type in ("error", "warning") else None)
                page.on("pageerror", lambda e, pe=page_errors: pe.append(str(e)[:500]))
                page.on("response", lambda r, fl=failed: fl.append({"status": r.status, "url": r.url[:300]})
                        if r.status >= 400 else None)
                page.on("requestfailed", lambda r, fl=failed: fl.append({"status": "failed", "url": r.url[:300],
                                                                          "error": (r.failure or "")[:200]}))
                rec = {"name": name, "route": route, "viewport": vp_name, "size": f"{w}x{h}", "url": url}
                t0 = time.time()
                try:
                    resp = page.goto(url, wait_until="domcontentloaded", timeout=args.timeout_ms)
                    rec["dom_ready_ms"] = int((time.time() - t0) * 1000)
                    try:
                        page.wait_for_load_state("networkidle", timeout=args.timeout_ms)
                    except PWTimeout:
                        rec["note"] = "networkidle 超时（可能有轮询或长连接），已继续截图"
                    if args.wait_for:
                        try:
                            page.wait_for_selector(args.wait_for, timeout=args.timeout_ms)
                        except PWTimeout:
                            rec["note"] = f"等待 {args.wait_for} 超时"
                    page.wait_for_timeout(args.wait_ms)
                    rec["settled_ms"] = int((time.time() - t0) * 1000)
                    rec["http_status"] = resp.status if resp else None
                    rec["final_url"] = page.url
                    rec["title"] = page.title()
                    if page.url.rstrip("/") != url.rstrip("/"):
                        rec["redirected"] = True
                        if re.search(r"login|signin|sso|auth|passport", page.url, re.I):
                            rec["note"] = "被重定向到登录页：需要 --save-auth 获取登录态"
                    # 页面整体尺寸，辅助判断横向溢出
                    dims = page.evaluate("() => ({sw: document.documentElement.scrollWidth,"
                                         " sh: document.documentElement.scrollHeight})")
                    rec["scroll_size"] = f"{dims['sw']}x{dims['sh']}"
                    rec["horizontal_overflow"] = dims["sw"] > w + 1
                    shot = os.path.join(args.out, f"{name}-{vp_name}.png")
                    page.screenshot(path=shot, full_page=args.full_page)
                    rec["screenshot"] = shot
                except Exception as e:  # 单页失败不影响其他页
                    rec["error"] = f"{type(e).__name__}: {str(e)[:300]}"
                rec["console"] = console[:30]
                rec["page_errors"] = page_errors[:30]
                rec["failed_requests"] = failed[:30]
                results.append(rec)
                page.close()
                flag = "✗" if "error" in rec else ("!" if rec.get("note") or page_errors or failed else "✓")
                print(f"{flag} {vp_name:8} {route}  {rec.get('settled_ms', '-')}ms  {rec.get('note', '')}", flush=True)
            ctx.close()
        browser.close()
    report_path = os.path.join(args.out, "report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    n_err = sum(1 for r in results if "error" in r)
    n_overflow = sum(1 for r in results if r.get("horizontal_overflow"))
    n_console = sum(1 for r in results if r.get("page_errors") or any(c["type"] == "error" for c in r["console"]))
    print(f"\n完成 {len(results)} 张；截图失败 {n_err}；有 JS 报错 {n_console}；横向溢出 {n_overflow}。报告：{report_path}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--routes", nargs="*")
    ap.add_argument("--routes-file")
    ap.add_argument("--out", default=".ux-refine/screenshots/before")
    ap.add_argument("--viewports", default=DEFAULT_VIEWPORTS)
    ap.add_argument("--storage-state")
    ap.add_argument("--save-auth", help="打开有界面浏览器手动登录，并把登录态保存到此路径")
    ap.add_argument("--full-page", action="store_true")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--wait-ms", type=int, default=800)
    ap.add_argument("--wait-for")
    ap.add_argument("--timeout-ms", type=int, default=20000)
    ap.add_argument("--locale", default="zh-CN")
    args = ap.parse_args()
    if args.save_auth:
        save_auth(args)
    else:
        snapshot(args)


if __name__ == "__main__":
    main()

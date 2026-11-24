# -*- coding: utf-8 -*-
"""
双色球概率实验室 · 本地服务

    python server.py            # 启动并打开 http://127.0.0.1:8899
    python server.py --no-open  # 只启动，不自动开浏览器

职责：
    1. 提供页面静态文件（index.html / assets / 单文件版）
    2. 用 SQLite 保存推演记录（data/ssq.db）
    3. 提供按期号 / 日期查询推演记录与开奖结果的接口

数据来源：assets/data.js（由 build_data.py 生成），文件更新后自动同步进库。
"""
import argparse
import datetime as dt
import ipaddress
import json
import os
import posixpath
import re
import sqlite3
import sys
import threading
import time
import webbrowser
from contextlib import closing
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_JS = os.path.join(BASE, "assets", "data.js")
DB_PATH = os.path.join(BASE, "data", "ssq.db")
SINGLE_FILE = "双色球概率实验室-单文件版.html"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS draws (
    issue TEXT PRIMARY KEY,
    day   TEXT NOT NULL,
    reds  TEXT NOT NULL,
    blue  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_draws_day ON draws(day);

CREATE TABLE IF NOT EXISTS predictions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    issue          TEXT NOT NULL,
    day            TEXT,
    strategy       TEXT NOT NULL,
    strategy_label TEXT,
    picks          TEXT NOT NULL,
    locks          TEXT,
    qty            INTEGER,
    created_at     TEXT,
    ts             INTEGER
);
CREATE INDEX IF NOT EXISTS idx_pred_issue ON predictions(issue);
CREATE INDEX IF NOT EXISTS idx_pred_day ON predictions(day);

CREATE TABLE IF NOT EXISTS checks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    issue      TEXT NOT NULL,
    day        TEXT,
    reds       TEXT NOT NULL,
    blue       INTEGER NOT NULL,
    prize      TEXT,
    red_hits   INTEGER,
    blue_hit   INTEGER,
    created_at TEXT,
    ts         INTEGER
);
CREATE INDEX IF NOT EXISTS idx_checks_issue ON checks(issue);
CREATE INDEX IF NOT EXISTS idx_checks_day ON checks(day);
"""

_lock = threading.Lock()
_draw_mtime = {"value": 0.0}


def connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with closing(connect()) as conn:
        conn.executescript(SCHEMA)
        conn.commit()


def read_draws_js():
    """从 assets/data.js 解析开奖数据。"""
    with open(DATA_JS, "r", encoding="utf-8") as f:
        raw = f.read()
    m = re.search(r'window\.SSQ_RAW\s*=\s*"([^"]+)"', raw)
    if not m:
        raise RuntimeError("assets/data.js 里找不到 SSQ_RAW")
    rows = []
    for chunk in m.group(1).split(";"):
        if not chunk.strip():
            continue
        issue, day, reds, blue = chunk.split("|")
        rows.append((issue.strip(), day.strip(), reds.strip(), int(blue)))
    return rows


def sync_draws(force=False):
    """data.js 变化时把开奖表刷新一遍（mtime 判断，开销可忽略）。"""
    try:
        mtime = os.path.getmtime(DATA_JS)
    except OSError:
        return
    with _lock:
        if not force and mtime == _draw_mtime["value"]:
            return
        rows = read_draws_js()
        with closing(connect()) as conn:
            conn.execute("BEGIN")
            conn.execute("DELETE FROM draws")
            conn.executemany(
                "INSERT OR REPLACE INTO draws(issue, day, reds, blue) VALUES (?,?,?,?)", rows
            )
            conn.execute(
                """
                UPDATE predictions
                   SET day = (SELECT day FROM draws WHERE draws.issue = predictions.issue)
                 WHERE issue IN (SELECT issue FROM draws)
                   AND (day IS NULL OR day <> (SELECT day FROM draws WHERE draws.issue = predictions.issue))
                """
            )
            conn.commit()
        _draw_mtime["value"] = mtime


def norm_query(q):
    s = (q or "").strip().replace("/", "-").replace(".", "-")
    if re.fullmatch(r"\d{7}", s):
        return ("issue", "issue = ?", [s])
    if re.fullmatch(r"\d{8}", s):
        return ("date", "day = ?", [f"{s[:4]}-{s[4:6]}-{s[6:]}"])
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return ("date", "day = ?", [s])
    m = re.fullmatch(r"(\d{1,2})-(\d{1,2})", s)
    if m:
        return ("date", "day LIKE ?", [f"%-{int(m.group(1)):02d}-{int(m.group(2)):02d}"])
    if re.fullmatch(r"\d{4}-\d{2}", s):
        return ("date", "day LIKE ?", [s + "-%"])
    return (None, None, None)


def hits_of(picks, draw):
    if not draw:
        return None
    reds = {int(x) for x in draw["reds"].split(",") if x.strip()}
    out = []
    for p in picks:
        rh = sum(1 for x in p["red"] if int(x) in reds)
        bh = 1 if int(p["blue"]) == int(draw["blue"]) else 0
        out.append({"red": rh, "blue": bh})
    return out


def next_draw_day(d):
    """双色球每周二、四、日开奖，返回 d 之后的下一个开奖日。"""
    for _ in range(10):
        d = d + dt.timedelta(days=1)
        if d.weekday() in (1, 3, 6):  # 周二 / 周四 / 周日
            return d
    return d


def expected_day(issue, conn):
    """目标期还没开奖时，按开奖日历推算它的开奖日期。"""
    row = conn.execute("SELECT issue, day FROM draws ORDER BY issue DESC LIMIT 1").fetchone()
    if not row:
        return None
    latest_issue = int(row["issue"])
    want = int(issue)
    if want <= latest_issue:
        return None
    day = dt.date.fromisoformat(row["day"])
    for _ in range(max(0, want - latest_issue)):
        day = next_draw_day(day)
    return day.isoformat()


def row_to_prediction(row, draws_by_issue):
    picks = json.loads(row["picks"])
    draw = draws_by_issue.get(row["issue"])
    return {
        "id": row["id"],
        "issue": row["issue"],
        "day": row["day"],
        "strategy": row["strategy"],
        "strategyLabel": row["strategy_label"],
        "qty": row["qty"],
        "picks": picks,
        "locks": json.loads(row["locks"]) if row["locks"] else None,
        "createdAt": row["created_at"],
        "ts": row["ts"],
        "hits": hits_of(picks, draw),
    }


def row_to_check(row):
    return {
        "id": row["id"],
        "issue": row["issue"],
        "day": row["day"],
        "reds": [int(x) for x in row["reds"].split(",") if x.strip()],
        "blue": row["blue"],
        "prize": row["prize"],
        "redHits": row["red_hits"],
        "blueHit": row["blue_hit"],
        "createdAt": row["created_at"],
        "ts": row["ts"],
    }


class Handler(SimpleHTTPRequestHandler):
    server_version = "SSQLab/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), fmt % args))

    # ---------- helpers ----------
    def send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return None

    def api_path(self):
        return unquote(urlparse(self.path).path)

    # ---------- 静态文件白名单 / Host 校验 ----------
    def host_allowed(self):
        """只接受回环名和 IP 字面量，挡掉 DNS rebinding 使用的域名 Host。"""
        host = (self.headers.get("Host") or "").strip()
        if not host:
            return True  # HTTP/1.0 客户端可能不带 Host
        if host.startswith("["):  # IPv6 字面量 [::1]:8899
            end = host.find("]")
            name = host[1:end] if end != -1 else host
        else:
            name = host.rsplit(":", 1)[0]
        name = name.strip().lower()
        if name in LOOPBACK_HOSTS:
            return True
        try:
            ipaddress.ip_address(name)
            return True
        except ValueError:
            return False

    def guard(self, head=False):
        if self.host_allowed():
            return True
        if head:
            self.send_response(403)
            self.send_header("Content-Length", "0")
            self.end_headers()
        else:
            self.send_json({"ok": False, "error": "Host 不被允许（只服务本机地址）"}, 403)
        return False

    def static_path_allowed(self, path):
        norm = posixpath.normpath(unquote(path).replace("\\", "/"))
        if norm in ("/", "/index.html"):
            return True
        if norm == "/" + SINGLE_FILE:
            return True
        return norm.startswith("/assets/")

    def translate_path(self, path):
        # 目录穿越（/assets/../server.py、%2e%2e）在 normpath 后落到白名单外，一并挡住
        if not self.static_path_allowed(urlparse(path).path):
            return os.path.join(self.directory, ".static-forbidden")
        return super().translate_path(path)

    # ---------- GET ----------
    def do_GET(self):
        if not self.guard():
            return
        path = self.api_path()
        if not path.startswith("/api/"):
            return super().do_GET()
        try:
            sync_draws()
            query = parse_qs(urlparse(self.path).query)

            if path == "/api/health":
                with closing(connect()) as conn:
                    draws = conn.execute("SELECT COUNT(*) c FROM draws").fetchone()["c"]
                    preds = conn.execute("SELECT COUNT(*) c FROM predictions").fetchone()["c"]
                    checks = conn.execute("SELECT COUNT(*) c FROM checks").fetchone()["c"]
                    latest = conn.execute("SELECT issue FROM draws ORDER BY issue DESC LIMIT 1").fetchone()
                return self.send_json({
                    "ok": True,
                    "draws": draws,
                    "predictions": preds,
                    "checks": checks,
                    "latest": latest["issue"] if latest else None,
                    "db": os.path.relpath(DB_PATH, BASE).replace("\\", "/"),
                })

            if path == "/api/predictions":
                limit = max(1, min(200, int((query.get("limit") or ["20"])[0])))
                args, params = "", []
                if query.get("issue"):
                    args, params = "WHERE issue = ?", [query["issue"][0]]
                elif query.get("day"):
                    args, params = "WHERE day = ?", [query["day"][0]]
                with closing(connect()) as conn:
                    total = conn.execute(f"SELECT COUNT(*) c FROM predictions {args}", params).fetchone()["c"]
                    rows = conn.execute(
                        f"SELECT * FROM predictions {args} ORDER BY ts DESC, id DESC LIMIT ?",
                        params + [limit],
                    ).fetchall()
                    draws = {r["issue"]: r for r in conn.execute("SELECT * FROM draws").fetchall()}
                return self.send_json({
                    "ok": True,
                    "total": total,
                    "items": [row_to_prediction(r, draws) for r in rows],
                })

            if path == "/api/query":
                q = (query.get("q") or [""])[0]
                kind, where, params = norm_query(q)
                if not kind:
                    return self.send_json(
                        {"ok": False, "error": "请输入 7 位期号或日期，如 2026133 / 2026-11-17"}, 400
                    )
                with closing(connect()) as conn:
                    draw = conn.execute(f"SELECT * FROM draws WHERE {where} ORDER BY issue DESC LIMIT 1", params).fetchone()
                    rows = conn.execute(
                        f"SELECT * FROM predictions WHERE {where} ORDER BY ts DESC, id DESC LIMIT 100", params
                    ).fetchall()
                    checks = conn.execute(
                        f"SELECT * FROM checks WHERE {where} ORDER BY ts DESC, id DESC LIMIT 100", params
                    ).fetchall()
                    draws = {r["issue"]: r for r in conn.execute("SELECT * FROM draws").fetchall()}
                return self.send_json({
                    "ok": True,
                    "query": {"type": kind, "value": q.strip()},
                    "draw": (
                        {"issue": draw["issue"], "day": draw["day"], "reds": draw["reds"], "blue": draw["blue"]}
                        if draw else None
                    ),
                    "items": [row_to_prediction(r, draws) for r in rows],
                    "checks": [row_to_check(r) for r in checks],
                })

            if path == "/api/checks":
                limit = max(1, min(200, int((query.get("limit") or ["12"])[0])))
                args, params = "", []
                if query.get("issue"):
                    args, params = "WHERE issue = ?", [query["issue"][0]]
                elif query.get("day"):
                    args, params = "WHERE day = ?", [query["day"][0]]
                with closing(connect()) as conn:
                    total = conn.execute(f"SELECT COUNT(*) c FROM checks {args}", params).fetchone()["c"]
                    rows = conn.execute(
                        f"SELECT * FROM checks {args} ORDER BY ts DESC, id DESC LIMIT ?",
                        params + [limit],
                    ).fetchall()
                return self.send_json({
                    "ok": True,
                    "total": total,
                    "items": [row_to_check(r) for r in rows],
                })

            return self.send_json({"ok": False, "error": "未知接口"}, 404)
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write(f"API 错误: {exc}\n")
            return self.send_json({"ok": False, "error": str(exc)}, 500)

    def do_HEAD(self):
        if not self.guard(head=True):
            return
        return super().do_HEAD()

    # ---------- POST ----------
    def do_POST(self):
        if not self.guard():
            return
        path = self.api_path()
        if path not in ("/api/predictions", "/api/checks"):
            return self.send_json({"ok": False, "error": "未知接口"}, 404)
        try:
            sync_draws()
            body = self.read_json()
            if body is None:
                return self.send_json({"ok": False, "error": "请求体不是合法 JSON"}, 400)
            if not isinstance(body, dict):
                return self.send_json({"ok": False, "error": "请求体必须是 JSON 对象"}, 400)

            if path == "/api/checks":
                issue = str(body.get("issue") or "").strip()
                if not re.fullmatch(r"\d{7}", issue):
                    return self.send_json({"ok": False, "error": "期号必须是 7 位数字"}, 400)
                try:
                    reds = sorted({int(x) for x in (body.get("reds") or [])})
                    blue = int(body.get("blue"))
                except (TypeError, ValueError):
                    return self.send_json({"ok": False, "error": "号码格式不正确"}, 400)
                if len(reds) != 6 or any(not 1 <= x <= 33 for x in reds) or not 1 <= blue <= 16:
                    return self.send_json({"ok": False, "error": "号码超出双色球范围"}, 400)
                reds_txt = ",".join(f"{x:02d}" for x in reds)
                try:
                    red_hits = max(0, min(6, int(body.get("redHits") or 0)))
                    blue_hit = 1 if body.get("blueHit") else 0
                except (TypeError, ValueError):
                    red_hits, blue_hit = 0, 0
                prize = str(body.get("prize") or "")
                created = time.strftime("%Y-%m-%d %H:%M:%S")
                ts = int(body.get("ts") or time.time() * 1000)
                with closing(connect()) as conn:
                    day_row = conn.execute("SELECT day FROM draws WHERE issue = ?", [issue]).fetchone()
                    day = day_row["day"] if day_row else (body.get("day") or expected_day(issue, conn))
                    dup = conn.execute(
                        "SELECT id FROM checks WHERE issue = ? AND reds = ? AND blue = ?",
                        [issue, reds_txt, blue],
                    ).fetchone()
                    if dup:
                        return self.send_json({"ok": True, "id": dup["id"], "duplicate": True})
                    cur = conn.execute(
                        """INSERT INTO checks (issue, day, reds, blue, prize, red_hits, blue_hit, created_at, ts)
                           VALUES (?,?,?,?,?,?,?,?,?)""",
                        (issue, day, reds_txt, blue, prize, red_hits, blue_hit, created, ts),
                    )
                    conn.commit()
                return self.send_json({"ok": True, "id": cur.lastrowid, "duplicate": False})

            issue = str(body.get("issue") or "").strip()
            picks = body.get("picks") or []
            if not re.fullmatch(r"\d{7}", issue):
                return self.send_json({"ok": False, "error": "期号必须是 7 位数字"}, 400)
            clean = []
            for p in picks:
                try:
                    red = sorted({int(x) for x in p.get("red", [])})
                    blue = int(p.get("blue"))
                except (TypeError, ValueError):
                    return self.send_json({"ok": False, "error": "号码格式不正确"}, 400)
                if len(red) != 6 or any(not 1 <= x <= 33 for x in red) or not 1 <= blue <= 16:
                    return self.send_json({"ok": False, "error": "号码超出双色球范围"}, 400)
                clean.append({"red": red, "blue": blue})
            if not clean:
                return self.send_json({"ok": False, "error": "至少要有 1 注"}, 400)

            strategy = str(body.get("strategy") or "hot")
            label = str(body.get("strategyLabel") or strategy)
            locks = body.get("locks") or {}
            created = time.strftime("%Y-%m-%d %H:%M:%S")
            ts = int(body.get("ts") or time.time() * 1000)

            with closing(connect()) as conn:
                day_row = conn.execute("SELECT day FROM draws WHERE issue = ?", [issue]).fetchone()
                day = day_row["day"] if day_row else (body.get("day") or expected_day(issue, conn))

                sig = json.dumps(clean, sort_keys=True)
                dup = None
                for r in conn.execute(
                    "SELECT id, picks FROM predictions WHERE issue = ? AND strategy = ?", [issue, strategy]
                ):
                    try:
                        if json.dumps(json.loads(r["picks"]), sort_keys=True) == sig:
                            dup = r["id"]
                            break
                    except json.JSONDecodeError:
                        continue
                if dup:
                    return self.send_json({"ok": True, "id": dup, "duplicate": True})

                cur = conn.execute(
                    """INSERT INTO predictions
                       (issue, day, strategy, strategy_label, picks, locks, qty, created_at, ts)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (issue, day, strategy, label, json.dumps(clean, ensure_ascii=False),
                     json.dumps(locks, ensure_ascii=False), len(clean), created, ts),
                )
                conn.commit()
                return self.send_json({"ok": True, "id": cur.lastrowid, "duplicate": False})
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write(f"保存失败: {exc}\n")
            return self.send_json({"ok": False, "error": str(exc)}, 500)

    # ---------- DELETE ----------
    def do_DELETE(self):
        if not self.guard():
            return
        path = self.api_path()
        m = re.fullmatch(r"/api/(predictions|checks)/(\d+)", path)
        if not m:
            return self.send_json({"ok": False, "error": "未知接口"}, 404)
        table = "predictions" if m.group(1) == "predictions" else "checks"
        try:
            with closing(connect()) as conn:
                conn.execute(f"DELETE FROM {table} WHERE id = ?", [int(m.group(2))])
                conn.commit()
            return self.send_json({"ok": True})
        except Exception as exc:  # noqa: BLE001
            return self.send_json({"ok": False, "error": str(exc)}, 500)


def pick_port(host, want):
    import socket
    for port in range(want, want + 10):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((host, port))
                return port
            except OSError:
                continue
    return want


def main():
    ap = argparse.ArgumentParser(description="双色球概率实验室 · 本地服务")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8899)
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()

    init_db()
    sync_draws(force=True)
    port = pick_port(args.host, args.port)
    open_host = "127.0.0.1" if args.host in ("0.0.0.0", "::", "") else args.host
    url = f"http://{open_host}:{port}/index.html"

    handler = partial(Handler, directory=BASE)
    httpd = ThreadingHTTPServer((args.host, port), handler)

    print("=" * 62)
    print("双色球概率实验室 · 本地服务已启动")
    print(f"  页面      {url}")
    print(f"  数据库    {os.path.relpath(DB_PATH, BASE)}")
    print(f"  开奖数据  assets/data.js（更新后自动同步进库）")
    print("  按 Ctrl+C 退出")
    if args.host not in LOOPBACK_HOSTS:
        print("-" * 62)
        print(f"  [警告] 正在监听 {args.host}，局域网内其他机器也能打开页面、")
        print("         读取 / 写入推演记录。仅本机使用时请保持默认的 127.0.0.1。")
    print("=" * 62)

    if not args.no_open:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()

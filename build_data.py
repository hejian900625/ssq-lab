# -*- coding: utf-8 -*-
"""把双色球历史数据打包成前端可直接 <script> 引入的 assets/data.js

设计要点（P1 #14）：
- 不再写死任何机器上的绝对路径。默认路径全部相对脚本自身定位（pathlib），
  换机器 / 换目录都能跑；需要时用命令行参数覆盖。
- 期数、期号范围、开奖日期范围不再手写，一律从数据里算出来，
  并可自动刷新 README.md 里的「数据概览」区块。

命令行示例：
    python build_data.py                              # 自动探测源文件并生成 assets/data.js
    python build_data.py --src "D:\\data\\ssq.json"    # 指定源文件
    python build_data.py --out dist/data.js            # 指定输出位置
    python build_data.py --stats-only                  # 只看统计，不生成文件
    python build_data.py --no-update-readme            # 生成数据但不碰 README.md
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent

DATA_FILENAME = "双色球历史开奖数据.json"
DEFAULT_OUT = BASE / "assets" / "data.js"
DEFAULT_DATA = BASE / "assets" / "data.js"
DEFAULT_README = BASE / "README.md"

# 源数据的候选位置：全部相对脚本目录，不含任何绝对路径。
# 第 3 项对应原始布局 —— 「双色球预测」与「双色球历史数据」并排放在同一个父目录下。
SRC_CANDIDATES = (
    BASE / DATA_FILENAME,
    BASE / "data" / DATA_FILENAME,
    BASE.parent / "双色球历史数据" / DATA_FILENAME,
    BASE.parent.parent / "双色球历史数据" / DATA_FILENAME,
)

BEGIN_MARK = "<!-- BEGIN DATA -->"
END_MARK = "<!-- END DATA -->"

_RAW_RE = re.compile(r'window\.SSQ_RAW\s*=\s*"(.*)"\s*;', re.S)


# --------------------------------------------------------------------------
# 读取与统计
# --------------------------------------------------------------------------
def iter_records(text):
    """从 assets/data.js 的文本里取出原始开奖记录。

    每条记录形如 ``期号|开奖日期|红球1,红球2,...,红球6|蓝球``。
    """
    m = _RAW_RE.search(text)
    if not m:
        raise ValueError("data.js 里找不到 window.SSQ_RAW 赋值，文件结构可能变了")
    return [r for r in m.group(1).split(";") if r]


def dataset_stats(records):
    """从记录列表算出期数 / 期号范围 / 开奖日期范围。

    不依赖记录顺序：最早、最晚都按开奖日期取，同日期再按期号排。
    """
    if not records:
        raise ValueError("数据集是空的")
    pairs = []
    for rec in records:
        parts = rec.split("|")
        if len(parts) < 4:
            raise ValueError(f"记录格式不对，应为 期号|日期|红球|蓝球：{rec!r}")
        pairs.append((parts[0], parts[1]))
    oldest = min(pairs, key=lambda p: (p[1], p[0]))
    newest = max(pairs, key=lambda p: (p[1], p[0]))
    return {
        "count": len(pairs),
        "issue_min": min(p[0] for p in pairs),
        "issue_max": max(p[0] for p in pairs),
        "date_min": oldest[1],
        "date_max": newest[1],
        "oldest_issue": oldest[0],
        "newest_issue": newest[0],
    }


def read_dataset_stats(data_js_path):
    """读取已有的 data.js，返回统计结果。"""
    path = Path(data_js_path)
    return dataset_stats(iter_records(path.read_text(encoding="utf-8")))


def build_records(rows):
    """把源 JSON 的每一行转成一条开奖记录。"""
    records = []
    for r in rows:
        reds = ",".join(str(r[f"红球{k}"]).zfill(2) for k in range(1, 7))
        blue = str(r["蓝球"]).zfill(2)
        records.append(f"{r['期号']}|{r['开奖日期']}|{reds}|{blue}")
    return records


def render_data_js(records, stats):
    """拼出 data.js 的完整内容（表头里的数字全部来自数据）。"""
    header = (
        "/* 中国福利彩票·双色球历史开奖数据（中国福彩官网 cwl.gov.cn 官方接口）\n"
        f"   共 {stats['count']} 期，期号 {stats['issue_min']} ~ {stats['issue_max']}，"
        f"开奖日期 {stats['date_min']} ~ {stats['date_max']}\n"
        "   格式：期号|开奖日期|红球1,红球2,...,红球6|蓝球  以 ; 分隔，按时间倒序 */\n"
    )
    return header + 'window.SSQ_RAW = "' + ";".join(records) + '";\n'


# --------------------------------------------------------------------------
# README 数据概览区块
# --------------------------------------------------------------------------
def render_data_block(stats):
    """渲染 README.md 里「数据概览」区块的内容。"""
    return "\n".join(
        [
            BEGIN_MARK,
            "",
            "| 项目 | 值 |",
            "| --- | --- |",
            f"| 期数 | {stats['count']} |",
            f"| 期号范围 | {stats['issue_min']} ~ {stats['issue_max']} |",
            f"| 开奖日期范围 | {stats['date_min']} ~ {stats['date_max']} |",
            f"| 最新一期 | {stats['newest_issue']}（{stats['date_max']}） |",
            f"| 最早一期 | {stats['oldest_issue']}（{stats['date_min']}） |",
            "",
            END_MARK,
        ]
    )


def update_readme_data_block(readme_path, stats):
    """按数据刷新 README.md 的「数据概览」区块，返回是否真的改动了文件。"""
    path = Path(readme_path)
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    if BEGIN_MARK not in text or END_MARK not in text:
        raise SystemExit(
            f"{path} 里找不到数据概览标记（{BEGIN_MARK} / {END_MARK}），无法自动更新"
        )
    new_text = re.sub(
        re.escape(BEGIN_MARK) + r".*?" + re.escape(END_MARK),
        lambda _m: render_data_block(stats),
        text,
        flags=re.S,
    )
    if new_text == text:
        return False
    path.write_text(new_text, encoding="utf-8", newline="")
    return True


# --------------------------------------------------------------------------
# 命令行
# --------------------------------------------------------------------------
def resolve_src(explicit):
    """定位源数据文件：显式指定优先，否则按相对路径候选列表逐个探测。"""
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise SystemExit(
                f"找不到源数据文件：{path}\n"
                "  请确认 --src 指向的路径是否正确"
            )
        return path.resolve()
    for cand in SRC_CANDIDATES:
        if cand.is_file():
            return cand.resolve()
    listing = "\n".join(f"    - {c}" for c in SRC_CANDIDATES)
    raise SystemExit(
        "找不到源数据文件，已按下列相对路径探测过：\n"
        f"{listing}\n"
        "  请用 --src 指定完整路径，例如：\n"
        '    python build_data.py --src "D:\\data\\双色球历史开奖数据.json"'
    )


def parse_args(argv=None):
    ap = argparse.ArgumentParser(
        description="把双色球历史数据打包成 assets/data.js",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("--src", help="源数据 JSON 路径；不填则按相对路径自动探测")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="输出的 data.js 路径")
    ap.add_argument("--data", default=str(DEFAULT_DATA), help="已有的 data.js 路径，--stats-only 时读它")
    ap.add_argument("--readme", default=str(DEFAULT_README), help="要刷新数据概览的 README.md")
    ap.add_argument("--stats-only", action="store_true", help="只统计并打印，不生成 data.js")
    ap.add_argument(
        "--no-update-readme",
        dest="update_readme",
        action="store_false",
        help="不刷新 README.md 的数据概览区块",
    )
    ap.set_defaults(update_readme=True)
    return ap.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    out = Path(args.out).expanduser()

    if args.stats_only:
        stats = read_dataset_stats(args.data)
        print(f"数据文件: {args.data}")
    else:
        src = resolve_src(args.src)
        rows = json.loads(src.read_text(encoding="utf-8"))
        records = build_records(rows)
        stats = dataset_stats(records)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render_data_js(records, stats), encoding="utf-8", newline="")
        print(f"已生成: {out}")
        print(f"源文件: {src}")
        print(f"期数 {stats['count']}，大小 {out.stat().st_size / 1024:.1f} KB")
        print(
            f"期号 {stats['issue_min']} ~ {stats['issue_max']}，"
            f"日期 {stats['date_min']} ~ {stats['date_max']}"
        )
        print("样例:", records[0])
        print("最后:", records[-1])

    if args.update_readme:
        changed = update_readme_data_block(args.readme, stats)
        print(f"README 数据概览{'已更新' if changed else '无需更新'}: {args.readme}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

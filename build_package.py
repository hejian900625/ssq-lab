# -*- coding: utf-8 -*-
"""把页面打包成可直接发给别人的 zip

设计要点（P1 #14 / P1 #15）：
- 不再写死任何机器上的绝对路径，输出位置、输入数据都用 argparse 指定，
  默认值全部相对脚本自身定位（pathlib）。
- 包里的《使用说明.txt》不再手写「3529 期 / 2003-02-23 至 2026-11-17」这种
  会过期的数字，改为从实际数据里现算。
- 打包结果可重复：条目顺序固定、时间戳归一，同一份输入两次打包字节一致。

命令行示例：
    python build_package.py                                  # 输出 dist/双色球预测.zip
    python build_package.py --out D:\\发布\\ssq.zip           # 指定输出位置
    python build_package.py --root 双色球预测 --no-update-readme
"""
from __future__ import annotations

import argparse
import io
import runpy
import shutil
import sys
import tempfile
import zipfile
from contextlib import redirect_stdout
from pathlib import Path

BASE = Path(__file__).resolve().parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from build_data import read_dataset_stats, update_readme_data_block  # noqa: E402

SINGLE_NAME = "双色球概率实验室-单文件版.html"
DATA_REL = Path("assets") / "data.js"
README_NAME = "使用说明.txt"
DEFAULT_ROOT = "双色球预测"
DEFAULT_OUT = BASE / "dist" / f"{DEFAULT_ROOT}.zip"
DEFAULT_DATA = BASE / DATA_REL
DEFAULT_SINGLE = BASE / SINGLE_NAME
DEFAULT_README = BASE / "README.md"

# 归一化的条目时间戳：让同样的输入打出同样的 zip（1980-01-01 是 zip 格式的起点）
ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)

README_TEMPLATE = """双色球 · 概率实验室
====================

【怎么打开】
双击 index.html，用 Chrome / Edge / Firefox 打开即可。
不需要联网，不需要安装任何东西，数据全在本地。

【本地记录（SQLite）】
双击 启动服务.bat（电脑需装 Python 3），会自动打开 http://127.0.0.1:8899/index.html
「保存推演」和「保存验票」的结果都写进 data/ssq.db，是个真正的 SQLite 文件，
可以用 DB Browser for SQLite 打开；页面里能按期号 / 日期查询推演记录、验票记录和对应开奖。
直接双击 index.html 时其余功能照常，但推演 / 验票记录需要上面的本地服务才能保存。

【两个版本】
index.html ........................ 需要和 assets 文件夹放在一起（保持现在的目录结构）
{single_name} ...... 数据和代码全在一个文件里
                                    只想发一个文件给别人、或放到手机上，用这个

【页面能做什么】
01 号码推演 ...... 四种策略生成号码；点矩阵格子可锁定胆码（胆码必定出现）
02 号码热力矩阵 ... {count} 期的出现次数 / 当前遗漏，颜色表示高于或低于均值
03 算法体检 ...... 四种策略同屏回测最近 120 期（界面可切 500 期 / 全部），
                    给出 95% 置信区间、多重比较校正与固定奖回收，
                    用同一批样本检验这套算法到底有没有预测力
04 验票机 ........ 输入你自己的一注，逐球比对开奖结果、判定奖级、查历史最佳战绩
                    支持上传票面图片自动识别号码并验票
                    验票后按「保存验票」写入 data/ssq.db，可按期号 / 日期查询
05 自进化预测 .... 从最早 100 期起步，逐期「预测 → 对照 → 修正」，
                    用在线学习的函数权重输出下一期号码，并给出滚动进化曲线
推演记录 ......... 保存每次推演，按期号 / 日期查询，并与实际开奖结果比对命中数

【数据来源】
中国福利彩票发行管理中心官网 cwl.gov.cn 官方接口，
并与 500 彩票网 / 中彩网历史数据交叉核验。
共 {count} 期，覆盖 {date_min} 至 {date_max}（期号 {issue_min} ~ {issue_max}）。

【联网说明】
除「上传图片识别」外，页面不需要联网；推演记录走 127.0.0.1 本机服务，同样不联网。
图片识别使用浏览器内的 Tesseract OCR，图片只在本机处理、不会上传；
首次识别需要联网加载识别引擎（约 3 MB），之后浏览器会缓存。

【一句提醒】
双色球每期开奖都是独立随机事件，历史频率和遗漏值不具备任何预测能力。
页面里的「算法体检」和「自进化预测」会亲自证明这一点——命中率与纯随机期望几乎重合。
理性购彩，量力而行。
"""


def render_readme(stats):
    """按实际数据生成《使用说明.txt》正文。"""
    return README_TEMPLATE.format(
        count=stats["count"],
        date_min=stats["date_min"],
        date_max=stats["date_max"],
        issue_min=stats["issue_min"],
        issue_max=stats["issue_max"],
        single_name=SINGLE_NAME,
    )


def ensure_single_file(single_path, base=BASE, allow_build=True):
    """确保单文件版存在。

    单文件版是构建产物（已进 .gitignore），干净检出后本来就没有，
    这里按需跑一次 build_single.py 生成。
    """
    path = Path(single_path)
    if path.is_file():
        return path, False

    builder = Path(base) / "build_single.py"
    if not allow_build or not builder.is_file():
        raise SystemExit(
            f"找不到单文件版 {path}\n"
            f"  请先运行：python {builder.name}"
        )
    print(f"单文件版缺失，正在用 {builder.name} 生成 ...")
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            runpy.run_path(str(builder), run_name="__main__")
    except SystemExit as exc:
        print(buf.getvalue().rstrip())
        raise SystemExit(f"生成单文件版失败：{exc}")
    for line in buf.getvalue().splitlines():
        print("  " + line)

    produced = Path(base) / SINGLE_NAME
    if not path.is_file() and produced.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(produced, path)
    if not path.is_file():
        raise SystemExit(f"生成单文件版失败：{path} 仍不存在")
    return path, True


def add_to_zip(zf, path, arcname):
    """往 zip 里写一个条目，时间戳归一以便复现。"""
    info = zipfile.ZipInfo(arcname, date_time=ZIP_EPOCH)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    zf.writestr(info, Path(path).read_bytes())


def build_zip(out_zip, files, root=DEFAULT_ROOT):
    """把 {本地路径: 归档内路径} 打进 zip，结果可重复。"""
    out = Path(out_zip)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()

    items = sorted(files.items(), key=lambda kv: kv[1])
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for src, arc in items:
            add_to_zip(zf, src, arc)

    print(f"已生成: {out}")
    print(f"大小: {out.stat().st_size / 1024:.1f} KB")
    print("包含:")
    with zipfile.ZipFile(out) as zf:
        for info in zf.infolist():
            print(f"  {info.filename}  ({info.file_size / 1024:.1f} KB)")
    return out


def parse_args(argv=None):
    ap = argparse.ArgumentParser(
        description="把页面打包成可直接发给别人的 zip",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="输出的 zip 路径")
    ap.add_argument("--data", default=str(DEFAULT_DATA), help="数据文件 data.js 路径")
    ap.add_argument("--single", default=str(DEFAULT_SINGLE), help="单文件版 HTML 路径")
    ap.add_argument("--index", default=str(BASE / "index.html"), help="多文件版 index.html 路径")
    ap.add_argument("--root", default=DEFAULT_ROOT, help="zip 里的顶层目录名")
    ap.add_argument("--readme", default=str(DEFAULT_README), help="要刷新数据概览的 README.md")
    ap.add_argument(
        "--no-build-single",
        dest="build_single",
        action="store_false",
        help="单文件版缺失时不自动生成，直接报错",
    )
    ap.add_argument(
        "--no-update-readme",
        dest="update_readme",
        action="store_false",
        help="不刷新 README.md 的数据概览区块",
    )
    ap.set_defaults(build_single=True, update_readme=True)
    return ap.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    data_js = Path(args.data).expanduser()
    if not data_js.is_file():
        raise SystemExit(f"找不到数据文件：{data_js}\n  请先运行：python build_data.py")
    stats = read_dataset_stats(data_js)
    print(
        f"数据: {data_js}（{stats['count']} 期，"
        f"{stats['date_min']} ~ {stats['date_max']}）"
    )

    index_html = Path(args.index).expanduser()
    if not index_html.is_file():
        raise SystemExit(f"找不到页面文件：{index_html}")
    single_html, built = ensure_single_file(args.single, allow_build=args.build_single)
    if built:
        print(f"单文件版已生成: {single_html}")

    with tempfile.TemporaryDirectory(prefix="ssq_pkg_") as tmp:
        stage = Path(tmp)
        target = stage / args.root
        (target / "assets").mkdir(parents=True, exist_ok=True)

        shutil.copy2(index_html, target / "index.html")
        shutil.copy2(data_js, target / "assets" / "data.js")
        shutil.copy2(single_html, target / SINGLE_NAME)
        (target / README_NAME).write_text(
            render_readme(stats), encoding="utf-8-sig", newline="\r\n"
        )

        files = {
            target / "index.html": f"{args.root}/index.html",
            target / "assets" / "data.js": f"{args.root}/assets/data.js",
            target / SINGLE_NAME: f"{args.root}/{SINGLE_NAME}",
            target / README_NAME: f"{args.root}/{README_NAME}",
        }
        build_zip(args.out, files, root=args.root)

    if args.update_readme:
        changed = update_readme_data_block(args.readme, stats)
        print(f"README 数据概览{'已更新' if changed else '无需更新'}: {args.readme}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

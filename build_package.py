# -*- coding: utf-8 -*-
"""把页面打包成可直接发给别人的 zip"""
import os
import shutil
import zipfile

BASE = os.path.dirname(os.path.abspath(__file__))
OUT_ZIP = r"C:\Users\Lenovo\Documents\Loomy Workspace\双色球预测.zip"
STAGE = os.path.join(os.environ.get("TEMP", "."), "ssq_pkg_stage")
ROOT = "双色球预测"

README = """双色球 · 概率实验室
====================

【怎么打开】
双击 index.html，用 Chrome / Edge / Firefox 打开即可。
不需要联网，不需要安装任何东西，数据全在本地。

【两个版本】
index.html ........................ 需要和 assets 文件夹放在一起（保持现在的目录结构）
双色球概率实验室-单文件版.html ...... 数据和代码全在一个文件里
                                    只想发一个文件给别人、或放到手机上，用这个

【页面能做什么】
01 号码推演 ...... 四种策略生成号码；点矩阵格子可锁定胆码（胆码必定出现）
02 号码热力矩阵 ... 3529 期的出现次数 / 当前遗漏，颜色表示高于或低于均值
03 算法体检 ...... 样本外回测，用最近 120 期验证这套算法到底有没有预测力
04 验票机 ........ 输入你自己的一注，逐球比对开奖结果、判定奖级、查历史最佳战绩
                    支持上传票面图片自动识别号码并验票

【数据来源】
中国福利彩票发行管理中心官网 cwl.gov.cn 官方接口，
并与 500 彩票网 / 中彩网历史数据交叉核验。
共 3529 期，覆盖 2003-02-23 至 2026-11-17。

【联网说明】
除「上传图片识别」外，其余功能完全离线。
图片识别使用浏览器内的 Tesseract OCR，图片只在本机处理、不会上传；
首次识别需要联网加载识别引擎（约 3 MB），之后浏览器会缓存。

【一句提醒】
双色球每期开奖都是独立随机事件，历史频率和遗漏值不具备任何预测能力。
页面里的「算法体检」会亲自证明这一点——回测命中率与纯随机期望几乎重合。
理性购彩，量力而行。
"""


def main():
    if os.path.isdir(STAGE):
        shutil.rmtree(STAGE, ignore_errors=True)
    target = os.path.join(STAGE, ROOT)
    os.makedirs(os.path.join(target, "assets"), exist_ok=True)

    shutil.copy2(os.path.join(BASE, "index.html"), target)
    shutil.copy2(os.path.join(BASE, "assets", "data.js"), os.path.join(target, "assets"))
    shutil.copy2(os.path.join(BASE, "双色球概率实验室-单文件版.html"), target)
    with open(os.path.join(target, "使用说明.txt"), "w", encoding="utf-8-sig") as f:
        f.write(README)

    if os.path.exists(OUT_ZIP):
        os.remove(OUT_ZIP)

    with zipfile.ZipFile(OUT_ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for root_dir, _, files in os.walk(STAGE):
            for name in files:
                full = os.path.join(root_dir, name)
                arc = os.path.relpath(full, STAGE)
                z.write(full, arc)

    print("已生成:", OUT_ZIP)
    print(f"大小: {os.path.getsize(OUT_ZIP)/1024:.1f} KB")
    print("包含:")
    with zipfile.ZipFile(OUT_ZIP) as z:
        for info in z.infolist():
            print(f"  {info.filename}  ({info.file_size/1024:.1f} KB)")


if __name__ == "__main__":
    main()

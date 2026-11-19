# -*- coding: utf-8 -*-
"""把双色球历史数据打包成前端可直接 <script> 引入的 assets/data.js"""
import json
import os

SRC = r"C:\Users\Lenovo\Documents\Loomy Workspace\双色球历史数据\双色球历史开奖数据.json"
OUT_DIR = r"C:\Users\Lenovo\Documents\Loomy Workspace\双色球预测\assets"
os.makedirs(OUT_DIR, exist_ok=True)

rows = json.load(open(SRC, encoding="utf-8"))

records = []
for r in rows:
    reds = [str(r[f"红球{k}"]).zfill(2) for k in range(1, 7)]
    blue = str(r["蓝球"]).zfill(2)
    records.append(f"{r['期号']}|{r['开奖日期']}|{','.join(reds)}|{blue}")

payload = ";".join(records)
out = os.path.join(OUT_DIR, "data.js")
header = (
    "/* 中国福利彩票·双色球历史开奖数据（中国福彩官网 cwl.gov.cn 官方接口）\n"
    f"   共 {len(records)} 期，范围 {records[-1].split('|')[0]} ~ {records[0].split('|')[0]}\n"
    "   格式：期号|开奖日期|红球1,红球2,...,红球6|蓝球  以 ; 分隔，按时间倒序 */\n"
)
with open(out, "w", encoding="utf-8") as f:
    f.write(header)
    f.write("window.SSQ_RAW = \"" + payload + "\";\n")

print(f"已生成 {out}")
print(f"期数 {len(records)}，大小 {os.path.getsize(out)/1024:.1f} KB")
print("样例:", records[0])
print("最后:", records[-1])

# -*- coding: utf-8 -*-
"""生成自包含单文件版：把 assets/data.js 内联进 index.html"""
import os

BASE = os.path.dirname(os.path.abspath(__file__))
html = open(os.path.join(BASE, "index.html"), encoding="utf-8").read()
data = open(os.path.join(BASE, "assets", "data.js"), encoding="utf-8").read()

TAG = '<script src="assets/data.js"></script>'
if TAG not in html:
    raise SystemExit("找不到 data.js 的 script 标签，页面结构可能变了")

if "</script>" in data:
    raise SystemExit("数据里含有 </script>，不能直接内联")

inline = "<script>\n" + data + "</script>"
out_html = html.replace(TAG, inline)

out = os.path.join(BASE, "双色球概率实验室-单文件版.html")
open(out, "w", encoding="utf-8").write(out_html)

print("已生成:", out)
print(f"大小: {os.path.getsize(out)/1024:.1f} KB")
print("外部引用残留:", 'assets/data.js' in out_html)

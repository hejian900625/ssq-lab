# 双色球 · 概率实验室

纯前端的双色球「概率实验室」：号码推演、冷热号矩阵、四策略回测、验票机、自进化预测。
数据全部打包在本地，不需要联网、不需要后端也能跑核心功能。

> 页面只做概率与统计演示。每期开奖都是独立随机事件，
> 历史频率和遗漏值没有预测力 —— 这正是「算法体检」和「自进化预测」会当场证明的事。

## 快速开始

| 想做什么 | 怎么做 |
| --- | --- |
| 只想看看 | 双击 `index.html`（需保证 `assets/` 文件夹在同级目录） |
| 要用保存推演 / 验票记录 | 双击 `启动服务.bat`（需装 Python 3），会自动打开 <http://127.0.0.1:8899/index.html> |
| 只想要一个文件发给别人 | 用 `双色球概率实验室-单文件版.html`（构建产物，见下方「构建」） |

推演 / 验票记录走本机 SQLite（`data/ssq.db`），只有起本地服务时才能写入；
双击 `index.html` 时其余功能照常。

## 数据概览

<!-- BEGIN DATA -->

| 项目 | 值 |
| --- | --- |
| 期数 | 3531 |
| 期号范围 | 2003001 ~ 2026134 |
| 开奖日期范围 | 2003-02-23 ~ 2026-11-22 |
| 最新一期 | 2026134（2026-11-22） |
| 最早一期 | 2003001（2003-02-23） |

<!-- END DATA -->

> 这张表由 `build_data.py` / `build_package.py` 从 `assets/data.js` 现场算出来，
> 不要手改；改完数据重新构建即可刷新。

## 目录结构

| 文件 | 作用 |
| --- | --- |
| `index.html` | 多文件版页面（样式与脚本全部内联） |
| `assets/data.js` | 历史开奖数据，挂在 `window.SSQ_RAW` 上 |
| `双色球概率实验室-单文件版.html` | 单文件版，**构建产物、不入库**，由 `build_single.py` 生成 |
| `build_data.py` | 源 JSON → `assets/data.js` |
| `build_single.py` | `index.html` + `assets/data.js` → 单文件版 |
| `build_package.py` | 打包成可直接分发的 zip（含动态生成的《使用说明.txt》） |
| `server.py` | 本地 HTTP + SQLite 服务 |
| `update_draw.ps1` | 抓取最新开奖数据 |
| `启动服务.bat` | 一键启动本地服务 |

## 构建

三个脚本都用 `pathlib` 定位路径、用 `argparse` 接参数，**没有写死的绝对路径**，
换目录、换机器都能跑。

### 更新数据

```bash
# 自动探测源文件（默认在脚本同级、data/、或与本目录并排的「双色球历史数据」里找）
python build_data.py

# 或显式指定
python build_data.py --src "D:\data\双色球历史开奖数据.json" --out assets/data.js

# 只看统计，不生成文件
python build_data.py --stats-only
```

生成 `assets/data.js` 的同时会刷新上面「数据概览」那张表；不想动 README 就加
`--no-update-readme`。

### 生成单文件版

```bash
python build_single.py
```

产物 `双色球概率实验室-单文件版.html` 是构建产物，已在 `.gitignore` 里，
**只在发版时产出，不进版本库**。

### 打包

```bash
# 默认输出 dist/双色球预测.zip
python build_package.py

# 指定输出位置
python build_package.py --out "D:\发布\ssq.zip"
```

包里的《使用说明.txt》会按实际数据现算期数与日期范围，不会再出现过期数字。
zip 的条目顺序与时间戳都归一化了，同一份输入两次打包结果字节一致。

## 数据来源

中国福利彩票发行管理中心官网 cwl.gov.cn 官方接口，
并与 500 彩票网 / 中彩网历史数据交叉核验。

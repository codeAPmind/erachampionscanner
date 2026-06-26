# 🔭 Era Champion Scanner — 时代主角扫描器

基于**六维共振模型**的美股量化扫描工具，寻找正处于结构性变革中心的"时代主角"。

## 核心理念

不是选"好公司"，而是选**此刻正在成为时代主角的公司**——财报断层、机构共识、叙事热度、现金流真实性、供需约束同时共振的标的。

## 快速开始

### 1. 克隆并配置

```bash
git clone https://github.com/codeAPmind/erachampionscanner.git
cd erachampionscanner

# 复制配置模板，填入真实 API Key
cp config.example.py config.py
# 编辑 config.py，填入 FMP_API_KEY
```

> 获取 FMP API Key：https://financialmodelingprep.com/developer/docs/

### 2. 创建 conda 环境并安装依赖

```bash
conda create -n erascanner python=3.11 -y
conda activate erascanner
pip install -r requirements.txt
```

### 3. 运行扫描

```bash
# 扫描默认候选池（32只）
python scanner.py

# 指定股票
python scanner.py --tickers NVDA MU TSLA

# 不发飞书通知
python scanner.py --no-feishu

# 同时输出 JSON 详细数据
python scanner.py --json
```

也可以直接用脚本（自动处理 conda 环境 + 飞书通知 + 失败告警）：

```bash
chmod +x run.sh
./run.sh
```

### 4. 查看结果

| 文件 | 说明 |
|------|------|
| `output/era_champion_report.md` | 完整报告：排名表 + S/A级详析 + 前5名目标价明细 + 退化信号 |
| `output/era_champion_ranking.csv` | CSV 排名表，可导入 Excel |
| `output/era_champion_data.json` | 完整评分数据（需加 `--json` 参数） |

## 六维共振模型

| 维度 | 权重 | 核心问题 |
|------|------|----------|
| 行业龙头 | 15% | 是否拥有定价权？市值/收入规模是否领先？ |
| **财报断层** | **25%** | 业绩是否显著超预期且领先同行？ |
| 机构共识 | 15% | 聪明钱是否在用真金白银下注？ |
| 时代叙事 | 15% | 是否绑定了十年级别的技术变革？ |
| 现金流验证 | 15% | 利润是真金白银还是会计幻觉？ |
| 供需约束 | 15% | 供不应求的信号是否可验证？ |

## 评级标准

| 等级 | 分数 | 含义 |
|------|------|------|
| 🏆 S | ≥ 85 | 时代主角候选，极少数 |
| ⭐ A | 70–84 | 强势龙头，值得深度研究 |
| 📊 B | 55–69 | 有亮点但存在短板 |
| 📉 C | < 55 | 不符合框架，观望 |

## 退化信号系统

独立于评分的第二层预警，专门捕捉"月盈则亏"——即使总分还在 A 级，只要出现以下信号即亮灯：

- 🟡 **黄灯**：收入增速减速（二阶导为负）、毛利率环比下降、目标价分析师分歧扩大
- 🔴 **红灯**：增速大幅放缓、连续 2 季毛利率下降、EPS 不及预期

## 分析师目标价置信度

报告前5名展示**近90天分析师目标价明细**（机构、日期、前后变化），并用**时间衰减加权**（半衰期30天）计算共识价——距今越近权重越高，过期数据自动降权。

## 候选池（32只）

按赛道分组，覆盖 AI 算力、存储、设备、基础设施、云、应用、新能源、生物科技等核心赛道。可在 `config.py` 中自由增删。

## 定时执行（cron）

```bash
# 周一至周五 北京时间 21:15（美东开盘前）自动扫描
15 21 * * 1-5 /path/to/erachampionscanner/run.sh >> /path/to/erachampionscanner/logs/cron.log 2>&1
```

## 配置项

所有配置均在 `config.py`（从 `config.example.py` 复制）：

- `FMP_API_KEY` — Financial Modeling Prep API Key
- `PROXY` — 本地代理（Clash/V2Ray 等）
- `WATCHLIST` — 候选股票池及主题标签
- `THEME_HEAT` — 各主题当前热度（1-10，手动维护）
- `DIMENSION_WEIGHTS` — 六维权重（默认合计 1.0）

## 数据源

- **Yahoo Finance**（免费）— 价格、市值、机构持仓、分析师评级历史
- **Financial Modeling Prep**（付费）— 财务报表、EPS数据、目标价共识

## 免责声明

本工具仅供研究参考，不构成任何投资建议。投资有风险，入市需谨慎。

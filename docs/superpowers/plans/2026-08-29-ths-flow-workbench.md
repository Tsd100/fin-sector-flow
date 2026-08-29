# 同花顺板块资金流工作台 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为现有板块资金流项目增加同花顺低延迟实验源，并把曲线图、排序图、赛车图、回放和导出整合进单页可视化工作台。

**Architecture:** 新增轻量 `ths.py`，直接请求同花顺行业/概念资金流 HTML 分页接口并归一化为现有 SQLite 行结构；`providers.py` 统一分发 `sina/ths/eastmoney`。前端继续使用单文件 ECharts 页面，客户端根据同一份 JSON 切换三种视图，避免增加前端构建链。

**Tech Stack:** Python 3.11、requests、pandas、PyYAML、SQLite、原生 HTML/CSS/JavaScript、ECharts 5。

---

### Task 1: 先锁定同花顺解析和页面契约

**Files:**
- Create: `tests/test_ths.py`
- Modify: `tests/test_pipeline.py`

- [ ] **Step 1: 写同花顺 HTML 解析失败测试**

在 `tests/test_ths.py` 中准备包含 GBK 页面解码后表格的最小 HTML，断言 `parse_page` 能得到板块代码、名称、涨跌幅和净额元值；在 provider 尚不存在时测试应因 `ModuleNotFoundError` 失败。

```python
class ThsFlowTests(unittest.TestCase):
    def test_parse_page_normalizes_board_values_and_code(self):
        html = """
        <div class="page_info">1/1</div>
        <table><tbody><tr>
          <td>1</td><td><a href="http://q.10jqka.com.cn/thshy/detail/code/881101/">消费电子</a></td>
          <td>5983.64</td><td>2.03%</td><td>86.85</td><td>87.11</td><td>-0.26</td>
          <td>95</td><td><a href="http://stockpage.10jqka.com.cn/000001/">示例股</a></td><td>5.0%</td><td>10.0</td>
        </tr></tbody></table>
        """
        rows, pages = ths.parse_page(html, "industry")
        self.assertEqual(pages, 1)
        self.assertEqual(rows[0]["code"], "881101")
        self.assertEqual(rows[0]["name"], "消费电子")
        self.assertEqual(rows[0]["pct_chg"], 2.03)
        self.assertEqual(rows[0]["main_net"], -26_000_000)
```

- [ ] **Step 2: 写分页、去重和后续页容错测试**

用注入的假 `Session` 返回两页 HTML，第一行重复，断言最终只保留一个板块；再让第二页抛出 `requests.RequestException`，断言仍返回第一页；让第一页失败时断言抛出 `ThsError`。

- [ ] **Step 3: 写 provider 与导出前端契约失败测试**

在 `tests/test_pipeline.py` 增加：`providers.fetch_sector_snapshot(..., provider="ths")` 分发到 `ths.fetch_board_snapshot`；`export.build` 对最后采集点之后的时点输出 `None`；viewer 源包含 `曲线图`、`排序图`、`赛车图`、`导出 CSV`、`导出图片`、`同花顺` 和 `setInterval(loadData, 60000)`。

- [ ] **Step 4: 运行新增测试确认是预期失败**

运行：`python -m unittest tests.test_ths tests.test_pipeline -v`
预期：因 `ths` 模块、`ths` provider 和新页面契约尚不存在而失败，不能因为测试语法或导入错误之外的原因失败。

### Task 2: 实现同花顺直接数据适配器

**Files:**
- Create: `ths.py`
- Test: `tests/test_ths.py`

- [ ] **Step 1: 实现请求常量和行归一化**

定义行业/概念路径映射、请求头、重试退避和 `ThsError`；实现 `_to_float`、`_extract_board_code`、`normalize_row`。同花顺的净额单位是亿元，归一化时乘以 `100_000_000` 写入 `main_net`；涨跌幅保持百分数值。

- [ ] **Step 2: 实现 HTML 页面解析**

用标准库 `html.parser.HTMLParser` 收集表格行和板块详情链接，读取 `.page_info` 得到总页数；只接受字段数不少于 11 的数据行，板块链接提取不到代码时使用 `ths:{sector_type}:{name}`，避免空主键。

- [ ] **Step 3: 实现带重试的分页抓取**

`_request_page` 使用 `requests.Session.get(..., timeout=10)`，按 `0.5/1.5/3.0` 秒重试；首页失败抛出 `ThsError`，后续页失败记录 warning 后返回已收集页面。`fetch_board_snapshot` 去重板块代码并输出与 `sina.normalize_board_row` 相同的项目字段。

- [ ] **Step 4: 运行同花顺测试确认通过**

运行：`python -m unittest tests.test_ths -v`
预期：所有同花顺解析、分页、去重和异常测试 PASS。

### Task 3: 接入 provider、配置和真实采集链路

**Files:**
- Modify: `providers.py`
- Modify: `config.yaml`
- Modify: `collector.py`
- Modify: `export.py`
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: 增加 `ths` provider 分发**

将 `Provider` 扩展为 `Literal["sina", "ths", "eastmoney"]`，在 `fetch_sector_snapshot` 中将 `ths` 路由到 `ths.fetch_board_snapshot`，保留 Sina 的 fenlei 配置和东方财富显式回退。

- [ ] **Step 2: 设置同花顺默认配置**

把 `config.yaml` 的 `provider` 改为 `ths`、`poll_interval_seconds` 改为 `60`、`metric_label` 改为 `板块净流入（同花顺口径）`；保持现有 watchlist，不把新浪和同花顺记录混写。

- [ ] **Step 3: 修正实时导出未来点**

在 `export.build` 中先记录当天最大 `session_min`，对 pivot 结果执行前向填充后，将索引大于最大采集时点的单元格恢复为 `NaN`，让页面只画到真实已采集位置。保留现有 stable code、同名板块和 UTF-8 行为。

- [ ] **Step 4: 运行 pipeline 测试并提交后端改动**

运行：`python -m unittest tests.test_ths tests.test_pipeline -v`
预期：新增 provider、未来空值和原有 pipeline 测试全部 PASS；提交：`git add ths.py providers.py config.yaml collector.py export.py tests/test_ths.py tests/test_pipeline.py && git commit -m "feat: add THS flow provider"`。

### Task 4: 实现三视图单页工作台

**Files:**
- Modify: `web/viewer.html`
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: 添加布局和状态控件**

保留 `?date=mock` 和中国时区日期选择；新增标题/来源徽标、三个视图标签、8s/13s/15s/30s 回放时长、CSV/PNG 导出、播放控制、时间滑块和实时按钮；不新增底部导航。

- [ ] **Step 2: 添加曲线图与排序图**

曲线图沿用当前累计净流入样式并在末端显示板块名；排序图读取当前游标的最后有效值，按净流入降序生成横向 bar，正负值使用流入/流出颜色。

- [ ] **Step 3: 添加赛车图和回放状态机**

新增 `viewMode`、`cursor`、`playbackSeconds`、`isLive` 状态；赛车图按时间游标推进排序 bar。播放/暂停只使用当前 JSON，实时按钮跳到最后有效点；切换视图不重置数据游标。

- [ ] **Step 4: 添加导出和刷新错误保护**

CSV 导出生成日期、时间、代码、名称、亿元净流入字段；PNG 导出调用 `chart.getDataURL`；真实日期每 60 秒刷新，刷新失败时保留旧图并更新状态提示。

- [ ] **Step 5: 运行静态契约和浏览器冒烟**

运行：`python -m unittest tests.test_pipeline -v`，再用本地 HTTP 服务打开 `http://127.0.0.1:3748/web/viewer.html?date=mock`，点击三个视图、速度、播放、实时、CSV、PNG 控件，确认无 Runtime exception、图表非空且布局响应式。

### Task 5: 全量验收、文档与远端同步

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-08-29-ths-flow-workbench.md`

- [ ] **Step 1: 更新 README 使用说明**

说明默认同花顺 provider、60 秒轮询、`--provider sina` 回退方式、三种视图和导出功能；明确同花顺净流入与新浪/东方财富口径不能直接合并。

- [ ] **Step 2: 执行全量自动化验证**

运行：`python -m unittest discover -v`；运行 Python AST/JSON 静态检查；用当前 HTTP 页面做 mock 数据浏览器冒烟；确认 `git diff --check` 无空白错误，`git status --short --branch` 只包含预期提交前改动。

- [ ] **Step 3: 做 Canvas dpr=1/2 验收**

使用可用的本地浏览器 CDP 检查页面标题、按钮和 canvas；分别以 dpr=1、dpr=2 读取每个 canvas 的 `getImageData`，断言绘制像素超过 500 且彩色像素占比超过 1%，并检查页面文本没有 `NaN` 或 `undefined`。

- [ ] **Step 4: 提交 UI 和文档并推送**

提交：`git add web/viewer.html README.md docs/superpowers/plans/2026-08-29-ths-flow-workbench.md tests && git commit -m "feat: add THS flow workbench views"`；运行 `git push origin main`，最后核对 `git rev-list --left-right --count origin/main...HEAD` 为 `0 0`。

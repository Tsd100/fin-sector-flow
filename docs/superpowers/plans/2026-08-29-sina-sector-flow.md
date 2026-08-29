# 新浪板块资金流与准实时展示 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将项目默认板块资金流来源切换到新浪，采集后自动生成当天 JSON，并让页面自动轮询展示准实时数据。

**Architecture:** 新增 `sina.py` 作为新浪 HTTP 适配器，输出兼容现有存储结构的板块快照；`collector.py` 按配置调用新浪并在写入 SQLite 后复用 `export.py` 生成当天 JSON；静态页面按中国时区轮询当天 JSON，`?date=mock` 保留离线演示。东方财富模块仍作为显式备用 provider，不参与默认链路。

**Tech Stack:** Python 3.11、requests、SQLite、pandas、PyYAML、标准库 unittest、原生 HTML/JavaScript、ECharts 5。

---

### Task 1: 建立新浪适配器契约

**Files:**
- Create: `sina.py`
- Create: `tests/test_sina.py`
- Modify: `requirements.txt` only if a missing runtime dependency is discovered

- [ ] **Step 1: Write failing tests for field normalization and category mapping**

测试固定新浪响应样例，要求 `fenlei=0` 归一为 `industry`、`fenlei=1` 归一为 `concept`，`avg_changeratio` 转为百分比，`netamount` 进入兼容字段 `main_net`，四档资金字段为空且保留原始 JSON。

- [ ] **Step 2: Run the focused tests and verify they fail for the missing module**

Run: `python -m unittest tests.test_sina -v`

Expected: FAIL because `sina.py` and its public adapter functions do not yet exist.

- [ ] **Step 3: Implement the minimal parser and category constants**

实现 `SINA_BOARD_FLOW_URL`、`FENLEI_BY_TYPE`、`SinaError`、`normalize_board_row()`，不在此步实现网络循环。

- [ ] **Step 4: Run the focused tests and verify they pass**

Run: `python -m unittest tests.test_sina -v`

Expected: PASS with all parser and mapping tests green.

- [ ] **Step 5: Commit the adapter contract**

Run: `git add sina.py tests/test_sina.py && git commit -m "feat: add Sina sector flow adapter"`

### Task 2: 完成新浪分页、重试与快照采集

**Files:**
- Modify: `sina.py`
- Modify: `tests/test_sina.py`

- [ ] **Step 1: Add failing tests for page fetching and partial-page behavior**

使用最小可控的 fake HTTP session 测试：首���成功后分页合并并按代码去重；第 1 页失败抛出 `SinaError`；后续页失败返回已有记录并产生可检查的告警路径。

- [ ] **Step 2: Run focused tests and verify the expected failures**

Run: `python -m unittest tests.test_sina -v`

Expected: FAIL on missing `fetch_board_snapshot()` and retry behavior.

- [ ] **Step 3: Implement bounded retry and pagination**

每页使用 `requests.Session`、新浪资金页面 Referer、10 秒超时和固定退避；以 `num=100` 请求，最多处理 20 页；首���失败直接抛错，后续页失败记录告警并返回已取得数据；遇到空页或没有新增代码时停止。

- [ ] **Step 4: Run focused tests and verify all adapter tests pass**

Run: `python -m unittest tests.test_sina -v`

Expected: PASS with parser, pagination, retry, deduplication, and error tests green.

- [ ] **Step 5: Commit pagination behavior**

Run: `git add sina.py tests/test_sina.py && git commit -m "feat: paginate Sina board flow snapshots"`

### Task 3: 接入配置、采集器和自动导出

**Files:**
- Modify: `config.yaml`
- Modify: `collector.py`
- Modify: `export.py`
- Create: `providers.py`
- Create: `tests/test_pipeline.py`

- [ ] **Step 1: Write failing tests for provider dispatch and post-collection JSON output**

测试配置默认 provider 为 Sina；测试 provider dispatch 将 `industry` 和 `concept` 路由到新浪；测试 `export.write_payload()` 使用 UTF-8 写入 JSON；测试一次注入式采集会同时写入 SQLite 和当天 JSON。

- [ ] **Step 2: Run pipeline tests and verify they fail before implementation**

Run: `python -m unittest tests.test_pipeline -v`

Expected: FAIL because provider dispatch and reusable JSON writer are missing.

- [ ] **Step 3: Implement provider dispatch and explicit UTF-8 export**

新增小型 provider 路由；`export.py` 增加 `write_payload()`；配置增加 `provider: sina`、`poll_interval_seconds: 300` 和 `sina` 分类映射；所有配置读取和 JSON 写入显式 `encoding="utf-8"`。

- [ ] **Step 4: Update collector with provider, interval, and post-upsert export**

新增 `--provider`、`--config`、`--output-dir`、`--interval-seconds` 参数；默认从配置读取新浪 provider 和 300 秒轮询；一次成功采集后调用导出写当天 JSON；失败只记录日志并进入下一轮。

- [ ] **Step 5: Run pipeline tests and verify they pass**

Run: `python -m unittest tests.test_pipeline -v`

Expected: PASS with SQLite and JSON output checks green.

- [ ] **Step 6: Commit pipeline integration**

Run: `git add config.yaml collector.py export.py providers.py tests/test_pipeline.py && git commit -m "feat: collect Sina flow and export live JSON"`

### Task 4: 增加页面自动刷新和数据口径提示

**Files:**
- Modify: `web/viewer.html`
- Modify: `tests/test_pipeline.py`

- [ ] **Step 1: Add failing static contract assertions**

测试页面源码包含中国时区当天日期计算、轮询定时器、`?date=mock` 分支和“新浪板块净流入”口径提示。

- [ ] **Step 2: Run the page contract tests and verify they fail**

Run: `python -m unittest tests.test_pipeline -v`

Expected: FAIL because the current page only loads once and has no live refresh contract.

- [ ] **Step 3: Implement polling without breaking replay**

默认日期使用中国时区当天；真实日期每 60 秒重新 fetch，成功后更新图表，失败保留旧图表并显示状态；`mock` 文件不自动轮询；标题/状态栏标出新浪板块净流入口径和最后刷新时间。

- [ ] **Step 4: Run page contract tests and verify they pass**

Run: `python -m unittest tests.test_pipeline -v`

Expected: PASS with all page contract checks green.

- [ ] **Step 5: Commit the live viewer**

Run: `git add web/viewer.html tests/test_pipeline.py && git commit -m "feat: auto-refresh live sector flow viewer"`

### Task 5: 文档、忽略规则与完整验证

**Files:**
- Modify: `README.md`
- Create: `.gitignore`
- Modify: `docs/superpowers/specs/2026-08-29-sina-sector-flow-design.md` only if self-review finds a contradiction

- [ ] **Step 1: Add runbook and data-source caveats**

README 写明安装、启动采集器、生成/查看当天数据、离线 mock URL、5 分钟数据延迟、Sina 与 EastMoney 字段口径差异及代理/网络失败诊断方式。

- [ ] **Step 2: Add runtime-data ignore rules**

忽略 `__pycache__/`、`*.pyc`、`data/*.db`、`data/20*.json`，保留 `data/mock.json`。

- [ ] **Step 3: Run the complete local test suite**

Run: `python -m unittest discover -v`

Expected: exit code 0 and zero failures.

- [ ] **Step 4: Run static and local HTTP checks**

Run: `python -c "import ast,json,pathlib; root=pathlib.Path('.'); [ast.parse(p.read_text(encoding='utf-8'), filename=str(p)) for p in root.glob('*.py')]; data=json.loads((root/'data/mock.json').read_text(encoding='utf-8')); assert len(data['series'])==16 and all(len(s['data'])==240 for s in data['series']); print('static smoke OK')"` to parse all Python and validate mock JSON; serve the repository over a local HTTP server and verify `web/viewer.html` and `data/mock.json` return HTTP 200.

- [ ] **Step 5: Run real Sina API smoke checks**

Request both `fenlei=0` and `fenlei=1`, verify non-empty rows, expected keys, and readable UTF-8 JSON. Record latest data timestamp/status in the final report.

- [ ] **Step 6: Review Git diff and commit docs**

Run: `git diff --check` and `git status --short`; confirm no database, daily JSON, secrets, or generated cache is staged; then `git add README.md .gitignore docs/superpowers/specs docs/superpowers/plans && git commit -m "docs: document Sina live flow setup"`.

### Task 6: 推送到远端并核验

**Files:**
- No source changes; Git remote state only

- [ ] **Step 1: Verify all commits and tests are present**

Run: `git log --oneline -6` and `python -m unittest discover -v`.

- [ ] **Step 2: Push the current branch to origin**

Run: `git push origin main`

Expected: origin accepts the new commits without force-push.

- [ ] **Step 3: Verify remote alignment**

Run: `git status --short --branch` and `git rev-parse HEAD`; confirm the branch is clean and tracking `origin/main` at the same commit.

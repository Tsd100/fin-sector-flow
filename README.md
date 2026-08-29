# fin-sector-flow

大 A 板块资金实时流向。默认使用同花顺板块资金流接口，采集行业和概念板块的净流入，并在本地生成可自动刷新的 ECharts 工作台。

## 运行链路

```text
同花顺板块资金接口 → collector.py → SQLite → 当天 JSON → web/viewer.html
```

同花顺页面提供行业和概念的“即时”资金流快照，项目默认每 60 秒采集一次。图表中的指标是“板块净流入（同花顺口径）”，不是东方财富的主力净流入，也不是新浪口径；金额在内部以元存储，导出和页面展示时转换为亿元。

## 安装

在项目根目录执行：

```powershell
python -m pip install -r requirements.txt
```

## 离线查看模拟页面

模拟数据已经包含在 `data/mock.json` 中。启动本地静态服务器：

```powershell
python -m http.server 8000
```

然后打开：

```text
http://127.0.0.1:8000/web/viewer.html?date=mock
```

## 采集真实板块数据

交易时段运行：

```powershell
python collector.py
```

默认配置见 `config.yaml`：

- provider：`ths`
- 采集间隔：60 秒
- 数据库：`data/sector_fund_flow.db`
- 当天导出：`data/YYYY-MM-DD.json`

采集器到达中国时间 15:05 后退出。采集成功后会立即更新当天 JSON；页面每 60 秒重新读取一次当天文件，因此页面刷新周期略快于数据源本身的更新周期。

打开真实日期页面：

```text
http://127.0.0.1:8000/web/viewer.html
```

页面默认使用中国时区当天日期，也可以显式指定：

```text
http://127.0.0.1:8000/web/viewer.html?date=2026-08-29
```

页面提供三种视图：`曲线图`、`排序图`、`赛车图`；支持 8s/13s/15s/30s 回放、时间轴、实时切换、CSV 导出和当前图表 PNG 导出。页面不包含个股池、板块池、工具箱或个人中心等底部导航。

## 备用数据源

新浪和原有东方财富采集器仍保留，可以显式切换：

```powershell
python collector.py --provider sina
```

```powershell
python collector.py --provider eastmoney
```

同花顺、东方财富和新浪的统计口径不同，不能把不同来源的数据直接拼在同一条曲线中。腾讯接口在本项目中只适合作为个股、指数行情交叉验证，不作为板块资金流主源。

## 测试

```powershell
python -m unittest discover -v
```

真实同花顺接口探测：

```powershell
python -c "import ths; print(len(ths.fetch_board_snapshot('industry'))); print(len(ths.fetch_board_snapshot('concept')))"
```

## 注意事项

- 同花顺资金数据存在源端刷新延迟，各家资金流统计口径也可能不同，仅供研究参考。
- 页面依赖 ECharts CDN，运行时需要浏览器能访问 `cdn.jsdelivr.net`。
- `data/*.db` 和当天生成的 `data/20*.json` 已加入 Git 忽略；`data/mock.json` 会保留。
- `ths.py` 直接解析同花顺公开 HTML 接口，不强制依赖完整 AkShare；这样可以减少封装层开销，但同花顺页面结构变化时需要同步调整解析器。
- 本项目只做数据采集和可视化，不提供下单、交易执行或投资建议。

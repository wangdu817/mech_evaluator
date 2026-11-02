# 单工况诊断与结果恢复验收（2026-10-09）

第 6 页新增独立 ROP/敏感性分析。实际 audited 工作机理的 PFR、JSR 工况，以及 clear 的点火工况完成 ROP 与单反应敏感性检查；原模拟 JSON/HDF5 哈希保持一致。点火原生温度敏感性另与独立中心差分结果对照。分析未进行全反应排序，也未完成实际火焰敏感性验收。

浏览器实际选择 Shin_Yoo_2004_MIX1 → 温度 1323.394 K → N_CHO_240725_working → OH → 固定时刻温度敏感性 → R13。生成/消耗/净 ROP 图、历程图和敏感性图均显示；R13 为 H + O2 (+M) ⇌ HO2 (+M)，S_T=-0.0283761，收紧容差复核通过。该系数是在 t=0.0004771039 s 的温度敏感性，不能当作着火延迟敏感性。网页下载 case-analysis.zip 成功。

修正分析对照表单位：内部 SI 值在显示前换算为列中声明的原单位，例如本例实验 782.09588 μs、模拟 477.10387 μs。内部原值保持不变。

## 刷新只显示 clear 的原因与修复

旧页面恢复最后运行的单机理配置，结果集合仅保存在浏览器会话中；同一输出目录下一次运行还会替换 manifest。现在结果集合独立保存至 `results/result-view-state.json`，刷新后恢复；误差页支持多选已有批次，不启动模拟。正常缓存运行前保留上一批清单与冻结 XML 至 `saved-batches/`。强制重算仍使用已有缓存备份流程。

当前已恢复 clear 与 N_CHO 的合并集合，范围采用全部 XML，原批次不修改，历程引用原文件：

| 机理 | 已有清单 XML | 已处理工况 | 验证成功 | 输入不完整 | 求解失败 |
|---|---:|---:|---:|---:|---:|
| clear_26092002 | 37 | 4698 | 1000 | 3698 | 0 |
| N_CHO_240725_working | 6 | 96 | 86 | 9 | 1 |

N_CHO 的历史批次已结束不代表覆盖全部 37 份 XML。全库 N_CHO 完成清单未找到；ui-run 缓存头审计只找到 clear 的 1000 个成功历程，覆盖 8 份 XML。缺失结果保留缺失，不用 clear 预测顶替。两个机理共同可评分的原始测量点为 160，正式总榜仍不成立。

真实浏览器刷新后，误差图与绘图机理选择均显示两个机理；新会话 AppTest 验证相同结果。截图为 `results/result-restore-browser.png` 和 `results/case-analysis-browser.png`。

## 检查记录

- `results/case-analysis-actual-validation.json`：实际数据、数值检查与原缓存哈希。
- `results/case-analysis-ui-smoke.json`：set → 变量值 → 机理 → 目标联动。
- `results/result-restore-ui-smoke.json`：新会话恢复两个机理及各自范围。
- `results/cached-mechanism-audit.json`：当前 ui-run 缓存机理归属。
- `results/tests-case-analysis-full.log`：全套测试；单位显示修正另有 `results/case-analysis-test-final.log`。
- wheel/sdist 含全部 23 个扩展模块；从 wheel 导入并解析 XML 成功。
- `results/source-audit.json`：78 份原始输入文件保持不变。

使用说明见 [CASE_ANALYSIS.md](CASE_ANALYSIS.md)。ROP 为所选状态的化学贡献，不等于敏感性；JSR ROP 不包含入口/出口输运。反应路径图和自动重新拟合未在此诊断入口实现。

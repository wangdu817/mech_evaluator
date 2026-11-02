# 原生敏感性与 PFR 全域积分验证（2026-10-09）

最新用户要求已覆盖下文历史容差复核流程：生产敏感性现在仅执行一次，使用 Cantera 默认状态/敏感性容差，不执行十倍收紧复核。结果 success 不能解释为通过容差收敛验证。新增实际验证见 `results/saved-species-actual-validation.json`：audited_working 的 PFR/JSR 各保存 164×3 矩阵，clear 的点火固定时刻保存 199×3 矩阵；均只积分一次，切换 NO/CH3NH2 导出不重新求解，原历程哈希保持不变。3 列为本次选择的反应，并非全反应验收。旧的全反应两轮任务按旧实现完成，其结果保留。9 项相关测试通过，网页独立测试服务验证历史载入、物种切换和导出；凭据 `results/saved-species-browser.png`。

用户要求覆盖原先的逐反应中心差分工作流。当前页面提供仅敏感性、仅 ROP 或两者，CLI 提供 `--no-rop`。仅敏感性报告的 ROP 为空，导出不生成 ROP 图或 CSV。

## 数值方法

PFR 与 JSR 采用 Cantera ReactorNet 前向敏感性方程；同时注册所选反应，用精确链式法则从质量分数换算实际摩尔分数/摩尔浓度导数。JSR 要求状态与敏感性连续三个窗口收敛。着火沿用固定时刻温度敏感性代理。火焰速度使用 Cantera 的 FreeFlame 伴随接口；它内部的参数残差偏导可采用数值差分，不宣称是全解析雅克比。正常分析没有逐反应扰动并重新求解完整工况；独立差分仅用于开发验证。

PFR 的反应排名使用 `∫ωᵢ,r(t)dt`，积分包括整个入口至出口历程所有状态，单位 mol/m³。沿程图仍为瞬时速率 mol/m³/s。变密度情况下，积分源项不等于出口浓度差，报告提供按 V(t)/V(0) 加权的净积分作为额外物质衡算量。

## 实际甲胺验证

`results/native-analysis-actual-validation.json`：audited_working 的实际 PFR、JSR 观测目标与 clear_26092002 的实际着火工况，分别同时处理三个反应参数，并验证仅敏感性不计算 ROP。PFR 所选反应原生系数 7.15709308e-5，独立差分 7.13252429e-5；JSR 原生系数 4.13197402e-4，独立差分 4.13197222e-4。原历程文件哈希保持不变。这里是所选反应集合的验证，不宣称完成了两个甲胺机理的全部反应敏感性排名。

`results/pfr-integral-actual-validation.json`：audited_working / Hjuler_1995_Set14 的实际 NO 全域积分。原 101 点存储历程未通过积分网格复核，分析独立重算同一物理工况为 1001 点后通过。隔行积分绝对差 3.39109850e-7 mol/m³，反应净积分与物种源项积分的衡算绝对差 6.72205347e-18 mol/m³。原缓存保持不变。初次粗网格失败也保存在原生分析验证记录中，以独立积分验证报告为最终结论。

## 自动与界面验证

解析一阶反应测试覆盖 PFR 出口摩尔分数、浓度、JSR 稳态敏感性，以及变体积 PFR 的积分和体积加权物质衡算。氢氧示例火焰的原生伴随系数与独立差分对照通过；本轮未完成实际甲胺火焰伴随验收，不将示例验证冒称甲胺验证。

`results/native-analysis-tests.log`：上述专项数值测试 10 项通过。
`results/native-analysis-full-tests.log`：148 项回归通过、1 项跳过；1 项界面测试因默认 3 秒超时失败，已调整为 30 秒并单独复测。原失败记录保留，复测结果见 `results/native-analysis-recheck.log`。
复测包含界面网格控件、数值分析与批次中断处理，共 20 项通过。wheel/sdist 构建及 25 个扩展模块检查通过，源文件审计 78 项保持不变。
`results/case-analysis-ui-smoke.json`：实际数据的 set/mix→变量→机理→目标流程、仅敏感性隐藏 ROP 输入、空反应集合阻止启动均通过。
`results/native-sensitivity-browser.png`：实际网页显示仅敏感性、原生方法和 all 反应选择。截图选中了全部反应，但未启动 1881 条反应分析，不能作为该全量计算完成的证据。

## 批次中断修复

网页发现 results/ui-run 因模块重载 import lock 冲突已中断。没有活跃 run.lock 后，按当前工况身份回收已提交缓存，状态改为 interrupted：401 个成功工况保留，3411 个尚未完成。新异常处理会提交真实中断状态与可恢复缓存；调度入口提前解析，避免在每次任务提交时动态导入。生产启动关闭 Streamlit 源码监视（`.streamlit/config.toml`、`start.ps1`），代码更新后应重启服务。没有自动重新启动原 3812 工况批次。

## 官方依据

- https://cantera.org/stable/python/zerodim.html#cantera.ReactorNet.sensitivities
- https://cantera.org/stable/python/onedim.html#cantera.FreeFlame.get_flame_speed_reaction_sensitivities
- https://cantera.org/stable/python/onedim.html#cantera.Sim1D.solve_adjoint

当前会话没有可调用的 Context7 工具，使用官方 3.2 文档及安装环境进行验证。

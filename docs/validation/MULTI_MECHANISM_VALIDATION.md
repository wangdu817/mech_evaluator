# 单机理计算、历史复用与实际多机理校验

每次运行可以只配置一个机理。已有结果可以直接载入、重新评分和绘图，也可在“4 误差与覆盖率 → 载入其他机理的历史结果并比较”中追加另一批结果。默认比较共有 XML，记录来源、排除的数据集和重复工况选择；不执行模拟。请保留原结果目录，合并批次的完整 HDF5 历程引用原文件。

## 实际复用与网页证据

- `examples/respecth/single-ncho.yaml`：只计算修订 N_CHO 机理的 Hjuler Set13，12 个工况全部数值验证通过。
- `single-ncho-reused.yaml`：输出到另一目录，从上述目录复用全部 12 个工况，新增模拟 0 次。证据：`results/multi-mechanism/cache-reuse-verification.json`。
- 网页载入 `results/actual-audited/full` 的原机理结果，再追加 `results/multi-mechanism/single-ncho`，得到 `results/multi-mechanism/web-saved-comparison`：24/24 工况成功、72 条实验—模拟对应记录、两个机理。单独选择一个机理重绘后恢复双机理，全部三种物种默认合图；已下载并核查 ZIP。
- 网页修复：比较目录使用稳定会话键，避免刷新时重置用户输入。
- 截图与下载：`results/multi-mechanism/evidence/saved-two-mechanisms.png`、`saved-comparison-export.zip`。

模拟缓存身份不包含输出目录、评分或绘图设置；包含实验内容、机理内容、气相、映射、工况、模型、求解和验证参数以及计算实现版本。跨目录自动复用仅接受身份完全一致、成功且通过数值验证、历程文件存在的结果。旧版本历史结果可以载入比较，但不能绕过实现版本检查成为新求解缓存。

## 修订工作机理审计

原 `mech/N_CHO_mechanism_2406_revised_240725.inp` 与 `N_CHO_therm_2406.dat` 保持不变。副本补充来源热力学文件中的温度范围行、移除重复物种声明；重复热力学数据按用户指定保留首次记录，NASA 系数逐块保留。语法差异与原输入哈希位于 `results/multi-mechanism/inputs/audit.json`、`mechanism.diff`、`thermo.diff`。

原 HCCO + OH = CO2 + CH2 的三个重复 PLOG 通道中，一个在 0.1 atm 含负 A，不能作为独立 PLOG 通道加载。经用户授权，将三个通道在压力节点先求和，再进行 PLOG 插值；增加压力节点以逼近中间压力的总速率。其他反应和全部热力学条目不改。

交付 `results/multi-mechanism/inputs/N_CHO_240725_working.yaml`，166 物种、1460 反应，明确称为修订工作机理。原压力节点及本批次的 1、1.3 atm 总速率保持到浮点精度；200–10000 K、1–10 atm 的独立 61×331 加密检查最大相对差异 0.469604%。低于 1 atm 时原独立负通道无法定义合法对数压力插值，修订是有记录的模型选择，不声称恢复作者原意或完成实验参数优化。完整速率证据在 `plog-audit.json`；原有第三体重复警告保留于日志。

## 双机理实际批次结果

`examples/respecth/multi-actual.yaml` 使用原 audited_working 和修订 N_CHO，各自运行 96 个工况，合计 192；输入为 Niu Phi0p9、Shin MIX1/MIX5、Hjuler Set13/Set14、Takizawa LBV 六份真实 XML。

| 状态 | audited_working | N_CHO 工作机理 | 总计 |
|---|---:|---:|---:|
| success（含数值验证） | 86 | 86 | 172 |
| solver_failed | 1 | 1 | 2 |
| invalid_input | 9 | 9 | 18 |

两个失败均为 JSR 1011 K、τ=1.75 s，达到 175 s 时限仍不满足稳态要求。18 个火焰工况因完整输运数据缺失而阻止；没有以零值替代。尚未确认测量干湿基准的 JSR 预测也不进入正式排名。

共同成功且可评分的原始测量集合为 160 点，排除 159 点。扩展组合诊断分数为 audited_working 10.8579908、N_CHO 10.8289925（点火 E 与 PFR NRMSE² 各权重 1）；完整总榜不成立，不能据此宣称整个实验库的优劣。Set13 单独共同比较具备完整覆盖，仅反映该数据集。结果可运行、机理可加载与实验预测准确是不同结论。

## 命令与验证

在项目目录运行：

```powershell
./start.ps1
./.venv313/Scripts/python.exe -m pyteck.respecth.cli run examples/respecth/single-ncho.yaml
./.venv313/Scripts/python.exe -m pyteck.respecth.cli run examples/respecth/single-ncho-reused.yaml
./.venv313/Scripts/python.exe -m pyteck.respecth.cli compare results/comparison-new results/actual-audited/full results/multi-mechanism/single-ncho
```

113 项自动测试通过（36 条保留的机理警告），含原始速率、单机理缓存身份、真实历史结果合并与冲突阻止。Streamlit 页面测试、实际浏览器载入/合并/机理选择/重绘/下载均完成。PFR、JSR、点火已有实际数值验证；缺输运数据的真实火焰流程仍有明确限制，不声称四类实际实验全部成功。

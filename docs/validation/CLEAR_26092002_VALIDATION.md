# 26092002_clear 转换与实际验证

## 转换结果与修复边界

使用 Cantera 3.2.0 官方 ck2yaml 严格转换（permissive=False），成功加载 **199 个物种、1881 条反应**。交付 `results/clear-26092002/26092002_cantera.yaml`；运行配置为 `examples/respecth/clear-26092002.yaml`。

当前 `mech/N_CHO_therm_2406.dat` 并非这份机理的完整配套数据，初次转换的缺失物种与格式错误保留在 `prepared/initial-conversion.log`。在 `D:/BaiduSyncdisk/Works/CH3NH2/MECH` 找到同名机理及配套 thermo.dat；同名机理与本次输入逐字节一致，trans.dat 也与当前 mech 目录文件一致。

在项目内创建副本，原文件不修改：

| 原文件位置 | 修复 |
|---|---|
| 第 178 行 | 移除 Cantera 不识别的 `MAXSP=8` 解析器字段，保留反应单位 |
| 第 7465–7469 行 | PLOG 的 A、b 数字补充缺失的指数标记 E，共 10 个数字；数值含义不变 |
| 配套 thermo.dat | 按精确物种名选择数据，重复条目保留首次；选中 NASA 四行块逐字保留 |
| trans.dat | 记录 NCNOH 两条输运记录与首次选择；另有 13 个物种缺输运参数 |

没有重新拟合、删除或合并反应，也没有改变 A、b、Ea 或 NASA 系数。原有三组第三体重复警告保留，不擅自改变第三体效率。严格转换日志、原始哈希、所有逐项差异、物种来源及缺失输运清单在 `results/clear-26092002/inputs/audit.json`、`*.diff`、`prepared/conversion.log` 和 `prepare.log`。

这些语法修复依据官方说明：[Cantera CHEMKIN 转换文档](https://cantera.org/stable/userguide/ck2yaml-tutorial.html)。热力学数据来自匹配的原 MECH 目录，不使用其他机理猜补物种；输运缺失没有用估计值补齐。

## 单机理真实运行

本次只运行新增机理，读取六份真实 XML：Niu_2025_Phi0p9、Shin_Yoo_2004_MIX1/MIX5、Hjuler_1995_Set13/Set14、Takizawa_2008_LBV；保持此前数据集模型、单位、逐点入口组成、干湿基和数值验证设置。没有重新计算旧机理。

| 状态 | 工况数 |
|---|---:|
| success，含容差加严数值验证 | 86 |
| solver_failed | 1 |
| invalid_input | 9 |
| 总计 | 96 |

未稳态 JSR：Niu XML 第 12 个原始点（索引 11），972 K，1 atm，τ=1.75 s，V=113 cm³；达到 175 s 最大物理时间后残差 0.0156856，超过稳态要求，保留失败。九个火焰工况因缺完整输运数据而阻止。本次没有覆盖全部 37 份实验库，不能声称全库验证通过。

86 个成功工况全部通过数值验证，HDF5 历程可读取；六份原始 XML 和三个机理配套输入哈希在运行后保持一致。成功表示数值求解通过，与实验误差小是不同结论。

## 历史合并与实验预测

将上述 96 个结果与原两个机理的 192 个历史结果合并到 `results/clear-26092002/comparison`，总计 288 个工况。合并执行的模拟次数为 0，原历史结果目录需保留，完整历程仍引用原文件。

共同可评分原始测量集合 160 点，排除 159 点。JSR 测量基准尚未确认、未稳态点及火焰无预测阻止完整总榜；下表仅是共同集合的诊断指标，点火与 PFR 权重各 1。

| 机理 | 点火平均 E | PFR 平均 NRMSE² | 扩展组合诊断指标 |
|---|---:|---:|---:|
| audited_working | 21.678821 | 0.0371604 | 10.857991 |
| N_CHO_240725_working | 21.620824 | 0.0371605 | 10.828992 |
| clear_26092002 | 28.516297 | 0.0295241 | 14.272911 |

该集合中 clear 的 PFR 误差指标较低、点火延迟误差指标较高。各数据集和物种的误差仍应分别查看；不把这些诊断分数当作全库正式排名。

实际浏览器已载入合并批次，确认三个机理可选择、同工况实验点和模拟线同色、机理用线型区分、四边框与朝内刻度、工况说明及三机理重绘。下载 ZIP 已核查，957 条实验—模拟对应记录包含全部三个机理，保留 CSV、配置、来源 JSON、PNG/PDF/SVG。截图：`results/clear-26092002/evidence/three-mechanisms-ignition.png`；下载：`three-mechanisms.zip`。

## 复现与证据

在项目目录运行：

```powershell
./.venv313/Scripts/python.exe tools/prepare_clear26092002.py
./.venv313/Scripts/python.exe -m pyteck.respecth.cli run examples/respecth/clear-26092002.yaml
./start.ps1
```

同一配置再次运行可使用现有缓存；旧机理可直接载入历史结果比较。网页“4 误差与覆盖率”载入 `results/clear-26092002/comparison` 即可。

新增 3 项审计测试通过：原输入哈希及选中 NASA 原文保留、序列化后所有 1881 条反应在 700/1300/2000 K 与 1/1.3/10 atm 下速率常数一致、缺输运清单明确。原项目此前 113 项测试已通过，本轮仅新增转换脚本、示例和审计测试，未修改核心求解器。机器可读证据为 `results/clear-26092002/verification.json`；失败条件与原因位于 `run/failed_cases.csv`。

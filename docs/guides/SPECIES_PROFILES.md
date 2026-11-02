# 激波管时间剖面、给定温度的平焰物种剖面和点火定义替代

ReSpecTh 已包含 `concentration time profile measurement` 和 `burner stabilized flame speciation measurement`；之前的软件只接入出口组分、JSR、点火延迟和火焰速度，报“不支持”是项目接口缺失。类型名称可参照 [PyKED 的 ReSpecTh 对照说明](https://pr-omethe-us.github.io/PyKED/ck-tutorial.html)。原 XML 保持只读。

## 激波管 OH 等组分时间历程

`experimentType` 使用 `concentration time profile measurement`，`apparatus/kind` 为 `shock tube`。commonProperties 提供反射激波后的初始 T、P、完整摩尔组成。dataGroup 以 `name="time"` 的 property 和实际 ID 指定测量时间；观测 property 使用 composition 或 concentration 以及 speciesLink。列顺序、ID 名称及 Xout 标签不参与物理语义判断。时间可使用 s、ms、us，内部统一为秒；合法零时间、零浓度和重复测量保留。

默认采用绝热定容理想气体模型。同一初始温度、压力、组成和模型配置下，只创建一个曲线任务，从初始状态连续积分至最大测量时间，按递增顺序精确采样所有实验时刻。不同物种、仪器、dataGroup、重复测量及绘图加密点共享这一条轨迹；原始实验点顺序和身份分别保留。初始状态不同则建立不同任务。关闭数值验证时只有一次积分；开启验证时额外收紧容差计算一次整条轨迹，逐观测值验证。不开启绘图加密时只采样原实验坐标。

结果支持 RMSE/NRMSE、按物种子图绘制时间曲线、导出和原生 ReactorNet 物种敏感性。实验为点，模拟为线，横轴明确为 Time (s)。这类工况的 ROP 是所选时刻的局部化学速率；PFR 的全域积分规则保持不变。

## 平焰燃烧器的轴向物种剖面

`experimentType` 使用 `burner stabilized flame speciation measurement`。物种 dataGroup 使用 `name="distance"`，支持 m、cm、mm，内部为米；composition/concentration 同上。T(z) 可放在独立 dataGroup，也可与物种共列，以 temperature 和 distance 的 ID 配对。输入温度不作为待评分的物种曲线，也不作为各位置不同的入口温度。

采用 Cantera [BurnerFlame 给定温度剖面方法](https://cantera.org/stable/examples/python/onedim/flame_fixed_T.html)：关闭能量方程，输入实际 T(z)，求解物种对流、扩散和反应。必须提供：

- 入口组成与压力；入口温度取 XML 固定值，或明确取给定 T(z=0)，有冲突时阻止运行。
- 从 z=0 开始并覆盖计算域的温度剖面，不自动补温度、不外推。测量物种的位置必须位于域内。
- 入口质量通量或入口流速，二选一；不能只靠入口浓度或温度猜测流量。质量通量为 kg/m²/s，流速为入口状态下 m/s。
- 完整、可加载的机理输运数据。默认 mixture-averaged、Soret 关闭。

可在数据集配置中补充物理输入，例如：

```yaml
dataset_configs:
  your-burner.xml:
    burner_mass_flux: {value: 0.05, units: kg/m2/s}
    # 或 burner_inlet_velocity: {value: 0.2, units: m/s}，不要同时设置
    burner_width: {value: 10, units: mm}
    temperature_profile:
      distance_units: mm
      temperature_units: K
      distance: [0, 1, 3, 6, 10]
      temperature: [300, 800, 1600, 1800, 1800]
```

这些数值仅为演示。XML 中也可用项目读取器支持的固定 `mass flux` 属性提供质量通量；按严格交换格式准备数据时，建议将流量配置置于数据集配置中并注明文献依据。入口速度转质量通量使用该机理在实际入口状态下的密度，不使用标准状态密度。配置与 XML 流量冲突会明确报告。

同一入口、压力、流量和温度曲线下只创建一个完整计算域的火焰任务，在同一个火焰场中提取所有位置、物种和仪器对应的预测值，测量位置通过网格插值采样。开启数值验证时进行必要的网格加密求解，同时检查全部观测位置；不会针对每个测量位置重复求解火焰。不越过温度数据的覆盖范围扩大计算域。完整火焰场只在求解和单点重建期间使用，常规结果仍精简保存。支持轴向物种评分、合图和局部 ROP；平焰物种伴随敏感性尚未实现，界面会明确阻止，避免误用自由火焰速度敏感性。

这两类剖面的运行进度按物理曲线任务计数，实验覆盖率按原始测量值计数。例如 Li_2015 的两条 OH 时间曲线共有 191 个测量值，对应两个曲线任务。评分和绘图不依赖完整历程，仍可在仅保留预测值和端点状态后执行。单工况分析按具体时间/位置选择，按需重建完整曲线。旧版逐点结果仍可打开；新版剖面任务使用新的目标身份，不误用旧版逐点缓存。

## 点火定义无法实现时

默认启用 `solver.ignition_fallback: temperature_gradient`。仅在原文献定义未实现，或机理缺少指定点火目标（例如 OH*）时，改用绝热定容历程中 **最大 dT/dt 的时刻**，不以 OH 冒充 OH*。原始定义、实际定义和替代原因保存在 case 配置、结果、CSV、图中工况说明及评分方法中。

这是一项近似替代，不能表述成严格重现文献判据。原定义本来可实现时保持原定义。未点火、未找到内部峰值及峰值截断仍报告 no_ignition，不因替代许可而填零或伪造延迟。在“条件检查→瞬态 / 平焰剖面与点火定义”取消替代并应用，或设置 `ignition_fallback: none`，可恢复严格拒绝模式。

合成示例：`examples/respecth/profile-demo.yaml`。真实平焰实验尚未提供，需在数据到位后核对流量、温度测量位置、坐标原点、边界条件和实验预测偏差；合成例只验证软件与数值流程。

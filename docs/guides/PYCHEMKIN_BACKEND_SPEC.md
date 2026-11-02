# PyChemkin / Ansys Chemkin 求解器接入 SPEC

日期：2026-11-02。状态：供其他 agent 实施；本轮仅编写规格，未安装依赖、执行 Chemkin 或修改功能代码。

## 1. 目标、已确认选择与交付边界

用户要求通过 https://github.com/ansys/pychemkin 调用 Ansys Chemkin，并已选择：覆盖全部现有模拟类型；网页和 YAML/CLI 均可选择后端。

实施主目录为 `pyteck-respecth`。`pyteck-respecth-release` 和同名 ZIP 是发布副本，本任务不直接修改或重新打包；先在主目录完成实现、文档和验收。保留原有 `SPEC.md`，本文件是本次新增功能的专门规格；旧 SPEC 与目前代码冲突时，以本文件明确要求及现有已实现行为为准。

交付要求：

- 增加 `cantera` / `chemkin` 后端选择；缺省仍为 Cantera。
- Chemkin 覆盖 `pfr`、`jsr`、`ignition`、`profile`、`flame`、`burner_profile` 六类；适配实际物理模型、观测量、数值验证、批处理、取消恢复、评分绘图和项目保存。
- 首版不增加 Chemkin ROP、反应路径、原生/扰动敏感性分析。在所有诊断入口明确拒绝 Chemkin 工况，不能偷偷用 Cantera 重算并当作 Chemkin 分析。
- 不实现机理优化、Chemkin GUI 自动操作、远程求解服务、加密/表面/多相/真实气体机理或同一批次混用后端。
- 不修改实验 XML、用户机理、旧结果或旧缓存证书；不把“接口调用成功”作为科学验收完成。

## 2. 调研事实与运行前提

本次已通过 Context7 成功解析 `/ansys/pychemkin` 并查询官方文档；不足之处查阅官方示例和源码。实施时优先再用 Context7 核对所安装版本，并记录实际版本、上游提交或 wheel 来源。

本机发现项目使用 `.venv313`、Python 3.13、Streamlit 1.65.0；已设置 `ANSYS252_DIR`、`AWP_ROOT252`，且相应 `reaction/chemkin.win64` 目录存在。没有安装 `ansys-chemkin-core` 的证据。未验证 DLL 是否可加载、许可证能否签出、2025 R2 对所选 PyChemkin 版本全部接口是否可用。目录存在不能作为可运行证明。

官方入门文档要求 Chemkin 2025 R2 或更新版本、有效许可证及 Python 3.10–3.x；安装包名为 `ansys-chemkin-core`，导入名为 `ansys.chemkin.core`。版本选择使用 `ANSYSxxx_DIR` 和 `PYCK_CHEMKIN_VER`。导入会初始化本地库，故只能在隔离子进程中执行。[官方安装与环境说明](https://chemkin.docs.pyansys.com/version/dev/getting-started.html)

本次查到上游主分支声明版本为 `0.2.0`。新增可选 extra：`chemkin = ["ansys-chemkin-core>=0.2,<0.3"]`；实施时确认该版本可从所用软件源获取，若不存在，不得静默安装同名第三方包或漂移到任意 main，须报告实际可获取版本并留下精确依赖记录。[上游包元数据](https://github.com/ansys/pychemkin/blob/main/pyproject.toml)

Cantera 仍是现有机理解析、统一表示和可选格式转换依赖；本功能不是移除 Cantera。无需 Chemkin 的用户应能安装、导入、启动网页、读取旧结果和运行 Cantera，且完全不加载 Ansys DLL、不签出许可证。

## 3. 配置与对外接口

### 3.1 配置约定

保持 `schema_version: 1`，仅在已有 `solver` 字典内增加可选字段：

```yaml
solver:
  backend: chemkin                 # cantera | chemkin；缺省 cantera
  rtol: 1.0e-9
  atol: 1.0e-15
  verify: true
  chemkin:
    version: "252"                 # 可选；省略时按官方规则发现
    ansys_dir: "E:/Program Files/ANSYS Inc/v252/ANSYS"  # 可选，本机路径
    max_workers: 1                 # 正整数；限制本批次同时占用许可证的工况数
    timeout_seconds: 1800           # 单次工况执行（含其验证）墙钟时限
```

上述目录只是本机配置示例，不能硬编码在源码或公共示例。`ansys_dir` 相对路径按运行配置文件所在目录解析；显式传入时必须同时指定数字字符串 `version`。显式设置只作用于该次任务的子进程环境，不写系统环境、注册表或许可证配置。

只有全局 `solver.backend` / `solver.chemkin` 控制后端和安装选择；`dataset_configs` 中出现这两项应在预检查中报配置错误，避免既有字典合并隐式改变执行引擎。数据集仍可覆盖已有物理与数值参数。

`linear_solver` 是现有 Cantera 线性求解选项，不是后端选择。Chemkin 下 `dense`/省略视为既有兼容占位，不传入 Ansys；`adaptive_preconditioned` 明确报配置错误。未知后端、未知 Chemkin 配置字段、布尔值冒充数值、非有限或非正时限/并行上限均拒绝。超限并行不自动申请额外许可。

保持原 `simulate_case(case, output=None, cancel_file=None)` 和 `CaseResult` 外形。旧 `SOLVERS` 映射可保留供 Cantera 分析内部使用；正常计算必须通过后端分派，不允许分析模块直接拿它计算 Chemkin case。

新增最小公开入口：

- `pyteck-respecth doctor chemkin [--version 252] [--ansys-dir PATH] [--timeout 30]`：隔离探测安装、包版本、DLL 初始化、许可证和六类模型所需符号，输出 JSON，失败非零退出。正常网页打开不自动执行此探测。
- 现有 `check CONFIG` 在 Chemkin 模式执行同样的环境预检查，并预处理所选机理；不做整批数值求解。环境缺失时返回可读原因和非零退出，不能产生伪成功工况。
- 现有 `run`、重试、取消、score、redraw 接口保持；运行前验证预检查指纹仍与当前配置一致。

探测输出至少包含 `available`、`package_version`、`chemkin_version`、`installation`、`capabilities`、`reason_code`、`reason`。理由区分包缺失、安装缺失、版本不符、DLL 加载、许可证、API 缺失、超时；不将许可证服务器配置或完整环境变量写入报告。

### 3.2 结果、存储与兼容

`CaseResult.metadata`、HDF5 属性及 manifest 增加实际 `backend`、PyChemkin/Ansys 版本、适配层版本、物理模型标识和输入哈希。保持既有状态集合：`success / invalid_input / unsupported / no_ignition / solver_failed / unverified / cancelled`。

预先发现无效配置或缺输运数据使用现有输入阻断；运行时原生返回非零、崩溃、超时及许可证丢失为 `solver_failed`，同时保存 `reason_code` 和原生返回码；取消为 `cancelled`。`verify: false` 仍是 `unverified`。跨后端失败绝不自动回退。

HDF5 继续使用现有 `time` 或 `grid`、`temperature`、`pressure`、`volume`（时间模型适用）、`velocity`（火焰适用）及三种组分矩阵。物种列严格重排至 `Mechanism.species`，并检查名字集合及一一对应关系；禁止依赖两个求解器天然有相同物种顺序。

预测值继续使用项目内部 SI 约定（包括以 `mol/cm3` 标记的观测，其内部浓度预测仍为 `mol/m3`，由原导出流程处理）。重用现有端点压缩流程；瞬态和火焰全域仅在执行/验证中暂存，不使批量存储变回全域永久保存。

## 4. 架构、机理与原生执行

### 4.1 模块边界和调用链

在 `src/pyteck/respecth` 增加 `backends` 子包，将后端选择/能力检查、Chemkin 环境、机理准备、单位换算和原生模型适配放在其中；不要把 Ansys 分支散落在 Cantera 反应器类中。

调用链：配置解析 → 后端静态验证 → 环境探测 → 机理准备 → 原有 build_cases/身份生成 → 原有调度器 → 后端分派 → 独立 Chemkin 进程 → SI 历程/预测/验证 → 既有原子存储、压缩、评分、绘图。

UI、父调度进程、共享包初始化以及结果重绘均不得顶层导入 `ansys.chemkin.core`。Chemkin 原生进程只接收可序列化 case/路径；调用前设置环境和独立工作目录，所有出口在可行时 `ck.done()`，并以进程退出最终回收许可和原生状态。预处理也遵守隔离要求。

采用每工况一个独立原生子进程，正常计算与其加严验证可在该进程内串行进行，但分别建目录和重置原生状态。外部 Python worker 监控取消文件和超时，轮询不超过 0.5 秒；取消后最多等待 5 秒，再终止本工况拥有的进程树并收集退出状态。Windows 启动使用隐藏窗口；不能按程序名杀掉其他 Chemkin 或用户进程。原生 `SystemExit`、硬崩溃、损坏 IPC 都不能让整个批次中断。

工况并发上限取全局 workers、火焰上限（适用时）、`chemkin.max_workers` 的最小值，默认 Chemkin 同时一个。由父调度器在提交层控制，不在一堆 worker 内等待许可证；不使用线程共享原生库。此次不增加全机器跨项目许可证调度，多个项目仍可能因实际许可不足失败。

### 4.2 机理输入

保留现有 `Mechanism.path` 的自包含 Cantera YAML 语义。在 `Mechanism.provenance` 增加 `backend_inputs.chemkin`，记录真正使用的 chem/therm/tran 文件路径、内容哈希、转换选项和日志。

- 原始 CHEMKIN `.inp`：继续现有 Cantera 校验并保留原始反应/热力学/输运输入的只读快照，Chemkin 使用这些快照，不必先转 YAML 再转回 INP。
- Cantera YAML：用当前 Cantera 3.2 官方 `yaml2ck` 转为独立 CHEMKIN 文件，保留指定气相、原 YAML 和转换记录；预检查时进行转换及 Chemkin 原生预处理。不能导出的反应/热力学/输运类型应明确失败，禁止删反应、拟合速率或静默改物种。
- 六类仍限当前项目可解析、可验证的气相机理。原生预处理成功后核对物种、反应数及 thermo/transport 可用性；集合和计数检查不能代替数值等价检查。
- 所有预处理输出使用内容身份目录和独立运行目录，禁止并发覆盖同名文件或改动源文件；Chemkin `preprocess()` 返回非零必须保留 summary/log。

新增来源路径必须纳入项目保存/迁移的依赖收集：复制到已保存项目，重写配置、manifest、case、provenance 中的路径。保存后的项目删除原临时会话仍可查看、重绘和在可用安装上重算；不复制商业 DLL、许可证或系统安装。

### 4.3 单位边界

PyChemkin 初始化默认 CGS，显式保持该约定；禁止更改全局单位后猜测某个方法的返回单位。[初始化源码](https://github.com/ansys/pychemkin/blob/main/src/ansys/chemkin/core/__init__.py)

| 量 | 项目 → Chemkin | Chemkin → 项目 |
| --- | --- | --- |
| 压力 | Pa × 10 → dyn/cm² | ÷ 10 → Pa |
| 距离/速度 | m 或 m/s × 100 → cm 或 cm/s | ÷ 100 |
| 体积 | m³ × 10⁶ → cm³ | × 10⁻⁶ |
| 密度 | kg/m³ × 10⁻³ → g/cm³ | × 10³ |
| 质量流量 | kg/s × 10³ → g/s | × 10⁻³ |
| 质量通量 | kg/(m²·s) × 0.1 → g/(cm²·s) | × 10 |
| 浓度 | mol/m³ × 10⁻⁶ → mol/cm³ | × 10⁶ |
| 温度/时间/组分分数 | K、s、无量纲保持 | 保持 |

对实际调用逐个核对官方单位。尤其不能将 Cantera kmol/m³ 的倍率套到 Chemkin mol/cm³。优先由已核实的混合物性质计算 X/Y/浓度，使用 SI 理想气体恒等式 `c_i = X_i P/(R T)` 交叉核对。`tolerances` 等元组顺序为 `(atol, rtol)`。[官方用户指南](https://github.com/ansys/pychemkin/blob/main/doc/source/user-guide.rst)

## 5. 六类模型与数值验证

所有下列名字必须以安装版本的真实 API 验证，不能用 Mock 中杜撰的符号替代。API 不可用应明确报告能力缺失，并视该类型未完成。

| kind | Chemkin 实现 | 保留的物理/观测语义 |
| --- | --- | --- |
| `pfr` | `batchreactors.batchreactor.GivenPressureBatchReactorFixedTemperature` | 现有等温定压流体微团沿停留时间积分，出口为 τ 时刻 |
| `ignition` | `batchreactors.batchreactor.GivenVolumeBatchReactorEnergyConservation` | 绝热定容，按现有定义提取点火延迟 |
| `profile` | 同上 | 同一初态求解一条轨迹，在全部观测时间提取组分 |
| `jsr` | `stirreactors.transient_PSR.TransientPSRSetResTimeFixedTemperature` | 等温、定压、指定 τ 的开放充分混合反应器，检查稳态 |
| `flame` | `premixedflames.premixedflame.FreelyPropagating` | 自由传播预混火焰，未燃气侧层流燃速 |
| `burner_profile` | `premixedflames.premixedflame.BurnedStabilizedGivenTemperature` | 固定实验 T(z)、入口质量通量/速度、全域组分 |

上述 batch 类名及时间/体积/历程接口见[官方 batch 源码](https://github.com/ansys/pychemkin/blob/main/src/ansys/chemkin/core/batchreactors/batchreactor.py)。PFR 用上述等价微团模型是为了沿用目前输入只有停留时间的假设；不凭空添加管径、长度、入口速度或改成 Chemkin 空间 PFR。结果中明确记录 `pfr_isothermal_constant_pressure_lagrangian`，确实由 Chemkin 积分。

### 5.1 瞬态、组分和点火

- PFR 必须覆盖 τ 终点，温压维持给定值；只有在输出轨迹确实包围目标时间时才允许插值，禁止外推或用最后一个早于 τ 的点充当出口。
- `profile` 保留 build_cases 合并后的全部 `target.coordinate` 和 key，覆盖 t=0、重复测量、不同物种/仪器/dataGroup；共享一条轨迹。Chemkin 输出不保证命中指定时间，因此对覆盖区间内的 SI 状态作线性插值，并通过保存间隔减半重算验证插值误差。t=0 唯一目标直接返回初态，仍标明无正时间积分。
- 点火复用项目 `extract_ignition` 的四种判据及质量分数信号语义；不直接把 Chemkin 默认 ignition time 当作最终值。现有“无法实现文献定义时允许 dT/dt 替代”的显式策略继续生效，必须保留原定义、有效定义和原因；不对未点火结果替代。
- 初始输出间隔与最大积分步长不超过 `end/history_min_intervals`（PFR/profile）或 `end/ignition_min_intervals`（点火），有效默认分别为 100、1000。点火需内峰与足够采样，时窗不足仍为 `no_ignition`。
- `verify` 时 rtol/atol 收紧十倍，保存/最大时间步长减半；比较全部目标，使用已有 `max(validation_absolute, abs(reference)*validation_relative)`。原生容差存在钳制下限时记录请求值/有效值；无法再收紧的那一项不得被假装为已收紧。未实际完成所要求的验证则为 `unverified`。
- 均匀闭式模型无实验体积时使用现有 Cantera 反应器默认的 1 m³ 参考体积，记为 numerical reference；不当作文献测量值。

### 5.2 JSR 归一化及稳态判据

官方定停留时间瞬态 PSR 使用固定入口质量流量、可变体积；项目当前模型固定体积、`mdot = rho*V/tau`。[原生 PSR 约束源码](https://github.com/ansys/pychemkin/blob/main/src/ansys/chemkin/core/stirreactors/transient_PSR.py)

首版采用以下明确适配，不换成直接求稳态根的 PSR：

- 限等温理想气体、无表面/壁面源项。Chemkin 参考入口质量流量取 `rho_in*V_config/tau`，设置相同 P/T/τ；初始组成独立使用入口或 continuation 的 `initial_X`，入口组成始终保持实验入口。
- 证明并验证两种约束得到同一组分方程 `dY/dt=(Y_in-Y)/tau + W*wdot/rho`。此证明只支持组分和定温定压状态等价，不声称原生体积/流量相同。
- 对外物理体积按实验 `V_config` 保持，物理质量流量由输出密度重新计算 `rho(t)*V_config/tau`；原生可变体积仅作为 `native_reference_volume` 的实现诊断，不混入物理 HDF5 volume。metadata 说明该归一化和适用假设。
- 求解到 `max_time`，默认 `max(100*tau,10s)`；每 τ 采样一次，用当前 `steady_floor`、`steady_threshold` 和相同公式检查连续三个窗口，温度/压力亦符合约束。记录首个满足稳态的端点作为结果；超过时限仍未稳态报告失败。
- 允许原生一次算完 max_time 后后处理寻找首个稳态时刻，随后裁剪输出；禁止把数值末态自动标成稳态。输出间隔不超过 τ/10，验证时减半。
- 延续顺序、前驱失败、初始组成的保存与恢复沿用现有逻辑。不能用“燃烧平衡态”替换独立入口初始化。

### 5.3 两种火焰

自由火焰调用 `get_flame_speed()`，cm/s 转 m/s；用 `process_solution()` 和解网格/stream 接口读取状态。初始化网格为 35 点，最大 2000 点；初始梯度/曲率阈值 0.06/0.1，后续每轮 0.03/2^i、0.05/2^i。网格上限影响身份并记录，达到上限且未收敛不能成功。[官方自由火焰示例](https://chemkin.docs.pyansys.com/version/stable/examples/premixed_flame/flamespeed.html)

自由火焰每轮先加密，再将当前域宽翻倍独立重算；分别记录燃速网格误差和域宽误差，均小于现有相对阈值才通过，最多 `flame_max_rounds`。不得用仅 native run status=0 代替验证。初始 width 沿用 0.03 m。

平焰通过 `set_temperature_profile` 提供 cm/K 曲线，域末端不得超出实验 T(z) 覆盖。入口流面积统一取 1 cm² 作为通量传递参考，显式将 SI 质量通量转为 g/(cm²·s)，不能把它当 g/s 直接传给任意面积；入口速度时由入口密度得到质量通量。物种边界选 `flux` 以匹配现有 burner 的入口组分通量条件，自由火焰选择 `comp`。核对所装版本对应边界语义并加测试。[官方给温度平焰示例](https://chemkin.docs.pyansys.com/version/stable/examples/premixed_flame/premixedburnerflame.html)

平焰初始网格用实验温度坐标，初始梯度/曲率 0.1/0.15，后续每轮 0.05/2^i、0.075/2^i；比较全部 target.coordinate 处的物种预测。只检查网格，不扩域、不外推温度；保留全部观测 key。

两种火焰都明确映射 `mixture-averaged / multicomponent` 和 `soret` 到原生接口，缺少输运数据阻断；不支持的输运选项不能静默改默认。稳态和伪时间容差显式设置为项目 atol/rtol，并记录有效设置。保留原失败/未验证状态。

## 6. 缓存、界面和诊断边界

### 6.1 身份与旧数据

- Chemkin case 身份加入后端、实际安装版本、PyChemkin 版本、适配源码哈希、原生输入哈希、转换参数、全部影响预测及验证的设置。实际安装必须在生成 case 身份前确定。
- 安装目录路径本身、取消文件、日志路径、并发数和墙钟超时不改变科学身份；版本、输入内容或物理/数值设置变化必须改变身份。容差/步长、JSR 归一化和火焰网格策略纳入指纹。
- 不给 Chemkin 添加任何历史 Cantera 身份别名；现有缓存仍可查看。因本次源码修改导致 Cantera 新身份可接受，不伪造兼容证书保证命中旧缓存。
- 缺省与显式 `backend: cantera` 具有一致的新身份；旧 manifest 缺 backend 视为 Cantera，只读加载无需安装 Chemkin。
- 同一机制的双后端比较使用两个独立批次和不同 mechanism 展示 ID（如 `model-cantera`、`model-chemkin`），复用现有 compare；不扩展评分键到双引擎维度，不把同 ID 的两份预测重复计分。backend 作为结果列/导出元数据保留。

### 6.2 网页

使用现有 Streamlit 原生组件，按 `developing-with-streamlit` 技能核对项目内 1.65 文档；无需改视觉风格。

- 数据与机理页提供求解器选择，默认 Cantera；选 Chemkin 后展开版本/安装目录、最大并行和超时设置。生成配置写入这些值。
- 条件检查页可应用/编辑同一配置，并有显式“检测 Chemkin 环境”按钮，隔离执行 doctor；显示环境就绪与各类型能力。控件采用配置为单一来源，导入配置、打开保存项目和直接编辑 YAML 后同步，避免旧 session_state 覆盖新配置。
- 更改后端/版本/路径使已准备运行失效，要求重新预检查；运行中禁用相关控件。不能修改已在运行的 case 或 manifest。
- 运行页显示实际后端和 Chemkin 并发上限；预检查错误阻止启动对应批次。错误可查看本次原生日志位置；普通界面不显示内部 ctypes 或调试堆栈。
- 结果页/导出标明后端及实际版本；离线 score/redraw/打开项目不触发原生初始化。
- Chemkin case 的单工况分析页显示“本版本尚未支持 Chemkin ROP/敏感性分析”，禁用诊断提交；CLI analyze、直接 analysis API、批量分析与历史分析缓存读取均设置同一能力检查，先检查后创建分析任务，禁止拿到旧 Cantera 分析报告充作 Chemkin 报告。

### 6.3 存储可靠性

保留已有每 case 原子提交；取消、崩溃和超时不得留下可复用的成功 JSON/HDF5。工作目录按 case/attempt 唯一命名，基准与加严运行互不覆盖；失败保留必要 native summary/stdout/stderr，成功删除可重建的原始全域文件。完整最终预测、状态、版本和验证记录不清理。

项目保存需覆盖新增 backend 输入和日志引用，避免只复制已准备 YAML。doctor 的机器目录只是运行配置，不能当必须打包的数值依赖。无原安装时打开项目可查看结果，再算时才要求重配安装。

## 7. 验收矩阵与执行顺序

### 7.1 必须新增的自动化测试

| 分组 | 场景及必须验证的行为 |
| --- | --- |
| 可选依赖 | 未安装 ansys 包时 Cantera 计算、包导入、网页启动、旧结果加载、score/redraw 正常；测试不得因顶层 import 签出许可 |
| 配置/环境 | 缺省/显式 Cantera、Chemkin 保存往返、非法后端/数值、数据集偷偷切后端被拒绝、进程局部版本覆盖、doctor 缺包/DLL/许可/API/超时 |
| 单位/顺序 | 全部换算、1 atm/1 cm/1 cm³/1 cm/s、mol/cm³、质量通量，反序物种列表；X/Y 和 SI 理想气体恒等式 |
| 六种适配 | 每类真实 API 调用契约；原生非零和 SystemExit；profile 多坐标/重复目标/t=0/范围外时间，平焰边界与域覆盖 |
| JSR | 推导组分 RHS 一致、独立初态/continuation、入口不被 initial_X 覆盖、三窗口、max_time 失败、归一化后的 V/mdot 一致 |
| 数值验证 | 收紧容差/减半输出步长实际发生，阈值内外、近零、NaN/负值、点火窗口边界/no_ignition、火焰网格/域宽分别检查、验证关闭为 unverified |
| 任务隔离 | 两个不同机理连续运行无状态污染，并发目录隔离、许可并发上限、取消/超时/原生崩溃后调度继续、恢复不复用不完整结果 |
| 缓存/保存 | 双引擎不同 ID、版本/输入/数值设置改变失效、非数值控制不改变 ID、端点压缩；保存项目后移走原会话仍可打开并解析全部输入 |
| 分析边界 | UI/CLI/直接 API/批量入口一致拒绝 Chemkin；Cantera 分析回归正常；不可加载跨后端分析缓存 |
| UI | 使用 Streamlit AppTest 检查生成配置、应用设置、导入/重开后控件同步、准备态失效、后端标签、分析禁用；实际浏览器完成选择→预检查→运行→查看结果 |

Mock 仅用于隔离失败模式、单位和调度测试；不能据此宣布六类后端可用。默认无许可测试必须能离线执行。

### 7.2 真实求解集成验收

新增 `chemkin_integration` pytest 标记，默认排除；通过明确环境开关及可用 doctor 执行。缺环境时跳过并记录原因；真实运行失败不能转成 skip。用项目公开合成机理和数据建立六类小案例，避免依赖私有 exp* 绝对路径；每类均需真实调用、通过其后端内部验证、保存和重开。

与 Cantera 比较使用同一反应/热力学/输运输入及物理条件：PFR、JSR、profile 的非近零目标相对差 ≤2%（近零绝对差 ≤1e-8 mole fraction / 1e-6 mol/m³）；点火延迟相对差 ≤2%；自由燃速 ≤5%；给温度平焰非近零目标 ≤5%。这些是初次集成验收阈值，不替代每个后端已有 1% 数值验证。超阈值输出差异和原因，不能随意放宽后标通过。

另外真实验证：同一配置第二次命中 Chemkin 成功缓存；切到 Cantera 不命中该缓存；单工况取消和超时回收进程/许可；包含中文和空格的工作路径；项目保存后移走临时原输入可重算；无 Chemkin 的离线结果浏览。

原生库若不支持中文路径，可在项目 `.cache/chemkin-native` 下的 ASCII 别名仍无效（项目绝对路径本身含中文），则使用系统临时目录创建 ASCII 运行目录并复制本工况只读输入、完成后回收，永久结果仍回写项目目录。不得修改用户源路径、系统 locale 或工作区结构来绕过。

### 7.3 分阶段实施与完成判定

1. 读取本 SPEC、现有代码和 AGENTS 指令，确认实际环境；依 Context7 和安装版本核验接口，新增可选依赖及 doctor；记录实际能否运行，不先改原有求解器。
2. 实现隔离执行、机理快照/转换、SI 历程和后端分派；优先跑通 PFR、点火、profile，再完成 JSR 和两种火焰及相应数值验证。
3. 接入身份、调度、保存迁移、后端元数据和分析能力检查，然后接入网页。不要只做 CLI 留下 UI 待办。
4. 执行新增离线测试，以及受影响的 `test_respecth`、`test_species_profiles`、`test_compact_storage`、`test_project_storage`、缓存/分析回归；新增失败才有依据扩展排查，不无目的重复全套长测试。
5. 有可用许可则执行六类真实验收和网页流程，形成 `docs/validation/chemkin-backend-validation.json`，记录实际版本、运行命令、每类结果/预测差异、状态、耗时、跳过/阻断原因及报告路径。文档更新 README_ReSpecTh、安装说明和配置示例。

全部六类真实验收通过才称“Chemkin 后端已验证可用”。若环境或 API 阻断，仍完成可验证的实现和测试，但交付必须逐项标注“实现完成/真实验证通过/待环境验证”，不能把未执行的集成测试当通过。本任务不授权改许可证服务器、安装商业 Chemkin 或删除已有数据。

## 8. 给执行 agent 的任务入口

可直接发送以下指令：

> 请在 `pyteck-respecth` 主目录实施 `docs/guides/PYCHEMKIN_BACKEND_SPEC.md`。用户已确认覆盖全部六种模拟类型，并通过网页和 YAML/CLI 选择后端。默认仍为 Cantera；Chemkin 使用可选 ansys-chemkin-core 依赖、真实 Ansys 求解、隔离进程和 SI 输出；遵守本 SPEC 的 JSR 归一化、数值验证、缓存隔离及分析能力边界。先核对 Context7/安装版本及运行条件，再实现并测试。不要修改发布副本、实验 XML、用户原始机理、旧结果或许可证设置。提交实现、配置示例、测试及真实验收记录；没有实际运行的类型必须明确标为未验证。


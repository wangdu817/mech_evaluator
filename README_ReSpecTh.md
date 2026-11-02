# ReSpecTh 机理评估与后处理

这是固定版本 PyTeCK 的扩展。原项目的 README、MIT 许可和 ChemKED 接口均保留。
实现范围与验收要求见 SPEC.md。实验 XML 仅作为只读输入。

## 启动

直接双击项目根目录的 `一键启动.bat`。脚本自动使用现有 `.venv313` 或 `.venv` 环境，后台启动服务并打开浏览器；关闭启动窗口不会停止计算。重复启动会复用本项目已有服务。默认地址为 http://127.0.0.1:8502 ，端口被其他程序占用时自动选择可用端口，实际地址会显示在启动提示中。服务仅监听本机。

首次安装才需要运行 `./setup.ps1`。也可使用 `./start.ps1`；指定优先端口：`./start.ps1 -Port 8510`，不自动打开浏览器：`./start.ps1 -NoBrowser`，仅检查环境：`./start.ps1 -CheckOnly`。本次服务日志与地址记录在 `results/runtime`。
本次机器使用 `.venv313` 验证；干净安装使用 `.venv`。
需要 Python 3.10 或更新版本。本次实际验证为 Python 3.13.3、Cantera 3.2.0、Streamlit 1.65.0。
已有本机环境无需重新安装，可直接运行 `./start.ps1`。界面已在本机启动时可直接访问上述地址。

界面顺序：选择 XML 和机理 → 编辑和预检查配置 → 确认假设后运行 → 查看评分和覆盖率 → 重绘和导出。

**GUI 新结果默认不归档为项目**，先在未保存临时会话内计算、分析与绘图。新批量计算仅保留绘图/评分预测值、验证信息和入口/出口状态；全部积分步/火焰场仅供求解临时使用，不长期保留。需要完整计算域的单点诊断自动临时重建并清理。需要长期保留时，使用左侧“项目：保存 / 打开”，选择模拟结果、敏感性/ROP、图表后保存；项目目录为 `results/projects/<名称>`。打开项目无需重算，后续修改仍写临时副本。旧结果保留。缓存管理可卸载内存视图、清理可再生缓存或确认舍弃旧临时会话；详见 [项目与缓存说明](docs/guides/PROJECT_STORAGE.md)。
运行页统一点击“载入 / 刷新计算结果”：运行中自动载入已完成结果快照，任务结束后载入完整批次。随后可切换到评分、绘图或单工况分析页。只读取已完整提交的结果，未完成工况保留待完成标记，不会填零；原任务继续运行。新增结果通过再次点击刷新载入，避免频繁自动更新。每个批次只保存一个快照视图，完整历程使用同一 NTFS 卷上的硬链接，不重复复制大文件；绘图和评分写入独立快照目录。命令行也可使用 `pyteck-respecth snapshot results/ui-run`，其输出为可用于 `redraw`、`score`、`analyze` 的快照目录。
计算结束自动显示分类成果、失败原因与各 XML 完成情况，可下载汇总 JSON 和失败 CSV。实际甲胺机理结果与后处理验收见 `docs/validation/ACTUAL_VALIDATION.md`。
绘图先选数据集：每个 set 默认全部物种，多仪器共用物种子图；勾选“只绘制指定物种 / 曲线”后可筛选。模拟用线、实验用点；宏观合图的同一条件线点同色，多机理用线型区分。四边框封闭、刻度向内。
图表页可显示实验工况说明，设置图底部、图顶部或首个子图左右上角及字号。说明从实际 scoring 工况读取压力、温度范围、入口组成、JSR 体积及停留时间；只有显式配置且与实际 τ 值一致时才显示 C/T 公式。逐点变化的入口组成显示范围，不冒称固定配比。XML 的估算压力与微量水按零表示的假设保留；文本随 PNG/PDF/SVG 和 figure_sources.json 导出，不改动模拟条件。

所有组分按 XML 记录的实际摩尔分数计算和比较，含水组分保留，不做除水归一化。旧相关配置被忽略；历史转换结果从原始历程恢复，详情见 ACTUAL_FRACTIONS_VALIDATION.md。
运行页可设置并行进程数，启动后显示同时求解的 XML、dataGroup、原始点、机理、温度、压力和停留时间，及完成数、待运行数、耗时、失败原因。独立工况按进程并行；JSR 延续模式仍遵守前驱顺序，火焰另受 `flame_workers` 限制。默认进程数为 `min(4, CPU数−1)`（至少 1），运行中不更改。增大并行数会增加内存占用，不能保证线性加速。
机理列表可以配置多个 YAML 或 CHEMKIN 输入。CHEMKIN 示例：

```yaml
- id: revised
  path: D:/path/mech.inp
  thermo: D:/path/thermo.dat
  transport: D:/path/trans.dat
  phase: gas
  species_map: {Ar: AR}
```

`species_map` 只进行用户明确指定的映射。缺物种不会自动换成别的物种；缺传输数据阻止火焰计算。

运行页预检查后显示“本次任务预览”：总工况 = 已处理 / 可复用 + 待处理；按机理列出已有验证成功、保留失败记录、待处理、输入受阻、预计新求解及评分 / 绘图工况数量。普通运行保留已完成失败记录，勾选重试才重新处理；输入受阻只记录状态，不启动求解器。全部重算时预览可复用数为零。启动时一次性载入所有可复用工况，进度从已有处理数量开始。历史批次只显示独立摘要，其工况数不替代本次预览。

条件检查页的“加密设置应用范围”可选择某一个机理，再设置总点数或变量间隔；其设置保存在该 `mechanisms` 条目的 `grid` 字段，其他机理沿用全局 `grid` 或自己的设置。选择“全部机理”会统一设置并清除各机理的单独覆盖。更换网格不删除旧结果；与当前计划一致的工况复用，旧网格中不属于本次计划的点不计入本次总数。

首页添加 YAML / CHEMKIN 时立即进行 Cantera 严格转换与加载校验；上传 CHEMKIN 与配套热力学文件齐全后自动检查，添加时按最终气相和别名再次校验。失败不会进入机理列表；成功回执包含气相、物种数、输运可用状态和工作 YAML。转换日志与输入哈希、成功 / 失败校验记录位于 `inputs/prepared-mechanisms`。加载成功只代表机理可用于预检查，不代表模拟成功或实验预测准确。

源码更新后，可在无计算任务时执行 `./.venv313/Scripts/python.exe tools/restart_idle_ui.py` 重启界面。该命令检测到计算子进程或运行锁时会拒绝重启。正常启动仍使用一键启动脚本。

工况分析页自动匹配敏感性与 ROP 缓存，并显示已有任务与待计算任务数量。切换类型时自动恢复对应结果；全部命中缓存时计算按钮禁用，可直接查看下方图表。“敏感性与 ROP”可复用此前分别计算的两类报告，只补算缺失部分。ROP 的物种或位置不再使敏感性缓存失效；敏感性目标、反应编号、物理 / 数值配置、历程内容改变时仍严格区分。已保存的全物种敏感性可通过下方“展示物种 / 目标”切换，不需要修改计算目标再积分。详见 docs/validation/ANALYSIS_AUTO_CACHE_LOADING.md。

图表工况说明自动补充入口元素氧平衡当量比 φ（固定值或范围），无法定义时说明原因；原 XML 当量比扫描坐标不被覆盖。采用 Cantera 的总元素定义，N 视为 N2，NO / 水等原组分仍计入。“宏观工况绘图方式”可选择不同 set / mix 同轴叠加或分别放入子图。

点火单工况选“仅敏感性”时，目标自动为 Temperature，无需选择物种；分析时刻默认取该工况的模拟着火延迟，也可直接编辑。下方默认显示归一化温度敏感性，温度单位 K。这是固定时刻温度敏感性代理，不是着火延迟导数。实际数据验证见 docs/validation/POSTPROCESSING_EXTENSIONS.md。

## 命令行

界面勾选“全部重新运行”并点击“运行 / 恢复”后，必须再次确认。确认区默认勾选删除本次输出目录内全部已有结果（包括未选机理缓存、图表、历史批次和关联快照）；实验源文件、机理转换成果和配置保留。取消删除选项则保留旧结果备份。只有点击“确认并开始全部重算”才执行清理和启动，取消不改变结果。命令行默认仍保留备份；显式使用 `--force-rerun --discard-previous` 可删除本次输出目录的旧结果后重算。

```powershell
.\.venv313\Scripts\python.exe -m pyteck.respecth.cli inventory ..
.\.venv313\Scripts\python.exe -m pyteck.respecth.cli run examples/respecth/demo.yaml
.\.venv313\Scripts\python.exe -m pyteck.respecth.cli run examples/respecth/demo.yaml --retry-failed
.\.venv313\Scripts\python.exe -m pyteck.respecth.cli run examples/respecth/demo.yaml --force-rerun
.\.venv313\Scripts\python.exe -m pyteck.respecth.cli redraw results/demo
.\.venv313\Scripts\python.exe -m pyteck.respecth.cli score results/demo
.\.venv313\Scripts\python.exe -m pyteck.respecth.cli cancel results/demo
```

已激活虚拟环境时，也可以使用简写 `pyteck-respecth`。新装环境将上述 `.venv313` 改为 `.venv`。
普通运行自动保留身份一致、历程完整且数值验证通过的成功缓存；默认保留失败记录，取消或尚未完成的工况继续计算。`--retry-failed` 重试失败工况并保留成功缓存。`--force-rerun` 忽略本次所选工况的全部缓存，先备份再重新计算。界面中的“重试失败工况”和“全部重新运行”分别对应这两个选项。`reuse_results` 可指定其他结果目录；本目录的失败记录不会阻止读取其他目录的同一工况成功结果。
载入、重绘、重新评分均不进行求解。崩溃后先核实任务所有者已经停止，再从已提交的工况文件恢复；运行中的批次禁止载入。XML、机理、物理条件、求解或数值验证设置以及计算引擎改变会使缓存身份变化，绘图、评分、输出目录和并行数改变不会使成功缓存失效。修改代码后应在正在运行的批次结束后重启网页服务。
`examples/respecth/local-library.yaml` 已列出全部 37 份本地实验；其中机理路径是明确的待填项。
将它换成实际甲胺机理路径后执行 `check`，按报告补齐配置再运行。

示例的氢气机理用于检查软件行为，不适用于甲胺机理评估。
本地实验配置不再要求浓度归一化基准，按 XML 的实际入口条件求解。
实际甲胺机理配置为 examples/respecth/audited-actual.yaml，显式映射 Ar: AR，直接求解原始实验工况。

## 模型与网格

PFR 为等温定压流体停留时间积分；JSR 是等温开放稳态网络，默认从入口组成独立初始化，τ=m/mdot。
JSR 延续模式使用 `initialization: continuation`，并设置 `scan_direction: ascending` 或 `descending`。
激波管为绝热定容；使用 XML 的点火定义。火焰默认 mixture-averaged、Soret 关闭，并做网格和域宽检查。
禁用 `verify` 的结果标为 `unverified`，不能进入正式总榜或作为已验证曲线。

实验点直接求解并评分。绘图网格不外推；变化字段需要显式规则。例如：

```yaml
grid_rules:
  residence_time: {kind: inverse_temperature, coefficient: 195}
  composition: linear
```

`coefficient` 单位为 K·s。线性组成插值是显式近似，不是自动重建当量比；火焰建议用户提供可追溯规则。
未确认变化字段的规则时，记录警告并只计算原始点。

补充 XML 中缺失的条件需明确提供数值和依据，例如：

```yaml
dataset_configs:
  example.xml:
    conditions:
      volume: {value: 30, units: cm3}
    condition_source: 文献表 1 的反应器体积
```

不带单位的补充数值按 SI 处理。已有 XML 值与配置冲突时阻止计算；补充不会改写原 XML。

## 评分解释

点火 E/D 保留上游方法，经验对数尺度不代表测量标准差。E 越低越好，D>0 表示预测延迟偏长。
组分和燃烧速度使用 RMSE 与实验峰值归一化 NRMSE；全零曲线需提供正归一化尺度（SI）才能归一化。
跨类型分数是扩展指标：点火 E 和其他类型 NRMSE² 分层加权平均。重复仪器曲线不额外增加物种权重。
正式总榜要求全部选定测量成功且数值验证通过；共同成功点的局部比较会显示排除数量。

```yaml
scoring:
  type_weights: {pfr: 1, jsr: 1, ignition: 1, flame: 1}
  species_weights: {CH3NH2: 2, NO: 1}
  experiment_weights: {}  # 实验身份见 manifest.json，默认均为 1
  scales: {NO2: 0.000001}  # 仅在全零曲线需要，摩尔分数
```

## 输出、恢复与独立后处理

结果目录包含冻结 XML 输入、解析对象、完整工况清单、转换后机理、每工况 JSON/HDF5、CSV 对应表、评分和图片。
HDF5 记录全物种摩尔/质量分数、温压体积和时间；火焰记录空间网格、速度、温度及组分。
CSV 标明原始点、dataGroup/property、机理、单位和状态。图形为 PNG 300 dpi、PDF 和可编辑 SVG。
`redraw` 和 `score` 从冻结输入及已保存预测工作，不调用求解器。

同一输出目录只允许一个活动任务。取消保留已完成工况，恢复复用匹配缓存。
进程意外崩溃可能遗留 `run.lock`；恢复时检查所有者并自动回收已退出进程的锁。
无法确认所有者的旧锁保留；确认对应任务已经停止后才能手动删除。
失败重试使用 `retry_failed: true`。输入、机理、求解规则或版本变化会改变缓存身份。

## 测试与限制

```powershell
python -m pytest
python -m build --no-isolation
```

详细证据见 `docs/validation/ACCEPTANCE.md` 和 `results/`。`tools/acceptance_smoke.py` 检查批量流程和缓存恢复；
`tools/ui_smoke.py` 检查界面；`tools/audit_sources.py` 核对原始文件哈希。
本机 `.venv313` 复用已有科学计算包，项目依赖的版本约束核对见 `results/runtime.json`；
全局环境其他工具的依赖冲突不属于本项目。独立新装使用 `setup.ps1` 的普通虚拟环境。

## Python 接口

界面、命令行和 Python API 共享数据与求解核心。例如：

```python
from pyteck.respecth.runner import load_config, prepare_run
from pyteck.respecth import simulate_case, evaluate_results, render_figures

config = load_config("examples/respecth/demo.yaml")
experiments, cases, warnings = prepare_run(config)
predictions = [simulate_case(case, config.output) for case in cases]
result_bundle = {"cases": cases, "results": predictions}
scores = evaluate_results(experiments, result_bundle, config.scoring)
figures = render_figures(experiments, result_bundle, {"output": config.output + "/figures"})
```

批量计算使用 `run_project(config)`，支持独立进程、缓存、恢复及取消。
直接调用严格评分时必须同时提供工况身份；结果包的 `cases` 不能省略。

软件验证、数值收敛和实验预测误差是不同结论。未点火或失败不会填零。
v1 不实现反应器热损失、压力增长、温度分布、RCM 或额外实验类型；旧 PyTeCK 入口原有能力仍独立保留。
其他 ReSpecTh 字段保留在原 XML 和解析元数据中；只有本规范的四类模型进入新求解器。

### 预条件器与多机理绘图

Cantera 3.2 零维计算可在运行配置加入 `solver.linear_solver: adaptive_preconditioned`，采用摩尔状态反应器和 AdaptivePreconditioner/GMRES；默认仍为 dense。动力学和物理工况不改变，结果保留求解统计并重新进行容差加严验证。更换求解器会改变缓存身份，因此应使用新结果目录；仅针对原失败 JSR 的真实重试脚本为 `tools/retry_actual_preconditioner.py`，输出 `results/preconditioner-retry/comparison.json`，不会覆盖原运行。预条件器不能补齐火焰输运数据，不支持直接用于 FreeFlame；JSR 达到时间上限仍不稳态时继续报告失败。

在“5 图表与导出”的“绘图机理”中选择一个或多个已运行机理，默认全部。选择仅影响绘图，评分范围仍为完整批次；点击“保存设置并重绘”后保存到 figure.yaml，图表来源 JSON 记录选定机理。机理颜色在切换选择后保持一致；宏观合图同一工况的点和线同色，不同机理使用不同线型。

### 单机理评估与历史结果比较

“1 数据与机理”提供三种添加方式：本地文件列表、填写完整路径、直接上传。默认列出 mech 文件夹和项目中已审计的工作 YAML；CHEMKIN 分别选择热力学及可选输运文件。机理名称可留空使用文件名，可连续添加多个机理或移除选中的条目；YAML 列表编辑收在高级入口。上传文件保存在项目 inputs/uploads 下，原文件不修改。转换及实际条件检查仍由“2 条件检查”完成。

`mechanisms` 列表可以只有一个机理，每次分别运行即可。已有结果在“4 误差与覆盖率”直接载入；追加其他机理的历史目录后可合并、重新评分和绘图，完全不重新模拟。默认只比较共有 XML。完整历程引用原目录，需保留这些目录。

“3 运行任务 → 本次运行机理”可选择一个或多个已添加并生成配置的机理；选择后到“2 条件检查”预检查选中的机理，再运行。改变选择后需要重新预检查。当前目录中相同缓存身份且通过数值验证的成功工况自动跳过；“复用其他结果目录”可填入其他目录。勾选“重试失败工况”只重试失败结果，成功缓存仍复用。进度面板显示缓存跳过和新提交数量。批次报告只包含本次选中机理，其他机理缓存继续保留，重新选中并恢复运行可重新生成其报告。

勾选“全部重新运行（本次选中的机理与工况）”会绕过当前目录和其他目录缓存，重新提交全部选中工况；旧的选中工况缓存与运行记录先备份到 `结果目录/rerun-backups/时间戳/`。未选中的机理缓存保留。强制重算仍执行输入和数值验证，缺条件或输运的工况不会因此变为可计算。命令行支持 `pyteck-respecth run config.yaml --force-rerun`；Python 支持 `run_project(config, force_rerun=True)`。取消后如需复用已完成结果，恢复运行时取消勾选即可。

实验目录自动扫描约定：选择包含 `exp1`、`exp2`、`exp_pw` 等实验子目录的总目录，XML 放在这些子目录第一层。总目录直属或更深层 XML 不自动列出，其他位置可在“其他 XML 路径”填写完整路径，无需搬移原文件。机理文件列表只扫描所选机理文件夹第一层，配套热力学/输运文件可从同目录选择或填写其他目录完整路径。界面提供结构示例。

新计算可通过运行配置自动复用其他目录的相同工况：

```yaml
reuse_results:
  - ../../results/multi-mechanism/single-ncho
```

相对路径按配置文件所在目录解析。只有缓存身份一致、通过数值验证且历程存在的成功结果被复用。输出目录和绘图设置不改变身份；机理、物理工况、物种映射、求解/验证设置和计算实现版本变化会触发重算。旧版结果仍能用于离线比较。

示例：`examples/respecth/single-ncho.yaml` 与 `single-ncho-reused.yaml`；命令行合并：`pyteck-respecth compare results/comparison-new results/actual-audited/full results/multi-mechanism/single-ncho`。实际验证与已知限制见 [MULTI_MECHANISM_VALIDATION.md](docs/validation/MULTI_MECHANISM_VALIDATION.md)。


### 当前选择、历史批次和图表范围

选择机理后，在运行页点击“预检查本次选择”并确认模型假设即可运行。进度中的“已处理”包含失败和输入受阻；数值验证通过数量另列。历史批次有独立名称及机理、XML 数，不能视为新选择的结果。

评分与绘图仅使用已载入结果目录，页面明确列出其数据范围和相对当前选择缺少的 XML；载入时恢复上次图表筛选，可点击“选择本批次全部数据集和机理”恢复全部可选数据。新增模拟结束后自动载入新结果。

误差 E、RMSE、NRMSE、扩展组合指标越低越好，D 的绝对值越接近 0 越好，评分覆盖率越高越完整。覆盖率和求解成功不代表预测准确。共同成功集合误差图是局部诊断；正式总榜仍要求全部选定工况通过验证、尺度完整。详见 UI_SCOPE_SCORE_VALIDATION.md。

刷新后独立恢复最近载入的结果集合，不再把最后运行的单机理批次当成全部比较结果。“误差与覆盖率”页可多选已有评估批次，选择共有或全部 XML 后合并，不启动模拟。正常缓存运行前会在输出目录的 `saved-batches/` 保存上一批清单及冻结 XML，完整历程仍引用原缓存；强制重算使用原有 `rerun-backups/` 备份。

新增第 6 页“单工况分析”：按 set/mix、扫描变量及具体值选取工况，再选择机理、ROP 物种和敏感性目标。点火默认使用固定时刻温度敏感性代理；组分使用 Cantera 原生前向敏感性，火焰速度使用原生伴随方法。使用及边界见 [CASE_ANALYSIS.md](docs/guides/CASE_ANALYSIS.md)，这是原 v1 规范之外的诊断扩展。

绘图页显示所选 XML 与机理的模拟曲线可用性。输入受阻或未计算的工况没有预测；全无模拟值的物种图标注“Experimental data only”。运行缺失工况，再载入结果重绘。详见 [PLOT_AVAILABILITY_VALIDATION.md](docs/validation/PLOT_AVAILABILITY_VALIDATION.md)。

### 绘图加密参数

“2 条件检查”提供“绘图加密工况”：可关闭，也可选择总点数或变量间隔，点击“应用加密设置”后重新预检查。当前正在运行的批次仍使用启动时的配置。

总点数包含每组不同的原始实验坐标；原始坐标超过总量时全部保留，不删除实验点。新增点优先填充最大坐标间隙。温度间隔使用 K，当量比无量纲，压力输入 atm，停留时间使用 s。间隔从组内最小坐标起算，同时保留所有原始坐标和终点，所以相邻点的实际距离可能小于设定间隔。禁止外推，每组最多 10000 点。

命令行配置：

```yaml
grid:
  enabled: true
  mode: count
  points: 100
```

或：

```yaml
grid:
  enabled: true
  mode: step
  steps:
    temperature: 20
    equivalence ratio: 0.1
    pressure: 10132.5  # 内部单位 Pa；GUI 中为 0.1 atm
    residence time: 0.01  # s
```

改变工况的入口组成和其他物理条件仍需显式 `grid_rules`。增加的点只用于绘图，评分仍使用原始实验点。没有 `mode` 的旧配置继续采用原来的均匀网格与原始点合并行为。


## 工况分析多选与组合图

在原第 6 页多选 set/mix、变量值、机理、匹配工况和物种。分析逐任务执行，完成后自动展示组合图；历史分析也支持多选载入。同机理同目标的不同工况用并列横条，不同机理、物种或 ROP 单位采用子图。每个反应器工况的原生敏感性矩阵包含全部物种；后处理切换物种不重复积分。PFR ROP 为全域积分。缺少保存值标记 ×，不补零。单张最多 8 子图，每子图最多 8 工况；最多选 4 物种、32 工况。具体定义与边界见 [分析说明](docs/guides/CASE_ANALYSIS.md)。

最终交付布局和验证结果见 [DELIVERY.md](DELIVERY.md)；历次证据汇总在 [docs/validation](docs/validation/README.md)。

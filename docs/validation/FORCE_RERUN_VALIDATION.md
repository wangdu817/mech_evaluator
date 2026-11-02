# 全部重算与目录说明

运行页新增“全部重新运行（本次选中的机理与工况）”，默认关闭。开启后忽略当前目录及 reuse_results 历史缓存，全部选中工况重新提交；关闭后沿用正常缓存/失败重试逻辑。其优先级高于“重试失败工况”，两个缓存相关输入在强制模式下禁用。

覆盖前将选中工况已有 JSON/HDF5 缓存及 manifest/config/evaluation/run_summary 记录备份到 rerun-backups 下独立目录。备份是用于恢复文件的快照，不能作为独立完整比较批次直接载入；未选中缓存及外部目录引用历程不覆盖。执行模式和备份路径写入 manifest.execution。没有改变工况或机理缓存身份计算。

实际验证：使用 clear_26092002 和原 Hjuler Set13 XML，正常运行 12 个缓存命中、0 提交；强制运行 0 命中、12 提交，12 个全部通过数值验证；24 个旧 JSON/HDF5 备份文件逐一哈希相同；再次正常恢复 12 个命中、0 提交且缓存时间戳保持。证据 results/force-rerun-validation/verification.json。

自动页面测试验证开关、互斥控件、正常缓存恢复和原绘图/评分流程；真实浏览器验证开关及提示，运行页截图 browser-force-rerun.png。验证后恢复默认关闭状态。

目录说明与实际扫描函数一致：实验总目录下 exp数字、exp_pw 子目录第一层的 XML 自动列入；总目录直属、更深层或其他命名文件夹的 XML 不自动列入，可通过“其他 XML 路径”读取。机理文件夹直接包含 YAML/INP 和可选配套 DAT，列表不递归；默认目录另列项目已转换的工作 YAML。原始文件无需搬移。两个目录输入下方已加入说明和结构示例。

CLI：`pyteck-respecth run config.yaml --force-rerun`。Python：`run_project(config, force_rerun=True)`。强制执行选项是任务调度参数，不改变物理求解和缓存身份；已有 RunConfig 与 YAML 兼容。

完整回归为 115 通过、1 跳过；跳过的是原 mech/audited_working.yaml 当前不存在时的序列化测试。历史机理结果及预条件器对照仍通过，新 clear 实际强制重算、页面回归和 wheel/sdist 打包校验通过。

# 当前任务与机理导入校验（2026-10-12）

已修复当前运行选择与历史批次统计混淆：预检查后按当前精确 case ID 核对缓存及完整 HDF5。预览与执行器共用缓存接受规则；成功必须有通过验证的完整历程和有限目标值。失败缓存在未勾选重试时保留并计作已处理，但独立列出，不计作验证成功；取消、缺文件、错身份、缺目标与非有限预测不能当作成功复用。先载入全部可复用工况再提交新求解，首次运行进度包括已有工况。

实际输入为当前 37 份 XML 与 clear_26092002、N_CHO_240725_working、Mech25_47_v1_NH3_CH4_260324_MECH。普通运行预览：总数 5718，可复用 3802（成功 3760，保留其他状态 42），待处理 1916。两个旧机理各需新求解 5 个，新机理 1906 个。勾选重试失败后：可复用 3760，待处理 1958，其中输入受阻 18，预计最多新求解 1940。当前原 XML 和机理、求解设置没有修改；旧网格中不属于当前计划的点仍保留。

单独设置新机理每组 75 点的 GUI 配置保存在 docs/delivery/gui-independent-grid.yaml；全局仍为 50，其他机理未添加覆盖。该设置仅作交互测试，用户当前配置已恢复。单元测试核对改变新机理网格前后旧机理所有 case ID 完全一致。

真实缓存恢复：独立 results/workload-validation/cached-resume 中运行一个 XML、clear 机理的 22 个工况，22 个全部缓存命中，0 新求解，首次进度 22/22；核对生产 cache 文件大小和修改时间完全未变。详见 docs/delivery/cached-resume-verification.json。

首页真实 CHEMKIN 路径入口转换成功：第三个机理包含 194 个物种，气相 gas，输运可用。GUI 用不存在的气相测试加载失败，显示检查提示并未加入列表；单元测试另使用非法 CHEMKIN 验证官方转换失败时保存日志和审计。原反应、热力学、输运文件哈希不变。

浏览器扩展禁止本地文件上传，因此浏览器拖入 / 上传文件动作未完成验证；没有调整扩展权限。文件路径入口与上传入口共用同一严格转换函数。上传文件齐全后自动校验的分支已实现，但不能将路径入口测试称为上传动作已通过。

回归：183 passed、12 skipped、1 deselected、27 warnings；被排除的是前次已记录阻塞的 tests/test_eval_model.py::TestEvalModel::test。新功能相关测试 55 passed。日志见 docs/delivery/tests-workload.txt。没有运行新机理全库模拟。

界面在独立 8503 验证后更新正式 8502；更新前检测没有计算子进程及运行锁，保存当前页面配置，未修改生产缓存。证据：docs/delivery/workload-preview.png、mechanism-intake-success.png、mechanism-intake-failure.png、workload-verification.json。

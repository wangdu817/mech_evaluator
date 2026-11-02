# 预条件器与多机理选择验收

使用 Cantera 3.2 的 IdealGasMoleReactor / IdealGasConstPressureMoleReactor 和 AdaptivePreconditioner。原物理模型、停留时间、入口、容差和稳态阈值保持一致；更换状态变量和线性求解器，不改反应速率。导数近似设置只用于求解器雅可比预条件，不删除动力学反应。

原 9 个 JSR solver_failed 工况全部独立重算，175 s 内仍未稳态，未将其标记成功；完整新旧原因和条件位于 results/preconditioner-retry/comparison.json。原 9 个火焰算例缺输运参数，预条件器不能修复此输入问题。

实际原 XML/甲胺机理的 PFR、成功 JSR 和点火分别对照预条件器解，通过容差加严验证，观测量与原稠密求解结果差异小于 1%（近零值使用记录的绝对容差）。tests/test_preconditioner.py 的 3 项真实结果回归通过。

“5 图表与导出”新增绘图机理多选，默认全部，可单机理或多机理重绘。绘图机理设置保存恢复通过 Streamlit 页面测试；颜色及宏观图线型按照整个批次机理顺序固定。评分选择独立，筛选绘图不触发重算。

新增 N_CHO CHEMKIN 的语法副本与首次热力学记录选择已完成审计。原负值 PLOG 加载障碍经用户授权，在工作副本中合并三个同产物通道并增加压力节点，原文件保持不变。实际双机理测试和独立单机理历史复用已完成；速率差异、模型限制及 192 个真实工况结果见 MULTI_MECHANISM_VALIDATION.md。该修订不作为预条件器功能的一部分，也不称为实验拟合成功。

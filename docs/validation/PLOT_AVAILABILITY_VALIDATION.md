# 绘图缺少模拟曲线检查（2026-10-09）

实际网页选中 N_CHO_240725_working、clear_26092002，以及 Marrodan_2024_Set4、Set5。原图片只有实验点。

对应历史记录：clear 的 Set4 共 120 个工况、Set5 共 121 个工况，均为 invalid_input，原因是浓度测量干湿基准未确认，没有预测值。N_CHO 历史结果不包含这两个 XML。批次完成数量包含输入受阻，不代表模拟全部成功。

修复：绘图页按所选 XML/机理/曲线检查实际可用预测点和相邻成功点是否能连线，列出缺失原因。没有任何成功模拟值的物种图标题标注 Experimental data only，不受“显示图例”开关影响。原输入、计算缓存、评分规则及物理模型不变，没有补算或填零。

真实网页已经重新绘制当前两个 set，检查提示、状态表与图片标题，并保存 `results/plot-availability-browser.png`。AppTest 在相同实际数据选择下验证提示。实际 MIX1 的两个机理均有可连线预测点；这些结果不是当前 Set4/Set5 的预测，不能混用。

验收：`results/tests-plot-availability-full.log` 为 135 passed、1 skipped；`tests/test_plot_availability.py` 覆盖真实输入受阻、缺少机理记录、成功预测可连线及导出 SVG 的实验数据限定标题。`results/ui-plot-availability-smoke.json` 记录真实数据选择下的界面检查。

后续生成 Set4/Set5 的对比需要先明确实验测量的 wet/dry 基准，再运行所需 XML 与机理。入口组成仍取 XML；这个基准描述浓度观测如何归一化，不能从入口条件推断。只有重绘不会生成缺失预测。

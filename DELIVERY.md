# 交付工作区

双击 `一键启动.bat` 启动；使用说明见 [README_ReSpecTh.md](README_ReSpecTh.md)。

| 位置 | 用途 |
|---|---|
| src/pyteck、tests | 原 PyTeCK、扩展源码与回归测试 |
| tools | 启动、维护、机理审计和验收工具 |
| examples/respecth | 合成示例及实际数据配置 |
| inputs、results | 输入、计算结果、分析、图表与用户保存的项目 |
| .cache/sessions | 尚未保存的工作会话，清理开发缓存时保留 |
| .venv313 | 当前电脑环境；迁移到新机器使用 setup.ps1 重建 |
| docs/guides | 操作与模型说明 |
| docs/validation、docs/upstream | 科学验收依据、边界及上游说明 |
| docs/delivery | 当前检查摘要、安装包哈希 |
| dist | 最新 wheel 与源码包，不含大型结果、外部 XML 和本机环境 |

新运行默认是未保存会话。批量计算只长期保留预测值、验证信息和入口/出口状态；完整计算域在单点诊断时按需重建。保存项目、清理会话与迁移限制见 [PROJECT_STORAGE.md](docs/guides/PROJECT_STORAGE.md)。

本次维护清理测试缓存、图片预览、闲置日志、旧配置备份和失效的一次性脚本，保留计算结果、未保存会话、环境、Git 仓库、许可证与机理转换依据。移除的两段旧函数无调用；其他函数的 AST 保持一致，精确版本映射保留既有模拟和分析缓存身份，今后的数值更改仍产生新身份。

清理结果见 `docs/delivery/project-cleanup.json`，源码审阅见 `dead-code-review.json`，验证见 `cleanup-verification.json`。历史验收材料按原日期阅读，不能视为本轮重算结果。当前实际数据精简存储验证见 `compact-storage-validation.json`；项目保存/重开验证见 `project-storage-verification.json`。

可执行 `python tools/cleanup_project.py` 预览可清理项，明确使用 `--apply` 才删除。检测到活动计算/分析时拒绝清理；正在使用的文件、完整输入及数值结果不在默认删除范围内。源码更新后应在计算完成时重启网页服务。

初始 SPEC 中“不做敏感性”等限制已由后续需求覆盖。点火温度敏感性是固定时刻温度代理；覆盖率、数值验证与实验预测准确度应分别解释。既有失败工况和模型限制仍保留在验收文档中。

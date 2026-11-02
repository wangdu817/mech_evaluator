# ReSpecTh 机理评估与后处理

双击 **一键启动.bat**，自动启动并打开中文科研界面。默认使用 `http://127.0.0.1:8502/`；重复启动复用已有服务，关闭启动窗口不停止计算。

本项目扩展固定版本 PyTeCK，支持 ReSpecTh 实验读取、Cantera 多机理评估、实验—模拟绘图及工况敏感性/ROP 分析。原 PyTeCK 接口、MIT 许可及引用说明保留。

- [使用说明](README_ReSpecTh.md)：数据与机理载入、运行、评分、图表和导出。
- [最终交付说明](DELIVERY.md)：目录结构、安装包、验证及限制。
- [工况分析说明](docs/guides/CASE_ANALYSIS.md)：原生敏感性、积分 ROP、多选合图。
- [历史验收证据](docs/validation/README.md)：各轮实际数据与网页检查。
- [初始规范](SPEC.md)：后续用户要求以使用说明及最终交付说明为准。
- [上游说明](docs/upstream/README.md)、[许可证](LICENSE)、[引用要求](CITATION.md)。

首次安装到新机器时运行 `setup.ps1`。当前本机使用 `.venv313`（依赖本机 Python 3.13），无需重新安装。原实验 XML 留在项目上一级的实验文件夹，项目中的 `inputs` 保存上传输入，`results` 保存实际计算成果和缓存；清理时不能删除这两个目录。

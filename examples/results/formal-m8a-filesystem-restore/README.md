# 六个正式端点的本机文件恢复

2026-10-25。已从六个实际跨主机备份包恢复到本机全新目录；输入整包SHA取自此前发布的[M4回执](../formal-m4e-training-complete/training-receipt.json)，不是从恢复输出反推。六次恢复均完成，逐文件字节数和SHA与包内源索引完全一致，索引hash与既有公开回执一致，所选适配器文件SHA也与既有公开选点记录一致。每个端点10个源文件，另保留backup-index.json；JSON元数据均成功解析。实际字节数和耗时见[实测摘要](summary.json)。

使用[恢复工具](../../../scripts/restore_model_backup.py)，复算形式如下。SOURCE_SHA256必须来自复制前保存的可信源索引；NEW_DIRECTORY必须不存在。输出在NEW_DIRECTORY/payload，逐文件恢复凭据为NEW_DIRECTORY/restore-receipt.json。失败目录保留，不覆盖或自动删除。

```bash
python scripts/restore_model_backup.py --archive PRIVATE/model.tar --expected-sha256 SOURCE_SHA256 --out NEW_DIRECTORY
```

工具先核对既有整包及成员校验，拒绝越界、链接、Windows保留名、大小写别名和文件/目录冲突，再逐文件写入和校验。它不调用extractall，不加载pickle或模型，不改写包内配置路径。恢复后训练配置仍保留原机器的路径，实际加载或恢复训练前须另行映射并记录；本轮未进行该操作。

四项恢复测试与四项既有备份测试通过，覆盖源文件一致、错误源SHA及覆盖拒绝、复制失败凭据、越界路径、Windows别名/文件目录冲突，以及既有包损坏、矩阵绑定和复制中变化。首次测试受Windows沙箱默认临时目录权限影响，7项报WinError 5；将临时目录设为工作区tmp后7项通过，补齐路径冲突测试后最终8项通过。没有因此修改实验代码或授权配置。

```bash
python -m unittest tests.test_model_restore tests.test_model_backup -v
```

本机实测没有Torch、safetensors或transformers依赖，不读取.pt训练状态内容、不解析张量、不加载底座或执行推理。本回执只完成文件恢复与JSON解析；不证明模型能实际加载、正式训练可恢复、结果可复算、存储永不失效或M8整体完成。原归档与恢复文件继续私有，GitHub仅保存工具、测试和聚合回执；M5当前仍在生成，M6/M7尚未执行。

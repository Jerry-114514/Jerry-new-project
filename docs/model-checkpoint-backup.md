# 模型、检查点的跨主机备份与校验

2026-10-24。新增 `python -m intentlab.model_backup`，在每个训练端点完成后，把适配器/完整导出、tokenizer、选点说明、result和恢复检查点封装成可逐文件校验的包。该工具只读取字节，不加载pickle、Torch模型或GPU，不把备份成功当作模型质量或M8完成证明。

实际验证已使用先前两步长历史压力实验端点：10个文件、886409656源字节，生成886435840字节未压缩tar。整包SHA256为4aa8cc37a683b945658c9e266c9ac6be2ead76f29ab3cdb8b1089a33ad81d6b6。源端包校验通过，已从AutoDL传输到用户Windows本地工作区，再用源端预先记录的整包SHA及内部各文件SHA独立核对，全部一致。该端点仍是工程压力产物，正式端点备份数0。

本轮官方底座固定revision c202236235762e1c871ad0ccb60c8ee5ba337b9a。[已有资产清单](../configs/qwen35-official-assets.json)涵盖四份权重分片和其余模型/tokenizer资产。正另行复制模型快照中的14个冻结输入文件（含下载来源记录），不创建第二份远端大模型tar；复制后逐项对照源SHA256，再核验13项官方资产。只有复制及核验成功后才生成 `official-base-backup-index.json`，不能把在传文件记成完成。

正式端点使用完成的矩阵job和协议hash绑定，逐项比对result/config及矩阵记录的checkpoint、导出文件SHA；可在六次矩阵尚未全部结束时备份已经完成的一项。冻结协议、矩阵快照及后续模型绑定也应单独保留，归档索引通过协议/job哈希联系这些记录，不能只留tar而丢失来源。没有矩阵绑定时必须显式使用engineering，不能把零散目录登记为正式完成。既有训练器/模型绑定负责验证选中的权重确为验证集最优；备份工具负责保存已绑定的字节，不能替代选点和完整实验核验。

封装前后检查源文件列表、大小和SHA；变化则保留失败状态和partial tar，不发布完成包。拒绝覆盖既有目录、源目录内部的归档位置、符号链接或外部文件。校验不解压，拒绝重复、非普通文件、非规范或越界成员名，并要求实际成员与索引严格相等。四项测试覆盖成功传输校验、矩阵绑定/未完成结果拒绝、数据损坏/危险成员拒绝及复制中真实文件变化导致失败。

```bash
python -m intentlab.model_backup create --matrix /private/formal-matrix/matrix.json --job cosine-seed-0 --out /private/backups/cosine-seed-0
python -m intentlab.model_backup verify --archive /local/backups/cosine-seed-0/model.tar --expected-sha256 SOURCE_SHA256
```

将SOURCE_SHA256替换为源端manifest.verification.archive_sha256，传输前保留该记录；不能从目的文件重新计算一个值再当作可信expected。复制命令使用实际已有的SSH认证，不把密钥、密码或认证参数写入公开归档。当前QLoRA端点包不递归复制配置所引用的原始底座目录，底座依赖由固定版本镜像和资产索引另行保存。

备份的字节校验与存储耐久性是两个判断：在同一AutoDL磁盘建tar不构成跨主机备份；通用verify返回off_host_durability_claim=false。本次实际SCP完成、用户本地文件存在且校验一致的观测另记为跨主机复制证据，不承诺任意硬盘不会失效。源码和校验索引进GitHub，模型二进制留在用户持久存储。原始训练目录保留，临时归档占用空间应在目的校验成功后按明确文件路径处理，不删除源模型或恢复检查点。

本地290项检查含16项可选ML跳过，其余通过；新增4项服务器字节检查和真实工程模型包验证已通过。实际生成包的初版源码哈希、最终校验器源码哈希及原始日志在[备份证据](../examples/results/formal-m3ad-model-backup/README.md)分别保存。正在执行的固定k重跑仍固定bb168cd0，无部署到该源目录；正式训练0/6，M8未完成。

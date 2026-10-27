# 统计与独立复算结果的备份

`scripts/backup_statistics_reproduction.py`只归档已经完成的统计监督记录、原报告和独立目录复算报告，不重新评分、不运行模型、不读取gold，也不代替M8科学验收。当前实际统计尚待M7完成，因此只有工程检查通过，没有正式统计归档完成结论。

创建前须提供此前已观察并绑定的监督状态SHA256和监督脚本SHA256，以及冻结协议和模型绑定标识。不能自行把任意未知文件的新哈希填入，以此绕过身份核验。原监督器和四阶段子进程必须全部退出，四阶段成功，原报告与复算报告相同，18个比较和17项次要比较族保持登记规模；两个统计manifest的封存、自身收据、上游M7收据与监督收据全部一致。

归档覆盖三个目录的完整普通文件清单，拒绝符号链接和嵌套源目录。准入前、复制前和复制后比较文件清单与SHA256，源文件变化时停止并保留失败记录；输出目录独占创建，不能覆盖已有档案。归档后再次校验成员大小与SHA256，保存完整receipt。此时`off_host_copy_verified=false`：仍须真正复制到另一台机器，再用原receipt逐成员复核，不能把服务器内校验称为异机备份。

```powershell
python -X utf8 scripts/backup_statistics_reproduction.py --supervision PRIVATE/SUPERVISION --analysis PRIVATE/ANALYSIS --replay PRIVATE/REPLAY --expected-status TRUSTED_STATUS_SHA256 --expected-driver TRUSTED_DRIVER_SHA256 --protocol FROZEN_PROTOCOL_HASH --binding FROZEN_BINDING_HASH --out NEW_PRIVATE_OUTPUT
```

三个合成夹具检查覆盖复制后的全成员校验、档案篡改、存活worker、不完整/失败状态、布尔值伪装退出码和重新封存但与原报告不一致的复算。本机与AutoDL服务器均三项通过，服务器工具部署在冻结源码之外，未打开正式统计材料或启动模型。首次部署验证命令因占位符误替换失败，修正命令后核对已有文件再执行检查，未覆盖正式结果。它们验证工程门禁，不能写作实际统计或真实异机复制结果。

```powershell
python -X utf8 -m unittest discover -s tests -p test_statistics_backup.py -v
```

实际执行仍须遵守冻结实验的先后顺序：M7完成并异机备份，登记统计及独立复算完成，统计归档并异机校验，随后执行已准备的模型恢复推理检查和其他验收项。M2质量边界、探索性证据支持补充、最终报告与允许公开的材料发布分别验收；归档工具始终保留`m8_complete=false`。

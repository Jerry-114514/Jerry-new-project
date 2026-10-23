# M3y 开发工程证据

范围见[共享底座开发验证](../../../docs/shared-base-residency-development.md)。不是正式训练或效果评估。

- `heldout-encoding.json` / `heldout-encoding-status.json`：0998的封存材料构建侧完整编码预检，读取参考目标、不读取模型输出，0模型调用；参数未改。
- `heldout-loss-server-tests.log` / `diagnostic-server-tests.log`：该修复的2+7项服务器检查。
- `local-tests.log`：276项本地检查，16可选ML跳过，其余通过。
- `first-fixture-failure.log`：新微型LoRA夹具因缺少匹配的底座身份被拒绝的初次失败；修正夹具后通过，未放宽资格检查。
- `server-status.json` / `server-full-tests.log`：服务器禁用GPU的完整检查及实际源码字节哈希。源码是0998加本轮三文件改动的工程快照；不是正式锁定检出。

共享常驻默认关闭，尚无实际9B共享/重载等价性或节省时长证明，正式M6/M7仍逐任务冷启动。实际财务金额、私有数据和认证材料不公开；正式训练0/6。

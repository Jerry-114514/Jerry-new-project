# M3t 开发代理功效校准

见[解释与限制](../../../docs/development-power-calibration.md)。summary.json包含16组假设场景、各400次模拟、每次10000赋号的结果和Wilson模拟误差区间；输入SHA绑定开发A/B3评分及验证案例，未公开私有内容。driver.py为实际执行的完整脚本（含生产检验一致性核对），不接触heldout模型输出。

复现需先还原M3n私有开发归档至脚本声明的runs/fewshot-completed-local-20261023路径；将driver.py复制为工作区tmp/calibrate_development_power.py，再从工作区根执行python -X utf8 tmp/calibrate_development_power.py。输出runs/development-power-calibration-20261023必须不存在，脚本拒绝覆盖；依赖NumPy（实测2.4.6）和当前仓库。固定模拟seed不是私有任务生成seed。100%模拟检出率也有有限重复误差，且不等于实际实验功效。

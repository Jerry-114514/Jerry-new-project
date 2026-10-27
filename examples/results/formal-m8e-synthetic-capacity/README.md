# 5090 共享推理配置的补充容量测量

原 RTX 5090、冻结 Python/ML 依赖及科学源码20214，BF16基础模型加余弦seed0 LoRA，沿用shared-condition-v1单底座双角色。仅使用公开合成词串，不打开测试题或gold，不重跑正式闭环。为实际走满生成上限，本进程临时禁用EOS停止并令min_new_tokens=max_new_tokens；未修改模型文件、冻结协议或科学结果。

|合成形状|角色|输入token|实际生成token|单次秒数|峰值allocated GiB|峰值reserved GiB|
|---|---|---:|---:|---:|---:|---:|
|短上下文|actor|1024|256|8.55|17.07|17.36|
|短上下文|analyzer|1024|256|12.67|17.11|17.40|
|满预算|actor|15872|1536|56.31|19.45|20.44|
|满预算|analyzer|15872|1536|75.91|20.29|22.86|

设备报告总容量31.36GiB；四个实际长度均完成，含加载的测量总耗时164.39秒。输入加生成最高17408token，与冻结上下文上限一致。allocated和reserved不能相加；后者包含缓存保留。设备used的调用后采样不是设备全程峰值，原始数值见[profile-status.json](profile-status.json)。模型文本未保存或公开。

这是原环境中的单次合成容量测量，受缓存、顺序和当前环境影响，不是通用吞吐承诺。EOS强制满长度与正式自然停止不同，**不能回填M6/M7原运行缺失的峰值显存**，也不证明任务正确性或任意更大配置可行。

源码：[profile_synthetic_inference_capacity.py](../../../scripts/profile_synthetic_inference_capacity.py)。脚本检查冻结源码干净、协议/绑定/统计完成状态、模型文件字节、原预算守护、依赖版本及GPU独占，再测量两个输入形状和两种角色；失败停止，无自动重试。实际退出0及异机复制字节核验见[verification.json](verification.json)。

输出JSON为公开排版副本，其SHA与原始复制字节SHA分开标记。测试材料和原始模型输出继续保持私有，本目录不包含它们。

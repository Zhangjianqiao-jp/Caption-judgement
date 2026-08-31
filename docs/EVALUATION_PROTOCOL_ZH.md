# 幽默图片 Caption 独立评测准则 v1.0

## 1. 适用范围

本准则用于比较两个或多个 image-to-humorous-caption 系统。核心观察对象是同一图片、同一目标文化和同一生成 seed 预算下的 caption group。它兼容 Text-HOMER、latent bridge、SFT、DPO 等方法，但评审界面不暴露方法名称。

## 2. 冻结与预注册

评分前冻结：数据 split、图片 SHA-256、系统 checkpoint、planner/generator prompt、generation 参数、generation seeds、候选数 N、主要 comparison、primary endpoint、bootstrap seed、claim gate。test 只运行一次正式去盲分析；调参使用 validation。

建议至少：

- pilot：每图 3 seeds，足够多的 held-out 图片；
- final：每图 10 candidates 更接近 Humor in AI group benchmark；
- 三名相互独立的评审；
- 文化任务使用目标文化匹配的人类评审。

## 3. 评审顺序

每个 packet 必须按以下顺序：

1. 查看真实图片，确定可见对象、行为、关系和中心冲突；
2. 独立阅读 A 组，不与 B 比较，判断每条的视觉事实性与笑点；
3. 独立阅读 B 组；
4. 选 A、B 各自最佳 caption；
5. 给每条 caption 绝对标签；
6. 给两组多维分数；
7. 最后回答 Overall 和 Best Pick；
8. 写一句可见图像依据。不要输出冗长推理。

## 4. 相对端点

### Overall

判断整组输出在相同采样预算下的总体表现。兼顾：好结果频率、稳定性、明显失败、图像相关性。不能因为一组只有一条偶然好 caption 就忽略另外两条严重失败。

### Best Pick

先独立选出每组最佳 caption，再比较二者。这衡量 best-of-N 能力。若差距不具有实际意义，选 Tie。

## 5. 绝对标签

- **good**：确实能产生幽默反应；笑点依赖图片；结构完整；具原创性；接近可发表。
- **weak**：相关且可理解，但仅轻微幽默、过于直白、泛化、俗套、牵强或措辞不自然。
- **bad**：不幽默、严重幻觉、逻辑不通、与图片无关、近乎复制、冒犯或不可理解。

“相对更好”不自动等于 good。Group absolute 是对整组的总体标签；candidate label 必须逐条填写。

## 6. 多维 1–5 分

- **Humor**：反差、意外、双关、角色错置、setup/payoff 的强度。
- **Image grounding**：笑点是否由可见细节支持；5 不允许关键对象/动作幻觉。
- **Image relevance**：是否真正回应这张图，而不是可套用到同类场景的泛化句子。
- **Originality**：是否避开可套在任意图片上的网络模板和陈词滥调。
- **Specificity**：是否利用本图独特关系、冲突或联想，而非只描述类别。
- **Fluency**：是否简洁自然，像 caption 而非解释文字。
- **Hallucination severity**：1 表示没有关键幻觉，5 表示笑点依赖严重虚构内容；此维度越低越好。
- **Cultural fit**：仅有明确 target culture 时评估该文化中的可理解性与适切性。
- **Stereotype risk**：1 表示低风险，5 表示高风险；它不是“越高越好”的质量维度。

## 7. 评审偏差控制

- A/B 位置由 HMAC 密钥确定性随机；每个比较默认有 A/B 反转镜像。
- 候选顺序单独确定性打乱。
- 不显示系统名、checkpoint、训练方法、预期假设。
- 不以较长、标点多、emoji、`POV/Bro/Meanwhile` 模板作为幽默替代。
- 两个镜像不能连续展示给同一人；评审顺序应再次随机并适当间隔。
- LLM temperature=0，记录精确模型版本；更换模型版本视作新实验条件。

## 8. 统计

图片而不是 caption 行是独立单位。每个镜像 pair 先在同一 rater 与图片内折叠；再在图片内合并 rater。报告：

- challenger win rate，Tie=0.5；
- 图片聚类 hierarchical bootstrap 95% CI；
- 图片级配对 sign-flip p-value；
- Holm 多重比较校正；
- Krippendorff nominal α；
- A-choice rate 和镜像系统选择一致率；
- absolute label 分布、good rate、seed 方差；
- 多维质量和 diversity。

## 9. 结论模板

允许：

> 在预注册的 Overall endpoint 上，系统 B 相对系统 A 的图片级 win rate 为 X，95% CI [L,U]；绝对 good rate 与 grounding 未退化。

不允许：

> B 的点估计为 52%，所以 B 显著更好。

> B 战胜一个 bad baseline，所以 B 已经真正好笑。

> Distinct-2 上升，所以幽默多样性提高。

## 10. 论文依据

本准则以 NeurIPS 2024 Humor in AI 的 group preference、ACL 2023 Electronic Sheep 的同图困难比较、NeurIPS 2023 MT-Bench 的 judge position-bias 分析、EMNLP 2023 G-Eval 的结构化标准为核心；diversity 参考 EACL 2021 diversity evaluation 与 TMLR 2023 Vendi Score。链接见根目录 README。

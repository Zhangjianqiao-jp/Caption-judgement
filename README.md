# Caption-judgement

一个面向 **image → humorous caption** 的、确定性、匿名、可复现评测框架。它把 Humor-generator 的生成结果转成密钥盲化的 Group-of-N packet，收集独立评审，执行镜像消偏、图片聚类统计、绝对质量与多维质量分析，并输出可审计报告。

本项目解决的不是“让一个 judge 随便打分”，而是建立如下闭环：

```text
固定 checkpoint / prompt / generation config / seeds
                 ↓
校验并冻结 generations.jsonl + SHA-256
                 ↓
HMAC 匿名化 + A/B 随机化 + 镜像 packet
                 ↓
独立人类或 LLM judge（先绝对、后相对）
                 ↓
完整性校验 + 去盲 + 镜像折叠
                 ↓
image-clustered CI + 配对置换检验 + Holm 校正
                 ↓
win rate + good/weak/bad + grounding/originality/diversity
                 ↓
预注册 claim gate → 报告、图、manifest
```

## 为什么这样设计

1. **任务匹配。** NeurIPS 2024 Humor in AI 使用 New Yorker Caption Contest 大规模评分数据，并报告 Group Overall / Group Best Pick。这里保留这两个端点，但候选组大小可配置；当前 Humor-generator 的历史主协议是 Group-of-3，若要更贴近该 benchmark 可设为 10。
2. **同图困难比较。** ACL 2023 *Do Androids Laugh at Electric Sheep?* 强调在同一图片内比较 finalist 与较弱 caption，以避免视觉内容成为混杂因素。本框架强制两个系统具有完全相同的 `image_id × target_culture` 覆盖和共享 generation seeds。
3. **控制 judge 偏差。** NeurIPS 2023 *Judging LLM-as-a-Judge* 识别了位置、冗长和自我偏好等偏差。本框架对 A/B 做密钥确定性随机化，并默认创建方向相反的镜像 packet；统计前先折叠镜像。
4. **结构化准则。** EMNLP 2023 G-Eval 支持“明确标准 + 固定评测步骤 + 结构化表单”。本框架要求先看图、再分别评价组、最后相对比较，并输出机器可校验 JSON；只要求简短视觉证据，不收集或依赖隐藏思维链。
5. **不把相对胜出误写成好笑。** 一个 weak 系统也能战胜 bad 系统，所以同时报告 group/candidate 的 `good / weak / bad`，以及 humor、grounding、originality、specificity、fluency 五维分数。
6. **正确统计单位。** 同一图片的多个 seed、两个镜像和多个评审不是独立图片。主要推断单位固定为 `image_id × target_culture`，bootstrap 先抽图片，再抽该图片内评审；显著性使用图片级配对 sign-flip test。

## 安装

服务器默认 `python` 可能是 3.6；本项目要求 Python 3.10+。本服务器可显式使用：

```bash
/home/app/python/3.12.11/bin/python3 -m pip install -e '.[test,plot]'
```

普通环境：

```bash
python3.12 -m pip install -e '.[test,plot]'
```

## 与 Humor-generator/v3.5 完整对接

v3.5 generation JSONL 应至少包含：

```json
{
  "receiver": "sft",
  "condition": "typed_bridge",
  "cluster_id": "nycc_123",
  "image": "/absolute/path/to/image.png",
  "caption": "...",
  "generation_seed": 20260830,
  "split": "test"
}
```

转换命令：

```bash
caption-judge adapt \
  --input /path/to/v3.5/generations.jsonl \
  --output run/generations.jsonl
```

映射规则是确定的：

| v3.5 | Caption-judgement | 说明 |
|---|---|---|
| `receiver + condition` | `system_id=receiver::condition` | 不丢失 receiver 身份 |
| `cluster_id` | `image_id` | 图片级统计单位 |
| `image` | `image_path` | 必须存在 |
| 图片字节 | `image_sha256` | adapter 现场计算 |
| `generation_seed` | `generation_seed` | 原样保留并配对 |
| `target_culture` | `target_culture` | 可选；存在时进入统计单位 |

adapter 会拒绝图片不存在、字段缺失、重复 seed 等情况。若输入已经是规范 schema，`adapt` 会原样标准化。规范见 `schemas/generation.schema.json`。

## 一次完整运行

### 1. 生成并冻结候选

每个系统必须对同一批图片使用相同 seed 集。至少 3 seeds；最终大样本实验可用 10 candidates。不要在看到 test 结果后更换 seed。

### 2. 生成盲评包

密钥只保留在可信机器，绝不能发送给评审：

```bash
umask 077
openssl rand -hex 32 > run/blind.secret

caption-judge build-packets \
  --generations run/generations.jsonl \
  --comparison 'sft::text_homer=>sft::typed_bridge' \
  --secret-file run/blind.secret \
  --group-size 3 \
  --family primary \
  --public run/blind_packets.jsonl \
  --private run/private_mapping.jsonl \
  --manifest run/packet_manifest.json
```

注意：v3.5 的 `system_id` 本身含 `::`，所以 comparison 使用无歧义的 `REFERENCE=>CHALLENGER`。不含冒号的简单系统名也兼容旧式 `REF:CHAL`。

生成评审提示与空白答卷：

```bash
caption-judge render-prompts --packets run/blind_packets.jsonl --output run/judge_prompts.jsonl
caption-judge rating-template --packets run/blind_packets.jsonl --rater-id judge-1 --output run/judge-1.json
```

调用多模态 judge 时，必须把 `image_path` 对应的真实图片作为图像输入发送；只把路径写入文本不算看图。temperature 固定为 0，记录 provider、model、版本日期和 prompt SHA-256。不同 judge 独立评审，不能看到其他评审结果或 private mapping。

### 3. 预审计

```bash
caption-judge audit \
  --generations run/generations.jsonl \
  --packets run/blind_packets.jsonl \
  --mapping run/private_mapping.jsonl \
  --output run/audit.json
```

审计覆盖：系统/图片/seed 完整性、重复 caption、长度与模板词差异、公开 packet 中系统名泄漏、镜像方向完整性。

### 4. 聚合三名以上独立评审

```bash
caption-judge aggregate \
  --mapping run/private_mapping.jsonl \
  --ratings run/judge-1.json run/judge-2.json run/judge-3.json \
  --seed 20250308 --bootstrap 10000 \
  --output run/aggregate.json

caption-judge diversity --generations run/generations.jsonl --output run/diversity.json
# 正式复现 Humor in AI 的语义多样性时，先安装 [semantic]，再加：
# --sbert-model sentence-transformers/all-mpnet-base-v2

caption-judge report \
  --aggregate run/aggregate.json \
  --audit run/audit.json \
  --diversity run/diversity.json \
  --plots-dir run/plots \
  --output run/REPORT.md
```

也可执行 `scripts/run_closed_loop.sh`。无 rating 参数时它停在空白答卷；有 rating 参数时完成聚合和报告。

## 评分准则

完整中文准则见 [docs/EVALUATION_PROTOCOL_ZH.md](docs/EVALUATION_PROTOCOL_ZH.md)。固定 prompt 在 `caption_judgement/prompts.py`，其 SHA-256 写入 manifest 与每份 rating。核心规则：

- `overall`：整组三条（或 N 条）总体谁更强；兼顾稳定性，不只看一个偶然好样本。
- `best_pick`：两组各自最佳 caption 谁更强；衡量 best-of-N 潜力。
- `absolute_*`：组级 good/weak/bad。
- `candidate_labels_*`：每条 caption 的 good/weak/bad，能报告 seed 方差和真实好结果比例。
- dimensions：`humor`, `image_grounding`, `image_relevance`, `originality`, `specificity`, `fluency`, `hallucination_severity`；文化实验额外填写 `cultural_fit` 与 `stereotype_risk`。两个 risk/severity 维度越低越好。

## 去盲和统计

相对选择转换为 challenger 分值：

```text
challenger chosen = 1
Tie               = 0.5
reference chosen  = 0
```

镜像 packet 先在 `rater × image-unit × comparison` 内取平均。一个总选 A 的位置偏置评审在镜像折叠后得到 0.5，而不是制造虚假的系统胜率。之后：

1. 每个图片单位内合并评审；
2. 对图片单位做 hierarchical bootstrap 95% CI；
3. 对图片级 `(win_rate - 0.5)` 做双侧 paired sign-flip test；
4. 多个比较使用 Holm family-wise correction；
5. 报告 Krippendorff nominal α 与镜像一致率，但低一致性不能靠增加 LLM 次数“投票掩盖”。

## 声明“更好”的门槛

默认策略在 `configs/evaluation_policy.yaml`。主结论只能在以下均满足时成立：

1. 预注册 primary endpoint 的 challenger 95% CI 下界高于 0.5；
2. Holm 校正后显著；
3. 至少 3 个独立评审；
4. 镜像与 A/B 位置诊断无严重异常；
5. absolute good/weak/bad 不退化；
6. image grounding 不退化，hallucination/generic-template rate 不恶化；
7. 结论在图片级而非 caption 行级成立。

若只满足相对 win rate，则只能写“在该对手下相对偏好更高”，不能写“真正更好笑”。若 CI 跨 0.5，应报告不确定，而不是以点估计决定胜负。

## LLM judge 与人类评审

- LLM judge 适合可复现筛选，但最终论文主结论建议加入与目标文化匹配的人类评审。
- 固定 judge 版本和日期；API 模型更新后视为新 rater stratum。
- 至少做少量专家 adjudication 和 calibration；不要让同一模型既生成又作为唯一 judge。
- 文化幽默必须指定 target culture，评审者要具有相应文化能力；不懂某文化应弃权/更换评审，不得猜测。
- prompt 不展示系统名、训练方法、checkpoint 或“哪个是新模型”。private mapping 不进入 judge 进程。

## 可复现产物

每次正式运行至少保存：

```text
generations.jsonl
blind_packets.jsonl
private_mapping.jsonl        # 保密到评分结束
packet_manifest.json
judge_prompts.jsonl
judge-*.json
audit.json
aggregate.json
diversity.json
REPORT.md
plots/
```

同时在上游保存 git commit、checkpoint manifest、generation config、prompt、seed、dataset split/hash。`packet_manifest.json` 固定源文件、公开 packet、private mapping 和 rubric 的 SHA-256。

## 测试

```bash
/home/app/python/3.12.11/bin/python3 -m pytest
```

测试覆盖 packet 的确定性、匿名性、镜像反转、真正 challenger 胜出的恢复、总选 A 的位置偏置被折叠为 tie、文化统计单位与覆盖失败。

## 方法边界

- Group-of-N 衡量的是固定采样预算下的系统行为，不等于单次 greedy deployment 性能。
- EAD/Distinct 等 diversity 指标可能被低质量随机文本提高，因此必须和 absolute good rate 联合解释。
- 自动 judge 不能替代目标人群对文化幽默的外部效度。
- 本框架不提供“真理分数”；它提供的是可审计的测量程序、偏差诊断和统计不确定性。

## 主要论文依据

- Hessel et al., **Humor in AI: Massive Scale Crowd-Sourced Preferences and Benchmarks for Cartoon Captioning**, NeurIPS 2024 Datasets and Benchmarks. [Official paper](https://proceedings.neurips.cc/paper_files/paper/2024/file/e297fb6cd1690ee5b39c5bb4c58ad801-Paper-Datasets_and_Benchmarks_Track.pdf)
- Hessel et al., **Do Androids Laugh at Electric Sheep? Humor “Understanding” Benchmarks from The New Yorker Caption Contest**, ACL 2023. [ACL Anthology](https://aclanthology.org/2023.acl-long.41/)
- Zheng et al., **Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena**, NeurIPS 2023. [arXiv](https://arxiv.org/abs/2306.05685)
- Liu et al., **G-Eval: NLG Evaluation using GPT-4 with Better Human Alignment**, EMNLP 2023. [ACL Anthology](https://aclanthology.org/2023.emnlp-main.153/)
- Tevet and Berant, **Evaluating the Evaluation of Diversity in Natural Language Generation**, EACL 2021. [ACL Anthology](https://aclanthology.org/2021.eacl-main.25/)
- Friedman and Dieng, **The Vendi Score: A Diversity Evaluation Metric for Machine Learning**, TMLR 2023. [OpenReview](https://openreview.net/forum?id=g97OHbQyk1)

## License

MIT.

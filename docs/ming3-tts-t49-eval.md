# Ming-3.0-tts T-49 质量评测执行包

对应 [ming3-tts-tasks.md](ming3-tts-tasks.md) 的 T-49 和 [ming3-tts-prd.md](ming3-tts-prd.md) §6.1.2。目标是拿这套材料就能完成 50 条样本的双人独立评分，并和 mlx-audio CLI 同参数结果对比。

## 1. 文件清单

| 文件 | 用途 |
| --- | --- |
| [ming3-tts-t49-samples.csv](ming3-tts-t49-samples.csv) | 50 条样本、参数、评分重点，生成音频的唯一数据源 |
| [ming3-tts-t49-rater-a.csv](ming3-tts-t49-rater-a.csv) | 评分者 A 的空白评分表 |
| [ming3-tts-t49-rater-b.csv](ming3-tts-t49-rater-b.csv) | 评分者 B 的空白评分表 |
| [ming3-tts-t49-cli.csv](ming3-tts-t49-cli.csv) | mlx-audio CLI 对照的空白评分表 |
| 本文件 | 流程、评分标准、汇总与回填模板 |

CSV 都是 UTF-8 with BOM，Excel 和 Numbers 可以直接打开。音频文件写到 `output/t49/`，`output/` 已在 `.gitignore` 中，不会进仓库。

## 2. 样本构成

| 语言 | 短句 | 长句 | 数字（写成文字） | 中英混排 | 声音设计 | 合计 |
| --- | --- | --- | --- | --- | --- | --- |
| 中文 | 6 | 6 | 4 | 2 | 2 | 20 |
| 英文 | 5 | 5 | 3 | 1 | 1 | 15 |
| 德/西/法/韩/日 | 各 1 | 各 1 | 各 1 | 0 | 0 | 各 3 |
| 合计 | 16 | 16 | 12 | 3 | 3 | 50 |

说明：

- 语言分布按 §6.1.2：中文 20、英文 15、德/西/法/韩/日各 3。
- 数字样本全部写成文字，不用阿拉伯数字，避免测成文本正则而不是发音。
- 47 条使用已验证能力（基础合成、多语言）；3 条声音设计样本用于评分「指令遵循」中的音色描述，声音设计在 §6.2 中属于已验证能力。
- 不包含情绪、语速、音高、音量、方言和 IP 样本。这些属于实验能力，是否可用由 T-05 听感确认，不混进 T-49 的主评分。

完整文本、`language`、`task`、`voice`、`instructions`、`seed` 和评分重点见 [ming3-tts-t49-samples.csv](ming3-tts-t49-samples.csv)。

## 3. 固定版本与生成音频

### 3.1 先记录环境

以下命令和 Python 片段都在仓库根目录执行。

```bash
git rev-parse HEAD
envs/ming-tts/bin/python -c "import mlx_audio, mlx.core as mx; print('mlx-audio', mlx_audio.__version__); print('mlx', mx.__version__)"
shasum -a 256 models/ming-tts/8bit/model.safetensors
```

权重 revision 固定为 `049da49260b32e19fe8336ecd9b38a89f490dc1d`，`mlx-audio` 固定为 `0.6.1`（必须包含 PR #1047）。换版本后旧分数不能和新分数直接比较。

### 3.2 生成服务端音频

所有样本 `seed=42`，保证服务端结果可复现。逐条执行或直接运行下面的 Python 片段：

```python
import csv
import subprocess
from pathlib import Path

root = Path(".")
out_dir = root / "output/t49/service"
out_dir.mkdir(parents=True, exist_ok=True)

with (root / "docs/ming3-tts-t49-samples.csv").open(encoding="utf-8-sig") as f:
    for row in csv.DictReader(f):
        cmd = [
            "envs/ming-tts/bin/python", "-m", "runtimes.ming_tts.cli",
            "--text", row["文本"],
            "--output", str(out_dir / f"{row['样本ID']}.wav"),
            "--language", row["API语言"],
            "--task", row["task"],
            "--voice", row["voice"],
            "--seed", row["seed"],
        ]
        if row["instructions"]:
            cmd += ["--instruct", row["instructions"]]
        subprocess.run(cmd, check=True)
```

单条命令示例：

```bash
envs/ming-tts/bin/python -m runtimes.ming_tts.cli \
  --text "今天的天气很好，适合去公园散步，顺便看看湖边新开的咖啡馆。" \
  --output output/t49/service/ZH-07.wav \
  --language zh --task auto --voice auto --seed 42
```

### 3.3 生成 CLI 对照音频

`mlx_audio.tts.generate` 没有 `--task` 和 `--seed`，其余参数按下表对齐。用下面的片段生成，输出为 `output/t49/cli/<样本ID>.wav`：

```python
import csv
import subprocess
from pathlib import Path

root = Path(".")
out_dir = root / "output/t49/cli"
out_dir.mkdir(parents=True, exist_ok=True)

with (root / "docs/ming3-tts-t49-samples.csv").open(encoding="utf-8-sig") as f:
    for row in csv.DictReader(f):
        cmd = [
            "envs/ming-tts/bin/mlx_audio.tts.generate",
            "--model", "models/ming-tts/8bit",
            "--text", row["文本"],
            "--output_path", str(out_dir),
            "--file_prefix", row["样本ID"],
            "--audio_format", "wav",
            "--join_audio",
        ]
        if row["instructions"]:
            cmd += ["--instruct", row["instructions"]]
        if row["API语言"] in {"de", "es", "fr", "ko", "ja"}:
            cmd += ["--lang_code", row["API语言"]]
        subprocess.run(cmd, check=True)
```

参数对齐说明：

| 参数 | 服务端 | CLI | 说明 |
| --- | --- | --- | --- |
| `voice` | `auto` | 省略 | 本套样本没有内置音色；`auto` 在服务端最终也按无音色处理 |
| `language` | `zh`/`en`/`auto` 或五语种 | 五语种传 `--lang_code`，其余省略 | CLI 默认 `en`，模型只对 de/es/fr/ko/ja 追加 Target language，因此 zh/en/auto 与省略等价 |
| `task` | `auto` 或 `voice_design` | 无对应参数 | CLI 通过是否传 `--instruct` 区分普通合成和声音设计 |
| `seed` | 42 | 无参数 | CLI 不支持 seed，这是两套结果的已知差异 |
| 输出 | 单文件 WAV | `--join_audio` 单文件 WAV | 不加 `--join_audio` 会按片段写成 `_000.wav` |

`seed` 差异会让 CLI 结果有随机波动。如果服务端与 CLI 的总平均差在 0.1 分以内，建议 CLI 重跑 3 次取总平均的中位数再判定，并在结论里注明。

### 3.4 试听前检查

- 每条音频都能完整播放，没有 0 字节、截断或明显静音。
- 文件名与样本 ID 一致，服务端和 CLI 两个目录数量都是 50。
- 用同一副耳机、同一音量；不要做响度归一化或二次降噪。
- 评分期间关闭其他音频，避免切歌和通知声。

## 4. 评分标准

四项各 1~5 分，必须打整数，不能打 4.5。评分者只看样本 ID、文本和参数，不知道音频来自服务端还是 CLI。

| 分数 | 可懂度 | 自然度 | 音色一致性 | 指令遵循 |
| --- | --- | --- | --- | --- |
| 5 | 完全听清，没有歧义 | 接近真人，韵律、停顿、重音自然 | 全程稳定，且完全符合目标音色 | 文本完整，数字、缩写、标点、停连全对；声音设计完全符合描述 |
| 4 | 清楚，个别字需要结合上下文 | 有轻微机械感，不影响整体 | 基本稳定，偶有轻微漂移 | 有少量偏差，但不影响理解 |
| 3 | 能听懂，但需要费力 | 明显机械或停顿不自然 | 有可察觉的音色变化 | 有可察觉的偏差，如数字读错一处、漏掉一个词 |
| 2 | 多处听不清 | 严重拼接感，难以连续听 | 明显变化、破音或忽大忽小 | 多处偏差，影响语义 |
| 1 | 无法理解 | 难以接受 | 完全不是目标音色，或全程不稳定 | 基本没有遵循文本或描述 |

评分口径：

- **可懂度**：第一次听能否听清。允许最多重放 2 次，重放后仍听不清按 1~3 分。
- **自然度**：只看韵律、节奏、停顿、气息和机械感，不因为音色不喜欢而扣分。
- **音色一致性**：普通样本看一条音频内部是否稳定；声音设计样本还要看是否像 `instructions` 描述的人。两者都满足才能给 5 分。
- **指令遵循**：普通样本看文本保真度，包括漏字、加字、数字读法、英文缩写、标点停顿；声音设计样本还要看描述中的年龄、性别、音色和语速是否实现。文本保真和音色描述各占一半权重，按较差的一项定档。
- 发现技术故障（无音频、截断、明显爆音）时，相关维度记 1 分，并在「问题描述」写清楚，不要空着。

## 5. 双人评分流程

1. A、B 各拿一份评分表，分别独立评分，不交流、不互看。
2. 建议两人使用不同的随机播放顺序，减少顺序和疲劳带来的偏差；评分表仍按样本 ID 填写。
3. 每条样本四项都填，均分列用 `=AVERAGE(G2:J2)`（评分表 G~J 列），也可以留空最后统一算。
4. 单人完成后先不汇总，交给第三人做一致性检查。
5. 逐维度比较 A/B：
   - 分差 ≤ 2：取两人平均分。
   - 分差 > 2：第三人独立重听该样本，分差超过 2 的维度用第三人的分数，其余维度仍取 A/B 平均。
6. 样本最终均分 = 四个维度最终分的平均。总体四项平均 = 50 个样本最终均分的平均。
7. 判定用未四舍五入的值，展示时保留两位小数。

通过条件（四条必须同时满足）：

- 四项总平均 ≥ 4.0。
- 四个单项平均各 ≥ 3.5。
- 最终均分低于 3 的样本不超过 5 条。
- 服务端四项总平均 ≥ mlx-audio CLI 四项总平均。

## 6. 汇总与 CLI 对照

建议在评分表旁边新建一个汇总页，列：

```text
样本ID | A可懂 | A自然 | A音色 | A指令 | B可懂 | B自然 | B音色 | B指令 |
不一致维度 | 复核分 | 最终可懂 | 最终自然 | 最终音色 | 最终指令 | 最终均分 | 是否<3 | 备注
```

汇总时记录：

| 指标 | 值 |
| --- | --- |
| 四项总平均 |  |
| 可懂度平均 |  |
| 自然度平均 |  |
| 音色一致性平均 |  |
| 指令遵循平均 |  |
| 低于 3 分样本数 |  |
| CLI 四项总平均 |  |
| 服务端是否不低于 CLI | 是 / 否 |
| 最终结论 | 通过 / 不通过 |

CLI 对照建议由没参加主评分的第三人盲评，或由 A/B 在主评分全部完成后盲评：把 CLI 文件重命名为 `C-01` 到 `C-50`，单独保存映射表，评分表只写 `C-xx`。如果直接用原样本 ID，评分者会知道哪份是服务端，容易产生预期偏差。

## 7. 回填 T-49

完成后把下面这段填进 [ming3-tts-tasks.md](ming3-tts-tasks.md) 的 T-49 结论，并勾选任务：

```text
结论：50 条样本由 A/B 独立评分，四项总平均 X.XX；可懂度 X.XX、自然度 X.XX、
音色一致性 X.XX、指令遵循 X.XX；低于 3 分样本 N 条；mlx-audio CLI 四项总平均
X.XX，服务端不低于/低于 CLI。结论通过/不通过。
环境：Apple M2 16GB，macOS 15.7.9，mlx-audio 0.6.1，权重 revision
049da49260b32e19fe8336ecd9b38a89f490dc1d，评测日期 YYYY-MM-DD。
评分者：A（ ）、B（ ），复核人（ ）。
失败样本：列出样本 ID 和主要问题。
```

T-49 未完成前不要勾选，也不要把预期结果写进任务清单。

## 8. 已知限制

- 本套样本只覆盖已验证能力；情绪、属性、方言、IP 等实验能力由 T-05 负责，不在 T-49 里下结论。
- CLI 不支持 `seed`，服务端固定 42；两者不是严格同种子对比。
- 评分是主观听感，必须保留原始 CSV 和音频，便于复核，不要只留汇总数字。
- 如果更换 `mlx-audio` 版本、权重 revision 或推理代码，旧分数失效，需要重跑。

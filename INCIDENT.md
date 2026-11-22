# 北口复测班的两次交接

`python3 -B incident.py` 使用 `samples/day.json` 中的同一录制。采集员先接管 r，值班员登记 A 并看到 r 的预览，再补收 s。低量程票 B 随后成功入班。现在逐票签发后，A 的报告和首执已经可以领取，原件却是 r，B 报无件，班账未能关闭。正常应按登记序核回 A 的 s（11 μg/L）和 B 的 r（7 μg/L）、各自原件身份、原出处和首执，正式票、成果及独立原件各两件。

`python3 -B incident.py --late` 复用这两件原测。A 的第一位经办人停在 `after_claim`，第二位按原号办理，在 `before_receipt` 注入确定回滚。第二位确认此时领不到 A 的成果，再接下低量程票 B。第一位恢复后，其旧尝试也须报确定未签，仍无 A 的新报告或首执。重新按原号办理时，两票须能签齐，并得到同一份正确班账。当前回放中旧尝试恢复时能签出 A 的 r。

脚本会重新打开站库核对冻结报告和班账。业务结果偏离时退出非零。常规核验 `python3 -B check_project.py` 和工作日演示 `python3 -B demo.py` 继续按现有运行清单执行。采集记录、错误类型与检查点的接口见 `README.md`。

## 根因与修复

根因有两处，都在签发链上。

1. 选件只看当前票的预览首项。`prepare_seal` 取 `preview_ticket(...).candidates[0]`，预览又不把其他已登记票的约束算进来，所以 A 在 r 可见时先占 r。等 B 入班后，B 只能匹配 r，A 的旧选择仍把 r 归档，B 报无件。修法：签发在登记集合上做整票册的完整匹配（`build_candidate_graph` + `find_covering_assignment`），为 A 选件时要求把它固定后其余待签票仍能各自匹配到不同合格件，按登记序任取可行解。选件与占用在同一写事务内落为 `seal_claims` 记录，不再用预览。预览仍无写入，只作可见候选。

2. 旧尝试缺少围栏。失败尝试的记录只更新 `publication_attempts`，不校验它是否仍持有该票的占用。第一位经办人恢复后直接按旧结果提交，把已被第二位重新占用的同一票再次签出。修法：归档前在 `_commit_attempt` 内再次核对 `seal_claims` 是否仍由本 attempt 持有、且所选原件仍摸足整票册的完整分配；不再持有则把本次 attempt 置为确定未签（`failed`），不发报告。确定未签的占用在 `_begin_attempt`/`settle_seal_claim` 释放，迟到者无法再签。

签用与归档仍各自提交：报告与首执在归档事务内成对写入，失败在 `before_receipt` 前回滚；成功后复领按请求号返回同一 `ReportPublication`。

## 实测

- `python3 -B check_project.py`：26 项全过，`result=PASS`。新增 3 项回归覆盖预览不占件、按登记序/完整分配选件、旧 attempt 被围栏。
- `python3 -B demo.py`：`POINTWISE_SCENARIO` 一次，`actual`/`downstream_actual` 均为 A→s(11)、B→r(7)，计数 `[2,2,2]`。
- `python3 -B incident.py`：`SHIFT_HANDOFF_OK`，`seals=["signed","signed"]`，报告与班账按 A(s,11)、B(r,7) 核回。
- `python3 -B incident.py --late`：`SHIFT_HANDOFF_OK`。第一位恢复后报 `SaveFailed`，无 A 的旧报告或首执；重按原号签齐两票，班账同前。


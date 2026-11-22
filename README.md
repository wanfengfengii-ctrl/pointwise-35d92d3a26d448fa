# 澄津供水复测站

采集员接管便携测定仪导出的原件。值班员按开班时冻结的检测规程承诺复测票，逐票签发。质检员关闭设备连接后，凭原号领取报告、首执和班账。

## 运行

需要 Python 3.11 标准库。平台物化项目时提供 `check_project.py`。

```text
python3 -B check_project.py
python3 -B -m unittest discover -s tests -t .
python3 -B demo.py
```

演示使用 `samples/day.json` 和独立临时目录，先核对签发及重开结果，再输出一行场景记录。导入 `Station` 后，向构造器传入自己的站内目录。初始化只补建 `operations.sqlite3` 和 `archive.sqlite3` 的缺失结构。已保存的数据继续可用。构造器和各业务调用自行管理连接。

## 一班的工作

1. 质检员登记 P1，配置常规复测和低量程复测。
2. 值班员为北口开班，班号固定 P1 和采样点。
3. 采集员接管录制中的 r。原读 0.007 mg/L 精确换算为 7 μg/L，接到确认后设备清出 r。
4. 值班员正式登记 A，再预览候选 r。
5. 采集员补收 11 μg/L 的 s，值班员接下只能使用 r 的 B。
6. A 正式签出 s，B 签出 r。报告保存各自的原值和出处，并与首执同存。
7. 停源后，经办人凭请求号或报告号复领原报告及首执。
8. 质检员按登记序核对 A、B。全部结清后固定班账，后续登记 P2 或重开均可按原班号领取。

## Python 接口

| 调用 | 输入与结果 |
| --- | --- |
| `register_protocol(revision_id, projects)` | `projects` 以项目名为键，项目规则含 `min`、`max`、`unit`、`sites`、`start`、`end`、`qualities`。返回修订号。等价规程可同号复投，异参冲突。 |
| `open_shift(shift_id, site, revision_id)` | 固定地点与已有规程，返回 `Shift`。同班同参可复领。 |
| `capture_readings(shift_id, source, *, checkpoint=None)` | 源提供 `source_id`、`read_pending()` 和 `acknowledge(ack)`。返回按录制原序处理的持久确认元组。可用 `station.capture.recording.DeviceRecording` 读取有限录制；其确认会释放对应原件。 |
| `admit_ticket(shift_id, ticket_id, project, *, start=None, end=None)` | 时窗缺省端取项目端点。返回带正式登记序的 `ShiftTicket`。同班同票同参沿用原登记。 |
| `preview_ticket(shift_id, ticket_id)` | 返回 `TicketPreview`，其 `candidates` 为当前可见的单票候选。它可以为空，调用无写入。 |
| `seal_ticket(request_id, shift_id, ticket_id, *, checkpoint=None)` | 返回 `ReportPublication`，包含 `report` 和 `receipt`。请求号全站唯一地绑定班、票。失败尝试可用同号同参续办，成功后复领原成果。 |
| `read_report(*, report_id=None, request_id=None)` | 恰传一个键。返回冻结报告及首执，尚无成功成果时返回 `None`。 |
| `reconcile_publication(request_id)` | 查持久结局，结清可确认的占用，返回 `PublicationOutcome`。待查时抛 `Pending`，可同号续签。 |
| `close_and_read_shift(shift_id)` | 关班并返回冻结的 `ShiftAccount`，或复领已冻结班账。未结票抛 `Pending`，仍可办理。无票班可关闭为空账。 |

录制每行含 `original_no`、正整数 `position`、`site`、带时区的 ISO 8601 `sampled_at`、`value`、`unit`、`quality`。源身份和原号共同定位原件，同一录制内原序唯一。采样时刻以 UTC 比较，原报时刻另存。上报值用十进制文本或整数，单位支持 `mg/L` 和 `μg/L`，质量码支持 `ok` 和 `review`。换算按精确整数比例进行，不能整除时拒收。原件以采集作业当时选定的开班班号固定归属。重投先查已存身份和原参，同参可在其他班次进行回认，原归属保持。设备收到确认后才释放。逐件持久确认，后续记录的错误不撤回已经确认的原件。

正式收票要求班内所有待签承诺可同时匹配到不同合格原件。合格条件来自冻结规程、班次点位、项目闭时窗和票据闭时窗、闭量程及质量码。签发按可见的正式票册裁决，允许任一保留完整余票分配的选件。报告包括 `value_ug_l`、实际 `original_id`、规程号及完整 `provenance`，包括上报值、上报单位和源原序。班账按正式登记序保留这些读值、出处和成果引用，计数分别为正式票、成功成果和不同原件。

## 错误与续办

`InvalidInput` 表示字段或规程无效，`NotFound` 表示要求的班、票或规程不存在，`Conflict` 表示同号异参或当前状态冲突。`Unavailable` 表示无可兑现资格。`Pending` 表示相关占用或关班条件尚未结清，`LostReply` 是其子类。`CaptureFailed` 和 `SaveFailed` 分别表示接管或签存已确认未提交。`IntegrityViolation` 表示持久记录无法核对。

签用与归档分别提交。归档成功前，待结绑定排除同一件的其他用途。可回查的失败结局会使当前尝试失效并释放绑定，随后可同号续办。成功失答后，可用 `read_report` 领取原成果，再通过原号续签或 `reconcile_publication` 结清。关班核对全体正式票和已结清结果，关班后拒绝新件及新票。

可选检查点接收一个阶段字符串，供可复现地停在实际提交边界。采集阶段为 `before_capture_commit`、`after_capture_commit`，签存阶段为 `after_claim`、`before_receipt`、`after_archive_commit`。在 `before_capture_commit` 抛 `CaptureFailed` 或在 `before_receipt` 抛 `SaveFailed` 可触发确定回滚。提交后的回调可抛 `LostReply` 复现失答。事务内回调只适合记录事件或触发故障；需要另一个办理者时，可在事务外的阶段使用独立 `Station` 实例。

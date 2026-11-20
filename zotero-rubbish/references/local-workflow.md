# 本地批次、页面与续办

此处只处理本地文件；实际 Zotero 操作使用现有集成。辅助脚本不会连接
Zotero，也不会把 JSON 文件中的字段当作真实用户授权。

## 输出目录与命令

以调用项目为根目录，生成 `.zotero-rubbish/runs/<run_id>/`。其中包含：

- `session.json`：本次画像、范围、清单、分数、证据、稳定编号与阶段。
- `scores.csv`、`review.html`：评分表和离线人工阅读页面。
- `decisions.json`：导入并校验后的人工决定。
- `move-preview.json` 或 `restore-preview.json`：当前具体操作预览。
- `operations.jsonl`：写入前意图、实际回执与重新读取后的核实记录。
- `Rubbish/操作记录.md`：操作进展报告。PDF、笔记和批注仍留在 Zotero。

批次目录所在的本地归档根目录带有自身的 Git 忽略规则。若已有规则不
覆盖运行文件，补充仅覆盖该归档目录的忽略规则；不要提交真实运行结果。
创建批次时不覆盖同名目录。时间戳存储为 UTC，显示给用户时按其时区解释。

命令中的 `<skill>` 是安装目录，`<run>` 是本批次目录，`<python>` 是
适用的 Python 3.10+ 解释器；本机遵守用户指定的 Python 环境。

    <python> <skill>/scripts/review.py create --input inventory-input.json --project <project>
    <python> <skill>/scripts/review.py update --session <run>/session.json --input inventory-input.json
    <python> <skill>/scripts/review.py render --session <run>/session.json
    <python> <skill>/scripts/review.py import-decisions --session <run>/session.json
    <python> <skill>/scripts/review.py import-decisions --session <run>/session.json --file <saved-file>
    <python> <skill>/scripts/review.py preview --session <run>/session.json --snapshot <fresh-snapshot>
    <python> <skill>/scripts/review.py record --session <run>/session.json --event <event-file>
    <python> <skill>/scripts/review.py restore-preview --session <run>/session.json --snapshot <fresh-snapshot> --records R0001 R0002

创建/更新输入是完整清单快照；更新保持旧编号且保留已有条目。变更画像或
范围需要新批次。操作日志产生后，不能重写该批次的评分证据。
文件读写采用 UTF-8，CSV 带 BOM，生成页面不加载外部资源。

## 评分输入格式

`profile` 的五个文本字段：`research_direction`、`current_question`、
`stage`、`method_background`、`desired_help`。它们记录用户本次提供或
明确确认的信息；未知内容可由用户明确写成“尚未确定”，不可替其编造。

`scope` 包含：

- `library_id`：已核实的 Zotero 本地文库 ID。
- `library_type`：`user` 或 `group`。组库还需核实公开 `group_id`，
  不能把本地文库 ID 当组 ID；它只用于组库原生阅读链接。
- `mode`：`library` 或 `collection`。
- `collection_ids`：筛选集合；包含子分类时提前展开成实际 ID 列表。
- `include_subcollections`：布尔值。
- `excluded_collection_ids`：顶层 !Rubbish 及其子分类的实际 ID 列表。

`coverage.enumeration_complete` 必须来自实际分页检查；可附
`pages_read`、`source_total_count` 和说明。跨分类查询的总数可能重复，
不要把其相加当作唯一文献数。脚本另记录输入行数、唯一条目、跳过原因和
未评分数。枚举未完成或存在 `pending` 分数时不能生成移动预览。

每个 `items` 条目：

    {
      "library_id": 1,
      "item_id": 101,
      "item_key": "ABCD2345",
      "title": "虚构示例论文",
      "authors": "示例作者",
      "year": "2026",
      "collections": [{"id": 10, "key": "JKLM2345", "path": "示例主题/子主题"}],
      "attachment_keys": ["PQRS2345"],
      "note_keys": ["TUVW2345"],
      "pdf_key": "PQRS2345",
      "score": 3,
      "score_status": "scored",
      "reason": "结合本次问题给出适配判断及依据。",
      "evidence": "abstract",
      "evidence_locator": "Zotero abstractNote"
    }

`evidence` 为 `title/abstract/full_text/insufficient`。
`score_status` 为 `scored/insufficient/pending`；证据不足的分数为
`null`。`collections` 记录全部当前归属，不能只保留筛选分类。
子条目由枚举接口解析到母条目，脚本只跳过附件/笔记行，不替代母条目查询。
若同一条目重复出现且分数冲突，先解决判断冲突再生成结果。

## 人工决定格式与等待点

页面勾选的是计划阅读条目，人工下拉框标记判断；分次阅读时导出并重新导入
决定文件。未保存的浏览器状态不能作为持久记录。新增“移入”判断会清除
页面之前的整体阅读确认，防止对后来新增的条目沿用旧确认。

    {
      "schema_version": 1,
      "run_id": "本批次ID",
      "profile_hash": "session中的原值",
      "review_confirmed": true,
      "decisions": [{
        "library_id": 1, "item_key": "ABCD2345", "record_id": "R0001",
        "planned_read": true, "read_confirmed": true,
        "decision": "rubbish", "reason": "用户阅读后的判断"
      }]
    }

编号回复也生成这种格式：准确复用批次指纹和条目身份，记录真正的人类阅读
确认，不能因为用户说“导出好了”就补造授权。判断值为
`pending/keep/defer/rubbish`。未处理和暂缓不进入移动清单。

默认从本批次目录和系统下载目录查找 `decisions-<run_id>.json` 及浏览器
生成的 ` (1)` 等副本；选择最新的同批次文件，再严格校验。最新版损坏时
报告错误，不静默使用旧决定。最新修改时间并列且内容不同的文件需要用户
指出保存位置，不按文件遍历顺序猜测。可用 `--file` 指定用户选中的文件。
导入动作不会移动 Zotero 条目。

**等待点一**：评分交付后告诉用户页面位置与保存方法，结束当前轮，等待
其阅读。**等待点二**：用户只提供决定文件时，完成具体预览再询问是否执行，
结束当前轮等待答复。已明确授权本批次具体移动时无需再次询问。

## 新鲜快照与日志格式

移动快照包含 `library_id`、`target_collection` 和 `items`。
目标结构为 `{"library_id":1,"id":99,"path":"!Rubbish","parent_id":null}`；
尚不存在时 `id` 为 `null`，只产生创建目标的预览，不执行创建。
`items` 只需要本次决定涉及的条目，保留其 ID/key、全部 `collections`、
`attachment_keys`、`note_keys`；这些关联必须实际读取。分类字段必须显式
存在，只有实际读取到空列表才表示未分类；字段缺失应停止而非补空列表。

获授权并解析真实目标 ID 后，记录日志事件。`intent` 可基于对应预览条目，
追加以下字段；`authorization_text` 应为真实用户指令或准确引述，不能虚构：

    {
      "operation": "move", "phase": "intent", "attempt_id": "unique-attempt",
      "library_id": 1, "item_key": "ABCD2345", "item_id": 101,
      "authorization_text": "用户针对这些条目的实际执行指令",
      "record_id": "R0001", "title": "虚构示例论文",
      "before_collections": [{"id":10,"path":"示例主题"}],
      "attachment_keys": ["PQRS2345"], "note_keys": ["TUVW2345"],
      "rubbish_collection_id": 99, "rubbish_added": true,
      "expected_collection_ids": [99]
    }

调用写入接口后，记录同 `attempt_id`、身份、操作的 `result` 事件，将实际
`receipt` 和 `action_ids` 原样保存。回执阶段只标为未核实。
再读取条目，将 `after`（ID/key、全部归属和附件/笔记 key）放入
`verification` 事件，脚本判断已核实、部分完成、未发生或冲突。
网络失败不能伪造空 `after`；保存未知回执状态，待连接恢复后核查。

恢复快照还应包含 `available_collection_ids`，来自当前完整分类树，用来核实
原分类仍存在。恢复预览基于完整日志和新鲜快照，补回原归属、保留后来新增的
归属，只移除本次操作新增的 !Rubbish 归属。部分完成后续办也保留最初来源。
任何写入与续办都由 AI 经现有接口执行，脚本不执行计划或自动重试。
日志更新会同步会话阶段：执行中、未核实、部分完成、移入已完成、已恢复等，
续办时同时核对最新日志，不能仅根据旧的人工决定再次执行。

# Unified Interactive Coding Agent

Coding agent thực thi công cụ trên môi trường local, dùng **Ollama Cloud với `nemotron-3-ultra:cloud`** và nhận yêu cầu bằng hội thoại liên tục. Đây là bản nâng cấp từ `agent.py` chạy một task qua shell sang runtime có provider độc lập, công cụ riêng, vai trò chuyên biệt và lưu phiên.

## Chạy nhanh

Yêu cầu Python 3.10+, Internet và `OLLAMA_API_KEY` trong `.env` (hoặc biến môi trường). Không cần cài Ollama hay tải model local để dùng cấu hình Cloud.

```powershell
python -m pip install -e .
agent
```

Mặc định là `https://ollama.com/api`, model `nemotron-3-ultra:cloud`. Mở đúng project này bằng launcher PowerShell:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\start-agent.ps1
```

Có thể chạy từ source mà không cài console command:

```powershell
python agent.py --repo C:\code\my-project --host https://ollama.com/api --model nemotron-3-ultra:cloud
```

Chạy agent ở bất kỳ repo nào với toàn quyền local, không permission prompt hay rule từng command:

```powershell
.\start-agent.ps1 -Repo "C:\Users\AD\Downloads\a" -FullAccess
# hoặc
agent --repo "C:\Users\AD\Downloads\a" --full-access
```

Để mở terminal hiển thị và chạy ngay một task mới, truyền thêm `-Task`:

```powershell
.\start-agent.ps1 -Repo "C:\code\my-project" -FullAccess -Task "Inspect and improve this project."
```

Sau đó nhập tự nhiên:

```text
> xem project này đang làm gì
> sửa lỗi tính tổng và thêm regression test
> giải thích thay đổi vừa rồi
> /diff
> /exit
```

Tạo dự án mới bằng cách mở một thư mục trống:

```powershell
mkdir todo-api
agent --repo todo-api
```

```text
> tạo một FastAPI todo API có PostgreSQL và test
```

Shortcut cũ vẫn được hỗ trợ:

```powershell
python agent.py --repo . --task "Fix the failing tests" --max-steps 40
python -m unified_agent --help
```

## Cấu hình

Copy `examples/config.yaml` thành `.agent/config.yaml` trong **dự án đích**. Có thể copy thêm `examples/permissions.yaml` thành `.agent/rules.yaml` để cho phép các lệnh test đã chọn.

Thứ tự ưu tiên provider: CLI > biến môi trường > `.env` cạnh source launcher > `.agent/config.yaml` > mặc định. `.env` cũ được giữ nguyên khi nâng cấp; nếu nó chọn model/host cloud, dùng `--host` và `--model` để chọn local một cách rõ ràng.

```yaml
provider:
  type: ollama
  host: https://ollama.com/api
  model: nemotron-3-ultra:cloud
  stream: true
  keep_alive: 10m
agent:
  # null = unlimited. Set a number only for evaluation or a fixed budget.
  max_agent_turns: null
  max_role_turns: null
  command_timeout: 120
validation:
  targeted: python -m unittest discover -v
```

`max_agent_turns` là giới hạn tùy chọn cho tổng số request model trong một lượt, gồm subagent và compaction; `max_role_turns` là giới hạn tùy chọn riêng mỗi subagent. Cả hai mặc định là `null` (unlimited). Chỉ khai báo lệnh validation phù hợp với dự án đích; model tự quyết định có dùng chúng hay không.

Có thể chọn model riêng cho `build`, `explore`, `architect`, `reviewer`, `compaction` trong section `models`. Tất cả dùng chung endpoint Ollama.

API key từ `OLLAMA_API_KEY` chỉ được tự lấy khi endpoint là `ollama.com`. Local hoặc endpoint khác chỉ nhận key khi truyền rõ `--api-key`. `.env.example` chỉ chứa cấu hình mẫu, không chứa credential. Muốn dùng local, truyền `--host http://localhost:11434 --model TEN_MODEL_LOCAL`.

## Luồng thực thi

- Runtime dùng một vòng lặp chung: model tự chọn tool, subagent hoặc skill theo evidence hiện có. Không còn router `brownfield`/`greenfield`, keyword bug/feature, hay chuỗi stage bắt buộc.
- Mỗi yêu cầu có Turn lifecycle bền vững. `plan.update` là context có thể sửa, `user.question` dừng Turn để chờ cùng session trả lời, và loop guard cảnh báo/chặn tool call lặp lại không tiến triển.
- Mặc định không có hard limit cho agent turn. Context được compact khi cần, tool loop lặp lại bị chặn và người dùng có thể ngắt bằng `Ctrl+C`. Dùng `--max-agent-turns 20` (hoặc `agent.max_agent_turns: 20`) khi chạy evaluation/benchmark cần tái lập hoặc muốn đặt ngân sách cố định.
- `workspace.context` là tool tùy chọn, chỉ trả `cwd`, worktree Git, workspace roots, instruction-file chain và shallow tree. Nó không nhận diện ngôn ngữ, framework, package manager hay tự chọn lệnh build/test.
- Các subagent `explore`, `architect`, `reviewer` có context riêng và profile tool hạn chế; main agent chỉ gọi khi hữu ích. Skills `issue-resolution`, `project-planning`, `test-generation`, `code-review` cũng chỉ được load khi cần.
- Tool names công khai theo capability (`workspace.context`, `fs.read`, `patch.apply`, `test.run`, `code.definition`, `subagent`, `skill.load`). Tên cũ chỉ được giữ nội bộ để đọc trajectory cũ.
- `submit` chỉ là cách ghi summary; model có thể kết thúc bằng câu trả lời bình thường. Agent phải mô tả trung thực validation đã chạy hoặc giới hạn của nó.
- Hết budget, lỗi provider và Ctrl+C đều lưu trạng thái để tiếp tục.

## Công cụ

| Công cụ | Hành vi |
|---|---|
| `workspace.context` | CWD, Git worktree, workspace roots, AGENTS.md theo scope và shallow tree; không phân loại project |
| `fs.read`, `fs.glob`, `search.grep` | Đọc theo dòng, tìm file, tìm văn bản literal; bỏ qua thư mục sinh tự động và `.env` |
| `fs.write`, `patch.apply` | Tạo file mới hoặc thay một đoạn khớp chính xác duy nhất; bảo toàn CRLF |
| `terminal.exec`, `test.run` | Chạy lệnh local không tương tác tại `cwd` chỉ định, timeout, ghi exit code và output có giới hạn |
| `plan.update`, `user.question` | Plan mutable và câu hỏi chặn Turn chờ câu trả lời trong cùng context |
| `agent.spawn`, `agent.send`, `agent.wait`, `agent.resume`, `agent.close` | Quản lý child agent độc lập; parent chỉ wait khi cần kết quả |
| `tool.search` | Discover và bật deferred capability cho các inference sau |
| `git.read`, `search.bm25`, `code.*`, `fault.*` | Điều hướng, code intelligence và fault localization; các capability nâng cao là deferred |
| `web.search`, `web.fetch`, `mcp.*` | Deferred external capability; web và MCP chỉ xuất hiện sau `tool.search` |
| `fault.coverage`, `fault.localize` | Nhập coverage có test context; xếp hạng dòng/symbol bằng Ochiai, Tarantula hoặc DStar |
| `skill.list`, `skill.load`, `subagent` | Guidance tùy chọn và delegated exploration/design/review |
| `artifact.save`, `submit` | Artifact bất kỳ trong run và completion summary tùy chọn |

Workspace chỉ là ranh giới thư mục. Model tự đọc `AGENTS.md`, manifest, CI và tài liệu khi cần để hiểu repo, rồi tự chọn lệnh validation có bằng chứng. `test.run` không suy đoán test runner từ ngôn ngữ. Với monorepo, truyền `cwd` tương đối với worktree, ví dụ `frontend` hoặc `backend`, cho `terminal.exec` và `test.run`.

Mặc định model chỉ thấy core tools. Khi cần semantic code lookup, SBFL, web hoặc MCP, model gọi `tool.search`; tool được discover sẽ xuất hiện ở inference tiếp theo. Project có thể thêm plugin Python tại `.agent/extensions/*.py`, export `extension.tools()` với `ExtensionTool`; plugin deferred cũng đi qua `tool.search` và permission runtime.

MCP server dùng cấu hình argv tại `.agent/mcp.yaml`, sau đó model discover `mcp`, gọi `mcp.connect`, và các tool server xuất hiện dưới namespace `mcp.<server>.<tool>`:

```yaml
servers:
  github:
    command: [npx, -y, "@modelcontextprotocol/server-github"]
```

Code intelligence được tách khỏi workspace. `code.definition`, `code.references` và `code.diagnostics` ưu tiên LSP khi một server đã được cấu hình; nếu không có server, definition/references/symbols/structure dùng fallback source tổng quát. LSP được lazy-activate theo file mở và dùng language root gần nhất trong monorepo. Có thể đặt command dùng chung bằng `lsp.command`, hoặc chọn server theo language ID:

```yaml
lsp:
  servers:
    python: [pyright-langserver, --stdio]
    typescript: [typescript-language-server, --stdio]
    rust: [rust-analyzer]
```

Khả năng thực tế tùy server; diagnostics sử dụng pull diagnostics nếu server hỗ trợ. Agent không tự cài server.

Coverage sử dụng JSON theo định dạng coverage.py có `contexts` từng dòng. Cần tạo báo cáo với test contexts, truyền đúng danh sách failing/passing contexts vào công cụ `coverage`. Không suy đoán spectrum từ một báo cáo coverage gộp không có context. DStar dùng giá trị hữu hạn lớn hơn các score hữu hạn khi mẫu số bằng 0 để giữ JSON hợp lệ.

## Phiên và bộ nhớ

```text
.agent/
  config.yaml
  rules.yaml
  sessions.sqlite3
  permissions.sqlite3
  memory/experience.jsonl
  runs/<id>/
    state.json
    request.md
    patch.diff
    checkpoint.md
    <artifact-kind>.md
```

Artifact chỉ được tạo khi model thấy có ích. Kind là tên tự do, không gắn với task mode.

`state.json` được ghi qua file tạm và replace; `sessions.sqlite3` lưu index session/message/checkpoint để audit và tiếp tục bền vững. Khi khôi phục, tool call bị gián đoạn được đánh dấu kết quả chưa biết; runtime không tự phát lại thao tác có thể đã thực hiện.

```powershell
agent --resume
agent --resume RUN_ID
agent --new-session
```

Khi mở tương tác, CLI phát hiện phiên chưa xong và cho phép khôi phục. Compaction giữ system/project instructions, checkpoint và phần hội thoại gần nhất, không cắt đôi cặp tool call/result. Experience lưu kết quả các lượt và bài học người dùng nhập; truy xuất theo từ khóa.

## Lệnh quản lý phiên

| Lệnh | Tác dụng |
|---|---|
| `/help` | Hiện hướng dẫn đầy đủ cho mọi lệnh tương tác. |
| `/status` | Xem trạng thái Turn, plan, validation, số lần gọi model và queue. |
| `/diff` | Diff tích lũy của phiên, kể cả file mới |
| `/test` | Chạy các lệnh validation được khai báo trong `.agent/config.yaml`. |
| `/test <lệnh>` | Chạy một lệnh test cụ thể, ví dụ `/test npm test`. |
| `/review` | Review thay đổi hiện tại |
| `/plan` | Chuyển sang Plan Mode. Yêu cầu tiếp theo chỉ khảo sát và tạo `ProposedPlan`; source mutation bị chặn. |
| `/plan show` | Xem `ProposedPlan` đã lưu cùng progress plan hiện tại. |
| `/plan implement` | Chuyển về Default Mode và bắt đầu một turn triển khai `ProposedPlan`. |
| `/plan clear` | Xóa `ProposedPlan` và trở về Default Mode. |
| `/queue <yêu cầu>` | Xếp follow-up theo FIFO để chạy sau Turn hiện tại. |
| `/interrupt` | Đánh dấu Turn interrupted; `Ctrl+C` dừng work đang chạy. |
| `/compact` | Thu gọn ngữ cảnh cũ và giữ trao đổi tool gần đây. |
| `/context` | Hiện ước lượng token hiện tại, CTX %, CMP %, ngưỡng auto-compact và số lần compact. |
| `/session list` | Liệt kê mọi session đã lưu của project. |
| `/session show <id>` | Xem trạng thái, tóm tắt, plan và ProposedPlan của session. |
| `/session resume <id>` | Chuyển terminal sang session đã lưu. |
| `/session delete <id>` | Xóa vĩnh viễn session đã lưu; không thể xóa session đang mở. |
| `/memory` | Tra cứu experience có liên quan đến các yêu cầu đã gửi. |
| `/memory <ghi chú>` | Lưu một bài học hoặc quy tắc cho project. |
| `/model` | Xem model chính của session. |
| `/model <tên-model>` | Đổi model chính cho phần còn lại của session. |
| `/permissions` | Xem chính sách quyền |
| `/undo` | Hoàn tác thay đổi file gần nhất do agent ghi lại. |
| `/redo` | Áp dụng lại thay đổi vừa undo. |
| `/clear` | Tạo cuộc hội thoại mới, giữ dữ liệu session cũ. |
| `/exit` | Lưu và thoát |

Sau `Ctrl+C` hoặc lỗi tạm thời của provider, gõ `continue` hoặc `tiếp tục` như một yêu cầu bình thường để agent tiếp tục. Các lệnh trên chỉ hoạt động trong terminal tương tác; chúng không phải command PowerShell.

Plan Mode dùng cùng model chính và vẫn cho phép đọc file, tìm kiếm, code intelligence, Git read-only, skills, web, user question và optional child agents. Nó không tự ép model lập kế hoạch ở Default Mode và không tự triển khai các bước của `ProposedPlan`; chỉ `/plan implement` mới bắt đầu một turn implementation mới. `plan.update` vẫn là progress state độc lập với `ProposedPlan`.

Undo/redo kiểm tra nội dung hiện tại của tất cả file trước khi sửa, từ chối nếu có thay đổi tiếp theo của người dùng. Không rollback package cài toàn cục, network, database hay git state. Snapshot bỏ qua file >1 MB, thư mục sinh tự động và secret files; ngân sách snapshot là 32 MB/10.000 file. Với repo lớn, các giới hạn này cũng giới hạn phạm vi diff/undo. Agent không dùng git reset để undo.

## Quyền và giới hạn

Permission tách ba phần: access profile (`inspect`, `workspace`, `full`), approval policy (`on-request`, `never`) và argv-prefix rules. Mặc định là `workspace` + `on-request`: đọc/tìm/sửa trong workspace được phép; command shell chưa có rule sẽ hỏi. `never` từ chối action cần hỏi, không tự cho phép chúng. `--full-access` bật profile `full`: tất cả tool, command, network và rule đều được phép không prompt.

Rule nằm ở `.agent/rules.yaml` (mẫu: [permissions.yaml](C:/Users/AD/Downloads/sweagent/examples/permissions.yaml)); có thể có thêm user rules tại `~/.config/unified-agent/rules.yaml`. Rule dùng argv prefix, không match raw shell string. Compound command, substitution và redirection luôn cần duyệt. Quyết định `deny` luôn thắng; duyệt một lần hoặc theo phiên không tự biến thành persistent rule. Mọi quyết định được audit tại `.agent/permissions.sqlite3`.

Đây là runtime chạy local, **không phải OS sandbox**. Công cụ file chặn thoát root và chặn `.git`/`.agent`; shell hoặc test được cho phép vẫn có quyền của tài khoản đang chạy. Không dùng cấu hình allow rộng cho project không tin cậy. AGENTS.md là quy ước cho model, không thay thế quyền thực thi.

`--dry-run` chặn công cụ ghi source/chạy lệnh/LSP và undo/redo, nhưng vẫn gọi model và lưu kế hoạch/phiên dưới `.agent/`. Không coi dry-run là đã kiểm thử. Console hiện nội dung trả lời và tóm tắt hành động, không hiện trường thinking của provider.

## Mức triển khai so với kế hoạch

| Mốc | Trạng thái |
|---|---|
| Universal loop | Model-controlled tools, subagents và skills; không routing mode/task-kind |
| Workspace | `WorkspaceContext`: directory/worktree roots/instruction chain, không detector ngôn ngữ hay test-command inference |
| Permissions | Profile, approval policy, parsed argv prefix rules, session grants và SQLite audit |
| Memory | JSON portable state + SQLite session/message/checkpoint index + compaction |
| Code intelligence | Service/registry riêng; LSP lazy fallback generic source, language root độc lập workspace root |
| Execution | `ExecutionBackend` protocol + `LocalExecutionBackend`; sandbox backend có thể thêm sau mà không đổi agent loop |
| Interactive runtime | Turn lifecycle, plan, blocking question, queue, interrupt và loop guard |
| Multi-agent | Spawn/send/wait/resume/close với child handle và concurrency guard |
| Dynamic tools | Direct/deferred/hidden catalog, `tool.search`, project extension interface |
| External capability | `web.search`, `web.fetch`, stdio MCP client với namespaced dynamic tools |
| Tương lai | Best-of-N, parallel candidates và MCTS sau khi evaluator/validator đủ tin cậy |

Bản này dùng CLI dòng lệnh với streaming, chưa có TUI toàn màn hình. Python dùng AST thật; fallback cho các source format khác đánh dấu `approximate`, nên LSP là lựa chọn chính xác hơn khi server tương ứng đã được cấu hình. `fault.coverage` vẫn nhận định dạng coverage.py có contexts; `fault.localize` nhận spectra tổng quát cho các ecosystem khác. Skills chỉ là guidance và chất lượng reproduce/test generation vẫn phụ thuộc model. Các mẫu kiến trúc trong plan được triển khai độc lập, không import framework MetaGPT/OpenCode.

## Kiểm thử phát triển

```powershell
python -m unittest discover -v
python -m ruff check unified_agent tests agent.py
```

Bộ test nằm trong `tests/`, bao gồm loop tổng quát không router, workspace context và scope instructions, code-intelligence fallback/LSP, monorepo `cwd`, skills, subagent profile, parsed argv permission rules/session grant/SQLite audit, session resume, compaction, undo/redo, timeout, BM25/SBFL và streaming tool fragments. Các test này không đo chất lượng model. Chạy agent cần kết nối Internet và API key hợp lệ.

API adapter đối chiếu với [Ollama Chat API](https://docs.ollama.com/api/chat) và [Ollama Tool Calling](https://docs.ollama.com/capabilities/tool-calling).

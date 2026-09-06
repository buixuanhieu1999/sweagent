# Unified Interactive Coding Agent

Coding agent thực thi công cụ trên môi trường local, dùng **Ollama Cloud với `gpt-oss:120b`** và nhận yêu cầu bằng hội thoại liên tục. Đây là bản nâng cấp từ `agent.py` chạy một task qua shell sang runtime có provider độc lập, công cụ riêng, vai trò chuyên biệt và lưu phiên.

## Chạy nhanh

Yêu cầu Python 3.10+, Internet và `OLLAMA_API_KEY` trong `.env` (hoặc biến môi trường). Không cần cài Ollama hay tải model local để dùng cấu hình Cloud.

```powershell
python -m pip install -e .
agent
```

Mặc định là `https://ollama.com/api`, model `gpt-oss:120b`. Mở đúng project này bằng launcher PowerShell:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\start-agent.ps1
```

Có thể chạy từ source mà không cài console command:

```powershell
python agent.py --repo C:\code\my-project --host https://ollama.com/api --model gpt-oss:120b
```

Chạy agent ở bất kỳ repo nào với toàn quyền local, không permission prompt hay rule từng command:

```powershell
.\start-agent.ps1 -Repo "C:\Users\AD\Downloads\a" -FullAccess
# hoặc
agent --repo "C:\Users\AD\Downloads\a" --full-access
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
  model: gpt-oss:120b
  stream: true
  keep_alive: 10m
agent:
  max_steps: 40
  role_steps: 10
  command_timeout: 120
validation:
  targeted: python -m unittest discover -v
```

`max_steps` là tổng số request model mỗi lượt, bao gồm subagent và compaction; `role_steps` giới hạn riêng mỗi subagent. Chỉ khai báo lệnh validation phù hợp với dự án đích; model tự quyết định có dùng chúng hay không.

Có thể chọn model riêng cho `build`, `explore`, `architect`, `reviewer`, `compaction` trong section `models`. Tất cả dùng chung endpoint Ollama.

API key từ `OLLAMA_API_KEY` chỉ được tự lấy khi endpoint là `ollama.com`. Local hoặc endpoint khác chỉ nhận key khi truyền rõ `--api-key`. `.env.example` chỉ chứa cấu hình mẫu, không chứa credential. Muốn dùng local, truyền `--host http://localhost:11434 --model TEN_MODEL_LOCAL`.

## Luồng thực thi

- Runtime dùng một vòng lặp chung: model tự chọn tool, subagent hoặc skill theo evidence hiện có. Không còn router `brownfield`/`greenfield`, keyword bug/feature, hay chuỗi stage bắt buộc.
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
| `git.read`, `search.bm25`, `code.definition`, `code.references`, `code.symbols`, `code.structure`, `code.diagnostics` | Điều hướng và bằng chứng source code qua code-intelligence layer |
| `fault.coverage`, `fault.localize` | Nhập coverage có test context; xếp hạng dòng/symbol bằng Ochiai, Tarantula hoặc DStar |
| `skill.list`, `skill.load`, `subagent` | Guidance tùy chọn và delegated exploration/design/review |
| `artifact.save`, `submit` | Artifact bất kỳ trong run và completion summary tùy chọn |

Workspace chỉ là ranh giới thư mục. Model tự đọc `AGENTS.md`, manifest, CI và tài liệu khi cần để hiểu repo, rồi tự chọn lệnh validation có bằng chứng. `test.run` không suy đoán test runner từ ngôn ngữ. Với monorepo, truyền `cwd` tương đối với worktree, ví dụ `frontend` hoặc `backend`, cho `terminal.exec` và `test.run`.

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
| `/help`, `/status` | Hướng dẫn và trạng thái |
| `/diff` | Diff tích lũy của phiên, kể cả file mới |
| `/test [command]` | Chạy validation cấu hình hoặc lệnh test nhập trực tiếp |
| `/review` | Review thay đổi hiện tại |
| `/compact` | Thu gọn ngữ cảnh cũ |
| `/memory [lesson]` | Tra cứu experience hoặc lưu bài học |
| `/model [name]` | Xem/đổi model chính, lưu lựa chọn trong phiên |
| `/permissions` | Xem chính sách quyền |
| `/undo`, `/redo` | Khôi phục thay đổi file của một lượt |
| `/clear` | Tạo phiên hội thoại mới, giữ dữ liệu phiên cũ |
| `/exit` | Lưu và thoát |

Undo/redo kiểm tra nội dung hiện tại của tất cả file trước khi sửa, từ chối nếu có thay đổi tiếp theo của người dùng. Không rollback package cài toàn cục, network, database hay git state. Snapshot bỏ qua file >1 MB, thư mục sinh tự động và secret files; ngân sách snapshot là 32 MB/10.000 file. Với repo lớn, các giới hạn này cũng giới hạn phạm vi diff/undo. Agent không dùng git reset để undo.

## Quyền và giới hạn

Permission tách ba phần: access profile (`inspect`, `workspace`, `full`), approval policy (`on-request`, `never`) và argv-prefix rules. Mặc định là `workspace` + `on-request`: đọc/tìm/sửa trong workspace được phép; command shell chưa có rule sẽ hỏi. `never` từ chối action cần hỏi, không tự cho phép chúng. `full` chỉ user bật rõ ràng.

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
| Optional capability | BM25, graph/symbol, coverage-context/SBFL, LSP |
| Tương lai | Best-of-N, parallel candidates và MCTS sau khi evaluator/validator đủ tin cậy |

Bản này dùng CLI dòng lệnh với streaming, chưa có TUI toàn màn hình. Python dùng AST thật; fallback cho các source format khác đánh dấu `approximate`, nên LSP là lựa chọn chính xác hơn khi server tương ứng đã được cấu hình. `fault.coverage` vẫn nhận định dạng coverage.py có contexts; `fault.localize` nhận spectra tổng quát cho các ecosystem khác. Skills chỉ là guidance và chất lượng reproduce/test generation vẫn phụ thuộc model. Các mẫu kiến trúc trong plan được triển khai độc lập, không import framework MetaGPT/OpenCode.

## Kiểm thử phát triển

```powershell
python -m unittest discover -v
python -m ruff check unified_agent tests agent.py
```

Bộ test nằm trong `tests/`, bao gồm loop tổng quát không router, workspace context và scope instructions, code-intelligence fallback/LSP, monorepo `cwd`, skills, subagent profile, parsed argv permission rules/session grant/SQLite audit, session resume, compaction, undo/redo, timeout, BM25/SBFL và streaming tool fragments. Các test này không đo chất lượng model. Chạy agent cần kết nối Internet và API key hợp lệ.

API adapter đối chiếu với [Ollama Chat API](https://docs.ollama.com/api/chat) và [Ollama Tool Calling](https://docs.ollama.com/capabilities/tool-calling).

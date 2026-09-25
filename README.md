# MultiDocuCollator

酒店需求工作联系单本地汇总工具。程序只读扫描资料子目录，解析 Word 当前有效
文字及“内容：”后的下划线需求正文，在资料根目录生成正式 JSON 数据库和离线
HTML 汇总。通过本地服务打开 HTML 时，还可在固定末行填写新联系单；程序以
“消防水-004”固化模板生成 DOCX，并调用 Microsoft Word 导出 PDF。既有 Word、
PDF、图片、DWG 及其他资料不会被移动、改名或删除。

最新更新说明见 [2026-09-25：汇总页人工状态筛选](docs/UPDATE_2026-09-25.md)。

## 数据规则

一级子目录名称必须符合：

```text
专业-编号-YYYY-MM-DD_主题
```

例如：

```text
给排水-003-2026-08-13_关于厨房排水油脂分离器增加跨越管的事宜
```

HTML 前六列固定为“序号、专业、编号、目录日期、致送单位、主题”。JSON 每条记录
包含中文字段 `致送单位`、`需求内容`、`需求单已经打印`、`作废状态`、`是否需要变更`、
`现场是否已经完成`；这些人工标记只允许“是”或“否”，其余字段由资料目录和 Word
自动提取。`需求内容` 只来自 Word 中“内容：”
与“备注：”之间当前有效且带下划线的文字。Word 日期、事由与目录不一致时只记录
核对提示，不修改原始资料。

## 配置

先在每台机器的项目根目录分别建立本地虚拟环境。环境目录不进入 Git，也不要在
Windows、macOS 和 Linux 之间复用。

macOS/Linux：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip --version
```

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip --version
```

安装 PDF 页面合并依赖，并在运行和测试时优先显式使用 `.venv` 内的解释器：

```bash
python -m pip install -r requirements.txt
```

复制 `common.env.example` 为本机私有的 `.env`（也兼容旧的 `common.env`）。程序
优先读取 `.env`，再用 `common.env` 补齐缺少的配置，并自动按运行系统选择群晖同步
根目录：

```dotenv
CLOUDSTATION_ROOT_WINDOWS=D:\CloudStation
CLOUDSTATION_ROOT_MACOS=~/SynologyDrive/
CLOUDSTATION_ROOT_LINUX=~/CloudStation
```

显式 `CLOUDSTATION_ROOT` 优先于平台变量；`HOTEL_REQUIREMENTS_ROOT` 或运行时
`--data-root` 可进一步覆盖工作流资料目录。公开的 `config.yaml` 不保存用户名、
盘符之外的本机私有绝对路径。

## 快速使用

首次使用按以下顺序执行：

```bash
# 1. 激活本机虚拟环境
source .venv/bin/activate

# 2. 扫描资料并生成或刷新 JSON/HTML
python build_archive.py

# 3. 启动支持打开目录和新增联系单的本地页面（启动时会先刷新 JSON/HTML）
python serve_summary.py
```

Windows PowerShell 将第一条命令替换为：

```powershell
.\.venv\Scripts\Activate.ps1
```

浏览器会打开 `127.0.0.1` 本地地址。页面的保存、删除和复制文件功能依赖本地服务
持续运行；完成使用后回到终端按 `Ctrl+C` 停止服务。Windows 下自动打开的浏览器
与服务进程相互独立，在 VS Code/Code Runner 中停止服务不会关闭现有 Chrome 页面。

Windows 可直接双击项目根目录的 `build_archive.cmd`：脚本会先更新 JSON/HTML，
构建成功后继续启动 `serve_summary.py` 并自动打开浏览器。

也可以双击项目根目录生成的 `酒店需求工作联系单汇总.exe`。EXE 会读取其同目录的
`config.yaml`、`.env` 或 `common.env`，并将运行日志写入同目录的 `logs/`。重新构建
EXE 前安装构建依赖，然后运行打包脚本：

```powershell
python -m venv .build-venv
.\.build-venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\build_serve_summary_exe.ps1
```

程序图标源文件和 Windows ICO 位于 `assets/`。打包使用控制台模式，运行期间请保留
控制台窗口；关闭服务时在窗口中按 `Ctrl+C`。

## 迁移存档

需要把现有存档复制到另一块磁盘或长期归档目录时，使用根目录的
`migrate_archive.py`：

在 Windows 的 VS Code 中直接使用 Code Runner 运行该脚本即可：程序会自动使用
项目配置的资料根目录，并弹出窗口让您选择迁移目标目录；完成后会自动打开目标根目录
的 `存档检索.html`。取消选择目录不会修改任何文件。

```bash
python migrate_archive.py --source-root "D:/CloudStation/国会二期/02 酒店需求工作联系单" \
  --destination-root "E:/酒店需求存档"
```

脚本会复制每条联系单的完整目录和全部附件，不改动源目录。目标目录按
`专业/原存档目录名/` 组织，并在目标根目录生成：

- `存档迁移数据.json`：迁移后的正式数据及相对路径。
- `存档检索.html`：无需启动 Python 服务即可检索；默认按编号自然排序，可按专业和
  “是否需要出变更”筛选，并导出当前结果为 JSON 或 CSV。主题是对应资料目录链接，
  资料文件仅显示 Word、PDF、DWG 等类型标签；需求内容超出固定行高后在单元格内滚动。
  表格统一使用 14px 字体。

目标目录可以重复迁移，已有同名文件会更新；源目录不能设置为目标目录本身或目标目录的
上级/子目录，以避免递归复制。

若个别附件正在被 CAD、Word、同步客户端等程序占用，迁移会继续复制其余资料，并在
迁移数据和检索页中记录该文件的跳过提示；关闭占用程序后，重新运行迁移即可补齐文件。

若重启后文件仍提示 `PermissionError`，可先运行项目根目录的权限修复脚本。首次运行
仅扫描和输出预览日志，不修改权限；确认列表后，以管理员身份应用修复：

```powershell
.\repair_archive_permissions.ps1
.\repair_archive_permissions.ps1 -Apply
```

脚本只修改“文件无法读取且 ACL 同样无法读取”的异常文件；对于 ACL 正常、可能只是
被软件占用的文件，仅记录提示而不修改权限。修复过程会写入 `logs/permission_repair_*.log`。

早期版本生成的 `archives/专业/年份/` 目录不会被脚本自动删除，以免误删已迁移资料；
如需完全采用新结构，请选择新的空目标目录，或在确认内容无误后手动清理旧的 `archives`
目录。

## 生成成果

```bash
python build_archive.py --data-root "/path/to/02 酒店需求工作联系单"
```

配置好 `.env` 或 `common.env` 后也可以直接运行：

```bash
python build_archive.py
```

默认在资料根目录生成：

- `酒店需求工作联系单数据.json`：唯一正式结构化数据源。
- `酒店需求工作联系单汇总.html`：从 JSON 生成的离线查询页面。
- `需求工作联系单模板.docx`：与 JSON、HTML 同级的“消防水-004”版式模板。

重复运行按稳定记录 ID 和文件 SHA-256 更新，不重复创建记录。生成过程使用原子
替换写入 JSON 和 HTML。

## 浏览与管理联系单

推荐通过本地汇总服务打开页面：

```bash
python serve_summary.py
```

服务仅监听 `127.0.0.1` 并自动选择空闲端口。点击“主题”后：

- Windows 使用资源管理器打开对应目录。
- macOS 使用 Finder 打开对应目录。
- Linux 使用 `xdg-open` 调用默认文件管理器。

在 Windows 上通过本地服务打开页面时，左键点击“资料文件”中的文件标签，会把
真实文件复制到系统文件剪贴板，随后可在资源管理器、桌面或其他目录直接粘贴。
文件名含“附图”的 PDF 显示为“PDF附图”标签；直接双击静态 HTML 时，文件标签
仍按普通链接打开。

人工调整实际资料目录名称或目录内文件后，可点击页面工具栏的“重新扫描刷新”。服务
会重新提取实际目录信息、更新 JSON、重建 HTML，并自动刷新当前页面。

“需求单已经打印”列可人工选择“是”或“否”（旧记录默认“否”），列标题下可按
“是”或“否”筛选。“状态 / 核对”列在系统自动状态下方增加“有效/作废”人工选择；
作废记录仍保留显示，整行覆盖半透明斜线阴影，同时保持下方文字可辨认，也可重新
改回“有效”。修改后点击页面顶部的“保存修改内容”，会同时保存打印标记和作废
状态，写回正式 JSON 并同步更新 HTML。保存不重新加载页面，筛选条件、所在行及
滚动位置保持不变；重新扫描实际目录时会保留全部四类人工标记。

“是否需要变更”和“现场是否已经完成”列可人工选择“是”或“否”，列标题下也可分别按
“全部 / 是 / 否”筛选。两个筛选条件可与关键词、专业、打印状态和“状态 / 核对”组合
使用；两项标记与打印、作废标记一起通过“保存修改内容”提交。

重新扫描时，如个别资料文件因权限、软件独占或同步状态而暂时无法读取，程序会
跳过该文件并在对应记录中显示警告，不会中断其余目录及 JSON/HTML 的刷新。待文件
恢复可读后再次扫描，即会重新纳入文件清单并计算哈希。

鼠标移到顶部“有提示记录”统计卡时，会弹出含提示条目的专业编号、日期、主题和
提示摘要；也可用键盘将焦点移到该统计卡查看。提示较多时可在小窗内滚动。

页面顶部生成时间固定显示为 `YYYY-MM-DD HH:MM:SS`，不附带时区名称或 ISO
时区偏移字符串。

新增行的“主题”和“需求内容”框采用弹窗人工输入，点击框体即可打开相应编辑窗。
既有记录的需求内容框同样通过弹窗修改；点击主题会先显示“打开资料目录”和“修改
主题”两个选项。需求内容下方的“修改”按钮可在同一弹窗内同时调整主题和正文，
确认回填后点击“保存内容”才会正式更新。

服务端只接受记录 ID、页面数据版本、新主题和新正文，不允许通过该接口修改编号、
日期或致送单位。保存时程序先在同目录临时区修改原 DOCX 并回读校验，再调用
Microsoft Word 重新导出 PDF；修改主题时还会同步更新一级资料目录及联系单
DOCX/PDF 文件名。如果目录中已有同名 PDF，新生成的单页 PDF 会先保存在事务临时
目录中，再替换原 PDF 的第一页，原 PDF 第二页起的附件页保持不变。Word、PDF、
目录及 JSON/HTML 全部更新成功后才提交，失败时恢复旧文件和旧目录。

## Windows 11 本地 AI 公文勘误

页面的“AI 公文勘误”连接由独立启动器管理的 llama.cpp 本地服务。本项目只检查并
调用 `http://127.0.0.1:8080/v1`，不负责启动、关闭、加载模型或释放显存，内容
不会发送到外部服务。

在项目根目录的 `.env` 中配置（旧的 `common.env` 仍可兼容）：

```dotenv
LLAMACPP_BASE_URL=http://127.0.0.1:8080/v1
LLAMACPP_MODEL=Qwen3.8-27B-Q4_K_M.gguf
LLAMACPP_API_KEY=独立启动器配置的密钥
LLAMACPP_TIMEOUT_SEC=180
```

启动 `serve_summary.py` 后，页面会自动检查 `/health` 和 `/v1/models`。顶部状态灯
红色表示 API 不可用、黄色表示正在检查、绿色表示模型已经就绪；也可点击“检查本地
AI”重新检查。API 不可用时请在新的本地 AI 启动器项目中启动服务，本项目不会尝试
拉起或终止该进程。检查通过后才启用“AI 公文勘误”按钮。

点击某行“AI 公文勘误”后，模型除修正错别字、标点和病句外，还会将口语化、重复、
含混或冗长表达改为准确、简洁、庄重的公文用语，并优化句式、语序、逻辑衔接和
术语规范；不得更改事实、数字、日期、计量含义、专有名词、责任主体、具体要求或
时限。弹窗采用左右对照布局，左侧显示原文，右侧显示 AI 公文修订稿，两侧有变化
的文字均以黄底标出：

AI 修订时，距离、长度、面积、功率等单位统一采用 `mm`、`m`、`m²`、`W`、`kW`
等字母或符号表示，不使用汉字单位且不改变数值。“以下空白”属于排版标记，不进入
AI 审核结果：原文中存在时会删除，不存在时也不会新增。

- “手动修改”：解除右侧只读并清除差异标记，可继续人工调整 AI 版本。
- “接受”：关闭弹窗并把版本回填到当前表格，尚未修改磁盘文件。
- “保存内容”：最终更新 Word、重新出具 PDF，并刷新 JSON/HTML。

AI 输出仍需人工核对，特别是金额、日期、设备参数、单位名称和责任边界。

HTML 和 JSON 只保存相对于资料根目录的路径。服务在运行时通过当前平台的
`CLOUDSTATION_ROOT` 解析实际位置，并执行路径越界检查，因此同一份成果可以在
Windows 和 macOS 的不同群晖根目录下使用。直接双击静态 HTML 时，主题链接退化
为浏览器可访问的相对目录链接。

表格末行始终保留新增表单，可填写专业、编号、目录日期、致送单位、主题和需求
内容。页面首次打开时会在页面渲染、资源加载和会话恢复后自动校准滚动位置，直接
显示表格底部的最后一条记录和新增表单。
专业既可直接输入，也可点击输入框右侧的原生下拉箭头从已有专业类型中选择；
致送单位默认填写“中国建筑第二工程局有限公司国家会议中心二期项目配套部分
项目部”，主题默认填写“关于   的事宜”，两项均可继续修改。
新增行“需求内容”下方的“临时保存内容”只把正文写入项目本地的
`log/new_record_content_draft.json`，不写正式归档 JSON，也不创建目录、Word 或
PDF。重启 `serve_summary.py` 后页面会自动恢复草稿；正式新增成功后自动清空草稿。
旁边的“AI 公文勘误”可直接校对尚未正式创建的需求内容，并复用左右对照、黄底
差异、手动修改和接受功能；接受后只回填新增行，仍需点击“临时保存内容”才能保留
草稿，也不会生成 Word 或 PDF。
新增行各单元格统一顶部对齐，增加临时保存按钮后不会导致其他输入框垂直错位。
本地 AI API 不可用时显示红灯，检查过程中显示黄灯，模型可用后转为绿灯；点击
“检查本地 AI”可随时刷新状态，但不会启动或关闭外部 AI 服务。
编号会按所选专业取现有最大编号加一并补足三位，也可手动覆盖；日期默认
本机当天且可修改。点击“保存”后，服务会：

1. 校验页面数据版本、重复编号和 Windows/macOS 通用文件名规则。
2. 在同盘临时目录套用模板生成 DOCX，并回读核对所有输入字段。
3. 通过 macOS Word AppleScript 或 Windows Word COM 导出 PDF。
4. DOCX、PDF 均有效后创建 `专业-编号-YYYY-MM-DD_主题` 目录并刷新 JSON/HTML。

生成 DOCX 时会根据致送单位、事由和需求内容的预计换行数，动态增减“以下空白”
后的填充行；正文能够容纳在一页时，不会因模板固定空白把抄送、签字区推到第二页。

新增功能必须通过 `serve_summary.py` 使用；直接双击静态 HTML 时不会尝试写入。
macOS 或 Windows 需要安装 Microsoft Word，并在首次使用时允许系统自动化权限。

每条现有记录的“状态/核对”列带有“删除”按钮。确认删除后，程序不会永久清除
文件，而是把整条资料目录移动到 JSON/HTML 同级的 `_trash`，再重新扫描并从 JSON
和 HTML 中移除该记录。`_trash` 不参与资料扫描；同名目录已存在时会为移入目录
追加时间戳。若 JSON/HTML 刷新失败，程序会自动把目录移回原位置。

需要恢复时，先停止本地服务，把对应目录从 `_trash` 移回资料根目录，然后重新运行：

```bash
python build_archive.py
```

新建结果的命名规则为：

```text
专业-编号-YYYY-MM-DD_主题/
├── 需求工作联系单（专业-编号）_主题.docx
└── 需求工作联系单（专业-编号）_主题.pdf
```

模板必须命名为 `需求工作联系单模板.docx`，并与 JSON、HTML 保持同一目录层级。
当前正式模板来自最新且无内嵌旧图片的“消防水-004”。如以后替换模板，应保持
“资料编号、日 期、致(单位)、事由、内容、备注”等定位文字及正文表格结构不变，
随后先用临时记录验证 DOCX 与 PDF 版式。

## VS Code / Code Runner

建议在 VS Code 中选择项目自己的 Python 解释器：

- macOS/Linux：`.venv/bin/python`
- Windows：`.venv\Scripts\python.exe`

Code Runner 必须以项目根目录作为工作目录，否则可能找不到 `config.yaml`、
`logging_config.py` 或 `src`。也可以直接在 VS Code 集成终端运行
`python build_archive.py` 或 `python serve_summary.py`，便于查看完整错误信息。

如果点击“保存”后 Word 导出失败：

- macOS：在“系统设置 → 隐私与安全性 → 自动化”中允许终端或 VS Code 控制
  Microsoft Word。
- Windows：确认已安装桌面版 Microsoft Word，并避免用其他程序占用目标 DOCX。
- 不要直接双击 HTML；新增保存接口只在 `serve_summary.py` 启动期间可用。
- 删除按钮同样只在本地服务中可用，并且只执行可恢复的 `_trash` 移动。

## 独立校验

```bash
python validate_archive.py --data-root "/path/to/02 酒店需求工作联系单"
```

校验数据版本、记录唯一性、路径边界、文件大小和哈希，以及 HTML 的数据版本和
记录数。大批量资料可临时添加 `--skip-hashes` 跳过哈希复核。

## 测试

项目支持 Python 3.10 及以上版本；运行测试前先安装 `requirements.txt`：

```bash
python -m unittest discover -s tests -v
python -m compileall -q build_archive.py serve_summary.py validate_archive.py logging_config.py src tests
```

测试全部使用临时目录和自建最小 DOCX，不接触真实业务资料。

## 跨平台运行

- Windows PowerShell：`python .\build_archive.py`
- macOS/Linux：`python3 ./build_archive.py`
- 路径统一由 `pathlib.Path` 处理，JSON 内文件路径统一保存为 POSIX 风格相对路径。
- `.venv/`、`.conda/` 和 `.vscode/` 均为每台机器本地环境，不通过 Git 或群晖
  复用。
- Python 依赖统一通过 `requirements.txt` 安装，不在不同系统之间复用虚拟环境。
- 自动生成 PDF 支持装有 Microsoft Word 的 Windows 和 macOS；Linux 可继续扫描、
  查询和校验，但不能从末行新增并导出 PDF。

项目统一规范见 `docs/CROSS_PLATFORM_PROGRAMMING.md`、`docs/GitHub.md` 和
`docs/COMMON_PROJECT_SKILLS.md`。

## GitHub 同步

GitHub 使用 SSH remote。提交前必须检查忽略文件，确保 `.env`、`common.env`、日志、缓存、
虚拟环境和真实业务资料未进入版本库：

```bash
git status --short --ignored
git diff --check
git push origin main
```

## 项目结构

```text
build_archive.py                 生成 JSON 和 HTML 的独立入口
migrate_archive.py               复制存档目录并生成离线检索/导出索引
repair_archive_permissions.ps1   扫描并修复无法读取文件的 Windows ACL
validate_archive.py              独立校验入口
serve_summary.py                 本地汇总、目录打开及新增联系单入口
logging_config.py                统一控制台及滚动文件日志
requirements.txt                Python 运行依赖（PDF 页面合并）
requirements-build.txt          Windows EXE 构建依赖
build_serve_summary_exe.ps1     生成带项目图标的单文件 Windows EXE
assets/                         应用图标 PNG/ICO
src/multidocu_collator/modules/  DOCX 解析/生成、Word PDF、扫描、HTML、校验
src/multidocu_collator/flows/    扫描建库、新增联系单及服务编排
tests/                           单元和集成测试
docs/                            架构说明
logs/                            本地运行日志（不入库）
```

# MultiDocuCollator

酒店需求工作联系单本地汇总工具。程序只读扫描资料子目录，解析 Word 当前有效
文字及“内容：”后的下划线需求正文，在资料根目录生成正式 JSON 数据库和离线
HTML 汇总。通过本地服务打开 HTML 时，还可在固定末行填写新联系单；程序以
“消防水-004”固化模板生成 DOCX，并调用 Microsoft Word 导出 PDF。既有 Word、
PDF、图片、DWG 及其他资料不会被移动、改名或删除。

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
包含中文字段 `致送单位`、`需求内容`、`需求单已经打印`；打印标记只允许“是”或
“否”，其余字段由资料目录和 Word 自动提取。`需求内容` 只来自 Word 中“内容：”
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

项目当前没有第三方运行依赖，因此创建环境后无需安装额外软件包。运行和测试时
优先显式使用 `.venv` 内的解释器。

复制 `common.env.example` 为本机私有的 `common.env`。程序自动按运行系统选择群晖
同步根目录：

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

# 3. 启动支持打开目录和新增联系单的本地页面
python serve_summary.py
```

Windows PowerShell 将第一条命令替换为：

```powershell
.\.venv\Scripts\Activate.ps1
```

浏览器会打开 `127.0.0.1` 本地地址。页面的保存、删除和复制文件功能依赖本地服务
持续运行；完成使用后回到终端按 `Ctrl+C` 停止服务。

Windows 可直接双击项目根目录的 `build_archive.cmd`：脚本会先更新 JSON/HTML，
构建成功后继续启动 `serve_summary.py` 并自动打开浏览器。

## 生成成果

```bash
python build_archive.py --data-root "/path/to/02 酒店需求工作联系单"
```

配置好 `common.env` 后也可以直接运行：

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
“是”或“否”筛选。修改后点击页面顶部的“保存打印标记”，会写回正式 JSON 并
同步更新正式 HTML，但当前页面不重新加载，筛选条件、所在行及滚动位置保持不变；
重新扫描实际目录时会保留已保存的人工标记。

重新扫描时，如个别资料文件因权限、软件独占或同步状态而暂时无法读取，程序会
跳过该文件并在对应记录中显示警告，不会中断其余目录及 JSON/HTML 的刷新。待文件
恢复可读后再次扫描，即会重新纳入文件清单并计算哈希。

鼠标移到顶部“有提示记录”统计卡时，会弹出含提示条目的专业编号、日期、主题和
提示摘要；也可用键盘将焦点移到该统计卡查看。提示较多时可在小窗内滚动。

页面顶部生成时间固定显示为 `YYYY-MM-DD HH:MM:SS`，不附带时区名称或 ISO
时区偏移字符串。

每条既有记录的“需求内容”可直接编辑，但服务端只接受记录 ID、页面数据版本和新
正文，不允许通过该接口修改编号、日期、致送单位、事由或目录名。点击“保存内容”
后，程序先在同目录临时区修改原 DOCX 并回读校验，再调用 Microsoft Word 重新导出
PDF；两份文件全部生成成功后才替换原文件并刷新 JSON/HTML。失败时恢复旧文件。

## Windows 11 本地 AI 公文勘误

页面的“AI 公文勘误”复用 `LocalAiOcrFile` 已部署的 llama.cpp、CUDA 和本地 GGUF
模型。默认只允许访问 `http://127.0.0.1:8080/v1`、`localhost` 或 IPv6 回环地址，
内容不会发送到外部服务。

`common.env` 需要配置：

```dotenv
LLAMACPP_BASE_URL=http://127.0.0.1:8080/v1
LLAMACPP_MODEL=Qwen_Qwen2.5-VL-7B-Instruct-Q4_K_S.gguf
LLAMACPP_AUTOSTART=true
LLAMACPP_SERVER_PATH=D:\llama-cpp-cu12\llama-server.exe
LLAMACPP_MODEL_PATH=C:\path\to\Qwen_Qwen2.5-VL-7B-Instruct-Q4_K_S.gguf
LLAMACPP_MMPROJ_PATH=C:\path\to\mmproj-Qwen_Qwen2.5-VL-7B-Instruct-f16.gguf
LLAMACPP_N_GPU_LAYERS=999
```

重新双击 `build_archive.cmd` 后，页面会依次检查 `/health` 和 `/v1/models`，顶部
用状态灯显示运行情况：红色表示未启动、黄色表示正在启动或关闭、绿色表示已经
就绪。点击“启动本地 AI”后，如果 8080 服务不可用且
`LLAMACPP_AUTOSTART=true`，程序会在后台启动 `llama-server.exe`、加载模型并等待
健康检查通过；点击“关闭本地 AI”会释放本项目加载的模型和显存。

`serve_summary.py` 退出时也会关闭由本项目启动的进程。如果连接的是外部已经运行
的服务，状态灯仍显示绿色，但“关闭本地 AI”不可用，避免误关其他程序的服务。

启动日志位于项目的 `log/llama_server.out.log` 和
`log/llama_server.err.log`。模型首次加载可能需要一些时间，工具栏会显示
“正在启动并加载模型”；就绪后才启用“AI 公文勘误”按钮。

点击某行“AI 公文勘误”后，模型除修正错别字、标点和病句外，还会将口语化、重复、
含混或冗长表达改为准确、简洁、庄重的公文用语，并优化句式、语序、逻辑衔接和
术语规范；不得更改事实、数字、日期、计量含义、专有名词、责任主体、具体要求或
时限。弹窗采用左右对照布局，左侧显示原文，右侧显示 AI 公文修订稿，两侧有变化
的文字均以黄底标出：

AI 修订时，距离、长度、面积、功率等单位统一采用 `mm`、`m`、`m²`、`W`、`kW`
等字母或符号表示，不使用汉字单位且不改变数值。修订稿最后必须另起一行写
“以下空白”；原文中人工填写的“以下空白”不得删除，程序也会在模型漏写时自动
补齐，已有正确末行不会重复添加。

- “手动修改”：解除右侧只读并清除差异标记，可继续人工调整 AI 版本。
- “接受”：关闭弹窗并把版本回填到当前表格，尚未修改磁盘文件。
- “保存内容”：最终更新 Word、重新出具 PDF，并刷新 JSON/HTML。

AI 输出仍需人工核对，特别是金额、日期、设备参数、单位名称和责任边界。

HTML 和 JSON 只保存相对于资料根目录的路径。服务在运行时通过当前平台的
`CLOUDSTATION_ROOT` 解析实际位置，并执行路径越界检查，因此同一份成果可以在
Windows 和 macOS 的不同群晖根目录下使用。直接双击静态 HTML 时，主题链接退化
为浏览器可访问的相对目录链接。

表格末行始终保留新增表单，可填写专业、编号、目录日期、致送单位、主题和需求
内容。页面首次打开时会自动滚动到表格底部，直接显示最后一条记录和新增表单。
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
本地 AI 未启动时显示红灯；点击“启动本地 AI”后显示黄灯，并在状态文字和按钮上
持续读秒，模型可用后转为绿灯；点击关闭后恢复红灯。
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

项目只使用 Python 标准库，支持 Python 3.10 及以上版本：

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
- 项目没有第三方 Python 运行依赖；不同系统只需安装 Python 3.10 或更高版本。
- 自动生成 PDF 支持装有 Microsoft Word 的 Windows 和 macOS；Linux 可继续扫描、
  查询和校验，但不能从末行新增并导出 PDF。

项目统一规范见 `docs/CROSS_PLATFORM_PROGRAMMING.md`、`docs/GitHub.md` 和
`docs/COMMON_PROJECT_SKILLS.md`。

## GitHub 同步

GitHub 使用 SSH remote。提交前必须检查忽略文件，确保 `common.env`、日志、缓存、
虚拟环境和真实业务资料未进入版本库：

```bash
git status --short --ignored
git diff --check
git push origin main
```

## 项目结构

```text
build_archive.py                 生成 JSON 和 HTML 的独立入口
validate_archive.py              独立校验入口
serve_summary.py                 本地汇总、目录打开及新增联系单入口
logging_config.py                统一控制台及滚动文件日志
src/multidocu_collator/modules/  DOCX 解析/生成、Word PDF、扫描、HTML、校验
src/multidocu_collator/flows/    扫描建库、新增联系单及服务编排
tests/                           单元和集成测试
docs/                            架构说明
logs/                            本地运行日志（不入库）
```

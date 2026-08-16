# MultiDocuCollator

酒店需求工作联系单本地汇总工具。程序只读扫描资料子目录，解析 Word 当前有效
文字及“内容：”后的下划线需求正文，在资料根目录生成正式 JSON 数据库和离线
HTML 汇总。原始 Word、PDF、图片、DWG 及其他资料不会被移动、改名或删除。

## 数据规则

一级子目录名称必须符合：

```text
专业-编号-YYYY-MM-DD_主题
```

例如：

```text
给排水-003-2026-08-13_关于厨房排水油脂分离器增加跨越管的事宜
```

HTML 前五列固定为“序号、专业、编号、目录日期、主题”。JSON 每条记录包含中文
字段 `需求内容`，其值只来自 Word 中“内容：”与“备注：”之间当前有效且带下划线
的文字。Word 日期、事由与目录不一致时只记录核对提示，不修改原始资料。

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
CLOUDSTATION_ROOT_WINDOWS=D:\CloudStaion
CLOUDSTATION_ROOT_MACOS=~/SynologyDrive/
CLOUDSTATION_ROOT_LINUX=~/CloudStation
```

显式 `CLOUDSTATION_ROOT` 优先于平台变量；`HOTEL_REQUIREMENTS_ROOT` 或运行时
`--data-root` 可进一步覆盖工作流资料目录。公开的 `config.yaml` 不保存用户名、
盘符之外的本机私有绝对路径。

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

重复运行按稳定记录 ID 和文件 SHA-256 更新，不重复创建记录。生成过程使用原子
替换写入 JSON 和 HTML。

## 从主题打开资料目录

推荐通过本地汇总服务打开页面：

```bash
python serve_summary.py
```

服务仅监听 `127.0.0.1` 并自动选择空闲端口。点击“主题”后：

- Windows 使用资源管理器打开对应目录。
- macOS 使用 Finder 打开对应目录。
- Linux 使用 `xdg-open` 调用默认文件管理器。

HTML 和 JSON 只保存相对于资料根目录的路径。服务在运行时通过当前平台的
`CLOUDSTATION_ROOT` 解析实际位置，并执行路径越界检查，因此同一份成果可以在
Windows 和 macOS 的不同群晖根目录下使用。直接双击静态 HTML 时，主题链接退化
为浏览器可访问的相对目录链接。

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
python -m compileall -q build_archive.py validate_archive.py logging_config.py src tests
```

测试全部使用临时目录和自建最小 DOCX，不接触真实业务资料。

## 跨平台运行

- Windows PowerShell：`python .\build_archive.py`
- macOS/Linux：`python3 ./build_archive.py`
- 路径统一由 `pathlib.Path` 处理，JSON 内文件路径统一保存为 POSIX 风格相对路径。
- `.venv/`、`.conda/` 和 `.vscode/` 均为每台机器本地环境，不通过 Git 或群晖
  复用。
- 项目没有第三方运行依赖；不同系统只需安装 Python 3.10 或更高版本。

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
serve_summary.py                 本地汇总及跨平台目录打开入口
logging_config.py                统一控制台及滚动文件日志
src/multidocu_collator/modules/  DOCX、扫描、存储、HTML、校验能力
src/multidocu_collator/flows/    工作流编排
tests/                           单元和集成测试
docs/                            架构说明
logs/                            本地运行日志（不入库）
```

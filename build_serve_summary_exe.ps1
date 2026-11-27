$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $projectRoot

$python = if (Test-Path -LiteralPath ".build-venv\Scripts\python.exe") {
    ".build-venv\Scripts\python.exe"
} elseif (Test-Path -LiteralPath ".venv\Scripts\python.exe") {
    ".venv\Scripts\python.exe"
} elseif (Test-Path -LiteralPath ".conda\python.exe") {
    ".conda\python.exe"
} else {
    "python"
}

& $python -c "import PyInstaller, PIL, pypdf, docx" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "缺少构建依赖，请先运行: $python -m pip install -r requirements-build.txt"
}

$appName = "酒店需求工作联系单汇总"
$iconPath = Join-Path $projectRoot "assets\serve_summary.ico"
$sourcePath = Join-Path $projectRoot "src"
$deliveryDir = Join-Path $projectRoot "build\delivery"
New-Item -ItemType Directory -Path $deliveryDir -Force | Out-Null
& $python -m PyInstaller `
    --onefile `
    --windowed `
    --clean `
    --noconfirm `
    --name $appName `
    --icon $iconPath `
    --add-data "$iconPath;." `
    --paths $sourcePath `
    --distpath $deliveryDir `
    --workpath "build\serve_summary" `
    --specpath "build" `
    "serve_summary.py"

if ($LASTEXITCODE -ne 0) {
    throw "EXE 构建失败，退出代码: $LASTEXITCODE"
}

$output = Join-Path $deliveryDir "$appName.exe"
if (-not (Test-Path -LiteralPath $output)) {
    throw "构建完成但未找到输出文件: $output"
}
$workspaceExe = Join-Path $projectRoot "酒店需求工作联系单汇总v2.exe"
try {
    Copy-Item -LiteralPath $output -Destination $workspaceExe -Force -ErrorAction Stop
} catch {
    throw "EXE 已构建到 $output，但工作区 App 正在运行，无法替换 $workspaceExe。请先退出 App，再重新运行本脚本。"
}
if ((Get-FileHash -LiteralPath $output -Algorithm SHA256).Hash -ne
    (Get-FileHash -LiteralPath $workspaceExe -Algorithm SHA256).Hash) {
    throw "工作区启动文件复制校验失败: $workspaceExe"
}

Copy-Item -LiteralPath (Join-Path $projectRoot "config.yaml") -Destination $deliveryDir -Force
Copy-Item -LiteralPath (Join-Path $projectRoot "common.env.example") -Destination $deliveryDir -Force
foreach ($envName in @(".env", "common.env")) {
    $envSource = Join-Path $projectRoot $envName
    if (Test-Path -LiteralPath $envSource -PathType Leaf) {
        Copy-Item -LiteralPath $envSource -Destination $deliveryDir -Force
    }
}

Write-Host "构建完成: $output"
Write-Host "工作区启动文件已更新: $workspaceExe"

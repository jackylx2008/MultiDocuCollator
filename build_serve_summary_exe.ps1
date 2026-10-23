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

Copy-Item -LiteralPath (Join-Path $projectRoot "config.yaml") -Destination $deliveryDir -Force
Copy-Item -LiteralPath (Join-Path $projectRoot "common.env.example") -Destination $deliveryDir -Force
foreach ($envName in @(".env", "common.env")) {
    $envSource = Join-Path $projectRoot $envName
    if (Test-Path -LiteralPath $envSource -PathType Leaf) {
        Copy-Item -LiteralPath $envSource -Destination $deliveryDir -Force
    }
}

Write-Host "构建完成: $output"

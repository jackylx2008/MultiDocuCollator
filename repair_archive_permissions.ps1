[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter()]
    [string]$DataRoot = 'D:\CloudStation\国会二期\02 酒店需求工作联系单',

    [Parameter()]
    [switch]$Apply
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Test-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Test-ReadableFile {
    param([Parameter(Mandatory)][string]$LiteralPath)

    try {
        $share = [IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete
        $stream = [IO.File]::Open(
            $LiteralPath,
            [IO.FileMode]::Open,
            [IO.FileAccess]::Read,
            $share
        )
        try {
            $buffer = [byte[]]::new(1)
            [void]$stream.Read($buffer, 0, 1)
        }
        finally {
            $stream.Dispose()
        }
        return $true
    }
    catch {
        return $false
    }
}

function Test-ReadableAcl {
    param([Parameter(Mandatory)][string]$LiteralPath)

    try {
        [void](Get-Acl -LiteralPath $LiteralPath -ErrorAction Stop)
        return $true
    }
    catch {
        return $false
    }
}

if (-not (Test-Path -LiteralPath $DataRoot -PathType Container)) {
    throw "资料根目录不存在：$DataRoot"
}

$resolvedRoot = (Resolve-Path -LiteralPath $DataRoot).ProviderPath
$driveRoot = [IO.Path]::GetPathRoot($resolvedRoot)
if ($resolvedRoot.TrimEnd('\') -eq $driveRoot.TrimEnd('\')) {
    throw '拒绝对磁盘根目录执行权限扫描，请指定具体的资料目录。'
}

if ($Apply -and -not (Test-Administrator)) {
    throw '应用权限修复需要管理员权限。请右键 PowerShell 选择“以管理员身份运行”，再使用 -Apply。'
}

$logDirectory = Join-Path $PSScriptRoot 'logs'
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
$timestamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$logPath = Join-Path $logDirectory "permission_repair_$timestamp.log"
$currentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent().Name

Write-Host "扫描目录：$resolvedRoot"
Write-Host '正在识别无法读取且 ACL 异常的文件……'

$scanErrors = [Collections.Generic.List[string]]::new()
$files = Get-ChildItem -LiteralPath $resolvedRoot -Recurse -Force -File -ErrorAction SilentlyContinue `
    -ErrorVariable +scanErrors
$aclProblems = [Collections.Generic.List[IO.FileInfo]]::new()
$possibleLocks = [Collections.Generic.List[IO.FileInfo]]::new()

foreach ($file in $files) {
    if (Test-ReadableFile -LiteralPath $file.FullName) {
        continue
    }
    if (Test-ReadableAcl -LiteralPath $file.FullName) {
        $possibleLocks.Add($file)
    }
    else {
        $aclProblems.Add($file)
    }
}

$report = [Collections.Generic.List[string]]::new()
$report.Add("扫描时间：$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')")
$report.Add("资料根目录：$resolvedRoot")
$report.Add("当前账户：$currentIdentity")
$report.Add("ACL 异常文件：$($aclProblems.Count)")
$report.Add("可能被占用但 ACL 正常：$($possibleLocks.Count)")
$report.Add('')
$report.Add('ACL 异常文件：')
foreach ($file in $aclProblems) {
    $report.Add($file.FullName)
}
$report.Add('')
$report.Add('可能被占用但未修改权限的文件：')
foreach ($file in $possibleLocks) {
    $report.Add($file.FullName)
}

if (-not $Apply) {
    $report.Add('')
    $report.Add('当前为预览模式，未修改任何权限。')
    $report | Set-Content -LiteralPath $logPath -Encoding utf8
    Write-Host "发现 $($aclProblems.Count) 个 ACL 异常文件。"
    Write-Host "另有 $($possibleLocks.Count) 个文件可能只是被程序占用，脚本不会修改它们。"
    Write-Host "预览日志：$logPath"
    Write-Host ''
    Write-Host '确认列表后，以管理员身份运行以下命令应用修复：'
    Write-Host ".\repair_archive_permissions.ps1 -Apply"
    exit 0
}

$takeownPath = Join-Path $env:SystemRoot 'System32\takeown.exe'
$icaclsPath = Join-Path $env:SystemRoot 'System32\icacls.exe'
$repaired = 0
$failed = [Collections.Generic.List[string]]::new()

foreach ($file in $aclProblems) {
    $path = $file.FullName
    if (-not $PSCmdlet.ShouldProcess($path, '取得所有权、恢复权限继承并授予当前账户完整控制')) {
        continue
    }
    try {
        $takeownOutput = & $takeownPath /F $path 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "takeown 失败：$($takeownOutput -join ' ')"
        }

        $inheritOutput = & $icaclsPath $path /inheritance:e /C /Q 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "启用权限继承失败：$($inheritOutput -join ' ')"
        }

        $resetOutput = & $icaclsPath $path /reset /C /Q 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "重置 ACL 失败：$($resetOutput -join ' ')"
        }

        $grantOutput = & $icaclsPath $path /grant:r "${currentIdentity}:(F)" /C /Q 2>&1
        if ($LASTEXITCODE -ne 0) {
            throw "授予当前账户权限失败：$($grantOutput -join ' ')"
        }

        if (-not (Test-ReadableAcl -LiteralPath $path) -or -not (Test-ReadableFile -LiteralPath $path)) {
            throw '权限命令执行后文件仍无法读取'
        }

        $repaired++
        $report.Add("修复成功：$path")
        Write-Host "[成功] $path" -ForegroundColor Green
    }
    catch {
        $message = "$path：$($_.Exception.Message)"
        $failed.Add($message)
        $report.Add("修复失败：$message")
        Write-Warning $message
    }
}

$report.Add('')
$report.Add("修复成功：$repaired")
$report.Add("修复失败：$($failed.Count)")
$report | Set-Content -LiteralPath $logPath -Encoding utf8

Write-Host ''
Write-Host "完成：成功 $repaired，失败 $($failed.Count)。"
Write-Host "日志：$logPath"
if ($failed.Count -gt 0) {
    exit 1
}
Write-Host '现在可以重新运行 migrate_archive.py 补齐此前跳过的文件。'

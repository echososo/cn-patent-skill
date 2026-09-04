<#
patent-writing-pro 一键安装（Windows PowerShell 5.1 / PowerShell 7+）
只做三件事：把技能文件夹复制进你已有的 agent 的 skills 目录、去掉 UTF-8 BOM、打印验证用的一句话。
不联网、不装依赖、不改任何别的文件。

用法：
  powershell -ExecutionPolicy Bypass -File install.ps1
  powershell -ExecutionPolicy Bypass -File install.ps1 -DryRun
  powershell -ExecutionPolicy Bypass -File install.ps1 -Dest D:\somewhere
#>
[CmdletBinding()]
param(
    [switch]$DryRun,
    [string]$Dest
)

$ErrorActionPreference = 'Stop'
$SkillName = 'patent-writing-pro'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PkgRoot   = Split-Path -Parent $ScriptDir

if (-not (Test-Path (Join-Path $PkgRoot 'SKILL.md'))) {
    Write-Host "错误：在 $PkgRoot 里没找到 SKILL.md。"
    Write-Host "请把整个 $SkillName 文件夹解压好，再运行 install\install.ps1。"
    exit 1
}

$UserHome = if ($env:USERPROFILE) { $env:USERPROFILE } else { $HOME }

$Hosts = @(
    @{ Label = 'Claude Code'; Root = (Join-Path $UserHome '.claude');   Sub = 'skills' },
    @{ Label = 'Codex CLI';   Root = (Join-Path $UserHome '.codex');    Sub = 'skills' },
    @{ Label = 'Cursor';      Root = (Join-Path $UserHome '.cursor');   Sub = 'skills' },
    @{ Label = 'WorkBuddy';   Root = (Join-Path $UserHome '.workbuddy');Sub = 'skills' },
    @{ Label = 'nanobot';     Root = (Join-Path $UserHome '.nanobot');  Sub = 'workspace/skills' }
)

function Remove-Bom {
    param([string]$Dir)
    Get-ChildItem -Path $Dir -Recurse -Filter *.md -File | ForEach-Object {
        $bytes = [System.IO.File]::ReadAllBytes($_.FullName)
        if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
            [System.IO.File]::WriteAllBytes($_.FullName, $bytes[3..($bytes.Length - 1)])
            Write-Host ("    去掉 BOM：" + $_.FullName.Substring($Dir.Length + 1))
        }
    }
}

function Copy-Skill {
    param([string]$Target)
    if (Test-Path $Target) {
        # 备份必须放在 skills\ 外面：放在里面会被宿主当成第二个技能注册，
        # agent 可能加载到旧规则那一份（2026-09-02 在 macOS 上实测到，Windows 同理）。
        $bakRoot = Join-Path (Split-Path -Parent (Split-Path -Parent $Target)) '.patent-writing-pro-backups'
        New-Item -ItemType Directory -Path $bakRoot -Force | Out-Null
        $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
        $backup = Join-Path $bakRoot $stamp
        $n = 1
        while (Test-Path $backup) { $backup = Join-Path $bakRoot "$stamp-$n"; $n++ }
        Move-Item -Path $Target -Destination $backup
        Write-Host ("    原来那份已备份到 " + $backup)
    }
    # v1.0.2 及更早的安装把备份留在了 skills\ 里，那些残留同样会被宿主当成技能注册。
    # 顺手搬走，不然买家升级完还是两个技能，verify 也会一直判失败
    # （2026-09-03 在 Windows Server 2022 上实测：不搬走的话，买家照着自检提示重跑
    #  install.ps1 之后自检仍旧报同一条失败，出不去这个圈）。
    $skillsDir = Split-Path -Parent $Target
    $legacyRoot = Join-Path (Split-Path -Parent $skillsDir) '.patent-writing-pro-backups'
    foreach ($legacy in @(Get-ChildItem -Path $skillsDir -Filter ($SkillName + '.bak-*') -Force -ErrorAction SilentlyContinue)) {
        New-Item -ItemType Directory -Path $legacyRoot -Force | Out-Null
        $moveTo = Join-Path $legacyRoot $legacy.Name
        $k = 1
        while (Test-Path $moveTo) { $moveTo = Join-Path $legacyRoot ($legacy.Name + "-$k"); $k++ }
        Move-Item -Path $legacy.FullName -Destination $moveTo
        Write-Host ("    旧版留在 skills\ 里的备份已挪走：" + $legacy.Name)
    }
    New-Item -ItemType Directory -Path $Target -Force | Out-Null
    # 整目录递归拷贝，不是白名单：新加的 scripts\vendor\（内置 mermaid.min.js）会跟着一起过去。
    Copy-Item -Path (Join-Path $PkgRoot '*') -Destination $Target -Recurse -Force
    Get-ChildItem -Path $Target -Recurse -Force -Include '__pycache__', '.pytest_cache', '.DS_Store' -ErrorAction SilentlyContinue |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Bom -Dir $Target
}

$installed = @()

function Install-To {
    param([string]$Label, [string]$SkillsDir)
    $target = Join-Path $SkillsDir $SkillName
    Write-Host "  ${Label}：$target"
    if ($DryRun) {
        Write-Host '    （-DryRun，没有真的复制）'
    } else {
        New-Item -ItemType Directory -Path $SkillsDir -Force | Out-Null
        Copy-Skill -Target $target
        Write-Host '    装好了'
    }
    $script:installed += [pscustomobject]@{ Label = $Label; Path = $target }
}

Write-Host "包目录：$PkgRoot"
Write-Host ''

if ($Dest) {
    New-Item -ItemType Directory -Path $Dest -Force | Out-Null
    Install-To -Label '手动指定' -SkillsDir (Resolve-Path $Dest).Path
} else {
    Write-Host '探测已安装的 agent……'
    foreach ($h in $Hosts) {
        if (Test-Path $h.Root) {
            Install-To -Label $h.Label -SkillsDir (Join-Path $h.Root ($h.Sub -replace '/', [System.IO.Path]::DirectorySeparatorChar))
        } else {
            Write-Host ("  " + $h.Label + "：没找到 " + $h.Root + "，跳过")
        }
    }
}

Write-Host ''
if ($installed.Count -eq 0) {
    Write-Host @"
一个 agent 都没探测到。手动装也很简单：把整个 $SkillName 文件夹复制到下面任意一个位置——

  Claude Code   %USERPROFILE%\.claude\skills\$SkillName\
  Codex CLI     %USERPROFILE%\.codex\skills\$SkillName\
  Cursor        %USERPROFILE%\.cursor\skills\$SkillName\
  WorkBuddy     %USERPROFILE%\.workbuddy\skills\$SkillName\
  nanobot       %USERPROFILE%\.nanobot\workspace\skills\$SkillName\

复制完重启一下 agent。文件夹名必须就叫 ${SkillName}，Cursor 会按它匹配。
"@
    exit 0
}

if ($DryRun) {
    Write-Host ("会装到这 " + $installed.Count + " 处（本次没有真的复制）：")
} else {
    Write-Host ("装好 " + $installed.Count + " 处：")
}
foreach ($item in $installed) { Write-Host ("  " + $item.Label + "  ->  " + $item.Path) }

$first = $installed[0].Path
Write-Host ''
Write-Host '下一步：重启你的 agent，然后复制这句话给它——'
Write-Host ''
Write-Host ("  专利审查：" + (Join-Path $first 'examples\demo-case\bad-draft.md'))
Write-Host ''
Write-Host '想先不动模型、几秒钟看一眼形式检查：'
Write-Host ''
Write-Host ('  python "' + (Join-Path $first 'scripts\check_patent_package.py') + '" "' + (Join-Path $first 'examples\demo-case\bad-draft.md') + '"')

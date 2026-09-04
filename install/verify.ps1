<#
patent-writing-pro 装完自检（Windows PowerShell 5.1 / PowerShell 7+）
和 macOS 的 install/verify.sh 一一对应：挨个宿主看装上没有、装的那份是不是完好的。
不联网、不改任何文件，只读。

用法：
  powershell -ExecutionPolicy Bypass -File install\verify.ps1
#>

$ErrorActionPreference = 'Continue'
$SkillName = 'patent-writing-pro'
$script:Pass = 0
$script:Fail = 0

function Write-Ok   { param([string]$M) Write-Host ("    [OK]   " + $M); $script:Pass = $script:Pass + 1 }
function Write-Bad  { param([string]$M) Write-Host ("    [失败] " + $M); $script:Fail = $script:Fail + 1 }
function Write-Skip { param([string]$M) Write-Host ("    [跳过] " + $M) }

# 找一个真能跑的 Python。顺序按 Windows 的实情来：
#   py -3   官方安装器一定带的启动器，最可靠；
#   python  install.ps1 末尾提示买家敲的就是它；
#   python3 放最后——%LOCALAPPDATA%\Microsoft\WindowsApps\python3.exe 常常是应用商店的
#           占位程序，敲下去只弹商店，所以必须真跑一次 -V 看它回不回 "Python 3"。
function Resolve-Python {
    $candidates = @(
        @{ Exe = 'py';      Pre = @('-3') },
        @{ Exe = 'python';  Pre = @() },
        @{ Exe = 'python3'; Pre = @() }
    )
    foreach ($c in $candidates) {
        if (-not (Get-Command $c.Exe -ErrorAction SilentlyContinue)) { continue }
        $out = ''
        try { $out = (& $c.Exe @($c.Pre + @('-V')) 2>&1 | Out-String) } catch { continue }
        if ($LASTEXITCODE -eq 0 -and $out -match 'Python 3') { return $c }
    }
    return $null
}

# 跑一条 Python 命令，还回输出的最后一行非空文本。
# 加了 2>&1，所以 $raw 可能是「一串对象」而不是一整段字符串（unittest 的结果就写在 stderr）。
# 必须逐个对象转字符串再拆行——直接 "$raw" 会用空格把所有行拼成一行，末行判据就废了。
function Invoke-Py {
    param($Py, [string[]]$PyArgs)
    $raw = & $Py.Exe @($Py.Pre + $PyArgs) 2>&1
    $lines = @()
    foreach ($item in @($raw)) {
        foreach ($ln in ([string]$item -split "`r?`n")) {
            if ($ln.Trim() -ne '') { $lines = $lines + $ln.Trim() }
        }
    }
    if ($lines.Count -eq 0) { return '' }
    return $lines[$lines.Count - 1]
}

function Test-OneHost {
    param([string]$Label, [string]$Dir, $Py)
    Write-Host ("  " + $Label + "：" + $Dir)

    $skillMd = Join-Path $Dir 'SKILL.md'
    if (Test-Path $skillMd) { Write-Ok 'SKILL.md 在' } else { Write-Bad '没有 SKILL.md'; return }

    # 读前三个字节判 BOM。不用 Get-Content -Encoding Byte：PowerShell 7 已经把它删了。
    $bytes = [System.IO.File]::ReadAllBytes($skillMd)
    if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
        Write-Bad 'SKILL.md 带 BOM，Codex 会不认'
    } else {
        Write-Ok 'SKILL.md 没有 BOM'
    }

    # 明确按 UTF-8 读。PowerShell 5.1 的 Get-Content 默认按 ANSI(936) 读，中文规则文件会乱。
    $enc  = New-Object System.Text.UTF8Encoding($false)
    $text = [System.IO.File]::ReadAllText($skillMd, $enc)
    $name = ''
    foreach ($line in ($text -split "`r?`n")) {
        if ($line -match '^name:\s*(.+?)\s*$') { $name = $Matches[1]; break }
    }
    $leaf = Split-Path -Leaf $Dir
    if ($name -eq $leaf) {
        Write-Ok ("name 和文件夹名一致（" + $name + "）")
    } else {
        Write-Bad ("name=" + $name + " 和文件夹名 " + $leaf + " 不一致")
    }

    $refDir = Join-Path $Dir 'references'
    $n = 0
    if (Test-Path $refDir) {
        $n = @(Get-ChildItem -Path $refDir -Recurse -Filter *.md -File -ErrorAction SilentlyContinue).Count
    }
    if ($n -ge 17) { Write-Ok ("references 有 " + $n + " 份") } else { Write-Bad ("references 只有 " + $n + " 份，应该 17 份（包里 12 份规则 + 2 份审查提示词 + 3 份官方法源摘录）") }

    if (Test-Path (Join-Path $Dir 'examples\demo-case\bad-draft.md')) {
        Write-Ok '演练案例在'
    } else {
        Write-Bad '演练案例缺失'
    }

    # skills\ 里不能有第二个 patent-writing-pro：宿主按目录扫描，
    # 一个 .bak-… 残留就会被当成第二个技能注册，agent 可能加载到旧规则那份。
    $skillsDir = Split-Path -Parent $Dir
    $stray = @(Get-ChildItem -Path $skillsDir -Directory -Filter ($SkillName + '.bak-*') -ErrorAction SilentlyContinue).Count
    if ($stray -eq 0) {
        Write-Ok 'skills\ 里没有重复的技能目录'
    } else {
        Write-Bad ("skills\ 里还有 " + $stray + " 个 " + $SkillName + ".bak-* 残留，会被当成第二个技能；重跑 install.ps1 会自动挪走")
    }

    if ($null -eq $Py) {
        Write-Skip '没找到 Python，跳过脚本检查（技能本身不需要 Python）'
        return
    }

    # 判据只认 ASCII 片段，不比中文整句。
    # check_patent_package.py 没有把 stdout 改成 UTF-8，输出被捕获时在中文 Windows 上是
    # GBK 字节；PowerShell 用哪个编码去解随版本和控制台设置变（5.1 按 936，7 按 UTF-8），
    # 拿中文整句当判据必然出现「真机是对的、自检却报红」。ASCII 片段在两种编码下字节相同。
    # v1.2.0 起全包统一机读约定：Invoke-Py 取的最后一行不再是中文的「汇总：ERROR=3，WARN=7」，
    # 而是 stderr 上那行 ASCII 的「FAIL: errors=3 warnings=7 files=1」（小写），
    # 所以判据从 ERROR=3 / WARN=7 改成 errors=3 / warnings=7。
    $draft   = Join-Path $Dir 'examples\demo-case\bad-draft.md'
    $checker = Join-Path $Dir 'scripts\check_patent_package.py'
    $out = Invoke-Py -Py $Py -PyArgs @($checker, $draft)
    if ($out -match 'errors=3' -and $out -match 'warnings=7') {
        Write-Ok ("形式检查输出正确（" + $out + "）")
    } else {
        Write-Bad ("形式检查输出异常：" + $out)
    }

    # unittest 把结果写在 stderr，最后一行是 ASCII 的 OK 或 FAILED。
    $srcDir = Join-Path $Dir 'examples\demo-case\src'
    $old = $env:PYTHONDONTWRITEBYTECODE
    $env:PYTHONDONTWRITEBYTECODE = '1'
    Push-Location $srcDir
    try {
        $out = Invoke-Py -Py $Py -PyArgs @('-m', 'unittest', 'test_alert_suppressor')
    } finally {
        Pop-Location
        if ($null -eq $old) {
            Remove-Item Env:\PYTHONDONTWRITEBYTECODE -ErrorAction SilentlyContinue
        } else {
            $env:PYTHONDONTWRITEBYTECODE = $old
        }
    }
    if ($out -eq 'OK') { Write-Ok '演练案例 13 个测试全过' } else { Write-Bad ("演练案例测试没过：" + $out) }

    # v1.2.0 新增：附图主路径是 mermaid 围栏 → PNG。这台机器有浏览器就真渲染一张最小的图，
    # 没有就跳过（不算失败：规则本身不需要出图，附图还能走 make_figure.py）。
    # 只往临时目录写，不动装好的那份。
    $renderer = Join-Path $Dir 'scripts\mermaid_render.py'
    $null = Invoke-Py -Py $Py -PyArgs @($renderer, '--probe')
    if ($LASTEXITCODE -eq 0) {
        $tmpd = Join-Path ([System.IO.Path]::GetTempPath()) ('pwp-verify-' + [System.Guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $tmpd -Force | Out-Null
        try {
            # 明确写 UTF-8 无 BOM：PowerShell 5.1 的 Set-Content 默认按 ANSI(936) 写，中文会乱。
            $lines = @('# 出图自检', '', '```mermaid', 'flowchart LR', '  A[开始] --> B[结束]', '```')
            $enc   = New-Object System.Text.UTF8Encoding($false)
            $inMd  = Join-Path $tmpd 'in.md'
            [System.IO.File]::WriteAllText($inMd, (($lines -join "`r`n") + "`r`n"), $enc)
            $out = Invoke-Py -Py $Py -PyArgs @($renderer, '-i', $inMd, '-o', (Join-Path $tmpd 'out.md'))
            $png = Join-Path $tmpd 'mermaid_figures\fig_001.png'
            if ((Test-Path $png) -and ((Get-Item $png).Length -gt 0)) {
                Write-Ok ("出图链路正常（" + $out + "）")
            } else {
                Write-Bad ("出图链路不通：" + $out)
            }
        } finally {
            Remove-Item -Path $tmpd -Recurse -Force -ErrorAction SilentlyContinue
        }
    } else {
        Write-Skip '这台机器出不了附图（没装 playwright，或既没有 Chrome/Edge 也没有 Chromium）——不影响规则，附图可改用 make_figure.py；装法见 INSTALL.md 第五节'
    }
}

Write-Host ("自检开始（" + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + "）")
$Py = Resolve-Python
if ($null -eq $Py) {
    Write-Host 'Python：没找到（不影响技能本身）'
} else {
    $ver  = (& $Py.Exe @($Py.Pre + @('-V')) 2>&1 | Out-String).Trim()
    $call = ((@($Py.Exe) + $Py.Pre) -join ' ')
    Write-Host ("Python：" + $ver + "（" + $call + "）")
}
Write-Host ''

$UserHome = if ($env:USERPROFILE) { $env:USERPROFILE } else { $HOME }
$Hosts = @(
    @{ Label = 'Claude Code'; Root = (Join-Path $UserHome '.claude');   Sub = 'skills' },
    @{ Label = 'Codex CLI';   Root = (Join-Path $UserHome '.codex');    Sub = 'skills' },
    @{ Label = 'Cursor';      Root = (Join-Path $UserHome '.cursor');   Sub = 'skills' },
    @{ Label = 'WorkBuddy';   Root = (Join-Path $UserHome '.workbuddy');Sub = 'skills' },
    @{ Label = 'nanobot';     Root = (Join-Path $UserHome '.nanobot');  Sub = 'workspace/skills' }
)

$found = 0
foreach ($h in $Hosts) {
    $sub = $h.Sub -replace '/', [System.IO.Path]::DirectorySeparatorChar
    $d = Join-Path (Join-Path $h.Root $sub) $SkillName
    if (Test-Path $d) {
        $found = $found + 1
        # 自检是诊断工具，任何一步意外报错都要变成一行看得懂的「失败」，不能甩一屏红字。
        try {
            Test-OneHost -Label $h.Label -Dir $d -Py $Py
        } catch {
            Write-Bad ("检查这个宿主时脚本自己出错了：" + $_.Exception.Message)
        }
        Write-Host ''
    } else {
        Write-Host ("  " + $h.Label + "：没装（" + $d + " 不存在）")
        Write-Host ''
    }
}

Write-Host '================================'
Write-Host ("装了 " + $found + " 个宿主，检查项 通过 " + $script:Pass + " 条 / 失败 " + $script:Fail + " 条")
if ($found -eq 0) {
    Write-Host '结论：一个宿主都没找到，这次什么也没验。先跑 install.ps1 装进去再来自检'
    exit 2
}
if ($script:Fail -eq 0) {
    Write-Host '结论：全部正常'
    exit 0
} else {
    Write-Host '结论：有问题，看上面 [失败] 那几行'
    exit 1
}

#Requires -Version 5.1
<#
Bootstrap installer for Rona (Windows). The only job of this script is to
make sure a Python 3.11+ interpreter is on PATH -- installing one via
winget if it's missing or too old -- then it hands off to the real
installer, which is written in Python (installer/main.py). See that
file (and installer/*.py) for component selection, venvs, .env
generation, and the web dashboard's npm build.
#>

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

function Test-PythonVersion($exe, $exeArgs) {
    try {
        $versionOutput = & $exe @exeArgs --version 2>&1
    } catch {
        return $false
    }
    if ("$versionOutput" -match "Python (\d+)\.(\d+)") {
        $major = [int]$Matches[1]
        $minor = [int]$Matches[2]
        return ($major -gt 3 -or ($major -eq 3 -and $minor -ge 11))
    }
    return $false
}

# Returns the path of an acceptable (3.11+) interpreter, or $null.
# The `py` launcher is probed per version (-3.13/-3.12/-3.11) because a bare
# `python`/`py` may resolve to an older install (or the Store stub) even when
# a newer one is installed alongside.
function Find-Python {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        foreach ($v in @("-3.13", "-3.12", "-3.11")) {
            if (Test-PythonVersion $py.Source @($v)) {
                $resolved = & $py.Source $v -c "import sys; print(sys.executable)" 2>$null
                if ($resolved) { return "$resolved".Trim() }
            }
        }
    }
    foreach ($cmd in @("python3", "python")) {
        $found = Get-Command $cmd -ErrorAction SilentlyContinue
        if (-not $found) { continue }
        if (Test-PythonVersion $found.Source @()) {
            return $found.Source
        }
    }
    return $null
}

# Shown in both languages -- the installer hasn't had a chance to ask which
# one yet (that question, and everything after it, is Python's job).
$python = Find-Python
if (-not $python) {
    Write-Host "Python 3.11+ not found. / Python 3.11 ya da üstü bulunamadı."
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Write-Host "winget not found either. Install Python 3.11+ from https://python.org and run this script again."
        Write-Host "winget de bulunamadı. https://python.org adresinden Python 3.11+ kur ve bu scripti tekrar çalıştır."
        exit 1
    }
    $answer = Read-Host "Install Python 3.12 via winget? / winget ile Python 3.12 kurulsun mu? [y/e, N/H]"
    if ($answer -notmatch "^[yYeE]") {
        Write-Host "Cancelled. / Vazgeçildi."
        exit 1
    }
    winget install --id Python.Python.3.12 -e --source winget
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Python installation failed. / Python kurulumu başarısız oldu."
        exit 1
    }
    $python = Find-Python
    if (-not $python) {
        Write-Host "Python was installed but doesn't appear on PATH in this session. Open a new terminal and run the script again."
        Write-Host "Python kuruldu ama bu oturumda PATH'te görünmüyor. Yeni bir terminal açıp scripti tekrar çalıştır."
        exit 1
    }
}

& $python (Join-Path $RepoRoot "installer\main.py") @args
exit $LASTEXITCODE

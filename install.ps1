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

function Find-Python {
    foreach ($cmd in @("python", "python3", "py")) {
        $found = Get-Command $cmd -ErrorAction SilentlyContinue
        if (-not $found) { continue }
        try {
            $versionOutput = & $found.Source --version 2>&1
        } catch {
            continue
        }
        if ($versionOutput -match "Python (\d+)\.(\d+)") {
            $major = [int]$Matches[1]
            $minor = [int]$Matches[2]
            if ($major -gt 3 -or ($major -eq 3 -and $minor -ge 11)) {
                return $found.Source
            }
        }
    }
    return $null
}

$python = Find-Python
if (-not $python) {
    Write-Host "Python 3.11 ya da üstü bulunamadı."
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Write-Host "winget de bulunamadı. https://python.org adresinden Python 3.11+ kur ve bu scripti tekrar çalıştır."
        exit 1
    }
    $answer = Read-Host "winget ile Python 3.12 kurulsun mu? [e/H]"
    if ($answer -notmatch "^[eE]") {
        Write-Host "Vazgeçildi."
        exit 1
    }
    winget install --id Python.Python.3.12 -e --source winget
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Python kurulumu başarısız oldu."
        exit 1
    }
    $python = Find-Python
    if (-not $python) {
        Write-Host "Python kuruldu ama bu oturumda PATH'te görünmüyor. Yeni bir terminal açıp scripti tekrar çalıştır."
        exit 1
    }
}

& $python (Join-Path $RepoRoot "installer\main.py") @args
exit $LASTEXITCODE

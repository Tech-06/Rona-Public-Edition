#Requires -Version 5.1
<#
Bootstrap uninstaller for Rona (Windows). Mirrors install.ps1's own
bootstrap: find a Python 3.11+ interpreter, then hand off to the real
uninstaller (installer/uninstall.py). Unlike install.ps1, this never
offers to *install* Python -- installing an interpreter just to remove
Rona would be backwards; if none is found, it says so and stops.
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

# Shown in both languages -- the uninstaller hasn't had a chance to ask
# which one yet (that question is Python's job, same as install.ps1).
$python = Find-Python
if (-not $python) {
    Write-Host "Python 3.11+ not found, needed to run the uninstaller. / Kaldırma aracını çalıştırmak için Python 3.11 ya da üstü gerekli, bulunamadı."
    Write-Host "Install Python 3.11+ from https://python.org and run this script again. / https://python.org adresinden Python 3.11+ kur ve bu scripti tekrar çalıştır."
    exit 1
}

& $python (Join-Path $RepoRoot "installer\uninstall.py") @args
exit $LASTEXITCODE

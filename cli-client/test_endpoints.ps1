param(
    [string]$Url = "http://127.0.0.1:8000",
    [string]$Message = "merhaba",
    [string]$Token
)

if (-not $Token) {
    $envPath = Join-Path $PSScriptRoot "..\backend\.env"
    if (Test-Path $envPath) {
        $line = Get-Content $envPath | Where-Object { $_ -match '^AUTH_TOKEN=' } | Select-Object -First 1
        if ($line) { $Token = ($line -replace '^AUTH_TOKEN=', '').Trim() }
    }
}
if (-not $Token) {
    Write-Error "AUTH_TOKEN bulunamadi (-Token parametresi veya backend/.env dosyasi)."
    exit 1
}

$authHeader = "Authorization: Bearer $Token"

Write-Host "== GET $Url/health ==" -ForegroundColor Cyan
curl.exe -s -w 'HTTP %{http_code}\n' -H $authHeader "$Url/health"

Write-Host ""
Write-Host "== POST $Url/chat ==" -ForegroundColor Cyan
$conversationId = [guid]::NewGuid().ToString()
$payload = '{\"message\": \"' + $Message + '\", \"conversation_id\": \"' + $conversationId + '\"}'
curl.exe -s -w 'HTTP %{http_code}\n' -X POST "$Url/chat" -H "Content-Type: application/json" -H $authHeader -d $payload

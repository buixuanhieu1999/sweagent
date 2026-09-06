param(
    [string]$Repo = $PSScriptRoot,
    [switch]$FullAccess
)

$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
$Host.UI.RawUI.WindowTitle = 'SWE Agent - Ollama Cloud - gpt-oss:120b'

Push-Location -LiteralPath $PSScriptRoot
try {
    $agentArgs = @(
        '-B', '-u', "$PSScriptRoot\agent.py",
        '--repo', $Repo,
        '--host', 'https://ollama.com/api',
        '--model', 'gpt-oss:120b'
    )
    if ($FullAccess) {
        $agentArgs += '--full-access'
    }
    & python @agentArgs
}
finally {
    Pop-Location
}

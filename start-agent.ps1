param(
    [string]$Repo = $PSScriptRoot,
    [switch]$FullAccess
)

$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
$Host.UI.RawUI.WindowTitle = 'SWE Agent - Ollama Cloud - nemotron-3-ultra:cloud'

Push-Location -LiteralPath $PSScriptRoot
try {
    $agentArgs = @(
        '-B', '-u', "$PSScriptRoot\agent.py",
        '--repo', $Repo,
        '--host', 'https://ollama.com/api',
        '--model', 'nemotron-3-ultra:cloud'
    )
    if ($FullAccess) {
        $agentArgs += '--full-access'
    }
    & python @agentArgs
}
finally {
    Pop-Location
}

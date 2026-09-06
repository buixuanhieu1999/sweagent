param(
    [string]$Repo = $PSScriptRoot,
    [switch]$FullAccess,
    [string]$Task,
    [string]$TaskFile
)

$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
$Host.UI.RawUI.WindowTitle = 'SWE Agent - Ollama Cloud - nemotron-3-ultra:cloud'

Push-Location -LiteralPath $PSScriptRoot
try {
    if ($Task -and $TaskFile) {
        throw 'Use either -Task or -TaskFile, not both.'
    }
    if ($TaskFile) {
        $Task = Get-Content -LiteralPath $TaskFile -Raw -Encoding utf8
    }
    $agentArgs = @(
        '-B', '-u', "$PSScriptRoot\agent.py",
        '--repo', $Repo,
        '--host', 'https://ollama.com/api',
        '--model', 'nemotron-3-ultra:cloud'
    )
    if ($FullAccess) {
        $agentArgs += '--full-access'
    }
    if ($Task) {
        $agentArgs += @('--new-session', '--task', $Task)
    }
    & python @agentArgs
}
finally {
    Pop-Location
}

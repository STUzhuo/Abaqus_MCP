$ErrorActionPreference = "Stop"

if (-not $env:ABAQUS_MCP_WORKSPACE) {
    $env:ABAQUS_MCP_WORKSPACE = (Get-Location).Path
}

if (-not $env:ABAQUS_COMMAND) {
    $abaqus = Get-Command abaqus -ErrorAction SilentlyContinue
    if ($abaqus) {
        $env:ABAQUS_COMMAND = $abaqus.Source
    } elseif (Test-Path -LiteralPath "C:\SIMULIA\Commands\abaqus.bat") {
        $env:ABAQUS_COMMAND = "C:\SIMULIA\Commands\abaqus.bat"
    } else {
        throw "Abaqus command not found. Set ABAQUS_COMMAND first."
    }
}

Set-Location -LiteralPath $PSScriptRoot
python -m abaqus_mcp.server

# Acceptance of the packaged executable; no development tools run on the host.
param([string]$ApplicationExecutable = '')
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path $PSScriptRoot -Parent
$appPath = Join-Path $repoRoot 'dist\Codix-win32-x64\Codix.exe'
if ($ApplicationExecutable) { $appPath = $ApplicationExecutable }
$env:CODIX_API_PORT = '43220'
$env:CODIX_MODEL = [Environment]::GetEnvironmentVariable('CODIX_MODEL', 'User')
# Coding-tool shells can inherit Node-only mode from their Electron parent.
Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue
$appProcess = Start-Process -FilePath $appPath -WorkingDirectory (Split-Path $appPath) -ArgumentList '--force-renderer-accessibility' -PassThru
try {
    $deadline = [DateTime]::UtcNow.AddSeconds(30)
    do {
        Start-Sleep -Milliseconds 500
        $appProcess.Refresh()
        if ($appProcess.HasExited) { throw 'Packaged application exited during startup' }
    } until ($appProcess.MainWindowTitle -eq 'Codix' -or [DateTime]::UtcNow -ge $deadline)
    if ($appProcess.MainWindowTitle -ne 'Codix') { throw 'Codix window did not appear' }
    Add-Type -AssemblyName UIAutomationClient
    Add-Type -AssemblyName UIAutomationTypes
    $connected = 'Backend: ' + (-join [char[]]@(0x645, 0x62a, 0x635, 0x644))
    $ready = $false
    do {
        $window = [Windows.Automation.AutomationElement]::FromHandle($appProcess.MainWindowHandle)
        $elements = $window.FindAll([Windows.Automation.TreeScope]::Descendants, [Windows.Automation.Condition]::TrueCondition)
        $names = @()
        foreach ($element in $elements) {
            $names += $element.Current.Name
            if ($element.Current.Name -like "*$connected*") { $ready = $true; break }
        }
        if ((($names -join '') -replace '\s', '') -like ('*' + ($connected -replace '\s', '') + '*')) { $ready = $true }
        if (-not $ready) { Start-Sleep -Milliseconds 500 }
    } until ($ready -or [DateTime]::UtcNow -ge $deadline)
    if (-not $ready) { throw 'Could not confirm connected backend from native UI accessibility tree' }
    'PASS native portable UI: Codix window, static resources, Electron bridge and connected backend.'
} finally {
    $appProcess.Refresh()
    if (-not $appProcess.HasExited) {
        $null = $appProcess.CloseMainWindow()
        if (-not $appProcess.WaitForExit(10000)) { $appProcess.Kill() }
    }
    $appProcess.Dispose()
}

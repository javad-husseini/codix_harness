# Test only the native packaged product; no host build tools.
param([string]$BackendExecutable = '')
$ErrorActionPreference = 'Stop'
if (-not $BackendExecutable) { $BackendExecutable = Join-Path (Split-Path $PSScriptRoot -Parent) 'dist\Codix-MVP-win32-x64\resources\backend\codix-backend.exe' }
function Test-RejectedStart([string]$PortValue) {
    $settings = New-Object Diagnostics.ProcessStartInfo
    $settings.FileName = $BackendExecutable
    $settings.WorkingDirectory = Split-Path $BackendExecutable
    $settings.UseShellExecute = $false
    $settings.CreateNoWindow = $true
    $settings.RedirectStandardInput = $true
    $settings.RedirectStandardOutput = $true
    $settings.RedirectStandardError = $true
    $settings.EnvironmentVariables['CODIX_API_PORT'] = $PortValue
    $child = New-Object Diagnostics.Process
    $child.StartInfo = $settings
    try {
        $null = $child.Start()
        $stdout = $child.StandardOutput.ReadToEndAsync()
        $stderr = $child.StandardError.ReadToEndAsync()
        $child.StandardInput.WriteLine(('a' * 64))  # Nonsecret fixture launch token.
        $child.StandardInput.Close()
        if (-not $child.WaitForExit(15000)) { throw 'Rejected startup did not exit within the supported deadline' }
        if ($child.ExitCode -eq 0 -or $stdout.Result.Contains('CODIX_READY')) { throw 'Invalid/conflicting port was accepted' }
    } finally {
        if (-not $child.HasExited) { $child.Kill() }
        $child.Dispose()
    }
}
Test-RejectedStart 'invalid'
$listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 43218)
$listener.Server.ExclusiveAddressUse = $true
$listener.Start()
try { Test-RejectedStart '43218' } finally { $listener.Stop() }
$settings = New-Object Diagnostics.ProcessStartInfo
$settings.FileName = $BackendExecutable
$settings.WorkingDirectory = Split-Path $BackendExecutable
$settings.UseShellExecute = $false
$settings.CreateNoWindow = $true
$settings.RedirectStandardInput = $true
$settings.RedirectStandardOutput = $true
$settings.RedirectStandardError = $true
$settings.EnvironmentVariables.Clear()
$settings.EnvironmentVariables['SystemRoot'] = $env:SystemRoot
$settings.EnvironmentVariables['TEMP'] = $env:TEMP
$settings.EnvironmentVariables['USERPROFILE'] = $env:USERPROFILE
$settings.EnvironmentVariables['CODIX_API_PORT'] = '43217'
$settings.EnvironmentVariables['PATH'] = Join-Path $env:SystemRoot 'System32'
$settings.EnvironmentVariables['ProgramFiles'] = Join-Path (Split-Path $PSScriptRoot -Parent) '.verification\absent-program-files'
$child = New-Object Diagnostics.Process
$child.StartInfo = $settings
try {
    $null = $child.Start()
    $stderr = $child.StandardError.ReadToEndAsync()
    $child.StandardInput.WriteLine(('b' * 64))
    $ready = $child.StandardOutput.ReadLineAsync()
    if (-not $ready.Wait(15000) -or $ready.Result -ne 'CODIX_READY') { throw 'Missing-Docker test backend failed startup' }
    $blocked = $false
    try { $missingResult = Invoke-RestMethod 'http://127.0.0.1:43217/prerequisites' -Method Post -ContentType 'application/json' -Body '{}' -Headers @{Authorization = ('Bearer ' + ('b' * 64))} }
    catch { if ([int]$_.Exception.Response.StatusCode -eq 503) { $blocked = $true } else { throw } }
    if (-not $blocked) { throw 'Missing Docker did not block execution' }
    $child.StandardInput.Close()
    if (-not $child.WaitForExit(10000)) { throw 'Missing-Docker test backend did not shut down' }
} finally {
    if (-not $child.HasExited) { $child.Kill() }
    $child.Dispose()
}
'PASS native startup: invalid/occupied Windows ports rejected; missing Docker CLI blocks execution without fallback.'

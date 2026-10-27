# Acceptance of the built backend; all shell commands below execute only in its Docker project.
param([string]$BackendExecutable = '')
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path $PSScriptRoot -Parent
if (-not $BackendExecutable) { $BackendExecutable = Join-Path $repoRoot 'runtime\codix-backend\codix-backend.exe' }
$start = New-Object System.Diagnostics.ProcessStartInfo
$start.FileName = $BackendExecutable
$start.WorkingDirectory = Split-Path $BackendExecutable -Parent
$start.UseShellExecute = $false
$start.CreateNoWindow = $true
$start.RedirectStandardInput = $true
$start.RedirectStandardOutput = $true
$start.RedirectStandardError = $true
$start.EnvironmentVariables['CODIX_API_PORT'] = '43223'
foreach ($name in @('AVALAI_API_KEY', 'OPENAI_API_KEY')) { $start.EnvironmentVariables.Remove($name) }
$bytes = New-Object byte[] 32
$rng = [Security.Cryptography.RandomNumberGenerator]::Create()
$rng.GetBytes($bytes); $rng.Dispose()
$token = [BitConverter]::ToString($bytes).Replace('-', '').ToLowerInvariant()
$process = New-Object System.Diagnostics.Process
$process.StartInfo = $start
$containerName = $null
try {
    if (-not $process.Start()) { throw 'Native backend did not start' }
    $null = $process.StandardError.ReadToEndAsync()
    $process.StandardInput.WriteLine($token)
    $ready = $process.StandardOutput.ReadLineAsync()
    if (-not $ready.Wait(30000) -or $ready.Result -ne 'CODIX_READY') { throw 'Native backend not ready' }
    $headers = @{ Authorization = "Bearer $token" }
    function Invoke-Workspace($endpoint, $body) {
        Invoke-RestMethod ('http://127.0.0.1:43223' + $endpoint) -Method Post -Headers $headers -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes(($body | ConvertTo-Json -Depth 6)))
    }
    $projectRoot = Join-Path $repoRoot ('.verification\workspace-' + [Guid]::NewGuid().ToString('N'))
    $null = New-Item -ItemType Directory -Path (Join-Path $projectRoot 'sub')
    [IO.File]::WriteAllText((Join-Path $projectRoot 'hello.py'), "print('Native read-only file')`n", (New-Object Text.UTF8Encoding $false))
    [IO.File]::WriteAllBytes((Join-Path $projectRoot 'binary.dat'), [byte[]]@(0, 255, 0))
    [IO.File]::WriteAllText((Join-Path $projectRoot 'large.txt'), ('x' * 32769))
    $preview = Invoke-Workspace '/projects/preview' @{root=$projectRoot}
    $project = Invoke-Workspace '/projects/prepare' @{ticket=$preview.ticket; approved=$false}
    $containerName = $project.container
    $pidProject = $project.project_id
    foreach ($pair in @(@('hello.py','text'),@('binary.dat','binary'),@('large.txt','too_large'))) {
        $file = Invoke-Workspace '/files/view' @{project_id=$pidProject;path=$pair[0]}
        if ($file.status -ne $pair[1]) { throw 'Unexpected native file view result' }
    }
    function Open-Terminal {
        $proposal = Invoke-Workspace '/terminals/propose' @{project_id=$pidProject;action='open';session_id='';text=''}
        (Invoke-Workspace '/terminals/execute' @{project_id=$pidProject;ticket=$proposal.ticket;approved=$true}).session_id
    }
    function Send-Terminal($sid, $text) {
        $proposal = Invoke-Workspace '/terminals/propose' @{project_id=$pidProject;action='input';session_id=$sid;text=$text}
        $null = Invoke-Workspace '/terminals/execute' @{project_id=$pidProject;ticket=$proposal.ticket;approved=$true}
    }
    function Get-Output($sid) {
        (Invoke-Workspace '/terminals/poll' @{project_id=$pidProject;session_id=$sid;cursor=0}).output
    }
    function Wait-Output($sid, $literal) {
        $deadline = [DateTime]::UtcNow.AddSeconds(10)
        do {
            $output = Get-Output $sid
            if ($output.Contains($literal)) { return }
            Start-Sleep -Milliseconds 80
        } until ([DateTime]::UtcNow -ge $deadline)
        throw 'Expected real PTY output did not arrive'
    }
    $a = Open-Terminal
    $b = Open-Terminal
    Send-Terminal $a 'cd sub; export MANUAL_STATE=alpha; printf "A:%s:%s\n" "$PWD" "$MANUAL_STATE"'
    Send-Terminal $b 'printf "B:%s:%s\n" "$PWD" "${MANUAL_STATE-unset}"'
    Wait-Output $a "A:/workspace/sub:alpha`r`n"
    Wait-Output $b "B:/workspace:unset`r`n"
    $null = Invoke-Workspace '/terminals/resize' @{project_id=$pidProject;session_id=$a;cols=93;rows=18}
    Send-Terminal $a 'stty size'
    Wait-Output $a "18 93`r`n"
    Send-Terminal $a 'printf "LIVE_READY\n"; sleep 60'
    Wait-Output $a "`r`nLIVE_READY`r`n"
    $promptsBefore = ([regex]::Matches((Get-Output $a), [regex]::Escape('codix$ '))).Count
    $null = Invoke-Workspace '/terminals/interrupt' @{project_id=$pidProject;session_id=$a}
    $deadline = [DateTime]::UtcNow.AddSeconds(10)
    do {
        Start-Sleep -Milliseconds 80
        $promptsAfter = ([regex]::Matches((Get-Output $a), [regex]::Escape('codix$ '))).Count
    } until ($promptsAfter -gt $promptsBefore -or [DateTime]::UtcNow -ge $deadline)
    if ($promptsAfter -le $promptsBefore) { throw 'Ctrl+C did not restore shell prompt' }
    Send-Terminal $a 'sleep 60 & echo CHILD_PID:$!'
    Wait-Output $a 'CHILD_PID:'
    $deadline = [DateTime]::UtcNow.AddSeconds(10)
    do {
        $match = [regex]::Match((Get-Output $a), 'CHILD_PID:([0-9]+)')
        if ($match.Success) { break }
        Start-Sleep -Milliseconds 80
    } until ([DateTime]::UtcNow -ge $deadline)
    if (-not $match.Success) { throw 'Background process did not start' }
    $childId = $match.Groups[1].Value
    $null = Invoke-Workspace '/terminals/close' @{project_id=$pidProject;session_id=$a}
    Send-Terminal $b ('if test -e /proc/' + $childId + '; then echo CHILD_LEAK; else echo CHILD_REAPED; fi')
    Wait-Output $b "`r`nCHILD_REAPED`r`n"
    $proposal = Invoke-Workspace '/terminals/propose' @{project_id=$pidProject;action='input';session_id=$b;text='touch DENIED'}
    $denied = $false
    try { $null = Invoke-Workspace '/terminals/execute' @{project_id=$pidProject;ticket=$proposal.ticket;approved=$false} }
    catch { if ([int]$_.Exception.Response.StatusCode -eq 403) { $denied=$true } else { throw } }
    if (-not $denied -or (Test-Path -LiteralPath (Join-Path $projectRoot 'DENIED'))) { throw 'Terminal input rejection failed' }
    $null = Invoke-Workspace '/terminals/close-project' @{project_id=$pidProject}
    $docker = Join-Path $env:ProgramFiles 'Docker\Docker\resources\bin\docker.exe'
    $running = & $docker inspect --format '{{.State.Running}}' $containerName
    if ($running -ne 'true') { throw 'Closing tabs stopped the shared project container' }
    'PASS native Windows backend + real Docker PTYs: file viewing/binary/size, independent shell cwd/state, live output, resize, Ctrl+C, background cleanup, sibling survival, exact input rejection, container remains running.'
} finally {
    if ($process.Id -and -not $process.HasExited) {
        $process.StandardInput.Close()
        if (-not $process.WaitForExit(30000)) { $process.Kill() }
    }
    $process.Dispose(); $token = $null
    if ($containerName -match '^codix-[0-9a-f]{24}$') {
        $docker = Join-Path $env:ProgramFiles 'Docker\Docker\resources\bin\docker.exe'
        & $docker stop $containerName | Out-Null
        & $docker rm $containerName | Out-Null
    }
}

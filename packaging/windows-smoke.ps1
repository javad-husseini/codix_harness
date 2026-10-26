# Native packaged-artifact test only; no host Python/npm/build commands.
param([string]$BackendExecutable = '', [switch]$LiveProvider)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path $PSScriptRoot -Parent
$executable = Join-Path $repoRoot 'dist\Codix-win32-x64\resources\backend\codix-backend.exe'
if ($BackendExecutable) { $executable = $BackendExecutable }
$start = New-Object System.Diagnostics.ProcessStartInfo
$start.FileName = $executable
$start.WorkingDirectory = Split-Path $executable -Parent
$start.UseShellExecute = $false
$start.CreateNoWindow = $true
$start.RedirectStandardInput = $true
$start.RedirectStandardOutput = $true
$start.RedirectStandardError = $true
$start.EnvironmentVariables['CODIX_API_PORT'] = '43219'
if ($LiveProvider) { $start.EnvironmentVariables['CODIX_MODEL'] = [Environment]::GetEnvironmentVariable('CODIX_MODEL', 'User') }
$bytes = New-Object byte[] 32
$rng = [Security.Cryptography.RandomNumberGenerator]::Create()
$rng.GetBytes($bytes)
$rng.Dispose()
$token = [BitConverter]::ToString($bytes).Replace('-','').ToLowerInvariant()
$process = New-Object System.Diagnostics.Process
$process.StartInfo = $start
$containerName = $null
try {
    if (-not $process.Start()) { throw 'Backend did not start' }
    $errors = $process.StandardError.ReadToEndAsync()
    $process.StandardInput.WriteLine($token)
    $ready = $process.StandardOutput.ReadLineAsync()
    if (-not $ready.Wait(30000) -or $ready.Result -ne 'CODIX_READY') {
        throw 'Packaged backend did not announce readiness'
    }
    $headers = @{ Authorization = "Bearer $token" }
    $health = Invoke-RestMethod 'http://127.0.0.1:43219/health' -Headers $headers
    if ($health.status -ne 'ready') { throw 'Health check failed' }
    $catalog = Invoke-RestMethod 'http://127.0.0.1:43219/tools/catalog' -Headers $headers
    if ($catalog.tools.Count -lt 1) { throw 'Tool catalog missing' }
    $prerequisites = Invoke-RestMethod 'http://127.0.0.1:43219/prerequisites' -Method Post -Headers $headers -ContentType 'application/json' -Body '{}'
    if ($prerequisites.docker -ne 'ready') { throw 'Docker prerequisite check failed' }
    $projectRoot = Join-Path $repoRoot '.verification\native windows project'
    New-Item -ItemType Directory -Path $projectRoot -Force | Out-Null
    $preview = Invoke-RestMethod 'http://127.0.0.1:43219/projects/preview' -Method Post -Headers $headers -ContentType 'application/json' -Body (@{ root = $projectRoot } | ConvertTo-Json)
    $project = Invoke-RestMethod 'http://127.0.0.1:43219/projects/prepare' -Method Post -Headers $headers -ContentType 'application/json' -Body (@{ ticket = $preview.ticket; approved = $false } | ConvertTo-Json)
    $containerName = $project.container
    $smoke = Invoke-RestMethod 'http://127.0.0.1:43219/projects/smoke' -Method Post -Headers $headers -ContentType 'application/json' -Body (@{ project_id = $project.project_id } | ConvertTo-Json)
    if (-not $smoke.compatible -or $smoke.exit_code -ne 0) { throw 'Native Windows project mount/container smoke failed' }
    $listing = Invoke-RestMethod 'http://127.0.0.1:43219/tools/propose' -Method Post -Headers $headers -ContentType 'application/json' -Body (@{ project_id = $project.project_id; name = 'list_files'; arguments = @{ path = '.' } } | ConvertTo-Json -Depth 4)
    $null = Invoke-RestMethod 'http://127.0.0.1:43219/tools/execute' -Method Post -Headers $headers -ContentType 'application/json' -Body (@{ project_id = $project.project_id; ticket = $listing.ticket; approved = $false } | ConvertTo-Json)
    if ($LiveProvider) {
        $task = Invoke-RestMethod 'http://127.0.0.1:43219/tasks/start' -Method Post -Headers $headers -ContentType 'application/json' -Body (@{ project_id = $project.project_id; request = 'Connectivity check only. Set a one-step plan titled Check connectivity, then immediately finish_step with acceptance_met=false. Do not modify files, read files, delete files, install dependencies or run commands.' } | ConvertTo-Json)
        $deadline = [DateTime]::UtcNow.AddSeconds(110)
        do {
            Start-Sleep -Milliseconds 500
            $state = Invoke-RestMethod 'http://127.0.0.1:43219/tasks/status' -Method Post -Headers $headers -ContentType 'application/json' -Body (@{ task_id = $task.task_id } | ConvertTo-Json)
            if ($state.status -eq 'awaiting_approval') {
                $null = Invoke-RestMethod 'http://127.0.0.1:43219/tasks/decide' -Method Post -Headers $headers -ContentType 'application/json' -Body (@{ task_id = $task.task_id; decision_id = $state.approval.decision_id; approved = $false } | ConvertTo-Json)
            }
        } until ($state.status -notin @('running', 'awaiting_approval') -or [DateTime]::UtcNow -ge $deadline)
        # Only fixed diagnostic messages and accounting leave this read-only probe.
        'Provider probe status: ' + $state.status
        'Provider probe tokens reserved/used: ' + $state.tokens_used
        $state.report.unresolved | ForEach-Object { $_ }
    }
    $process.StandardInput.Close()
    if (-not $process.WaitForExit(10000)) { throw 'Backend did not exit after parent EOF' }
    if ($process.ExitCode -ne 0) { throw 'Backend exited unsuccessfully' }
    'PASS native packaged backend: startup, authentication, bundled workers/LangGraph, catalog, Docker/WSL, Windows project path with spaces, isolated Node/Python smoke and shutdown.'
} finally {
    if ($process.Id -and -not $process.HasExited) { $process.Kill() }
    $process.Dispose()
    $token = $null
    if ($containerName -match '^codix-[0-9a-f]{24}$') {
        $docker = Join-Path $env:ProgramFiles 'Docker\Docker\resources\bin\docker.exe'
        & $docker stop $containerName | Out-Null
        & $docker rm $containerName | Out-Null
    }
}

# Acceptance of the built backend only. All generated code executes in Docker.
param([string]$BackendExecutable = '', [string]$ConfigurationFile = '', [switch]$Chat)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path $PSScriptRoot -Parent
if (-not $BackendExecutable) { $BackendExecutable = Join-Path $repoRoot 'runtime\codix-backend\codix-backend.exe' }
if (-not $ConfigurationFile) { $ConfigurationFile = Join-Path $repoRoot 'dist\Codix-MVP-win32-x64\.env' }
$start = New-Object System.Diagnostics.ProcessStartInfo
$start.FileName = $BackendExecutable
$start.WorkingDirectory = Split-Path $BackendExecutable -Parent
$start.UseShellExecute = $false
$start.CreateNoWindow = $true
$start.RedirectStandardInput = $true
$start.RedirectStandardOutput = $true
$start.RedirectStandardError = $true
# This acceptance helper supports the simple unquoted/fully quoted template values.
# It never evaluates file content, prints keys or passes them to the project container.
foreach ($key in @('AVALAI_API_KEY', 'OPENAI_API_KEY', 'CODIX_MODEL', 'OPENAI_BASE_URL')) {
    $start.EnvironmentVariables.Remove($key)
}
$file = Get-Item -LiteralPath $ConfigurationFile
if ($file.Length -gt 16384 -or ($file.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Invalid local configuration file' }
foreach ($line in [IO.File]::ReadAllLines($file.FullName, [Text.Encoding]::UTF8)) {
    if ($line -match '^\s*(AVALAI_API_KEY|OPENAI_API_KEY|CODIX_MODEL|OPENAI_BASE_URL)\s*=\s*(.*?)\s*$') {
        $name, $value = $Matches[1], $Matches[2]
        if ($value.StartsWith('"') -or $value.StartsWith("'")) {
            if ($value.Length -lt 2 -or $value[0] -ne $value[$value.Length - 1]) { throw 'Unsupported quoted configuration' }
            $value = $value.Substring(1, $value.Length - 2)
        } elseif ($value.Contains('#')) { throw 'Use simple template values for this acceptance test' }
        $start.EnvironmentVariables[$name] = $value
    }
}
$value = $null; $line = $null
if (-not ($start.EnvironmentVariables['AVALAI_API_KEY'] -or $start.EnvironmentVariables['OPENAI_API_KEY'])) {
    throw 'Fill the portable .env before the live Hello World acceptance test.'
}
$start.EnvironmentVariables['CODIX_API_PORT'] = '43222'
$bytes = New-Object byte[] 32
$rng = [Security.Cryptography.RandomNumberGenerator]::Create()
$rng.GetBytes($bytes)
$rng.Dispose()
$token = [BitConverter]::ToString($bytes).Replace('-', '').ToLowerInvariant()
$process = New-Object System.Diagnostics.Process
$process.StartInfo = $start
$containerName = $null
try {
    if (-not $process.Start()) { throw 'Packaged backend did not start' }
    $null = $process.StandardError.ReadToEndAsync()
    $process.StandardInput.WriteLine($token)
    $ready = $process.StandardOutput.ReadLineAsync()
    if (-not $ready.Wait(30000) -or $ready.Result -ne 'CODIX_READY') { throw 'Packaged backend was not ready' }
    $headers = @{ Authorization = "Bearer $token" }
    function Invoke-Backend($endpoint, $body) {
        Invoke-RestMethod ('http://127.0.0.1:43222' + $endpoint) -Method Post -Headers $headers -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes(($body | ConvertTo-Json -Depth 6)))
    }
    $projectRoot = Join-Path $repoRoot ('.verification\hello budget-' + [Guid]::NewGuid().ToString('N'))
    $null = New-Item -ItemType Directory -Path $projectRoot
    $preview = Invoke-Backend '/projects/preview' @{ root = $projectRoot }
    $project = Invoke-Backend '/projects/prepare' @{ ticket = $preview.ticket; approved = $false }
    $containerName = $project.container
    $chatTokens = 0
    if ($Chat) {
        foreach ($message in @('Remember the session code LILAC-742. Reply briefly without taking actions.', 'What is the session code I gave you? Reply with just the code.')) {
            $chatRun = Invoke-Backend '/chat/send' @{ project_id = $project.project_id; message = $message }
            $chatDeadline = [DateTime]::UtcNow.AddSeconds(100)
            do {
                Start-Sleep -Milliseconds 250
                $chatState = Invoke-Backend '/tasks/status' @{ task_id = $chatRun.task_id }
            } until ($chatState.status -notin @('running', 'awaiting_approval') -or [DateTime]::UtcNow -ge $chatDeadline)
            if ($chatState.chat_status -ne 'completed' -or $chatState.commands.Count -ne 0 -or $chatState.changed_files.Count -ne 0 -or $chatState.approval) {
                throw 'Native chat did not complete without tool execution'
            }
        }
        if ($chatState.messages.Count -ne 4 -or $chatState.messages[-1].content -notmatch 'LILAC-742') { throw 'Native chat did not preserve two-turn context' }
        $chatTokens = $chatState.tokens_used
        'PASS real two-turn AvalAI chat: remembered session code, no file/command/approval actions.'
        'Pre-task chat tokens: ' + $chatTokens
    }
    $task = Invoke-Backend '/tasks/start' @{ project_id = $project.project_id; request = 'یک فایل hello.py بساز که فقط Hello, World! چاپ کند. یک گام برای ساخت و اجرای python3 -B hello.py و تایید خروجی کافی است. هیچ وابستگی نصب نکن، فایلی حذف نکن و فایل دیگری نساز.' }
    $deadline = [DateTime]::UtcNow.AddSeconds(180)
    $approvedCommands = 0
    do {
        Start-Sleep -Milliseconds 250
        $state = Invoke-Backend '/tasks/status' @{ task_id = $task.task_id }
        if ($state.status -eq 'awaiting_approval') {
            $safe = $false
            $created = Join-Path $projectRoot 'hello.py'
            if ((Test-Path -LiteralPath $created) -and $state.approval.reason -like 'Every terminal command requires approval.*') {
                $content = [IO.File]::ReadAllText($created)
                # Approve only execution of a literal one-line print statement in this disposable root.
                $safe = ($content -match '^\s*print\(\s*["'']Hello, World!["'']\s*\)\s*$' -and
                         $state.approval.detail -match '^/bin/sh -c [''"]python3 -B hello\.py[''"]\r?\nWorking directory: /workspace$' -and
                         $approvedCommands -eq 0)
            }
            $null = Invoke-Backend '/tasks/decide' @{ task_id = $task.task_id; decision_id = $state.approval.decision_id; approved = [bool]$safe }
            if (-not $safe) {
                'Rejected acceptance proposal (already redacted by backend policy):'
                $state.approval.reason
                $state.approval.detail
                'Reported tokens before rejection: ' + $state.tokens_reported
                'Unreported reservations before rejection: ' + $state.tokens_reserved
                throw 'Live model requested an operation outside the exact Hello World acceptance check; rejected.'
            }
            $approvedCommands++
        }
    } until ($state.status -notin @('running', 'awaiting_approval') -or [DateTime]::UtcNow -ge $deadline)
    # Only fixed status/counters and verified literal output leave the acceptance helper.
    'Live Hello World status: ' + $state.status
    'Model calls: ' + $state.model_calls
    'Reported tokens: ' + $state.tokens_reported
    'Unreported reservations: ' + $state.tokens_reserved
    if ($state.next_call_tokens) { 'Next call required: ' + $state.next_call_tokens }
    if ($state.status -ne 'completed') { throw 'Live Hello World acceptance did not complete; inspect fixed provider diagnostics in Codix.' }
    if ($state.tokens_used -gt 25000 -or $state.correction_cycles -ne 0 -or $approvedCommands -ne 1) { throw 'Unexpected live task limits or approvals' }
    if ($state.commands.Count -ne 1 -or $state.commands[0].exit_code -ne 0 -or $state.commands[0].stdout.Trim() -ne 'Hello, World!') { throw 'Actual Python output did not match Hello World' }
    if ($state.changed_files.Count -ne 1 -or $state.changed_files[0] -ne 'hello.py') { throw 'Unexpected changed files' }
    if ($Chat) {
        if ($state.tokens_used -le $chatTokens -or $state.model_calls -lt 6 -or $state.messages.Count -lt 6) { throw 'Execution did not include pre-task chat in its shared budget/context' }
        $beforeFollowup = $state.tokens_used
        $followup = Invoke-Backend '/chat/send' @{ project_id = $project.project_id; message = 'What exact text did the executed Python command print? Reply briefly using the recorded result. Do not run anything.' }
        do {
            Start-Sleep -Milliseconds 250
            $state = Invoke-Backend '/tasks/status' @{ task_id = $followup.task_id }
        } until ($state.status -notin @('running', 'awaiting_approval') -or [DateTime]::UtcNow -ge $deadline)
        if ($followup.task_id -ne $task.task_id -or $state.chat_status -ne 'completed' -or $state.commands.Count -ne 1 -or
            $state.tokens_used -le $beforeFollowup -or $state.tokens_used -gt 25000 -or $state.messages[-1].content -notmatch 'Hello, World!') { throw 'Related chat did not reuse the task result and budget' }
        'PASS related chat: same task ID, shared budget, actual result context, no extra command.'
        'Final reported tokens including chat: ' + $state.tokens_reported
    }
    'PASS live native backend: AvalAI planning, actual Docker file creation, exact guarded command approval and Hello, World! output within 25000 tokens.'
} finally {
    if ($process.Id -and -not $process.HasExited) {
        $process.StandardInput.Close()
        if (-not $process.WaitForExit(10000)) { $process.Kill() }
    }
    $process.Dispose()
    $token = $null; $content = $null
    $start.EnvironmentVariables.Remove('AVALAI_API_KEY')
    $start.EnvironmentVariables.Remove('OPENAI_API_KEY')
    if ($containerName -match '^codix-[0-9a-f]{24}$') {
        $docker = Join-Path $env:ProgramFiles 'Docker\Docker\resources\bin\docker.exe'
        & $docker stop $containerName | Out-Null
        & $docker rm $containerName | Out-Null
    }
}

# Task 4 — Resumable Review Workflow Demonstration Script
# Demonstrates run -> checkpoint pause -> resume -> approve -> duplicate approval check

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$pkgDir = Split-Path -Parent $scriptDir
$repoDir = Split-Path -Parent (Split-Path -Parent $pkgDir)

$env:PYTHONPATH = $pkgDir
$python = Join-Path $repoDir ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    $python = "python"
}

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "Task 4: Resumable Review Workflow End-to-End Demonstration" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# Step 1: Run workflow with one revision scenario
Write-Host "`n[Step 1] Running workflow with scenario 'one_revision_then_pass'..." -ForegroundColor Yellow
& $python -m workflow.cli run content-001 --scenario one_revision_then_pass

# Step 2: Resume (inspect checkpoint)
Write-Host "`n[Step 2] Resuming and inspecting saved checkpoint..." -ForegroundColor Yellow
& $python -m workflow.cli resume content-001

# Step 3: Approve and complete
Write-Host "`n[Step 3] Approving workflow..." -ForegroundColor Yellow
& $python -m workflow.cli approve content-001

# Step 4: Duplicate approval (verify idempotency)
Write-Host "`n[Step 4] Attempting duplicate approval (idempotency check)..." -ForegroundColor Yellow
& $python -m workflow.cli approve content-001

Write-Host "`n[Step 5] Displaying inspectable event log..." -ForegroundColor Yellow
$logPath = Join-Path $pkgDir "events.jsonl"
if (Test-Path $logPath) {
    Get-Content $logPath
}

Write-Host "`nDemonstration finished successfully!" -ForegroundColor Green

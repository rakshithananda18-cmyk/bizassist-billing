<#
  deploy_space.ps1 - push field-team/ to its own Hugging Face Space.

  A Space builds from the ROOT of its git repo (README front-matter +
  Dockerfile), so the Space must receive this folder as its root.
  `git subtree split` turns field-team/'s committed history into a standalone
  commit chain, and that is what gets pushed. Billing's own Space push
  (`git push space main`) is unchanged and unaffected.

  Usage (from anywhere in the repo, normally on an up-to-date main):
    .\field-team\deploy_space.ps1              # deploy field-team/ as committed at HEAD
    .\field-team\deploy_space.ps1 -DryRun      # split only: show what would be pushed
    .\field-team\deploy_space.ps1 -FirstPush   # first push to a NEW Space (replaces its starter commit)

  Every push rebuilds the Space. Before the first one, set the Space secrets
  DATABASE_URL and JWT_SECRET (same values as the billing Space) - see
  field-team/docs/MASTER_PLAN.md section 8.1.
#>
param(
    [string]$Remote = "space-field-team",
    [string]$Url = "https://huggingface.co/spaces/rakshit-dev/bizassist-task",
    [switch]$FirstPush,
    [switch]$DryRun
)

$repo = (git -C $PSScriptRoot rev-parse --show-toplevel).Trim()
Push-Location $repo
try {
    $branch = (git rev-parse --abbrev-ref HEAD).Trim()
    if ($branch -ne "main") {
        Write-Host "Note: deploying from branch '$branch', not main." -ForegroundColor Yellow
    }
    if (git status --porcelain -- field-team) {
        Write-Host "Uncommitted changes in field-team/ are NOT deployed - only committed history is." -ForegroundColor Yellow
    }

    Write-Host "Splitting field-team/ out of the repo history (can take a minute)..." -ForegroundColor Cyan
    $sha = (git subtree split --prefix=field-team HEAD | Select-Object -Last 1)
    if (-not $sha -or $LASTEXITCODE -ne 0) { Write-Host "git subtree split failed." -ForegroundColor Red; exit 1 }
    $sha = $sha.Trim()
    Write-Host "field-team/ at HEAD = $sha" -ForegroundColor Green
    git ls-tree --name-only $sha | ForEach-Object { Write-Host "  $_" }

    if ($DryRun) { Write-Host "Dry run - nothing pushed." -ForegroundColor Yellow; exit 0 }

    if (-not (git remote | Where-Object { $_ -eq $Remote })) {
        git remote add $Remote $Url
        Write-Host "Added remote $Remote -> $Url" -ForegroundColor Cyan
    }
    $pushArgs = @("push")
    if ($FirstPush) { $pushArgs += "--force" }
    $pushArgs += @($Remote, "${sha}:refs/heads/main")
    & git @pushArgs
    if ($LASTEXITCODE -ne 0) { Write-Host "Push failed." -ForegroundColor Red; exit 1 }
    Write-Host "Pushed. The Space is rebuilding: $Url" -ForegroundColor Green
}
finally {
    Pop-Location
}

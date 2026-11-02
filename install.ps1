# Installs uv for this user when it is missing, then runs the Microsoft 365 connectors setup.
# Nothing here needs administrator rights. Arguments pass through to lrh-m365-setup (try -- --help).
$ErrorActionPreference = 'Stop'

$Owner = 'lucasrhode95'
$SetupRef = 'main'
$AuthRef = 'refs/heads/feat/device-code-prompt'
# Overrides for testing a local checkout: a folder path or any uv-supported source.
$SetupSource = if ($env:LRH_M365_SETUP_SOURCE) { $env:LRH_M365_SETUP_SOURCE } else { "https://github.com/$Owner/lrh-m365-setup/archive/$SetupRef.zip" }
$AuthSource = if ($env:LRH_M365_AUTH_SOURCE) { $env:LRH_M365_AUTH_SOURCE } else { "https://github.com/$Owner/lrh-m365-auth/archive/$AuthRef.zip" }

$uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
if (-not $uv) {
    $uv = Join-Path $HOME '.local\bin\uv.exe'
    if (-not (Test-Path $uv)) {
        Write-Host 'Installing uv, the Python tool manager, for this user...'
        Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    }
}

Write-Host 'Starting the Microsoft 365 connectors setup...'
& $uv tool run --from $SetupSource --with "lrh-m365-auth @ $AuthSource" lrh-m365-setup @args
exit $LASTEXITCODE

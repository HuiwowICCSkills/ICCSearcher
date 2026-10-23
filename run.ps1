# Locate a Python with the packages needed by ICCSearcher, then run the CLI.
$iccCandidates = @(
    (Join-Path $PSScriptRoot 'venv\Scripts\python.exe'),
    (Join-Path $PSScriptRoot 'venv/bin/python'),
    (Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'),
    (Join-Path $env:USERPROFILE '.workbuddy\binaries\python\versions\3.13.12\python.exe')
)
$iccPathPython = (Get-Command python -ErrorAction SilentlyContinue).Source
if ($iccPathPython) { $iccCandidates += $iccPathPython }
$iccPathPython3 = (Get-Command python3 -ErrorAction SilentlyContinue).Source
if ($iccPathPython3) { $iccCandidates += $iccPathPython3 }

function Get-IccPythonScore {
    param([string]$Candidate)
    if (-not $Candidate -or -not (Test-Path -LiteralPath $Candidate -PathType Leaf)) { return 0 }
    & $Candidate -c 'import requests, bs4' 2>$null
    if ($LASTEXITCODE -ne 0) { return 0 }
    & $Candidate -c 'import pypdf' 2>$null
    if ($LASTEXITCODE -eq 0) { return 2 }
    return 1
}

$iccPython = $null
$iccBestScore = 0
foreach ($iccCandidate in $iccCandidates) {
    $iccScore = Get-IccPythonScore $iccCandidate
    if ($iccScore -gt $iccBestScore) {
        $iccPython = $iccCandidate
        $iccBestScore = $iccScore
        if ($iccBestScore -eq 2) { break }
    }
}
if (-not $iccPython) {
    throw 'No Python with requests and beautifulsoup4 was found. Install requirements.txt or create venv/.'
}
if ($iccBestScore -lt 2) {
    Write-Warning 'Selected Python lacks pypdf; HTML search works, but PDF extraction may fail.'
}
$iccArguments = foreach ($iccArgument in $args) {
    if ($iccArgument -is [array]) { $iccArgument -join ',' } else { $iccArgument }
}
& $iccPython -X utf8 (Join-Path $PSScriptRoot 'scripts\icc_search.py') $iccArguments
exit $LASTEXITCODE

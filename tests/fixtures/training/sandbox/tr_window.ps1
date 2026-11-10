# The sandbox re-ingest window for the training fixture decks, driven from PowerShell.
#
#     .\tr_window.ps1 -Mode <guard|stage|check|dry|launch|status|readback|pull|build> -Work <local dir>
#
# Every pod mode runs `guard` first and stops on a mismatch: the Deployment's one
# Running pod must carry one of -Digests as its imageID and -ExpectVersion as its
# DOC_TOOLS_VERSION. Read off the pod, never the chart: a fire is a Job and a pin PR
# changes no pod, so neither says what an ingest runs.
#
#   guard     read-only: pod, imageID, DOC_TOOLS_VERSION
#   stage     write <Work>\stage (scripts, decks, key lists), copy it to a FRESH /tmp/tr_run
#   check     read-only: tr_upload.py --check (each deck already in MinIO, same bytes)
#   dry       tr_two_streams.sh --dry: the runner's guards in the pod, executes nothing
#   launch    check must be all MATCH, then the two streams start detached
#   status    the tail of each stream's log
#   readback  read-only: tr_readback_all.sh (tr_readback.py per deck, tr_never_written.py)
#   outline   read-only: tr_outline_check.py, each deck's outline through the workbench's reader
#   pull      copy /tmp/tr_run/out back to <Work>\pull
#   build     local: measure_decks, build_golden per deck, deck_table
#
# Stores are written ONLY by `launch`. Prints no env value but DOC_TOOLS_VERSION.
param(
    [Parameter(Mandatory)][ValidateSet("guard", "stage", "check", "dry", "launch", "status", "readback", "outline", "pull", "build")]
    [string]$Mode,
    [Parameter(Mandatory)][string]$Work,
    [string]$ExpectVersion = "728afaf",
    # The 728afaf pin (ecf80ee): the index digest and its linux/amd64 child.
    [string[]]$Digests = @(
        "sha256:ca3e7d830c75294f18406444d79e5b52e7751ef7352e3ab7ba6bde3457d0fc4c",
        "sha256:29a161a17133149c58ffd118f2febe5bb0d074f8bedc2f8fe6587bba3ba0c986")
)
$ErrorActionPreference = "Stop"
$K = @("--context", "edge", "-n", "sandbox")
$Sandbox = $PSScriptRoot
$Fixtures = Split-Path $Sandbox -Parent
$Py = Join-Path $Fixtures "..\..\..\.venv\Scripts\python.exe"
$R = "/tmp/tr_run"
$Scripts = @("tr_run_by_hand.py", "tr_two_streams.sh", "tr_upload.py", "tr_readback.py",
    "tr_readback_all.sh", "tr_never_written.py", "tr_outline_check.py")

function Slugs { Get-ChildItem $Fixtures -Directory | Where-Object { $_.Name -ne "sandbox" -and (Get-ChildItem $_.FullName -Filter *.pptx) } | ForEach-Object { $_.Name } }
function DeckKey($slug) { "training/course/$slug/" + (Get-ChildItem (Join-Path $Fixtures $slug) -Filter *.pptx | Select-Object -First 1).Name }

function Guard {
    $sel = "app.kubernetes.io/name=doc-tools,app.kubernetes.io/instance=doc-tools"
    # Write-Host, not Write-Output: anything output here becomes the return value.
    $pods = @((kubectl @K get pods -l $sel -o json | ConvertFrom-Json).items |
        Where-Object { $_.metadata.ownerReferences[0].kind -eq "ReplicaSet" -and $_.status.phase -eq "Running" -and -not $_.metadata.deletionTimestamp })
    if ($pods.Count -ne 1) { Write-Host "GUARD FAIL: $($pods.Count) Running Deployment pods, need 1"; exit 1 }
    $pod = $pods[0].metadata.name
    $imageId = $pods[0].status.containerStatuses[0].imageID
    $digest = ($imageId -split "@")[-1]
    $ver = (kubectl @K exec $pod -- printenv DOC_TOOLS_VERSION | Out-String).Trim()
    $short = $digest.Substring(0, [Math]::Min(15, $digest.Length))
    if ($Digests -notcontains $digest) { Write-Host "GUARD FAIL: pod=$pod imageID=$short is not the pin; RUN NOTHING"; exit 1 }
    # The image sets it as `doc-tools@<full sha>`; any other prefix fails the match.
    if (-not ($ver -replace '^doc-tools@', '').StartsWith($ExpectVersion)) { Write-Host "GUARD FAIL: pod=$pod DOC_TOOLS_VERSION=$ver is not $ExpectVersion; RUN NOTHING"; exit 1 }
    Write-Host "GUARD OK pod=$pod imageID=$short DOC_TOOLS_VERSION=$ver"
    return $pod
}

function Exec($pod, [string]$sh) { kubectl @K exec $pod -- sh -c $sh }

if ($Mode -eq "build") {
    $pull = Join-Path $Work "pull"
    & $Py -I (Join-Path $Sandbox "measure_decks.py") $Fixtures (Join-Path $Work "measure.json")
    foreach ($slug in Slugs) {
        $dir = Join-Path $Fixtures $slug
        $deck = (Get-ChildItem $dir -Filter *.pptx | Select-Object -First 1).FullName
        $meta = if (Test-Path (Join-Path $dir "metadata.json")) { Join-Path $dir "metadata.json" } else { "-" }
        & $Py -I (Join-Path $Sandbox "build_golden.py") (Join-Path $pull "rb\$slug.json") (Join-Path $pull "runs.jsonl") $deck $meta "training/course/$slug" (Join-Path $dir "golden.json")
    }
    & $Py -I (Join-Path $Sandbox "deck_table.py") $Fixtures (Join-Path $Work "measure.json") (Join-Path $pull "never_written.json") (Join-Path $Work "deck_table.md")
    exit $LASTEXITCODE
}

$pod = Guard
switch ($Mode) {
    "guard" { }
    "stage" {
        $stage = Join-Path $Work "stage"
        if (Test-Path $stage) { Write-Output "REFUSE: $stage exists"; exit 1 }
        New-Item -ItemType Directory -Force (Join-Path $stage "decks") | Out-Null
        foreach ($s in $Scripts) { Copy-Item (Join-Path $Sandbox $s) $stage }
        $a = @(); $b = @()
        foreach ($slug in Slugs) {
            $d = New-Item -ItemType Directory -Force (Join-Path $stage "decks\$slug")
            Get-ChildItem (Join-Path $Fixtures $slug) | Where-Object { $_.Name -like "*.pptx" -or $_.Name -eq "metadata.json" } | Copy-Item -Destination $d
            if ($slug -like "long-*") { $a += DeckKey $slug } else { $b += DeckKey $slug }
        }
        # LF, no BOM: the pod's sh reads these.
        [IO.File]::WriteAllText((Join-Path $stage "keys_A.txt"), (($a -join "`n") + "`n"))
        [IO.File]::WriteAllText((Join-Path $stage "keys_B.txt"), (($b -join "`n") + "`n"))
        Write-Output "stream A $($a.Count) keys, stream B $($b.Count) keys"
        $there = (Exec $pod "test -e $R && echo yes || echo no" | Out-String).Trim()
        if ($there -ne "no") { Write-Output "REFUSE: $R already exists in $pod"; exit 1 }
        # kubectl cp reads "C:" as a pod name, so copy from a relative path.
        Push-Location $Work
        try { kubectl @K cp "stage" "${pod}:$R" } finally { Pop-Location }
        Exec $pod "ls $R; ls $R/decks | wc -l"
    }
    "check" { Exec $pod "cd $R && /opt/venv/bin/python -I tr_upload.py --check decks"; exit $LASTEXITCODE }
    "dry" { Exec $pod "sh $R/tr_two_streams.sh $ExpectVersion --dry; sleep 20; tail -n 25 $R/A.dry.log $R/B.dry.log" }
    "launch" {
        Exec $pod "cd $R && /opt/venv/bin/python -I tr_upload.py --check decks"
        if ($LASTEXITCODE -ne 0) { Write-Output "REFUSE: not every deck MATCHes in MinIO; nothing launched"; exit 1 }
        Exec $pod "sh $R/tr_two_streams.sh $ExpectVersion"
    }
    "status" { Exec $pod "for S in A B; do echo == `$S; tail -n 3 $R/`$S.log; done; wc -l $R/runs_*.jsonl 2>/dev/null" }
    "readback" { Exec $pod "sh $R/tr_readback_all.sh"; exit $LASTEXITCODE }
    "outline" { Exec $pod "cd /app && PYTHONPATH=/app /opt/venv/bin/python $R/tr_outline_check.py $R/out/rb $R/out/outline_check.json"; exit $LASTEXITCODE }
    "pull" {
        $pull = Join-Path $Work "pull"
        if (Test-Path $pull) { Write-Output "REFUSE: $pull exists"; exit 1 }
        Push-Location $Work
        try { kubectl @K cp "${pod}:$R/out" "pull" } finally { Pop-Location }
        Get-ChildItem $pull -Recurse -File | Measure-Object | ForEach-Object { "pulled $($_.Count) files" }
    }
}

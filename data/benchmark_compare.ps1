# Does the benchmark choice actually matter? Rebase Nifty 50 / 100 / 500 / Smallcap 250
# to the same start date and see how far apart they drift.
$ua = @{ "User-Agent" = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)" }

function Get-MonthlyCloses($symbol, $range) {
    $uri = "https://query1.finance.yahoo.com/v8/finance/chart/$symbol" + "?interval=1mo&range=$range"
    $r = Invoke-RestMethod -Uri $uri -Headers $ua -TimeoutSec 25
    $res = $r.chart.result[0]
    $ts = $res.timestamp; $close = $res.indicators.quote[0].close
    $map = @{}
    for ($i = 0; $i -lt $ts.Count; $i++) {
        if ($null -ne $close[$i]) {
            $d = ([datetimeoffset]::FromUnixTimeSeconds($ts[$i])).ToString("yyyy-MM")
            $map[$d] = [double]$close[$i]
        }
    }
    return $map
}

$idx = @{
    "Nifty 50"        = Get-MonthlyCloses "^NSEI" "10y"
    "Nifty 100"       = Get-MonthlyCloses "^CNX100" "10y"
    "Nifty 500"       = Get-MonthlyCloses "^CRSLDX" "10y"
    "Nifty Smallcap 250" = Get-MonthlyCloses "NIFTYSMLCAP250.NS" "10y"
}

$anchors = @("2016-12","2019-09","2021-09","2023-09","2026-09")
$base = @{}
foreach ($k in $idx.Keys) { $base[$k] = $idx[$k]["2016-12"] }

Write-Output "-- Each index rebased to 100 at 2016-12 --"
$rows = foreach ($d in $anchors) {
    $row = [ordered]@{ date = $d }
    foreach ($k in $idx.Keys) { $row[$k] = [math]::Round(($idx[$k][$d] / $base[$k]) * 100, 1) }
    [PSCustomObject]$row
}
$rows | Format-Table -AutoSize

Write-Output "-- CDMO basket (Divis+Laurus) relative to EACH benchmark, at the same anchors --"
$divis = Get-MonthlyCloses "DIVISLAB.NS" "10y"
$laurus = Get-MonthlyCloses "LAURUSLABS.NS" "10y"
$divBase = $divis["2016-12"]; $lauBase = $laurus["2016-12"]

$rows2 = foreach ($d in $anchors) {
    $dR = ($divis[$d] / $divBase) * 100
    $lR = ($laurus[$d] / $lauBase) * 100
    $basket = ($dR + $lR) / 2
    $row = [ordered]@{ date = $d; CDMO_basket = [math]::Round($basket,1) }
    foreach ($k in $idx.Keys) {
        $benchR = ($idx[$k][$d] / $base[$k]) * 100
        $row["vs " + $k] = [math]::Round((100 * $basket / $benchR), 1)
    }
    [PSCustomObject]$row
}
$rows2 | Format-Table -AutoSize

# save full monthly series for a chart
$dates = $idx["Nifty 50"].Keys | Where-Object { $_ -ge "2016-12" } | Sort-Object
$out = foreach ($d in $dates) {
    $row = [ordered]@{ date = $d }
    foreach ($k in $idx.Keys) {
        if ($idx[$k].ContainsKey($d)) { $row[$k] = [math]::Round(($idx[$k][$d] / $base[$k]) * 100, 2) }
    }
    if ($divis.ContainsKey($d) -and $laurus.ContainsKey($d)) {
        $dR = ($divis[$d] / $divBase) * 100
        $lR = ($laurus[$d] / $lauBase) * 100
        $row["CDMO Basket"] = [math]::Round((($dR+$lR)/2), 2)
    }
    [PSCustomObject]$row
}
$outPath = Join-Path $PSScriptRoot "benchmark_compare_series.csv"
$out | Export-Csv -Path $outPath -NoTypeInformation -Encoding utf8
Write-Output "Wrote $($out.Count) rows to $outPath"

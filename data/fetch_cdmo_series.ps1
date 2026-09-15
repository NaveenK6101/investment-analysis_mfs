# Full monthly series (not just anchor points) for the CDMO chart, Dec 2016 - Sep 2026.
$ua = @{ "User-Agent" = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)" }

function Get-MonthlyCloses($symbol, $range) {
    $uri = "https://query1.finance.yahoo.com/v8/finance/chart/$symbol" + "?interval=1mo&range=$range"
    $r = Invoke-RestMethod -Uri $uri -Headers $ua -TimeoutSec 25
    $res = $r.chart.result[0]
    $ts = $res.timestamp; $close = $res.indicators.quote[0].close
    $out = @()
    for ($i = 0; $i -lt $ts.Count; $i++) {
        if ($null -ne $close[$i]) {
            $out += [PSCustomObject]@{
                date  = ([datetimeoffset]::FromUnixTimeSeconds($ts[$i])).ToString("yyyy-MM")
                close = [double]$close[$i]
            }
        }
    }
    return $out
}

$divis  = Get-MonthlyCloses "DIVISLAB.NS" "10y"
$laurus = Get-MonthlyCloses "LAURUSLABS.NS" "10y"
$pharma = Get-MonthlyCloses "^CNXPHARMA" "10y"

$divMap = @{}; foreach ($p in $divis)  { $divMap[$p.date]  = $p.close }
$lauMap = @{}; foreach ($p in $laurus) { $lauMap[$p.date]  = $p.close }
$phMap  = @{}; foreach ($p in $pharma) { $phMap[$p.date]   = $p.close }

$start = "2016-12"
$divBase = $divMap[$start]; $lauBase = $lauMap[$start]; $phBase = $phMap[$start]

$dates = $laurus.date | Where-Object { $_ -ge $start } | Sort-Object

$rows = foreach ($d in $dates) {
    if ($divMap.ContainsKey($d) -and $lauMap.ContainsKey($d) -and $phMap.ContainsKey($d)) {
        $dR = ($divMap[$d] / $divBase) * 100
        $lR = ($lauMap[$d] / $lauBase) * 100
        $basket = ($dR + $lR) / 2
        $phR = ($phMap[$d] / $phBase) * 100
        $rel = 100 * $basket / $phR
        [PSCustomObject]@{
            date          = $d
            divis_price   = $divMap[$d]
            laurus_price  = $lauMap[$d]
            pharma_index  = $phMap[$d]
            divis_reb     = [math]::Round($dR, 2)
            laurus_reb    = [math]::Round($lR, 2)
            cdmo_basket   = [math]::Round($basket, 2)
            pharma_reb    = [math]::Round($phR, 2)
            relative      = [math]::Round($rel, 2)
        }
    }
}

$outPath = Join-Path $PSScriptRoot "cdmo_vs_pharma_series.csv"
$rows | Export-Csv -Path $outPath -NoTypeInformation -Encoding utf8
Write-Output "Wrote $($rows.Count) monthly rows to $outPath"
$rows | Select-Object -First 3 | Format-Table -AutoSize
$rows | Select-Object -Last 3 | Format-Table -AutoSize

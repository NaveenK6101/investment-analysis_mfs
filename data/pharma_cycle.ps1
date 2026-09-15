# Where is pharma in its cycle? Pull index history and compute relative performance
# vs the broad market, plus drawdowns, so the answer rests on data not vibes.

$ua = @{ "User-Agent" = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)" }

$symbols = @{
    "Nifty Pharma"     = "^CNXPHARMA"
    "Nifty Healthcare" = "NIFTY_HEALTHCARE.NS"
    "Nifty 50"         = "^NSEI"
    "Nifty Smallcap"   = "^CNXSC"
}

$series = @{}

foreach ($name in $symbols.Keys) {
    $s = $symbols[$name]
    try {
        $uri = "https://query1.finance.yahoo.com/v8/finance/chart/$s" + "?interval=1mo&range=10y"
        $r = Invoke-RestMethod -Uri $uri -Headers $ua -TimeoutSec 30
        $res = $r.chart.result[0]
        $ts = $res.timestamp
        $close = $res.indicators.quote[0].close

        $pts = @()
        for ($i = 0; $i -lt $ts.Count; $i++) {
            if ($null -ne $close[$i]) {
                $pts += [PSCustomObject]@{
                    date  = ([datetimeoffset]::FromUnixTimeSeconds($ts[$i])).ToString("yyyy-MM")
                    close = [double]$close[$i]
                }
            }
        }
        $series[$name] = $pts
        Write-Output "$name ($s): $($pts.Count) monthly points, $($pts[0].date) -> $($pts[-1].date), last=$([math]::Round($pts[-1].close,1))"
    } catch {
        Write-Output "$name ($s): FAILED - $($_.Exception.Message)"
    }
}

Write-Output ""
Write-Output "=== Trailing returns (%, price only) ==="
$rows = @()
foreach ($name in $series.Keys) {
    $p = $series[$name]
    $last = $p[-1].close
    function RetN($months) {
        if ($p.Count -gt $months) {
            $past = $p[$p.Count - 1 - $months].close
            return [math]::Round((($last / $past) - 1) * 100, 1)
        }
        return $null
    }
    $rows += [PSCustomObject]@{
        index  = $name
        "1Y"   = RetN 12
        "2Y"   = RetN 24
        "3Y"   = RetN 36
        "5Y"   = RetN 60
        "10Y"  = RetN 119
    }
}
$rows | Format-Table -AutoSize

Write-Output "=== Drawdown from all-time high, and date of that high ==="
foreach ($name in $series.Keys) {
    $p = $series[$name]
    $peak = ($p | Measure-Object -Property close -Maximum).Maximum
    $peakPt = $p | Where-Object { $_.close -eq $peak } | Select-Object -First 1
    $last = $p[-1].close
    $dd = [math]::Round((($last / $peak) - 1) * 100, 1)
    Write-Output ("{0,-18} peak {1,10:N0} in {2}   now {3,10:N0}   drawdown {4}%" -f $name, $peak, $peakPt.date, $last, $dd)
}

# Pharma relative to Nifty - the line that actually defines a "theme"
if ($series.ContainsKey("Nifty Pharma") -and $series.ContainsKey("Nifty 50")) {
    Write-Output ""
    Write-Output "=== Nifty Pharma RELATIVE to Nifty 50 (ratio, rebased 100 at start) ==="
    $ph = $series["Nifty Pharma"]; $ni = $series["Nifty 50"]
    $map = @{}
    foreach ($x in $ni) { $map[$x.date] = $x.close }
    $base = $null
    $out = @()
    foreach ($x in $ph) {
        if ($map.ContainsKey($x.date)) {
            $ratio = $x.close / $map[$x.date]
            if ($null -eq $base) { $base = $ratio }
            $out += [PSCustomObject]@{ date = $x.date; rel = [math]::Round(($ratio / $base) * 100, 1) }
        }
    }
    # print roughly every 6 months so the shape is visible
    for ($i = 0; $i -lt $out.Count; $i += 6) {
        Write-Output ("  {0}  {1,7}" -f $out[$i].date, $out[$i].rel)
    }
    Write-Output ("  {0}  {1,7}  <- latest" -f $out[-1].date, $out[-1].rel)
    $relPeak = ($out | Measure-Object -Property rel -Maximum).Maximum
    $relPeakPt = $out | Where-Object { $_.rel -eq $relPeak } | Select-Object -First 1
    Write-Output ("  relative peak {0} in {1}; now {2} ({3}% off the relative peak)" -f `
        $relPeak, $relPeakPt.date, $out[-1].rel, [math]::Round((($out[-1].rel / $relPeak) - 1) * 100, 1))
}

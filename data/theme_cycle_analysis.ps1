# Same 3-step method as the pharma analysis, applied to two more themes:
#   - Data centers / AI infra capex (post-2025 theme, per Naveen's list)
#   - Railways (suspected exhausted, per Naveen's read)
#
# Neither has an official Nifty sector index, so step 1 builds a custom
# equal-weighted basket index first (rebase each stock to 100 at the common
# start date, average across the basket each month), then divides by Nifty 50
# the same way as the Pharma analysis.

$ua = @{ "User-Agent" = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)" }

$themes = @{
    "Railways" = @(
        @{ s="IRFC.NS";     n="IRFC" }
        @{ s="IRCTC.NS";    n="IRCTC" }
        @{ s="RVNL.NS";     n="RVNL" }
        @{ s="RAILTEL.NS";  n="RailTel" }
        @{ s="TITAGARH.NS"; n="Titagarh Rail" }
        @{ s="IRCON.NS";    n="Ircon Intl" }
        @{ s="RITES.NS";    n="RITES" }
        @{ s="JWL.NS";      n="Jupiter Wagons" }
        @{ s="BEML.NS";     n="BEML" }
    )
    "Data Center / AI Infra" = @(
        @{ s="NETWEB.NS";     n="Netweb Tech" }
        @{ s="SIFY.NS";       n="Sify Technologies" }
        @{ s="TECHNOE.NS";    n="Techno Electric" }
        @{ s="KEI.NS";        n="KEI Industries" }
        @{ s="POLYCAB.NS";    n="Polycab India" }
        @{ s="CGPOWER.NS";    n="CG Power" }
        @{ s="CUMMINSIND.NS"; n="Cummins India" }
        @{ s="BLUESTARCO.NS"; n="Blue Star" }
    )
}

function Get-MonthlyCloses($symbol, $range) {
    try {
        $uri = "https://query1.finance.yahoo.com/v8/finance/chart/$symbol" + "?interval=1mo&range=$range"
        $r = Invoke-RestMethod -Uri $uri -Headers $ua -TimeoutSec 25
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
        return $pts
    } catch {
        return @()
    }
}

# Nifty 50, for the relative-strength denominator
$nifty = Get-MonthlyCloses "^NSEI" "10y"
$niftyMap = @{}
foreach ($x in $nifty) { $niftyMap[$x.date] = $x.close }
Write-Output "Nifty 50: $($nifty.Count) months, $($nifty[0].date) to $($nifty[-1].date)"
Write-Output ""

foreach ($themeName in $themes.Keys) {
    Write-Output ("=" * 78)
    Write-Output "THEME: $themeName"
    Write-Output ("=" * 78)

    $stockSeries = @{}
    $rows = @()

    foreach ($u in $themes[$themeName]) {
        $pts = Get-MonthlyCloses $u.s "6y"
        if ($pts.Count -lt 6) {
            Write-Output "  $($u.n) ($($u.s)): fetch failed or too little history"
            continue
        }
        $stockSeries[$u.n] = $pts

        $c = $pts.close
        $last = $c[$c.Count - 1]
        $peak = ($c | Measure-Object -Maximum).Maximum
        $r1 = $null; $r3 = $null
        if ($c.Count -gt 12) { $r1 = [math]::Round((($last / $c[$c.Count - 13]) - 1) * 100, 0) }
        if ($c.Count -gt 36) { $r3 = [math]::Round((($last / $c[$c.Count - 37]) - 1) * 100, 0) }

        $rows += [PSCustomObject]@{
            stock    = $u.n
            hist_mo  = $pts.Count
            r1Y      = $r1
            r3Y      = $r3
            fromPeak = [math]::Round((($last / $peak) - 1) * 100, 0)
        }
        Start-Sleep -Milliseconds 150
    }

    Write-Output ""
    Write-Output "-- Stock level --"
    $rows | Sort-Object stock | Format-Table -AutoSize

    # ---- build the equal-weighted custom theme index ----
    # common start date = the latest "first month" among the basket (so every
    # stock has a value for every date used)
    $starts = $stockSeries.Values | ForEach-Object { $_[0].date }
    $commonStart = ($starts | Sort-Object -Descending)[0]
    Write-Output "Custom basket common start date: $commonStart (latest listing in the basket sets this)"

    $dateMaps = @{}
    foreach ($name in $stockSeries.Keys) {
        $m = @{}
        foreach ($p in $stockSeries[$name]) { $m[$p.date] = $p.close }
        $dateMaps[$name] = $m
    }
    $allDates = ($nifty | Where-Object { $_.date -ge $commonStart } | ForEach-Object { $_.date }) | Sort-Object

    $basketIndex = @()
    $baseVals = @{}
    foreach ($d in $allDates) {
        $relatives = @()
        foreach ($name in $dateMaps.Keys) {
            if ($dateMaps[$name].ContainsKey($d)) {
                if (-not $baseVals.ContainsKey($name)) { $baseVals[$name] = $dateMaps[$name][$d] }
                $relatives += ($dateMaps[$name][$d] / $baseVals[$name]) * 100
            }
        }
        if ($relatives.Count -gt 0) {
            $basketIndex += [PSCustomObject]@{ date = $d; level = ($relatives | Measure-Object -Average).Average }
        }
    }

    # relative strength: basket index level / Nifty50 level, both rebased to 100 at commonStart
    $niftyBaseVal = $niftyMap[$commonStart]
    Write-Output ""
    Write-Output "-- $themeName basket vs Nifty 50 (both rebased to 100 at $commonStart) --"
    $relBase = $null
    $relOut = @()
    foreach ($p in $basketIndex) {
        if ($niftyMap.ContainsKey($p.date)) {
            $niftyRebased = ($niftyMap[$p.date] / $niftyBaseVal) * 100
            $rel = $p.level / $niftyRebased * 100
            if ($null -eq $relBase) { $relBase = $rel }
            $relOut += [PSCustomObject]@{ date = $p.date; basket = [math]::Round($p.level,0); nifty = [math]::Round($niftyRebased,0); relative = [math]::Round(($rel/$relBase)*100, 1) }
        }
    }
    for ($i = 0; $i -lt $relOut.Count; $i += 3) {
        $r = $relOut[$i]
        Write-Output ("  {0}   basket={1,6}   nifty={2,6}   relative={3,7}" -f $r.date, $r.basket, $r.nifty, $r.relative)
    }
    if ($relOut.Count -gt 0) {
        $lastR = $relOut[-1]
        Write-Output ("  {0}   basket={1,6}   nifty={2,6}   relative={3,7}  <- latest" -f $lastR.date, $lastR.basket, $lastR.nifty, $lastR.relative)
        $peakRel = ($relOut | Measure-Object -Property relative -Maximum).Maximum
        $peakPt = $relOut | Where-Object { $_.relative -eq $peakRel } | Select-Object -First 1
        Write-Output ("  relative peak = $peakRel in $($peakPt.date); now $($lastR.relative), i.e. {0}% off that peak" -f [math]::Round((($lastR.relative/$peakRel)-1)*100,1))
    }
    Write-Output ""
}

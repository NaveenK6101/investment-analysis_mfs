# Live prices for the pharma/healthcare names held by TRUSTMF, Abakkus and Helios
# small cap funds. Yahoo's v7 quote and quoteSummary endpoints now return 401
# without a crumb, but the v8 chart endpoint still works unauthenticated.

$symbols = @(
    "LAURUSLABS.NS","SAILIFE.NS","ASTERDM.NS","SENORES.NS","GRANULES.NS",
    "NEULANDLAB.NS","RUBICON.NS","AMIORG.NS","KIMS.NS",
    "LALPATHLAB.NS","RAINBOW.NS","JUBLPHARMA.NS","DIVISLAB.NS","SANOFI.NS",
    "SANOFICONR.NS","APLLTD.NS","AETHER.NS",
    "PPLPHARMA.NS","GLAXO.NS","TORNTPHARM.NS","HCG.NS","NEPHROCARE.NS",
    "PARKMEDI.NS","GLS.NS","INDGN.NS","FORTIS.NS"
)

$ua = @{ "User-Agent" = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)" }
$rows = @()

foreach ($s in $symbols) {
    try {
        $uri = "https://query1.finance.yahoo.com/v8/finance/chart/$s" + "?interval=1d&range=5d"
        $r = Invoke-RestMethod -Uri $uri -Headers $ua -TimeoutSec 25
        $m = $r.chart.result[0].meta
        $rows += [PSCustomObject]@{
            symbol   = $s
            name     = $m.longName
            price    = $m.regularMarketPrice
            prevClose= $m.chartPreviousClose
            currency = $m.currency
            asOf     = ([datetimeoffset]::FromUnixTimeSeconds($m.regularMarketTime)).ToLocalTime().ToString("yyyy-MM-dd HH:mm")
        }
    } catch {
        $rows += [PSCustomObject]@{
            symbol = $s; name = "LOOKUP FAILED"; price = $null
            prevClose = $null; currency = $null; asOf = $null
        }
    }
    Start-Sleep -Milliseconds 200
}

$out = Join-Path $PSScriptRoot "pharma_quotes.csv"
$rows | Export-Csv -Path $out -NoTypeInformation -Encoding utf8
$rows | Format-Table -AutoSize

# Probe which Yahoo tickers actually return usable history, before promising
# anything. Tests: Nifty sector indices, India REITs, crypto, USD/INR.
$ua = @{ "User-Agent" = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)" }

$groups = [ordered]@{
  "NIFTY SECTOR INDICES" = @(
    "^CNXAUTO","^NSEBANK","^CNXFMCG","^CNXIT","^CNXMETAL","^CNXPHARMA",
    "^CNXREALTY","^CNXMEDIA","^CNXENERGY","^CNXINFRA","^CNXPSUBANK",
    "^CNXCONSUM","^CNXCMDT","^CNXSERVICE","^CNXFIN","NIFTY_HEALTHCARE.NS",
    "NIFTY_OIL_AND_GAS.NS","NIFTY_PVT_BANK.NS","NIFTY_CONSR_DURBL.NS"
  )
  "INDIA REITs / INVITs" = @(
    "EMBASSY.NS","MINDSPACE.NS","BIRET.NS","NXST.NS","IRBINVIT.NS","POWERGRID.NS"
  )
  "CRYPTO + FX" = @(
    "BTC-USD","ETH-USD","SOL-USD","XRP-USD","INR=X","USDINR=X"
  )
  "GLOBAL METALS (USD)" = @(
    "GC=F","SI=F"
  )
}

foreach ($g in $groups.Keys) {
  Write-Output ("=" * 72)
  Write-Output $g
  Write-Output ("=" * 72)
  foreach ($t in $groups[$g]) {
    try {
      $uri = "https://query1.finance.yahoo.com/v8/finance/chart/$t" + "?interval=1mo&range=10y"
      $r = Invoke-RestMethod -Uri $uri -Headers $ua -TimeoutSec 20
      $res = $r.chart.result[0]
      $n = ($res.timestamp | Measure-Object).Count
      $name = $res.meta.longName
      $cur  = $res.meta.currency
      $first = ([datetimeoffset]::FromUnixTimeSeconds($res.timestamp[0])).ToString("yyyy-MM")
      $last  = ([datetimeoffset]::FromUnixTimeSeconds($res.timestamp[-1])).ToString("yyyy-MM")
      Write-Output ("  {0,-22} OK  {1,4} mo  {2} -> {3}  [{4}] {5}" -f $t, $n, $first, $last, $cur, $name)
    } catch {
      Write-Output ("  {0,-22} FAILED" -f $t)
    }
    Start-Sleep -Milliseconds 120
  }
  Write-Output ""
}

# Adds a year-on-year projection cell for a plain Rs 10 lakh lumpsum, inserted
# straight after the SIP-vs-leveraged comparison table.

$nbPath = "C:\Users\Naveen\Desktop\Naveen_imp\investment\old-vahdam-files\leaveraged_inv_strategy.ipynb"
$nb = Get-Content -Raw $nbPath | ConvertFrom-Json

$yoyMarkdown = @'
### Year-on-year projection for a Rs 10 lakh lumpsum

The table above reports only the 15-year endpoint. This section tracks the same
posterior paths year by year, for the simplest possible case: **Rs 10,00,000
invested once at t=0, no SIP, no leverage** - so the funds are directly
comparable without any strategy effects mixed in.

`median_value` is the median across all posterior draws, so it already carries
both parameter uncertainty (how sure we are about each fund's true mean/vol) and
return uncertainty. The p05/p95 band is the honest spread, and it is wide - for
small caps over 15 years it spans a very large range. Funds marked
`low_confidence` (TRUSTMF, Helios, Abakkus) have only months of history, so
their bands are driven mostly by the prior rather than by data.
'@

$yoyCode = @'
# ============================================================
# Year-on-year: plain Rs 10 lakh lumpsum, no SIP, no leverage
# ============================================================
LUMPSUM = INITIAL_CAPITAL          # Rs 10,00,000
N_YEARS = TOTAL_MONTHS // 12       # 15

lumpsum_wealth = {}
yoy_rows = []

for k, asset_paths in fund_paths.items():
    # compound the monthly log returns: value_t = LUMPSUM * exp(cumsum(r))
    wealth = LUMPSUM * np.exp(np.cumsum(asset_paths, axis=1))   # (N draws, TOTAL_MONTHS)
    lumpsum_wealth[k] = wealth

    prev_median = float(LUMPSUM)
    for year in range(1, N_YEARS + 1):
        w = wealth[:, year * 12 - 1]
        cagr = (w / LUMPSUM) ** (1.0 / year) - 1.0
        median_value = float(np.median(w))

        yoy_rows.append({
            "fund": fund_display_name[k],
            "low_confidence": k in new_keys,
            "year": year,
            "median_value": median_value,
            "p05_value": float(np.percentile(w, 5)),
            "p95_value": float(np.percentile(w, 95)),
            "median_cagr": float(np.median(cagr)),
            "yoy_growth": median_value / prev_median - 1.0,   # growth of the median path
        })
        prev_median = median_value

yoy_df = pd.DataFrame(yoy_rows)

# order funds by their 15-year median outcome
fund_order = (
    yoy_df[yoy_df["year"] == N_YEARS]
    .sort_values("median_value", ascending=False)["fund"]
    .tolist()
)

print(f"Median value of a Rs {LUMPSUM:,.0f} lumpsum, in Rs lakh, by year")
print("(funds ordered by 15-year median; * = low confidence, only months of history)\n")

value_table = (
    yoy_df.pivot(index="fund", columns="year", values="median_value")
    .reindex(fund_order)
    .div(1e5)          # -> lakh
    .round(1)
)
value_table.index = [
    f"{f} *" if yoy_df.loc[yoy_df["fund"] == f, "low_confidence"].iloc[0] else f
    for f in value_table.index
]
value_table
'@

$cagrCode = @'
print("Median annualised return (CAGR) to date, %\n")

cagr_table = (
    yoy_df.pivot(index="fund", columns="year", values="median_cagr")
    .reindex(fund_order)
    .mul(100)
    .round(1)
)
cagr_table.index = value_table.index
display(cagr_table)

print("\n15-year summary for a Rs 10 lakh lumpsum:\n")
summary_15y = (
    yoy_df[yoy_df["year"] == N_YEARS]
    .set_index("fund")
    .reindex(fund_order)[["low_confidence", "median_value", "p05_value", "p95_value", "median_cagr"]]
    .assign(
        median_lakh=lambda d: (d["median_value"] / 1e5).round(1),
        p05_lakh=lambda d: (d["p05_value"] / 1e5).round(1),
        p95_lakh=lambda d: (d["p95_value"] / 1e5).round(1),
        median_cagr_pct=lambda d: (d["median_cagr"] * 100).round(1),
    )[["low_confidence", "median_lakh", "p05_lakh", "p95_lakh", "median_cagr_pct"]]
)
summary_15y
'@

$yoyPlotCode = @'
# Median lumpsum growth path per fund, with the p05-p95 band for context
n_funds = len(fund_paths)
ncols = 3
nrows = math.ceil(n_funds / ncols)

years = np.arange(1, N_YEARS + 1)
fig, axes = plt.subplots(nrows, ncols, figsize=(5.5 * ncols, 3.8 * nrows), squeeze=False, sharex=True)

for ax, k in zip(axes.flat, fund_paths):
    w = lumpsum_wealth[k][:, 11::12]                  # year-end months
    med = np.median(w, axis=0) / 1e5
    lo = np.percentile(w, 5, axis=0) / 1e5
    hi = np.percentile(w, 95, axis=0) / 1e5

    ax.plot(years, med, label="median", color="C0")
    ax.fill_between(years, lo, hi, alpha=0.2, color="C0", label="5-95 pct")
    ax.axhline(LUMPSUM / 1e5, color="grey", ls="--", lw=0.8)
    title = fund_display_name[k] + (" (LOW CONFIDENCE)" if k in new_keys else "")
    ax.set_title(title, fontsize=10)
    ax.set_xlabel("Year")
    ax.set_ylabel("Value (Rs lakh)")
    ax.set_yscale("log")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=7)

for ax in axes.flat[n_funds:]:
    ax.axis("off")

fig.suptitle(f"Rs {LUMPSUM/1e5:,.0f} lakh lumpsum: median growth with 5-95 percentile band (log scale)")
plt.tight_layout()
plt.show()
'@

function New-CodeCell([string]$src) {
    [PSCustomObject]@{
        cell_type       = "code"
        execution_count = $null
        metadata        = [PSCustomObject]@{}
        outputs         = @()
        source          = @($src)
    }
}
function New-MarkdownCell([string]$src) {
    [PSCustomObject]@{
        cell_type = "markdown"
        metadata  = [PSCustomObject]@{}
        source    = @($src)
    }
}

$insertAt = -1
for ($i = 0; $i -lt $nb.cells.Count; $i++) {
    $src = $nb.cells[$i].source -join ''
    if ($src.Contains('results_df = pd.DataFrame(rows).sort_values("median_irr_lev"')) {
        $insertAt = $i + 1
        Write-Output "Comparison table is cell $i; inserting YoY cells at $insertAt"
        break
    }
}
if ($insertAt -lt 0) { throw "Could not locate the comparison table cell" }

$newCells = @(
    (New-MarkdownCell $yoyMarkdown),
    (New-CodeCell $yoyCode),
    (New-CodeCell $cagrCode),
    (New-CodeCell $yoyPlotCode)
)

$nb.cells = @($nb.cells[0..($insertAt - 1)]) + @($newCells) + @($nb.cells[$insertAt..($nb.cells.Count - 1)])

Write-Output "New cell count: $($nb.cells.Count)"

$json = $nb | ConvertTo-Json -Depth 60
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($nbPath, $json, $utf8NoBom)

$check = Get-Content -Raw $nbPath | ConvertFrom-Json
Write-Output "Re-parsed OK. Cell count: $($check.cells.Count)"

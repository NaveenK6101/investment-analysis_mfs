# Two fixes needed to actually run the section end-to-end:
#
#  1. cores=1 on pm.sample. On Windows, PyMC's default multiprocessing backend
#     deadlocks / raises "attempt to start a new process before the current
#     process has finished its bootstrapping phase" when there is no __main__
#     guard. Chains run sequentially instead; the models are small so this is fast.
#
#  2. Vectorised wealth + IRR. The original scalar loops were ~34M Python-level
#     iterations for the wealth paths and ~192k scalar Newton solves over
#     181-element cashflow lists for the IRRs (billions of ops, hours of runtime).
#     The maths is unchanged - the loops now run over months with numpy handling
#     the draw dimension, and Newton's method iterates on whole arrays at once.

$nbPath = "C:\Users\Naveen\Desktop\Naveen_imp\investment\old-vahdam-files\leaveraged_inv_strategy.ipynb"
$nb = Get-Content -Raw $nbPath | ConvertFrom-Json

$newStrategyCell = @'
def emi_amount(principal, r, n):
    return principal * r * (1 + r) ** n / ((1 + r) ** n - 1)


emi = emi_amount(loan_amt, R_M, RELOAN_MONTHS)

# Fixed monthly cashflows the investor puts in, for t = 0 .. TOTAL_MONTHS-1.
# The terminal wealth is received at t = TOTAL_MONTHS and is appended per draw.
SIP_BASE_FLOWS = np.array([-INITIAL_CAPITAL] + [-emi] * (TOTAL_MONTHS - 1), dtype=float)
LEV_BASE_FLOWS = np.array(
    [-INITIAL_CAPITAL] + [(-loan_amt if t % RELOAN_MONTHS == 0 else 0.0) for t in range(1, TOTAL_MONTHS)],
    dtype=float,
)


def unleveraged_sip(paths_asset, emi):
    """Lumpsum at t=0, then a monthly SIP of `emi` from salary.

    Vectorised over posterior draws: the loop runs over months, numpy handles draws.
    """
    N, T = paths_asset.shape
    wealth = np.zeros((N, T))
    capital = np.zeros((N, T))

    growth = np.exp(paths_asset)
    w = np.full(N, float(INITIAL_CAPITAL))
    total_cap = float(INITIAL_CAPITAL)

    for t in range(T):
        w = w * growth[:, t] + emi
        total_cap += emi
        wealth[:, t] = w
        capital[:, t] = total_cap

    return wealth, capital


def self_leveraged_mf(paths_asset):
    """Pledge the corpus, take a fresh loan every RELOAN_MONTHS and invest it.

    EMI is serviced from salary, so it does not drag on the compounding corpus;
    only the cumulative *interest* paid is netted off wealth.
    """
    N, T = paths_asset.shape
    wealth = np.zeros((N, T))
    capital = np.zeros((N, T))

    growth = np.exp(paths_asset)
    emi_cycle = emi_amount(loan_amt, R_M, RELOAN_MONTHS)
    interest_per_cycle = emi_cycle * RELOAN_MONTHS - loan_amt

    invested = np.full(N, float(INITIAL_CAPITAL))
    total_cap = float(INITIAL_CAPITAL)
    total_interest_paid = 0.0

    for t in range(T):
        if t % RELOAN_MONTHS == 0:
            invested = invested + loan_amt
            total_cap += loan_amt
            total_interest_paid += interest_per_cycle

        invested = invested * growth[:, t]
        wealth[:, t] = invested - total_interest_paid
        capital[:, t] = total_cap

    return wealth, capital


def irr_newton_vec(final_wealth, base_flows, guess=0.01, tol=1e-8, max_iter=100):
    """Monthly IRR for many draws at once (Newton's method, vectorised).

    base_flows   : the fixed cashflows at t = 0 .. len(base_flows)-1 (same every draw)
    final_wealth : terminal wealth received at t = len(base_flows), one per draw

    Draws that fail to converge come back as nan, matching the scalar version.
    """
    base_flows = np.asarray(base_flows, dtype=float)
    final_wealth = np.asarray(final_wealth, dtype=float)

    t_base = np.arange(base_flows.size)
    t_final = base_flows.size
    rate = np.full(final_wealth.shape, float(guess))
    npv = np.full(final_wealth.shape, np.inf)

    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        for _ in range(max_iter):
            one_plus = 1.0 + rate

            npv = (base_flows[None, :] / one_plus[:, None] ** t_base[None, :]).sum(axis=1)
            npv = npv + final_wealth / one_plus ** t_final

            d_npv = (
                -(t_base[None, :] * base_flows[None, :]) / one_plus[:, None] ** (t_base[None, :] + 1)
            ).sum(axis=1)
            d_npv = d_npv - t_final * final_wealth / one_plus ** (t_final + 1)

            if np.nanmax(np.abs(npv)) < tol:
                break

            step = np.where(d_npv == 0, 0.0, npv / d_npv)
            step = np.where(np.isfinite(step), step, 0.0)
            # keep (1 + rate) strictly positive so the powers stay finite
            rate = np.clip(rate - step, -0.99, 10.0)

    return np.where(np.abs(npv) < 1e-4, rate, np.nan)


def annualise(monthly_rate):
    """Monthly IRR -> annualised IRR."""
    return (1 + monthly_rate) ** 12 - 1
'@

$newComparisonCell = @'
# Assemble a (N, TOTAL_MONTHS) path array per fund, regardless of which model produced it
fund_paths = {}
for i, k in enumerate(established_keys):
    fund_paths[k] = paths_established[:, :, i]
for k in new_keys:
    fund_paths[k] = paths_new[k]

rows = []
wealth_by_fund = {}  # cached for the plotting cell below

for k, asset_paths in fund_paths.items():
    w_sip, cap_sip = unleveraged_sip(asset_paths, emi)
    w_lev, cap_lev = self_leveraged_mf(asset_paths)
    wealth_by_fund[k] = {"sip": w_sip, "lev": w_lev, "cap_sip": cap_sip, "cap_lev": cap_lev}

    final_sip, final_lev = w_sip[:, -1], w_lev[:, -1]
    total_cap_sip, total_cap_lev = cap_sip[:, -1], cap_lev[:, -1]

    roic_sip = final_sip / total_cap_sip - 1
    roic_lev = final_lev / total_cap_lev - 1

    irr_sip_annual = annualise(irr_newton_vec(final_sip, SIP_BASE_FLOWS))
    irr_lev_annual = annualise(irr_newton_vec(final_lev, LEV_BASE_FLOWS))

    rows.append({
        "fund": fund_display_name[k],
        "low_confidence": k in new_keys,
        "months_of_history": fund_history_months[k],
        "p_lev_beats_sip": np.mean(final_lev > final_sip),
        "median_wealth_sip": np.median(final_sip),
        "median_wealth_lev": np.median(final_lev),
        "wealth_p05_lev": np.percentile(final_lev, 5),
        "wealth_p50_lev": np.percentile(final_lev, 50),
        "wealth_p95_lev": np.percentile(final_lev, 95),
        "median_roic_sip": np.median(roic_sip),
        "median_roic_lev": np.median(roic_lev),
        "median_irr_sip": np.nanmedian(irr_sip_annual),
        "median_irr_lev": np.nanmedian(irr_lev_annual),
        "irr_p05_lev": np.nanpercentile(irr_lev_annual, 5),
    })

results_df = pd.DataFrame(rows).sort_values("median_irr_lev", ascending=False).reset_index(drop=True)

pd.set_option("display.float_format", lambda v: f"{v:,.4f}")
results_df
'@

$newLtvCell = @'
def simulate_leveraged_wealth_for_ltv(paths_asset, ltv):
    """Terminal wealth under the self-leveraged strategy at an arbitrary LTV."""
    loan = ltv * INITIAL_CAPITAL
    emi_cycle = emi_amount(loan, R_M, RELOAN_MONTHS) if loan > 0 else 0.0
    interest_per_cycle = emi_cycle * RELOAN_MONTHS - loan

    N, T = paths_asset.shape
    growth = np.exp(paths_asset)
    invested = np.full(N, float(INITIAL_CAPITAL))
    total_interest = 0.0

    for t in range(T):
        if loan > 0 and t % RELOAN_MONTHS == 0:
            invested = invested + loan
            total_interest += interest_per_cycle
        invested = invested * growth[:, t]

    return invested - total_interest


def base_flows_for_ltv(ltv):
    loan = ltv * INITIAL_CAPITAL
    return np.array(
        [-INITIAL_CAPITAL] + [(-loan if (loan > 0 and t % RELOAN_MONTHS == 0) else 0.0)
                              for t in range(1, TOTAL_MONTHS)],
        dtype=float,
    )


LTV_grid = np.linspace(0, 1, 10)

ltv_results = {}
for k, asset_paths in fund_paths.items():
    rows = []
    for ltv in LTV_grid:
        final_w = simulate_leveraged_wealth_for_ltv(asset_paths, ltv)
        irr_annual = annualise(irr_newton_vec(final_w, base_flows_for_ltv(ltv)))
        rows.append([
            ltv,
            np.nanmedian(irr_annual),
            np.nanpercentile(irr_annual, 5),
            np.nanmean(irr_annual < 0),
        ])
    ltv_results[k] = np.array(rows)

n_funds = len(fund_paths)
ncols = 3
nrows = math.ceil(n_funds / ncols)

for col, title, ylabel in [(1, "Median Annual IRR vs LTV", "Median Annual IRR"),
                           (3, "P(IRR < 0) vs LTV", "Prob(IRR < 0)")]:
    fig, axes = plt.subplots(nrows, ncols, figsize=(5 * ncols, 3.5 * nrows), squeeze=False)
    for ax, k in zip(axes.flat, fund_paths):
        r = ltv_results[k]
        ax.plot(r[:, 0], r[:, col])
        fund_title = fund_display_name[k] + (" (LOW CONFIDENCE)" if k in new_keys else "")
        ax.set_title(fund_title, fontsize=10)
        ax.set_xlabel("LTV")
        ax.set_ylabel(ylabel)
        ax.grid(True)
    for ax in axes.flat[n_funds:]:
        ax.axis("off")
    fig.suptitle(title)
    plt.tight_layout()
    plt.show()
'@

$patched = @{ sampleJoint = 0; sampleNew = 0; strategy = 0; comparison = 0; ltv = 0 }

for ($i = 0; $i -lt $nb.cells.Count; $i++) {
    $src = $nb.cells[$i].source -join ''
    $orig = $src

    if ($src.Contains('with build_mv_normal_model(mf_log_return) as mf_model:')) {
        $src = $src.Replace(
            'mf_trace = pm.sample(draws=2000, tune=2000, chains=4, target_accept=0.9, random_seed=42)',
            'mf_trace = pm.sample(draws=2000, tune=2000, chains=4, cores=1, target_accept=0.9, random_seed=42)')
        $patched.sampleJoint++
        Write-Output "cell $i : joint pm.sample -> cores=1"
    }

    if ($src.Contains('new_fund_traces = {}')) {
        $src = $src.Replace(
            'trace = pm.sample(draws=2000, tune=2000, chains=4, target_accept=0.95, random_seed=42)',
            'trace = pm.sample(draws=2000, tune=2000, chains=4, cores=1, target_accept=0.95, random_seed=42)')
        $patched.sampleNew++
        Write-Output "cell $i : new-fund pm.sample -> cores=1"
    }

    # NB: cell 39 (the original gold-loan section) also defines emi_amount, so
    # require self_leveraged_mf too - that only exists in the rebuilt MF section.
    if ($src.Contains('def emi_amount(principal, r, n):') -and $src.Contains('def self_leveraged_mf')) {
        $src = $newStrategyCell
        $patched.strategy++
        Write-Output "cell $i : replaced strategy/IRR cell with vectorised version"
    }

    if ($src.Contains('# Assemble a (N, TOTAL_MONTHS) path array per fund')) {
        $src = $newComparisonCell
        $patched.comparison++
        Write-Output "cell $i : replaced comparison cell"
    }

    if ($src.Contains('def simulate_leveraged_wealth_for_ltv')) {
        $src = $newLtvCell
        $patched.ltv++
        Write-Output "cell $i : replaced LTV sweep cell with vectorised version"
    }

    if ($src -ne $orig) { $nb.cells[$i].source = @($src) }
}

foreach ($key in $patched.Keys) {
    if ($patched[$key] -ne 1) { throw "Expected exactly 1 patch for '$key', got $($patched[$key])" }
}

$json = $nb | ConvertTo-Json -Depth 60
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($nbPath, $json, $utf8NoBom)

$check = Get-Content -Raw $nbPath | ConvertFrom-Json
Write-Output "Re-parsed OK. Cell count: $($check.cells.Count)"

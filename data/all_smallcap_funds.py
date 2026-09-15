# Final, hand-verified list of every currently open-ended, actively-managed
# "Equity Scheme - Small Cap Fund" (Direct Plan, Growth option) on mfapi.in.
#
# Excluded and why:
#   - Index funds / ETF FoFs / smart-beta (Nifty Smallcap 250 Index, Momentum
#     Quality, etc.) - passive trackers, not actively managed picks
#   - Mid+Small combo funds (JPMorgan Mid and Small, MidSmallcap400 products)
#     - different SEBI category
#   - Sundaram "Emerging Small Cap Series I-VII" and "Select Small Cap Series
#     II-VI" - closed-end/interval schemes, last NAV 2018-2023, not open for
#     investment today
#   - IDBI Small Cap Fund (141475) - stale since Jul 2023: IDBI MF's schemes
#     were merged into LIC Mutual Fund in 2023 (LIC MF Small Cap Fund, 152004,
#     is the live successor)
#   - Principal Small Cap Fund (147131) - stale since Dec 2021: Principal's
#     India AMC business was acquired by Sundaram Mutual Fund in 2021
#   - Duplicate Sundaram Small Cap Fund listing (119589, identical to 119588)
#   - HSBC: two old codes were dead ends (120077 is actually categorised as an
#     "Income"/debt scheme despite the name; 120069 stopped updating in Nov
#     2022). The live Direct Growth plan is 151130 (confirmed against Groww's
#     quoted NAV, Rs 103.51 on 2026-09-11, matching 151130 exactly).

ALL_SMALLCAP_FUNDS = [
    {"key": "abakkus_small",   "code": 154215, "name": "Abakkus Small Cap"},
    {"key": "adityabirla_small","code": 119556, "name": "Aditya Birla Sun Life Small Cap"},
    {"key": "axis_small",      "code": 125354, "name": "Axis Small Cap"},
    {"key": "bandhan_small",   "code": 147946, "name": "Bandhan Small Cap"},
    {"key": "boi_small",       "code": 145678, "name": "Bank of India Small Cap"},
    {"key": "bajaj_small",     "code": 153612, "name": "Bajaj Finserv Small Cap"},
    {"key": "barodabnp_small", "code": 152128, "name": "Baroda BNP Paribas Small Cap"},
    {"key": "canara_small",    "code": 146130, "name": "Canara Robeco Small Cap"},
    {"key": "dsp_small",       "code": 119212, "name": "DSP Small Cap"},
    {"key": "edelweiss_small", "code": 146196, "name": "Edelweiss Small Cap"},
    {"key": "franklin_small",  "code": 118525, "name": "Franklin India Small Cap"},
    {"key": "groww_small",     "code": 154063, "name": "Groww Small Cap"},
    {"key": "hdfc_small",      "code": 130503, "name": "HDFC Small Cap"},
    {"key": "hsbc_small",      "code": 151130, "name": "HSBC Small Cap"},
    {"key": "helios_small",    "code": 153912, "name": "Helios Small Cap"},
    {"key": "icici_small",     "code": 120591, "name": "ICICI Prudential Small Cap"},
    {"key": "iti_small",       "code": 147919, "name": "ITI Small Cap"},
    {"key": "invesco_small",   "code": 145137, "name": "Invesco India Small Cap"},
    {"key": "jm_small",        "code": 152614, "name": "JM Small Cap"},
    {"key": "kotak_small",     "code": 120164, "name": "Kotak Small Cap"},
    {"key": "lic_small",       "code": 152004, "name": "LIC MF Small Cap"},
    {"key": "mahindra_small",  "code": 150915, "name": "Mahindra Manulife Small Cap"},
    {"key": "mirae_small",     "code": 153196, "name": "Mirae Asset Small Cap"},
    {"key": "motilal_small",   "code": 152237, "name": "Motilal Oswal Small Cap"},
    {"key": "nippon_small",    "code": 118778, "name": "Nippon India Small Cap"},
    {"key": "pgim_small",      "code": 149019, "name": "PGIM India Small Cap"},
    {"key": "quantum_small",   "code": 152107, "name": "Quantum Small Cap"},
    {"key": "quant_small",     "code": 120828, "name": "Quant Small Cap"},
    {"key": "sbi_small",       "code": 125497, "name": "SBI Small Cap"},
    {"key": "samco_small",     "code": 153868, "name": "Samco Small Cap"},
    {"key": "sundaram_small",  "code": 119588, "name": "Sundaram Small Cap"},
    {"key": "trustmf_small",   "code": 152939, "name": "TRUSTMF Small Cap"},
    {"key": "tata_small",      "code": 145206, "name": "Tata Small Cap"},
    {"key": "wealthco_small",  "code": 154269, "name": "The Wealth Company Small Cap"},
    {"key": "uti_small",       "code": 148618, "name": "UTI Small Cap"},
    {"key": "union_small",     "code": 129649, "name": "Union Small Cap"},
]

if __name__ == "__main__":
    print(f"{len(ALL_SMALLCAP_FUNDS)} funds")

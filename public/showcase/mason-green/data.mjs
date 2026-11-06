export const rows = [
  [
    "Plantéa Skin",
    "September 2026",
    "",
    "",
    "",
    ""
  ],
  [
    "Metric",
    "Target",
    "Actual",
    "Variance",
    "Status",
    "Evidence / assumptions"
  ],
  [
    "Revenue (USD)",
    "",
    "Not publicly reported",
    "",
    "Awaiting input",
    "Needs company records and an approved target"
  ],
  [
    "Sales orders",
    "",
    "Not publicly reported",
    "",
    "Awaiting input",
    "Needs company records and an approved target"
  ],
  [
    "Conversion rate (fraction)",
    "0,026",
    "Not publicly reported",
    "",
    "Awaiting input",
    "Proposed target from industry benchmark, not company performance: https://www.littledata.io/benchmarks/beauty?utm_source=openai · 90 days from Aug 3 – Oct 31, 2026; figures generated Nov 4, 2026"
  ],
  [
    "Average order value (USD)",
    "70",
    "Not publicly reported",
    "",
    "Awaiting input",
    "Proposed target from industry benchmark, not company performance: https://www.littledata.io/benchmarks/beauty?utm_source=openai · 90 days from Aug 3 – Oct 31, 2026; figures generated Nov 4, 2026"
  ],
  [
    "",
    "",
    "",
    "",
    "",
    ""
  ],
  [
    "Public benchmarks",
    "Value",
    "Unit",
    "Evidence period",
    "Population",
    "Source URL"
  ],
  [
    "conversion_rate",
    "0,026",
    "fraction",
    "90 days from Aug 3 – Oct 31, 2026; figures generated Nov 4, 2026",
    "Beauty & skincare stores on Shopify",
    "https://www.littledata.io/benchmarks/beauty?utm_source=openai"
  ],
  [
    "aov",
    "70",
    "USD",
    "90 days from Aug 3 – Oct 31, 2026; figures generated Nov 4, 2026",
    "Beauty & skincare stores on Shopify",
    "https://www.littledata.io/benchmarks/beauty?utm_source=openai"
  ],
  [
    "",
    "",
    "",
    "",
    "",
    ""
  ],
  [
    "Calculated scenario — not actual performance",
    "Value",
    "Assumption",
    "",
    "",
    ""
  ],
  [
    "Illustrative website sessions",
    "1000",
    "Scenario basis, not a company traffic estimate",
    "",
    "",
    ""
  ],
  [
    "Expected orders",
    "26",
    "Sessions × sourced benchmark conversion rate",
    "",
    "",
    ""
  ],
  [
    "Expected revenue (USD)",
    "1820",
    "Expected orders × sourced benchmark AOV; benchmark periods may differ",
    "",
    "",
    ""
  ],
  [
    "",
    "",
    "",
    "",
    "",
    ""
  ],
  [
    "Company comparison",
    "Plantéa Skin",
    "dermalogica.com",
    "bskincaretx.com",
    "",
    ""
  ],
  [
    "Comparable product",
    "Nourishing Serum",
    "Not publicly reported",
    "Ceramide Fortifying Serum",
    "",
    ""
  ],
  [
    "Observed product price — current, not September actual",
    "$70",
    "Not publicly reported",
    "$41.99",
    "",
    ""
  ],
  [
    "Size",
    "Not publicly reported",
    "Not publicly reported",
    "Not publicly reported",
    "",
    ""
  ],
  [
    "Positioning",
    "Cactus Based & Texas Made; nourishing serum",
    "Not publicly reported",
    "Natural skincare serum",
    "",
    ""
  ],
  [
    "Product source",
    "https://planteaskin.com/",
    "Not publicly reported",
    "https://www.bskincaretx.com/shop?utm_source=openai",
    "",
    ""
  ],
  [
    "",
    "",
    "",
    "",
    "",
    ""
  ],
  [
    "Limitations",
    "",
    "",
    "",
    "",
    ""
  ],
  [
    "September 2026 company-reported actual revenue, sales, and conversion for Plantéa Skin are not publicly reported in the provided evidence.",
    "",
    "",
    "",
    "",
    ""
  ],
  [
    "Dermalogica source access was denied, so no comparable September 2026 product, revenue, sales, or conversion actuals could be extracted.",
    "",
    "",
    "",
    "",
    ""
  ],
  [
    "The benchmark evidence is for beauty and skincare stores on Shopify across 90 days from Aug 3 – Oct 31, 2026, not specifically for September 2026 and not for the named companies.",
    "",
    "",
    "",
    "",
    ""
  ],
  [
    "No publicly reported traffic, orders, or revenue were provided for Plantéa Skin or dermalogica.com; do not infer private sales or traffic.",
    "",
    "",
    "",
    "",
    ""
  ],
  [
    "Product price evidence is not the same as average order value; it is included only as product pricing evidence.",
    "",
    "",
    "",
    "",
    ""
  ],
  [
    "Public prices reflect the retrieval date. Benchmarks and calculated scenarios are not company-reported September performance.",
    "",
    "",
    "",
    "",
    ""
  ],
  [
    "",
    "",
    "",
    "",
    "",
    ""
  ],
  [
    "Sources",
    "URL",
    "Dashboard prepared (UTC)",
    "",
    "",
    ""
  ],
  [
    "Plantéa Skin source",
    "https://planteaskin.com/",
    "2026-11-05T20:35:06.653892+00:00",
    "",
    "",
    ""
  ],
  [
    "Dermalogica source",
    "https://errors.edgesuite.net/18.7071002.1793910872.74248932",
    "2026-11-05T20:35:06.653892+00:00",
    "",
    "",
    ""
  ],
  [
    "Dermalogica source",
    "https://www.unilever.com/brands/beauty-wellbeing/dermalogica/?utm_source=openai",
    "2026-11-05T20:35:06.653892+00:00",
    "",
    "",
    ""
  ],
  [
    "B Skincare TX source",
    "https://www.bskincaretx.com/shop?utm_source=openai",
    "2026-11-05T20:35:06.653892+00:00",
    "",
    "",
    ""
  ],
  [
    "Benchmark source",
    "https://www.littledata.io/benchmarks/beauty?utm_source=openai",
    "2026-11-05T20:35:06.653892+00:00",
    "",
    "",
    ""
  ]
];

export const retryPrompt = "Create a simple KPI dashboard in a new Google Sheets workbook for Plantéa Skin Nourishing Serum in Texas, compared with dermalogica.com and bskincaretx.com. Reporting period: September 2026.\n\nResearch public sources before writing. Include the business name, reporting period, revenue, sales orders, conversion rate, average order value, target, actual, variance/status and source links. Keep company-reported actuals, public product prices, industry benchmarks and illustrative scenarios clearly separate. Use “Not publicly reported” or blank when evidence is missing; never fill unavailable figures with zero or invent company performance. State the evidence dates and any blocked sources.\n\nKeep the layout clean. Use Claude for the draft if it is available and selected in my account; otherwise clearly explain which drafting tool is available before proceeding. Reuse my existing Google Sheets connection. Create a new workbook in my own selected Google account, read the saved cells back, and show the main sheet result first in AURA with other tool outputs in dropdowns and a link to open the workbook.";
export const originalSheet = "https://docs.google.com/spreadsheets/d/1ZbIPkLIxbA-iyrEvDXcBRU4lagOYfbHCtEX7nj3K_Cc/edit#gid=1166718734&range=A1%3AG37";

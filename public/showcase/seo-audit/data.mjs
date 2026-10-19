// Anonymized real crawl + explicitly simulated research. No backend or customer CSV attachments.
export default {
  "version": 1,
  "client": "Texas auto finance client",
  "website": "https://client.example/",
  "anonymized": true,
  "backend": false,
  "scenarioDate": "2026-10-19",
  "crawl": {
    "source_tool": "Screaming Frog",
    "mode": "supplied_export",
    "website": "https://client.example/",
    "summary": "Analyzed 171 crawl URL records inside AURA; found 82 canonical/redirect conflicts.",
    "files": [
      {
        "filename": "internal_all.csv",
        "sha256": "b04e4d1294d7a16bd6541097384e7718e99e6cead1d560ed6e98e1f8a4a361ec",
        "rows": 171,
        "columns": 72,
        "kind": "internal_url_inventory",
        "duplicate_of": null
      },
      {
        "filename": "allinlinks.csv",
        "sha256": "b04e4d1294d7a16bd6541097384e7718e99e6cead1d560ed6e98e1f8a4a361ec",
        "rows": 171,
        "columns": 72,
        "kind": "internal_url_inventory",
        "duplicate_of": "internal_all.csv"
      },
      {
        "filename": "url_all.csv",
        "sha256": "77e64986914eb9e2518ed5076ac7c53c5ce65cc9822bb4a2ab38db092742b195",
        "rows": 171,
        "columns": 10,
        "kind": "internal_url_inventory",
        "duplicate_of": null
      }
    ],
    "counts": {
      "url_records": 171,
      "unique_comparison_urls": 171,
      "http_status": {
        "200": 87,
        "307": 84
      },
      "html_200": 86,
      "indexable_html": 4,
      "canonical_conflicts": 82,
      "link_edge_rows": 0
    },
    "crawl_period": {
      "first_raw": "2026-10-18 22:16:36",
      "last_raw": "2026-10-18 22:16:40",
      "timezone": "Not supplied",
      "export_created_at": "Not supplied"
    },
    "warnings": [
      "allinlinks.csv is byte-identical to internal_all.csv; counted once.",
      "Detailed link edges are missing. Aggregate Inlinks are occurrences, not unique source pages; orphan pages cannot be inferred."
    ],
    "issues": [
      {
        "id": "T01",
        "group": "Technical SEO",
        "priority": "P1",
        "state": "Observed",
        "title": "Resolve canonical URLs that redirect back to the declaring 200 URL",
        "affected": [
          {
            "url": "https://client.example/sms-terms",
            "csv_row": 8,
            "canonical": "https://client.example/sms-terms.html",
            "canonical_csv_row": 7,
            "canonical_status": "307",
            "redirect_to": "https://client.example/sms-terms"
          },
          {
            "url": "https://client.example/privacy",
            "csv_row": 9,
            "canonical": "https://client.example/privacy.html",
            "canonical_csv_row": 6,
            "canonical_status": "307",
            "redirect_to": "https://client.example/privacy"
          },
          {
            "url": "https://client.example/articles/title-loan-gps-tracker-kill-switch",
            "csv_row": 51,
            "canonical": "https://client.example/articles/title-loan-gps-tracker-kill-switch.html",
            "canonical_csv_row": 49,
            "canonical_status": "307",
            "redirect_to": "https://client.example/articles/title-loan-gps-tracker-kill-switch"
          },
          {
            "url": "https://client.example/articles/how-to-negotiate-with-title-loan-lender",
            "csv_row": 52,
            "canonical": "https://client.example/articles/how-to-negotiate-with-title-loan-lender.html",
            "canonical_csv_row": 47,
            "canonical_status": "307",
            "redirect_to": "https://client.example/articles/how-to-negotiate-with-title-loan-lender"
          },
          {
            "url": "https://client.example/articles/military-title-loan-illegal",
            "csv_row": 54,
            "canonical": "https://client.example/articles/military-title-loan-illegal.html",
            "canonical_csv_row": 48,
            "canonical_status": "307",
            "redirect_to": "https://client.example/articles/military-title-loan-illegal"
          },
          {
            "url": "https://client.example/articles/title-loan-calling-my-job-references",
            "csv_row": 94,
            "canonical": "https://client.example/articles/title-loan-calling-my-job-references.html",
            "canonical_csv_row": 46,
            "canonical_status": "307",
            "redirect_to": "https://client.example/articles/title-loan-calling-my-job-references"
          },
          {
            "url": "https://client.example/articles/title-loan-junk-fees-add-ons",
            "csv_row": 95,
            "canonical": "https://client.example/articles/title-loan-junk-fees-add-ons.html",
            "canonical_csv_row": 45,
            "canonical_status": "307",
            "redirect_to": "https://client.example/articles/title-loan-junk-fees-add-ons"
          },
          {
            "url": "https://client.example/articles/stuck-with-multiple-title-loans",
            "csv_row": 96,
            "canonical": "https://client.example/articles/stuck-with-multiple-title-loans.html",
            "canonical_csv_row": 44,
            "canonical_status": "307",
            "redirect_to": "https://client.example/articles/stuck-with-multiple-title-loans"
          },
          {
            "url": "https://client.example/articles/pay-down-title-loan-principal",
            "csv_row": 97,
            "canonical": "https://client.example/articles/pay-down-title-loan-principal.html",
            "canonical_csv_row": 43,
            "canonical_status": "307",
            "redirect_to": "https://client.example/articles/pay-down-title-loan-principal"
          },
          {
            "url": "https://client.example/articles/title-loan-and-bankruptcy",
            "csv_row": 98,
            "canonical": "https://client.example/articles/title-loan-and-bankruptcy.html",
            "canonical_csv_row": 42,
            "canonical_status": "307",
            "redirect_to": "https://client.example/articles/title-loan-and-bankruptcy"
          },
          {
            "url": "https://client.example/articles/cant-pay-title-loan-this-week",
            "csv_row": 99,
            "canonical": "https://client.example/articles/cant-pay-title-loan-this-week.html",
            "canonical_csv_row": 41,
            "canonical_status": "307",
            "redirect_to": "https://client.example/articles/cant-pay-title-loan-this-week"
          },
          {
            "url": "https://client.example/articles/title-loan-collections-deficiency",
            "csv_row": 100,
            "canonical": "https://client.example/articles/title-loan-collections-deficiency.html",
            "canonical_csv_row": 39,
            "canonical_status": "307",
            "redirect_to": "https://client.example/articles/title-loan-collections-deficiency"
          },
          {
            "url": "https://client.example/articles/hiding-car-from-title-loan-repo",
            "csv_row": 101,
            "canonical": "https://client.example/articles/hiding-car-from-title-loan-repo.html",
            "canonical_csv_row": 40,
            "canonical_status": "307",
            "redirect_to": "https://client.example/articles/hiding-car-from-title-loan-repo"
          },
          {
            "url": "https://client.example/articles/do-title-loans-affect-credit",
            "csv_row": 102,
            "canonical": "https://client.example/articles/do-title-loans-affect-credit.html",
            "canonical_csv_row": 38,
            "canonical_status": "307",
            "redirect_to": "https://client.example/articles/do-title-loans-affect-credit"
          },
          {
            "url": "https://client.example/articles/title-loan-buyout-process-step-by-step",
            "csv_row": 103,
            "canonical": "https://client.example/articles/title-loan-buyout-process-step-by-step.html",
            "canonical_csv_row": 37,
            "canonical_status": "307",
            "redirect_to": "https://client.example/articles/title-loan-buyout-process-step-by-step"
          },
          {
            "url": "https://client.example/articles/title-loan-refinance-buyout",
            "csv_row": 104,
            "canonical": "https://client.example/articles/title-loan-refinance-buyout.html",
            "canonical_csv_row": 36,
            "canonical_status": "307",
            "redirect_to": "https://client.example/articles/title-loan-refinance-buyout"
          },
          {
            "url": "https://client.example/articles/do-i-qualify-to-refinance-title-loan",
            "csv_row": 105,
            "canonical": "https://client.example/articles/do-i-qualify-to-refinance-title-loan.html",
            "canonical_csv_row": 35,
            "canonical_status": "307",
            "redirect_to": "https://client.example/articles/do-i-qualify-to-refinance-title-loan"
          },
          {
            "url": "https://client.example/articles/title-loan-refinance-lower-monthly-payment",
            "csv_row": 106,
            "canonical": "https://client.example/articles/title-loan-refinance-lower-monthly-payment.html",
            "canonical_csv_row": 34,
            "canonical_status": "307",
            "redirect_to": "https://client.example/articles/title-loan-refinance-lower-monthly-payment"
          },
          {
            "url": "https://client.example/articles/sell-car-with-title-loan",
            "csv_row": 107,
            "canonical": "https://client.example/articles/sell-car-with-title-loan.html",
            "canonical_csv_row": 33,
            "canonical_status": "307",
            "redirect_to": "https://client.example/articles/sell-car-with-title-loan"
          },
          {
            "url": "https://client.example/articles/being-sued-by-title-loan-company",
            "csv_row": 108,
            "canonical": "https://client.example/articles/being-sued-by-title-loan-company.html",
            "canonical_csv_row": 32,
            "canonical_status": "307",
            "redirect_to": "https://client.example/articles/being-sued-by-title-loan-company"
          },
          {
            "url": "https://client.example/articles/cosigned-title-loan-for-someone",
            "csv_row": 109,
            "canonical": "https://client.example/articles/cosigned-title-loan-for-someone.html",
            "canonical_csv_row": 31,
            "canonical_status": "307",
            "redirect_to": "https://client.example/articles/cosigned-title-loan-for-someone"
          },
          {
            "url": "https://client.example/articles/refinance-title-loan-now-vs-keep-paying",
            "csv_row": 110,
            "canonical": "https://client.example/articles/refinance-title-loan-now-vs-keep-paying.html",
            "canonical_csv_row": 30,
            "canonical_status": "307",
            "redirect_to": "https://client.example/articles/refinance-title-loan-now-vs-keep-paying"
          },
          {
            "url": "https://client.example/articles/why-title-loan-balance-never-goes-down",
            "csv_row": 111,
            "canonical": "https://client.example/articles/why-title-loan-balance-never-goes-down.html",
            "canonical_csv_row": 27,
            "canonical_status": "307",
            "redirect_to": "https://client.example/articles/why-title-loan-balance-never-goes-down"
          },
          {
            "url": "https://client.example/articles/behind-on-title-loan-repossession",
            "csv_row": 112,
            "canonical": "https://client.example/articles/behind-on-title-loan-repossession.html",
            "canonical_csv_row": 28,
            "canonical_status": "307",
            "redirect_to": "https://client.example/articles/behind-on-title-loan-repossession"
          },
          {
            "url": "https://client.example/articles/is-my-title-loan-legal",
            "csv_row": 113,
            "canonical": "https://client.example/articles/is-my-title-loan-legal.html",
            "canonical_csv_row": 26,
            "canonical_status": "307",
            "redirect_to": "https://client.example/articles/is-my-title-loan-legal"
          },
          {
            "url": "https://client.example/articles/can-they-take-my-car-title-loan",
            "csv_row": 114,
            "canonical": "https://client.example/articles/can-they-take-my-car-title-loan.html",
            "canonical_csv_row": 29,
            "canonical_status": "307",
            "redirect_to": "https://client.example/articles/can-they-take-my-car-title-loan"
          },
          {
            "url": "https://client.example/articles/should-i-let-them-take-the-car",
            "csv_row": 115,
            "canonical": "https://client.example/articles/should-i-let-them-take-the-car.html",
            "canonical_csv_row": 25,
            "canonical_status": "307",
            "redirect_to": "https://client.example/articles/should-i-let-them-take-the-car"
          },
          {
            "url": "https://client.example/articles/title-loan-renewal-cycle",
            "csv_row": 116,
            "canonical": "https://client.example/articles/title-loan-renewal-cycle.html",
            "canonical_csv_row": 24,
            "canonical_status": "307",
            "redirect_to": "https://client.example/articles/title-loan-renewal-cycle"
          },
          {
            "url": "https://client.example/articles/title-loan-vs-payday-vs-personal-loan",
            "csv_row": 117,
            "canonical": "https://client.example/articles/title-loan-vs-payday-vs-personal-loan.html",
            "canonical_csv_row": 23,
            "canonical_status": "307",
            "redirect_to": "https://client.example/articles/title-loan-vs-payday-vs-personal-loan"
          },
          {
            "url": "https://client.example/articles/get-car-title-back-after-payoff",
            "csv_row": 118,
            "canonical": "https://client.example/articles/get-car-title-back-after-payoff.html",
            "canonical_csv_row": 21,
            "canonical_status": "307",
            "redirect_to": "https://client.example/articles/get-car-title-back-after-payoff"
          },
          {
            "url": "https://client.example/articles/how-much-can-i-save-refinancing-title-loan",
            "csv_row": 119,
            "canonical": "https://client.example/articles/how-much-can-i-save-refinancing-title-loan.html",
            "canonical_csv_row": 22,
            "canonical_status": "307",
            "redirect_to": "https://client.example/articles/how-much-can-i-save-refinancing-title-loan"
          },
          {
            "url": "https://client.example/articles/online-tribal-title-loan",
            "csv_row": 120,
            "canonical": "https://client.example/articles/online-tribal-title-loan.html",
            "canonical_csv_row": 20,
            "canonical_status": "307",
            "redirect_to": "https://client.example/articles/online-tribal-title-loan"
          },
          {
            "url": "https://client.example/articles/title-loan-for-emergency-now-stuck",
            "csv_row": 121,
            "canonical": "https://client.example/articles/title-loan-for-emergency-now-stuck.html",
            "canonical_csv_row": 18,
            "canonical_status": "307",
            "redirect_to": "https://client.example/articles/title-loan-for-emergency-now-stuck"
          },
          {
            "url": "https://client.example/articles/rolled-over-title-loan-again",
            "csv_row": 122,
            "canonical": "https://client.example/articles/rolled-over-title-loan-again.html",
            "canonical_csv_row": 16,
            "canonical_status": "307",
            "redirect_to": "https://client.example/articles/rolled-over-title-loan-again"
          },
          {
            "url": "https://client.example/articles/title-loan-payoff-amount",
            "csv_row": 123,
            "canonical": "https://client.example/articles/title-loan-payoff-amount.html",
            "canonical_csv_row": 17,
            "canonical_status": "307",
            "redirect_to": "https://client.example/articles/title-loan-payoff-amount"
          },
          {
            "url": "https://client.example/articles/repossessed-car-belongings-inside",
            "csv_row": 124,
            "canonical": "https://client.example/articles/repossessed-car-belongings-inside.html",
            "canonical_csv_row": 19,
            "canonical_status": "307",
            "redirect_to": "https://client.example/articles/repossessed-car-belongings-inside"
          },
          {
            "url": "https://client.example/articles/can-title-loan-garnish-wages",
            "csv_row": 125,
            "canonical": "https://client.example/articles/can-title-loan-garnish-wages.html",
            "canonical_csv_row": 14,
            "canonical_status": "307",
            "redirect_to": "https://client.example/articles/can-title-loan-garnish-wages"
          },
          {
            "url": "https://client.example/articles/where-to-get-title-loan-help",
            "csv_row": 126,
            "canonical": "https://client.example/articles/where-to-get-title-loan-help.html",
            "canonical_csv_row": 13,
            "canonical_status": "307",
            "redirect_to": "https://client.example/articles/where-to-get-title-loan-help"
          },
          {
            "url": "https://client.example/articles/stop-paying-title-loan-what-happens",
            "csv_row": 127,
            "canonical": "https://client.example/articles/stop-paying-title-loan-what-happens.html",
            "canonical_csv_row": 12,
            "canonical_status": "307",
            "redirect_to": "https://client.example/articles/stop-paying-title-loan-what-happens"
          },
          {
            "url": "https://client.example/articles/hours-cut-cant-keep-up-title-loan",
            "csv_row": 128,
            "canonical": "https://client.example/articles/hours-cut-cant-keep-up-title-loan.html",
            "canonical_csv_row": 11,
            "canonical_status": "307",
            "redirect_to": "https://client.example/articles/hours-cut-cant-keep-up-title-loan"
          },
          {
            "url": "https://client.example/articles/partner-took-out-title-loan",
            "csv_row": 129,
            "canonical": "https://client.example/articles/partner-took-out-title-loan.html",
            "canonical_csv_row": 15,
            "canonical_status": "307",
            "redirect_to": "https://client.example/articles/partner-took-out-title-loan"
          },
          {
            "url": "https://client.example/articles/title-loan-myths",
            "csv_row": 130,
            "canonical": "https://client.example/articles/title-loan-myths.html",
            "canonical_csv_row": 10,
            "canonical_status": "307",
            "redirect_to": "https://client.example/articles/title-loan-myths"
          },
          {
            "url": "https://client.example/es/articles/stop-paying-title-loan-what-happens",
            "csv_row": 131,
            "canonical": "https://client.example/es/articles/stop-paying-title-loan-what-happens.html",
            "canonical_csv_row": 93,
            "canonical_status": "307",
            "redirect_to": "https://client.example/es/articles/stop-paying-title-loan-what-happens"
          },
          {
            "url": "https://client.example/es/articles/stuck-with-multiple-title-loans",
            "csv_row": 132,
            "canonical": "https://client.example/es/articles/stuck-with-multiple-title-loans.html",
            "canonical_csv_row": 91,
            "canonical_status": "307",
            "redirect_to": "https://client.example/es/articles/stuck-with-multiple-title-loans"
          },
          {
            "url": "https://client.example/es/articles/rolled-over-title-loan-again",
            "csv_row": 133,
            "canonical": "https://client.example/es/articles/rolled-over-title-loan-again.html",
            "canonical_csv_row": 92,
            "canonical_status": "307",
            "redirect_to": "https://client.example/es/articles/rolled-over-title-loan-again"
          },
          {
            "url": "https://client.example/es/articles/title-loan-collections-deficiency",
            "csv_row": 134,
            "canonical": "https://client.example/es/articles/title-loan-collections-deficiency.html",
            "canonical_csv_row": 89,
            "canonical_status": "307",
            "redirect_to": "https://client.example/es/articles/title-loan-collections-deficiency"
          },
          {
            "url": "https://client.example/es/articles/cosigned-title-loan-for-someone",
            "csv_row": 135,
            "canonical": "https://client.example/es/articles/cosigned-title-loan-for-someone.html",
            "canonical_csv_row": 90,
            "canonical_status": "307",
            "redirect_to": "https://client.example/es/articles/cosigned-title-loan-for-someone"
          },
          {
            "url": "https://client.example/es/articles/behind-on-title-loan-repossession",
            "csv_row": 136,
            "canonical": "https://client.example/es/articles/behind-on-title-loan-repossession.html",
            "canonical_csv_row": 87,
            "canonical_status": "307",
            "redirect_to": "https://client.example/es/articles/behind-on-title-loan-repossession"
          },
          {
            "url": "https://client.example/es/articles/hours-cut-cant-keep-up-title-loan",
            "csv_row": 137,
            "canonical": "https://client.example/es/articles/hours-cut-cant-keep-up-title-loan.html",
            "canonical_csv_row": 88,
            "canonical_status": "307",
            "redirect_to": "https://client.example/es/articles/hours-cut-cant-keep-up-title-loan"
          },
          {
            "url": "https://client.example/es/articles/can-title-loan-garnish-wages",
            "csv_row": 138,
            "canonical": "https://client.example/es/articles/can-title-loan-garnish-wages.html",
            "canonical_csv_row": 85,
            "canonical_status": "307",
            "redirect_to": "https://client.example/es/articles/can-title-loan-garnish-wages"
          },
          {
            "url": "https://client.example/es/articles/how-to-negotiate-with-title-loan-lender",
            "csv_row": 139,
            "canonical": "https://client.example/es/articles/how-to-negotiate-with-title-loan-lender.html",
            "canonical_csv_row": 86,
            "canonical_status": "307",
            "redirect_to": "https://client.example/es/articles/how-to-negotiate-with-title-loan-lender"
          },
          {
            "url": "https://client.example/es/articles/hiding-car-from-title-loan-repo",
            "csv_row": 140,
            "canonical": "https://client.example/es/articles/hiding-car-from-title-loan-repo.html",
            "canonical_csv_row": 83,
            "canonical_status": "307",
            "redirect_to": "https://client.example/es/articles/hiding-car-from-title-loan-repo"
          },
          {
            "url": "https://client.example/es/articles/refinance-title-loan-now-vs-keep-paying",
            "csv_row": 141,
            "canonical": "https://client.example/es/articles/refinance-title-loan-now-vs-keep-paying.html",
            "canonical_csv_row": 82,
            "canonical_status": "307",
            "redirect_to": "https://client.example/es/articles/refinance-title-loan-now-vs-keep-paying"
          },
          {
            "url": "https://client.example/es/articles/title-loan-refinance-lower-monthly-payment",
            "csv_row": 142,
            "canonical": "https://client.example/es/articles/title-loan-refinance-lower-monthly-payment.html",
            "canonical_csv_row": 84,
            "canonical_status": "307",
            "redirect_to": "https://client.example/es/articles/title-loan-refinance-lower-monthly-payment"
          },
          {
            "url": "https://client.example/es/articles/is-my-title-loan-legal",
            "csv_row": 143,
            "canonical": "https://client.example/es/articles/is-my-title-loan-legal.html",
            "canonical_csv_row": 81,
            "canonical_status": "307",
            "redirect_to": "https://client.example/es/articles/is-my-title-loan-legal"
          },
          {
            "url": "https://client.example/es/articles/title-loan-and-bankruptcy",
            "csv_row": 144,
            "canonical": "https://client.example/es/articles/title-loan-and-bankruptcy.html",
            "canonical_csv_row": 79,
            "canonical_status": "307",
            "redirect_to": "https://client.example/es/articles/title-loan-and-bankruptcy"
          },
          {
            "url": "https://client.example/es/articles/do-i-qualify-to-refinance-title-loan",
            "csv_row": 145,
            "canonical": "https://client.example/es/articles/do-i-qualify-to-refinance-title-loan.html",
            "canonical_csv_row": 78,
            "canonical_status": "307",
            "redirect_to": "https://client.example/es/articles/do-i-qualify-to-refinance-title-loan"
          },
          {
            "url": "https://client.example/es/articles/title-loan-buyout-process-step-by-step",
            "csv_row": 146,
            "canonical": "https://client.example/es/articles/title-loan-buyout-process-step-by-step.html",
            "canonical_csv_row": 80,
            "canonical_status": "307",
            "redirect_to": "https://client.example/es/articles/title-loan-buyout-process-step-by-step"
          },
          {
            "url": "https://client.example/es/articles/title-loan-junk-fees-add-ons",
            "csv_row": 147,
            "canonical": "https://client.example/es/articles/title-loan-junk-fees-add-ons.html",
            "canonical_csv_row": 77,
            "canonical_status": "307",
            "redirect_to": "https://client.example/es/articles/title-loan-junk-fees-add-ons"
          },
          {
            "url": "https://client.example/es/articles/get-car-title-back-after-payoff",
            "csv_row": 148,
            "canonical": "https://client.example/es/articles/get-car-title-back-after-payoff.html",
            "canonical_csv_row": 76,
            "canonical_status": "307",
            "redirect_to": "https://client.example/es/articles/get-car-title-back-after-payoff"
          },
          {
            "url": "https://client.example/es/articles/partner-took-out-title-loan",
            "csv_row": 149,
            "canonical": "https://client.example/es/articles/partner-took-out-title-loan.html",
            "canonical_csv_row": 74,
            "canonical_status": "307",
            "redirect_to": "https://client.example/es/articles/partner-took-out-title-loan"
          },
          {
            "url": "https://client.example/es/articles/where-to-get-title-loan-help",
            "csv_row": 150,
            "canonical": "https://client.example/es/articles/where-to-get-title-loan-help.html",
            "canonical_csv_row": 75,
            "canonical_status": "307",
            "redirect_to": "https://client.example/es/articles/where-to-get-title-loan-help"
          },
          {
            "url": "https://client.example/es/articles/online-tribal-title-loan",
            "csv_row": 151,
            "canonical": "https://client.example/es/articles/online-tribal-title-loan.html",
            "canonical_csv_row": 70,
            "canonical_status": "307",
            "redirect_to": "https://client.example/es/articles/online-tribal-title-loan"
          },
          {
            "url": "https://client.example/es/articles/title-loan-myths",
            "csv_row": 152,
            "canonical": "https://client.example/es/articles/title-loan-myths.html",
            "canonical_csv_row": 72,
            "canonical_status": "307",
            "redirect_to": "https://client.example/es/articles/title-loan-myths"
          },
          {
            "url": "https://client.example/es/articles/title-loan-payoff-amount",
            "csv_row": 153,
            "canonical": "https://client.example/es/articles/title-loan-payoff-amount.html",
            "canonical_csv_row": 73,
            "canonical_status": "307",
            "redirect_to": "https://client.example/es/articles/title-loan-payoff-amount"
          },
          {
            "url": "https://client.example/es/articles/why-title-loan-balance-never-goes-down",
            "csv_row": 154,
            "canonical": "https://client.example/es/articles/why-title-loan-balance-never-goes-down.html",
            "canonical_csv_row": 68,
            "canonical_status": "307",
            "redirect_to": "https://client.example/es/articles/why-title-loan-balance-never-goes-down"
          },
          {
            "url": "https://client.example/es/articles/title-loan-for-emergency-now-stuck",
            "csv_row": 155,
            "canonical": "https://client.example/es/articles/title-loan-for-emergency-now-stuck.html",
            "canonical_csv_row": 71,
            "canonical_status": "307",
            "redirect_to": "https://client.example/es/articles/title-loan-for-emergency-now-stuck"
          },
          {
            "url": "https://client.example/es/articles/can-they-take-my-car-title-loan",
            "csv_row": 156,
            "canonical": "https://client.example/es/articles/can-they-take-my-car-title-loan.html",
            "canonical_csv_row": 67,
            "canonical_status": "307",
            "redirect_to": "https://client.example/es/articles/can-they-take-my-car-title-loan"
          },
          {
            "url": "https://client.example/es/articles/how-much-can-i-save-refinancing-title-loan",
            "csv_row": 157,
            "canonical": "https://client.example/es/articles/how-much-can-i-save-refinancing-title-loan.html",
            "canonical_csv_row": 69,
            "canonical_status": "307",
            "redirect_to": "https://client.example/es/articles/how-much-can-i-save-refinancing-title-loan"
          },
          {
            "url": "https://client.example/es/articles/cant-pay-title-loan-this-week",
            "csv_row": 158,
            "canonical": "https://client.example/es/articles/cant-pay-title-loan-this-week.html",
            "canonical_csv_row": 65,
            "canonical_status": "307",
            "redirect_to": "https://client.example/es/articles/cant-pay-title-loan-this-week"
          },
          {
            "url": "https://client.example/es/articles/should-i-let-them-take-the-car",
            "csv_row": 159,
            "canonical": "https://client.example/es/articles/should-i-let-them-take-the-car.html",
            "canonical_csv_row": 64,
            "canonical_status": "307",
            "redirect_to": "https://client.example/es/articles/should-i-let-them-take-the-car"
          },
          {
            "url": "https://client.example/es/articles/do-title-loans-affect-credit",
            "csv_row": 160,
            "canonical": "https://client.example/es/articles/do-title-loans-affect-credit.html",
            "canonical_csv_row": 61,
            "canonical_status": "307",
            "redirect_to": "https://client.example/es/articles/do-title-loans-affect-credit"
          },
          {
            "url": "https://client.example/es/articles/title-loan-renewal-cycle",
            "csv_row": 161,
            "canonical": "https://client.example/es/articles/title-loan-renewal-cycle.html",
            "canonical_csv_row": 63,
            "canonical_status": "307",
            "redirect_to": "https://client.example/es/articles/title-loan-renewal-cycle"
          },
          {
            "url": "https://client.example/es/articles/pay-down-title-loan-principal",
            "csv_row": 162,
            "canonical": "https://client.example/es/articles/pay-down-title-loan-principal.html",
            "canonical_csv_row": 66,
            "canonical_status": "307",
            "redirect_to": "https://client.example/es/articles/pay-down-title-loan-principal"
          },
          {
            "url": "https://client.example/es/articles/repossessed-car-belongings-inside",
            "csv_row": 163,
            "canonical": "https://client.example/es/articles/repossessed-car-belongings-inside.html",
            "canonical_csv_row": 59,
            "canonical_status": "307",
            "redirect_to": "https://client.example/es/articles/repossessed-car-belongings-inside"
          },
          {
            "url": "https://client.example/es/articles/title-loan-refinance-buyout",
            "csv_row": 164,
            "canonical": "https://client.example/es/articles/title-loan-refinance-buyout.html",
            "canonical_csv_row": 62,
            "canonical_status": "307",
            "redirect_to": "https://client.example/es/articles/title-loan-refinance-buyout"
          },
          {
            "url": "https://client.example/es/articles/title-loan-calling-my-job-references",
            "csv_row": 165,
            "canonical": "https://client.example/es/articles/title-loan-calling-my-job-references.html",
            "canonical_csv_row": 58,
            "canonical_status": "307",
            "redirect_to": "https://client.example/es/articles/title-loan-calling-my-job-references"
          },
          {
            "url": "https://client.example/es/articles/military-title-loan-illegal",
            "csv_row": 166,
            "canonical": "https://client.example/es/articles/military-title-loan-illegal.html",
            "canonical_csv_row": 60,
            "canonical_status": "307",
            "redirect_to": "https://client.example/es/articles/military-title-loan-illegal"
          },
          {
            "url": "https://client.example/es/articles/title-loan-vs-payday-vs-personal-loan",
            "csv_row": 167,
            "canonical": "https://client.example/es/articles/title-loan-vs-payday-vs-personal-loan.html",
            "canonical_csv_row": 57,
            "canonical_status": "307",
            "redirect_to": "https://client.example/es/articles/title-loan-vs-payday-vs-personal-loan"
          },
          {
            "url": "https://client.example/es/articles/being-sued-by-title-loan-company",
            "csv_row": 168,
            "canonical": "https://client.example/es/articles/being-sued-by-title-loan-company.html",
            "canonical_csv_row": 56,
            "canonical_status": "307",
            "redirect_to": "https://client.example/es/articles/being-sued-by-title-loan-company"
          },
          {
            "url": "https://client.example/es/articles/sell-car-with-title-loan",
            "csv_row": 171,
            "canonical": "https://client.example/es/articles/sell-car-with-title-loan.html",
            "canonical_csv_row": 55,
            "canonical_status": "307",
            "redirect_to": "https://client.example/es/articles/sell-car-with-title-loan"
          },
          {
            "url": "https://client.example/es/articles/title-loan-gps-tracker-kill-switch",
            "csv_row": 172,
            "canonical": "https://client.example/es/articles/title-loan-gps-tracker-kill-switch.html",
            "canonical_csv_row": 53,
            "canonical_status": "307",
            "redirect_to": "https://client.example/es/articles/title-loan-gps-tracker-kill-switch"
          }
        ],
        "fix": "Confirm the preferred URL policy, then align canonical declarations with final 200 URLs and verify a fresh crawl plus URL Inspection.",
        "effort": "4–8 engineering hours plus 2–4 QA hours (provisional)",
        "dependencies": "Owner approval of URL policy; SEO and engineering review",
        "reasoning": "Conflicting canonical and redirect signals. This is not an HTTP loop or proof of Google exclusion."
      },
      {
        "id": "T02",
        "group": "Technical SEO",
        "priority": "P2",
        "state": "Review",
        "title": "Review redirect policy",
        "affected": [
          {
            "url": "https://client.example/privacy.html",
            "csv_row": 6,
            "status": "307",
            "redirect_to": "https://client.example/privacy",
            "inlinks": "7",
            "unique_inlinks": "3"
          },
          {
            "url": "https://client.example/sms-terms.html",
            "csv_row": 7,
            "status": "307",
            "redirect_to": "https://client.example/sms-terms",
            "inlinks": "2",
            "unique_inlinks": "2"
          },
          {
            "url": "https://client.example/articles/title-loan-myths.html",
            "csv_row": 10,
            "status": "307",
            "redirect_to": "https://client.example/articles/title-loan-myths",
            "inlinks": "7",
            "unique_inlinks": "6"
          },
          {
            "url": "https://client.example/articles/hours-cut-cant-keep-up-title-loan.html",
            "csv_row": 11,
            "status": "307",
            "redirect_to": "https://client.example/articles/hours-cut-cant-keep-up-title-loan",
            "inlinks": "3",
            "unique_inlinks": "3"
          },
          {
            "url": "https://client.example/articles/stop-paying-title-loan-what-happens.html",
            "csv_row": 12,
            "status": "307",
            "redirect_to": "https://client.example/articles/stop-paying-title-loan-what-happens",
            "inlinks": "2",
            "unique_inlinks": "2"
          },
          {
            "url": "https://client.example/articles/where-to-get-title-loan-help.html",
            "csv_row": 13,
            "status": "307",
            "redirect_to": "https://client.example/articles/where-to-get-title-loan-help",
            "inlinks": "24",
            "unique_inlinks": "17"
          },
          {
            "url": "https://client.example/articles/can-title-loan-garnish-wages.html",
            "csv_row": 14,
            "status": "307",
            "redirect_to": "https://client.example/articles/can-title-loan-garnish-wages",
            "inlinks": "4",
            "unique_inlinks": "3"
          },
          {
            "url": "https://client.example/articles/partner-took-out-title-loan.html",
            "csv_row": 15,
            "status": "307",
            "redirect_to": "https://client.example/articles/partner-took-out-title-loan",
            "inlinks": "3",
            "unique_inlinks": "3"
          },
          {
            "url": "https://client.example/articles/rolled-over-title-loan-again.html",
            "csv_row": 16,
            "status": "307",
            "redirect_to": "https://client.example/articles/rolled-over-title-loan-again",
            "inlinks": "2",
            "unique_inlinks": "2"
          },
          {
            "url": "https://client.example/articles/title-loan-payoff-amount.html",
            "csv_row": 17,
            "status": "307",
            "redirect_to": "https://client.example/articles/title-loan-payoff-amount",
            "inlinks": "19",
            "unique_inlinks": "14"
          },
          {
            "url": "https://client.example/articles/title-loan-for-emergency-now-stuck.html",
            "csv_row": 18,
            "status": "307",
            "redirect_to": "https://client.example/articles/title-loan-for-emergency-now-stuck",
            "inlinks": "2",
            "unique_inlinks": "2"
          },
          {
            "url": "https://client.example/articles/repossessed-car-belongings-inside.html",
            "csv_row": 19,
            "status": "307",
            "redirect_to": "https://client.example/articles/repossessed-car-belongings-inside",
            "inlinks": "2",
            "unique_inlinks": "2"
          },
          {
            "url": "https://client.example/articles/online-tribal-title-loan.html",
            "csv_row": 20,
            "status": "307",
            "redirect_to": "https://client.example/articles/online-tribal-title-loan",
            "inlinks": "2",
            "unique_inlinks": "2"
          },
          {
            "url": "https://client.example/articles/get-car-title-back-after-payoff.html",
            "csv_row": 21,
            "status": "307",
            "redirect_to": "https://client.example/articles/get-car-title-back-after-payoff",
            "inlinks": "4",
            "unique_inlinks": "3"
          },
          {
            "url": "https://client.example/articles/how-much-can-i-save-refinancing-title-loan.html",
            "csv_row": 22,
            "status": "307",
            "redirect_to": "https://client.example/articles/how-much-can-i-save-refinancing-title-loan",
            "inlinks": "5",
            "unique_inlinks": "4"
          },
          {
            "url": "https://client.example/articles/title-loan-vs-payday-vs-personal-loan.html",
            "csv_row": 23,
            "status": "307",
            "redirect_to": "https://client.example/articles/title-loan-vs-payday-vs-personal-loan",
            "inlinks": "13",
            "unique_inlinks": "12"
          },
          {
            "url": "https://client.example/articles/title-loan-renewal-cycle.html",
            "csv_row": 24,
            "status": "307",
            "redirect_to": "https://client.example/articles/title-loan-renewal-cycle",
            "inlinks": "14",
            "unique_inlinks": "10"
          },
          {
            "url": "https://client.example/articles/should-i-let-them-take-the-car.html",
            "csv_row": 25,
            "status": "307",
            "redirect_to": "https://client.example/articles/should-i-let-them-take-the-car",
            "inlinks": "2",
            "unique_inlinks": "2"
          },
          {
            "url": "https://client.example/articles/is-my-title-loan-legal.html",
            "csv_row": 26,
            "status": "307",
            "redirect_to": "https://client.example/articles/is-my-title-loan-legal",
            "inlinks": "9",
            "unique_inlinks": "7"
          },
          {
            "url": "https://client.example/articles/why-title-loan-balance-never-goes-down.html",
            "csv_row": 27,
            "status": "307",
            "redirect_to": "https://client.example/articles/why-title-loan-balance-never-goes-down",
            "inlinks": "22",
            "unique_inlinks": "15"
          },
          {
            "url": "https://client.example/articles/behind-on-title-loan-repossession.html",
            "csv_row": 28,
            "status": "307",
            "redirect_to": "https://client.example/articles/behind-on-title-loan-repossession",
            "inlinks": "29",
            "unique_inlinks": "19"
          },
          {
            "url": "https://client.example/articles/can-they-take-my-car-title-loan.html",
            "csv_row": 29,
            "status": "307",
            "redirect_to": "https://client.example/articles/can-they-take-my-car-title-loan",
            "inlinks": "13",
            "unique_inlinks": "10"
          },
          {
            "url": "https://client.example/articles/refinance-title-loan-now-vs-keep-paying.html",
            "csv_row": 30,
            "status": "307",
            "redirect_to": "https://client.example/articles/refinance-title-loan-now-vs-keep-paying",
            "inlinks": "2",
            "unique_inlinks": "2"
          },
          {
            "url": "https://client.example/articles/cosigned-title-loan-for-someone.html",
            "csv_row": 31,
            "status": "307",
            "redirect_to": "https://client.example/articles/cosigned-title-loan-for-someone",
            "inlinks": "2",
            "unique_inlinks": "2"
          },
          {
            "url": "https://client.example/articles/being-sued-by-title-loan-company.html",
            "csv_row": 32,
            "status": "307",
            "redirect_to": "https://client.example/articles/being-sued-by-title-loan-company",
            "inlinks": "5",
            "unique_inlinks": "4"
          },
          {
            "url": "https://client.example/articles/sell-car-with-title-loan.html",
            "csv_row": 33,
            "status": "307",
            "redirect_to": "https://client.example/articles/sell-car-with-title-loan",
            "inlinks": "2",
            "unique_inlinks": "2"
          },
          {
            "url": "https://client.example/articles/title-loan-refinance-lower-monthly-payment.html",
            "csv_row": 34,
            "status": "307",
            "redirect_to": "https://client.example/articles/title-loan-refinance-lower-monthly-payment",
            "inlinks": "4",
            "unique_inlinks": "3"
          },
          {
            "url": "https://client.example/articles/do-i-qualify-to-refinance-title-loan.html",
            "csv_row": 35,
            "status": "307",
            "redirect_to": "https://client.example/articles/do-i-qualify-to-refinance-title-loan",
            "inlinks": "3",
            "unique_inlinks": "3"
          },
          {
            "url": "https://client.example/articles/title-loan-refinance-buyout.html",
            "csv_row": 36,
            "status": "307",
            "redirect_to": "https://client.example/articles/title-loan-refinance-buyout",
            "inlinks": "69",
            "unique_inlinks": "37"
          },
          {
            "url": "https://client.example/articles/title-loan-buyout-process-step-by-step.html",
            "csv_row": 37,
            "status": "307",
            "redirect_to": "https://client.example/articles/title-loan-buyout-process-step-by-step",
            "inlinks": "4",
            "unique_inlinks": "4"
          },
          {
            "url": "https://client.example/articles/do-title-loans-affect-credit.html",
            "csv_row": 38,
            "status": "307",
            "redirect_to": "https://client.example/articles/do-title-loans-affect-credit",
            "inlinks": "9",
            "unique_inlinks": "6"
          },
          {
            "url": "https://client.example/articles/title-loan-collections-deficiency.html",
            "csv_row": 39,
            "status": "307",
            "redirect_to": "https://client.example/articles/title-loan-collections-deficiency",
            "inlinks": "16",
            "unique_inlinks": "10"
          },
          {
            "url": "https://client.example/articles/hiding-car-from-title-loan-repo.html",
            "csv_row": 40,
            "status": "307",
            "redirect_to": "https://client.example/articles/hiding-car-from-title-loan-repo",
            "inlinks": "2",
            "unique_inlinks": "2"
          },
          {
            "url": "https://client.example/articles/cant-pay-title-loan-this-week.html",
            "csv_row": 41,
            "status": "307",
            "redirect_to": "https://client.example/articles/cant-pay-title-loan-this-week",
            "inlinks": "9",
            "unique_inlinks": "6"
          },
          {
            "url": "https://client.example/articles/title-loan-and-bankruptcy.html",
            "csv_row": 42,
            "status": "307",
            "redirect_to": "https://client.example/articles/title-loan-and-bankruptcy",
            "inlinks": "3",
            "unique_inlinks": "3"
          },
          {
            "url": "https://client.example/articles/pay-down-title-loan-principal.html",
            "csv_row": 43,
            "status": "307",
            "redirect_to": "https://client.example/articles/pay-down-title-loan-principal",
            "inlinks": "18",
            "unique_inlinks": "14"
          },
          {
            "url": "https://client.example/articles/stuck-with-multiple-title-loans.html",
            "csv_row": 44,
            "status": "307",
            "redirect_to": "https://client.example/articles/stuck-with-multiple-title-loans",
            "inlinks": "3",
            "unique_inlinks": "3"
          },
          {
            "url": "https://client.example/articles/title-loan-junk-fees-add-ons.html",
            "csv_row": 45,
            "status": "307",
            "redirect_to": "https://client.example/articles/title-loan-junk-fees-add-ons",
            "inlinks": "2",
            "unique_inlinks": "2"
          },
          {
            "url": "https://client.example/articles/title-loan-calling-my-job-references.html",
            "csv_row": 46,
            "status": "307",
            "redirect_to": "https://client.example/articles/title-loan-calling-my-job-references",
            "inlinks": "3",
            "unique_inlinks": "3"
          },
          {
            "url": "https://client.example/articles/how-to-negotiate-with-title-loan-lender.html",
            "csv_row": 47,
            "status": "307",
            "redirect_to": "https://client.example/articles/how-to-negotiate-with-title-loan-lender",
            "inlinks": "23",
            "unique_inlinks": "19"
          },
          {
            "url": "https://client.example/articles/military-title-loan-illegal.html",
            "csv_row": 48,
            "status": "307",
            "redirect_to": "https://client.example/articles/military-title-loan-illegal",
            "inlinks": "2",
            "unique_inlinks": "2"
          },
          {
            "url": "https://client.example/articles/title-loan-gps-tracker-kill-switch.html",
            "csv_row": 49,
            "status": "307",
            "redirect_to": "https://client.example/articles/title-loan-gps-tracker-kill-switch",
            "inlinks": "2",
            "unique_inlinks": "2"
          },
          {
            "url": "https://client.example/es/articles/title-loan-gps-tracker-kill-switch.html",
            "csv_row": 53,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/title-loan-gps-tracker-kill-switch",
            "inlinks": "2",
            "unique_inlinks": "2"
          },
          {
            "url": "https://client.example/es/articles/sell-car-with-title-loan.html",
            "csv_row": 55,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/sell-car-with-title-loan",
            "inlinks": "2",
            "unique_inlinks": "2"
          },
          {
            "url": "https://client.example/es/articles/being-sued-by-title-loan-company.html",
            "csv_row": 56,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/being-sued-by-title-loan-company",
            "inlinks": "5",
            "unique_inlinks": "4"
          },
          {
            "url": "https://client.example/es/articles/title-loan-vs-payday-vs-personal-loan.html",
            "csv_row": 57,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/title-loan-vs-payday-vs-personal-loan",
            "inlinks": "11",
            "unique_inlinks": "10"
          },
          {
            "url": "https://client.example/es/articles/title-loan-calling-my-job-references.html",
            "csv_row": 58,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/title-loan-calling-my-job-references",
            "inlinks": "3",
            "unique_inlinks": "3"
          },
          {
            "url": "https://client.example/es/articles/repossessed-car-belongings-inside.html",
            "csv_row": 59,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/repossessed-car-belongings-inside",
            "inlinks": "2",
            "unique_inlinks": "2"
          },
          {
            "url": "https://client.example/es/articles/military-title-loan-illegal.html",
            "csv_row": 60,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/military-title-loan-illegal",
            "inlinks": "2",
            "unique_inlinks": "2"
          },
          {
            "url": "https://client.example/es/articles/do-title-loans-affect-credit.html",
            "csv_row": 61,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/do-title-loans-affect-credit",
            "inlinks": "9",
            "unique_inlinks": "6"
          },
          {
            "url": "https://client.example/es/articles/title-loan-refinance-buyout.html",
            "csv_row": 62,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/title-loan-refinance-buyout",
            "inlinks": "69",
            "unique_inlinks": "37"
          },
          {
            "url": "https://client.example/es/articles/title-loan-renewal-cycle.html",
            "csv_row": 63,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/title-loan-renewal-cycle",
            "inlinks": "12",
            "unique_inlinks": "9"
          },
          {
            "url": "https://client.example/es/articles/should-i-let-them-take-the-car.html",
            "csv_row": 64,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/should-i-let-them-take-the-car",
            "inlinks": "2",
            "unique_inlinks": "2"
          },
          {
            "url": "https://client.example/es/articles/cant-pay-title-loan-this-week.html",
            "csv_row": 65,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/cant-pay-title-loan-this-week",
            "inlinks": "9",
            "unique_inlinks": "6"
          },
          {
            "url": "https://client.example/es/articles/pay-down-title-loan-principal.html",
            "csv_row": 66,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/pay-down-title-loan-principal",
            "inlinks": "15",
            "unique_inlinks": "11"
          },
          {
            "url": "https://client.example/es/articles/can-they-take-my-car-title-loan.html",
            "csv_row": 67,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/can-they-take-my-car-title-loan",
            "inlinks": "13",
            "unique_inlinks": "10"
          },
          {
            "url": "https://client.example/es/articles/why-title-loan-balance-never-goes-down.html",
            "csv_row": 68,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/why-title-loan-balance-never-goes-down",
            "inlinks": "21",
            "unique_inlinks": "15"
          },
          {
            "url": "https://client.example/es/articles/how-much-can-i-save-refinancing-title-loan.html",
            "csv_row": 69,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/how-much-can-i-save-refinancing-title-loan",
            "inlinks": "6",
            "unique_inlinks": "5"
          },
          {
            "url": "https://client.example/es/articles/online-tribal-title-loan.html",
            "csv_row": 70,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/online-tribal-title-loan",
            "inlinks": "2",
            "unique_inlinks": "2"
          },
          {
            "url": "https://client.example/es/articles/title-loan-for-emergency-now-stuck.html",
            "csv_row": 71,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/title-loan-for-emergency-now-stuck",
            "inlinks": "2",
            "unique_inlinks": "2"
          },
          {
            "url": "https://client.example/es/articles/title-loan-myths.html",
            "csv_row": 72,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/title-loan-myths",
            "inlinks": "5",
            "unique_inlinks": "5"
          },
          {
            "url": "https://client.example/es/articles/title-loan-payoff-amount.html",
            "csv_row": 73,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/title-loan-payoff-amount",
            "inlinks": "16",
            "unique_inlinks": "12"
          },
          {
            "url": "https://client.example/es/articles/partner-took-out-title-loan.html",
            "csv_row": 74,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/partner-took-out-title-loan",
            "inlinks": "3",
            "unique_inlinks": "3"
          },
          {
            "url": "https://client.example/es/articles/where-to-get-title-loan-help.html",
            "csv_row": 75,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/where-to-get-title-loan-help",
            "inlinks": "24",
            "unique_inlinks": "17"
          },
          {
            "url": "https://client.example/es/articles/get-car-title-back-after-payoff.html",
            "csv_row": 76,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/get-car-title-back-after-payoff",
            "inlinks": "4",
            "unique_inlinks": "3"
          },
          {
            "url": "https://client.example/es/articles/title-loan-junk-fees-add-ons.html",
            "csv_row": 77,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/title-loan-junk-fees-add-ons",
            "inlinks": "2",
            "unique_inlinks": "2"
          },
          {
            "url": "https://client.example/es/articles/do-i-qualify-to-refinance-title-loan.html",
            "csv_row": 78,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/do-i-qualify-to-refinance-title-loan",
            "inlinks": "5",
            "unique_inlinks": "4"
          },
          {
            "url": "https://client.example/es/articles/title-loan-and-bankruptcy.html",
            "csv_row": 79,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/title-loan-and-bankruptcy",
            "inlinks": "3",
            "unique_inlinks": "3"
          },
          {
            "url": "https://client.example/es/articles/title-loan-buyout-process-step-by-step.html",
            "csv_row": 80,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/title-loan-buyout-process-step-by-step",
            "inlinks": "6",
            "unique_inlinks": "5"
          },
          {
            "url": "https://client.example/es/articles/is-my-title-loan-legal.html",
            "csv_row": 81,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/is-my-title-loan-legal",
            "inlinks": "9",
            "unique_inlinks": "7"
          },
          {
            "url": "https://client.example/es/articles/refinance-title-loan-now-vs-keep-paying.html",
            "csv_row": 82,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/refinance-title-loan-now-vs-keep-paying",
            "inlinks": "3",
            "unique_inlinks": "3"
          },
          {
            "url": "https://client.example/es/articles/hiding-car-from-title-loan-repo.html",
            "csv_row": 83,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/hiding-car-from-title-loan-repo",
            "inlinks": "2",
            "unique_inlinks": "2"
          },
          {
            "url": "https://client.example/es/articles/title-loan-refinance-lower-monthly-payment.html",
            "csv_row": 84,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/title-loan-refinance-lower-monthly-payment",
            "inlinks": "4",
            "unique_inlinks": "4"
          },
          {
            "url": "https://client.example/es/articles/can-title-loan-garnish-wages.html",
            "csv_row": 85,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/can-title-loan-garnish-wages",
            "inlinks": "4",
            "unique_inlinks": "3"
          },
          {
            "url": "https://client.example/es/articles/how-to-negotiate-with-title-loan-lender.html",
            "csv_row": 86,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/how-to-negotiate-with-title-loan-lender",
            "inlinks": "22",
            "unique_inlinks": "18"
          },
          {
            "url": "https://client.example/es/articles/behind-on-title-loan-repossession.html",
            "csv_row": 87,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/behind-on-title-loan-repossession",
            "inlinks": "26",
            "unique_inlinks": "16"
          },
          {
            "url": "https://client.example/es/articles/hours-cut-cant-keep-up-title-loan.html",
            "csv_row": 88,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/hours-cut-cant-keep-up-title-loan",
            "inlinks": "3",
            "unique_inlinks": "3"
          },
          {
            "url": "https://client.example/es/articles/title-loan-collections-deficiency.html",
            "csv_row": 89,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/title-loan-collections-deficiency",
            "inlinks": "16",
            "unique_inlinks": "10"
          },
          {
            "url": "https://client.example/es/articles/cosigned-title-loan-for-someone.html",
            "csv_row": 90,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/cosigned-title-loan-for-someone",
            "inlinks": "2",
            "unique_inlinks": "2"
          },
          {
            "url": "https://client.example/es/articles/stuck-with-multiple-title-loans.html",
            "csv_row": 91,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/stuck-with-multiple-title-loans",
            "inlinks": "2",
            "unique_inlinks": "2"
          },
          {
            "url": "https://client.example/es/articles/rolled-over-title-loan-again.html",
            "csv_row": 92,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/rolled-over-title-loan-again",
            "inlinks": "2",
            "unique_inlinks": "2"
          },
          {
            "url": "https://client.example/es/articles/stop-paying-title-loan-what-happens.html",
            "csv_row": 93,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/stop-paying-title-loan-what-happens",
            "inlinks": "2",
            "unique_inlinks": "2"
          },
          {
            "url": "https://client.example/articles/index.html",
            "csv_row": 169,
            "status": "307",
            "redirect_to": "https://client.example/articles/",
            "inlinks": "40",
            "unique_inlinks": "40"
          },
          {
            "url": "https://client.example/es/articles/index.html",
            "csv_row": 170,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/",
            "inlinks": "40",
            "unique_inlinks": "40"
          }
        ],
        "fix": "Verify whether each move is permanent before selecting a redirect status.",
        "effort": "1–2 incremental review hours; overlaps T01",
        "dependencies": "T01 URL policy",
        "reasoning": "307 status alone is not a defect."
      },
      {
        "id": "L01",
        "group": "Internal linking",
        "priority": "P2",
        "state": "Observed",
        "title": "Inspect links to redirected URL variants",
        "affected": [
          {
            "url": "https://client.example/privacy.html",
            "csv_row": 6,
            "status": "307",
            "redirect_to": "https://client.example/privacy",
            "inlinks": "7",
            "unique_inlinks": "3"
          },
          {
            "url": "https://client.example/sms-terms.html",
            "csv_row": 7,
            "status": "307",
            "redirect_to": "https://client.example/sms-terms",
            "inlinks": "2",
            "unique_inlinks": "2"
          },
          {
            "url": "https://client.example/articles/title-loan-myths.html",
            "csv_row": 10,
            "status": "307",
            "redirect_to": "https://client.example/articles/title-loan-myths",
            "inlinks": "7",
            "unique_inlinks": "6"
          },
          {
            "url": "https://client.example/articles/hours-cut-cant-keep-up-title-loan.html",
            "csv_row": 11,
            "status": "307",
            "redirect_to": "https://client.example/articles/hours-cut-cant-keep-up-title-loan",
            "inlinks": "3",
            "unique_inlinks": "3"
          },
          {
            "url": "https://client.example/articles/stop-paying-title-loan-what-happens.html",
            "csv_row": 12,
            "status": "307",
            "redirect_to": "https://client.example/articles/stop-paying-title-loan-what-happens",
            "inlinks": "2",
            "unique_inlinks": "2"
          },
          {
            "url": "https://client.example/articles/where-to-get-title-loan-help.html",
            "csv_row": 13,
            "status": "307",
            "redirect_to": "https://client.example/articles/where-to-get-title-loan-help",
            "inlinks": "24",
            "unique_inlinks": "17"
          },
          {
            "url": "https://client.example/articles/can-title-loan-garnish-wages.html",
            "csv_row": 14,
            "status": "307",
            "redirect_to": "https://client.example/articles/can-title-loan-garnish-wages",
            "inlinks": "4",
            "unique_inlinks": "3"
          },
          {
            "url": "https://client.example/articles/partner-took-out-title-loan.html",
            "csv_row": 15,
            "status": "307",
            "redirect_to": "https://client.example/articles/partner-took-out-title-loan",
            "inlinks": "3",
            "unique_inlinks": "3"
          },
          {
            "url": "https://client.example/articles/rolled-over-title-loan-again.html",
            "csv_row": 16,
            "status": "307",
            "redirect_to": "https://client.example/articles/rolled-over-title-loan-again",
            "inlinks": "2",
            "unique_inlinks": "2"
          },
          {
            "url": "https://client.example/articles/title-loan-payoff-amount.html",
            "csv_row": 17,
            "status": "307",
            "redirect_to": "https://client.example/articles/title-loan-payoff-amount",
            "inlinks": "19",
            "unique_inlinks": "14"
          },
          {
            "url": "https://client.example/articles/title-loan-for-emergency-now-stuck.html",
            "csv_row": 18,
            "status": "307",
            "redirect_to": "https://client.example/articles/title-loan-for-emergency-now-stuck",
            "inlinks": "2",
            "unique_inlinks": "2"
          },
          {
            "url": "https://client.example/articles/repossessed-car-belongings-inside.html",
            "csv_row": 19,
            "status": "307",
            "redirect_to": "https://client.example/articles/repossessed-car-belongings-inside",
            "inlinks": "2",
            "unique_inlinks": "2"
          },
          {
            "url": "https://client.example/articles/online-tribal-title-loan.html",
            "csv_row": 20,
            "status": "307",
            "redirect_to": "https://client.example/articles/online-tribal-title-loan",
            "inlinks": "2",
            "unique_inlinks": "2"
          },
          {
            "url": "https://client.example/articles/get-car-title-back-after-payoff.html",
            "csv_row": 21,
            "status": "307",
            "redirect_to": "https://client.example/articles/get-car-title-back-after-payoff",
            "inlinks": "4",
            "unique_inlinks": "3"
          },
          {
            "url": "https://client.example/articles/how-much-can-i-save-refinancing-title-loan.html",
            "csv_row": 22,
            "status": "307",
            "redirect_to": "https://client.example/articles/how-much-can-i-save-refinancing-title-loan",
            "inlinks": "5",
            "unique_inlinks": "4"
          },
          {
            "url": "https://client.example/articles/title-loan-vs-payday-vs-personal-loan.html",
            "csv_row": 23,
            "status": "307",
            "redirect_to": "https://client.example/articles/title-loan-vs-payday-vs-personal-loan",
            "inlinks": "13",
            "unique_inlinks": "12"
          },
          {
            "url": "https://client.example/articles/title-loan-renewal-cycle.html",
            "csv_row": 24,
            "status": "307",
            "redirect_to": "https://client.example/articles/title-loan-renewal-cycle",
            "inlinks": "14",
            "unique_inlinks": "10"
          },
          {
            "url": "https://client.example/articles/should-i-let-them-take-the-car.html",
            "csv_row": 25,
            "status": "307",
            "redirect_to": "https://client.example/articles/should-i-let-them-take-the-car",
            "inlinks": "2",
            "unique_inlinks": "2"
          },
          {
            "url": "https://client.example/articles/is-my-title-loan-legal.html",
            "csv_row": 26,
            "status": "307",
            "redirect_to": "https://client.example/articles/is-my-title-loan-legal",
            "inlinks": "9",
            "unique_inlinks": "7"
          },
          {
            "url": "https://client.example/articles/why-title-loan-balance-never-goes-down.html",
            "csv_row": 27,
            "status": "307",
            "redirect_to": "https://client.example/articles/why-title-loan-balance-never-goes-down",
            "inlinks": "22",
            "unique_inlinks": "15"
          },
          {
            "url": "https://client.example/articles/behind-on-title-loan-repossession.html",
            "csv_row": 28,
            "status": "307",
            "redirect_to": "https://client.example/articles/behind-on-title-loan-repossession",
            "inlinks": "29",
            "unique_inlinks": "19"
          },
          {
            "url": "https://client.example/articles/can-they-take-my-car-title-loan.html",
            "csv_row": 29,
            "status": "307",
            "redirect_to": "https://client.example/articles/can-they-take-my-car-title-loan",
            "inlinks": "13",
            "unique_inlinks": "10"
          },
          {
            "url": "https://client.example/articles/refinance-title-loan-now-vs-keep-paying.html",
            "csv_row": 30,
            "status": "307",
            "redirect_to": "https://client.example/articles/refinance-title-loan-now-vs-keep-paying",
            "inlinks": "2",
            "unique_inlinks": "2"
          },
          {
            "url": "https://client.example/articles/cosigned-title-loan-for-someone.html",
            "csv_row": 31,
            "status": "307",
            "redirect_to": "https://client.example/articles/cosigned-title-loan-for-someone",
            "inlinks": "2",
            "unique_inlinks": "2"
          },
          {
            "url": "https://client.example/articles/being-sued-by-title-loan-company.html",
            "csv_row": 32,
            "status": "307",
            "redirect_to": "https://client.example/articles/being-sued-by-title-loan-company",
            "inlinks": "5",
            "unique_inlinks": "4"
          },
          {
            "url": "https://client.example/articles/sell-car-with-title-loan.html",
            "csv_row": 33,
            "status": "307",
            "redirect_to": "https://client.example/articles/sell-car-with-title-loan",
            "inlinks": "2",
            "unique_inlinks": "2"
          },
          {
            "url": "https://client.example/articles/title-loan-refinance-lower-monthly-payment.html",
            "csv_row": 34,
            "status": "307",
            "redirect_to": "https://client.example/articles/title-loan-refinance-lower-monthly-payment",
            "inlinks": "4",
            "unique_inlinks": "3"
          },
          {
            "url": "https://client.example/articles/do-i-qualify-to-refinance-title-loan.html",
            "csv_row": 35,
            "status": "307",
            "redirect_to": "https://client.example/articles/do-i-qualify-to-refinance-title-loan",
            "inlinks": "3",
            "unique_inlinks": "3"
          },
          {
            "url": "https://client.example/articles/title-loan-refinance-buyout.html",
            "csv_row": 36,
            "status": "307",
            "redirect_to": "https://client.example/articles/title-loan-refinance-buyout",
            "inlinks": "69",
            "unique_inlinks": "37"
          },
          {
            "url": "https://client.example/articles/title-loan-buyout-process-step-by-step.html",
            "csv_row": 37,
            "status": "307",
            "redirect_to": "https://client.example/articles/title-loan-buyout-process-step-by-step",
            "inlinks": "4",
            "unique_inlinks": "4"
          },
          {
            "url": "https://client.example/articles/do-title-loans-affect-credit.html",
            "csv_row": 38,
            "status": "307",
            "redirect_to": "https://client.example/articles/do-title-loans-affect-credit",
            "inlinks": "9",
            "unique_inlinks": "6"
          },
          {
            "url": "https://client.example/articles/title-loan-collections-deficiency.html",
            "csv_row": 39,
            "status": "307",
            "redirect_to": "https://client.example/articles/title-loan-collections-deficiency",
            "inlinks": "16",
            "unique_inlinks": "10"
          },
          {
            "url": "https://client.example/articles/hiding-car-from-title-loan-repo.html",
            "csv_row": 40,
            "status": "307",
            "redirect_to": "https://client.example/articles/hiding-car-from-title-loan-repo",
            "inlinks": "2",
            "unique_inlinks": "2"
          },
          {
            "url": "https://client.example/articles/cant-pay-title-loan-this-week.html",
            "csv_row": 41,
            "status": "307",
            "redirect_to": "https://client.example/articles/cant-pay-title-loan-this-week",
            "inlinks": "9",
            "unique_inlinks": "6"
          },
          {
            "url": "https://client.example/articles/title-loan-and-bankruptcy.html",
            "csv_row": 42,
            "status": "307",
            "redirect_to": "https://client.example/articles/title-loan-and-bankruptcy",
            "inlinks": "3",
            "unique_inlinks": "3"
          },
          {
            "url": "https://client.example/articles/pay-down-title-loan-principal.html",
            "csv_row": 43,
            "status": "307",
            "redirect_to": "https://client.example/articles/pay-down-title-loan-principal",
            "inlinks": "18",
            "unique_inlinks": "14"
          },
          {
            "url": "https://client.example/articles/stuck-with-multiple-title-loans.html",
            "csv_row": 44,
            "status": "307",
            "redirect_to": "https://client.example/articles/stuck-with-multiple-title-loans",
            "inlinks": "3",
            "unique_inlinks": "3"
          },
          {
            "url": "https://client.example/articles/title-loan-junk-fees-add-ons.html",
            "csv_row": 45,
            "status": "307",
            "redirect_to": "https://client.example/articles/title-loan-junk-fees-add-ons",
            "inlinks": "2",
            "unique_inlinks": "2"
          },
          {
            "url": "https://client.example/articles/title-loan-calling-my-job-references.html",
            "csv_row": 46,
            "status": "307",
            "redirect_to": "https://client.example/articles/title-loan-calling-my-job-references",
            "inlinks": "3",
            "unique_inlinks": "3"
          },
          {
            "url": "https://client.example/articles/how-to-negotiate-with-title-loan-lender.html",
            "csv_row": 47,
            "status": "307",
            "redirect_to": "https://client.example/articles/how-to-negotiate-with-title-loan-lender",
            "inlinks": "23",
            "unique_inlinks": "19"
          },
          {
            "url": "https://client.example/articles/military-title-loan-illegal.html",
            "csv_row": 48,
            "status": "307",
            "redirect_to": "https://client.example/articles/military-title-loan-illegal",
            "inlinks": "2",
            "unique_inlinks": "2"
          },
          {
            "url": "https://client.example/articles/title-loan-gps-tracker-kill-switch.html",
            "csv_row": 49,
            "status": "307",
            "redirect_to": "https://client.example/articles/title-loan-gps-tracker-kill-switch",
            "inlinks": "2",
            "unique_inlinks": "2"
          },
          {
            "url": "https://client.example/es/articles/title-loan-gps-tracker-kill-switch.html",
            "csv_row": 53,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/title-loan-gps-tracker-kill-switch",
            "inlinks": "2",
            "unique_inlinks": "2"
          },
          {
            "url": "https://client.example/es/articles/sell-car-with-title-loan.html",
            "csv_row": 55,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/sell-car-with-title-loan",
            "inlinks": "2",
            "unique_inlinks": "2"
          },
          {
            "url": "https://client.example/es/articles/being-sued-by-title-loan-company.html",
            "csv_row": 56,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/being-sued-by-title-loan-company",
            "inlinks": "5",
            "unique_inlinks": "4"
          },
          {
            "url": "https://client.example/es/articles/title-loan-vs-payday-vs-personal-loan.html",
            "csv_row": 57,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/title-loan-vs-payday-vs-personal-loan",
            "inlinks": "11",
            "unique_inlinks": "10"
          },
          {
            "url": "https://client.example/es/articles/title-loan-calling-my-job-references.html",
            "csv_row": 58,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/title-loan-calling-my-job-references",
            "inlinks": "3",
            "unique_inlinks": "3"
          },
          {
            "url": "https://client.example/es/articles/repossessed-car-belongings-inside.html",
            "csv_row": 59,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/repossessed-car-belongings-inside",
            "inlinks": "2",
            "unique_inlinks": "2"
          },
          {
            "url": "https://client.example/es/articles/military-title-loan-illegal.html",
            "csv_row": 60,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/military-title-loan-illegal",
            "inlinks": "2",
            "unique_inlinks": "2"
          },
          {
            "url": "https://client.example/es/articles/do-title-loans-affect-credit.html",
            "csv_row": 61,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/do-title-loans-affect-credit",
            "inlinks": "9",
            "unique_inlinks": "6"
          },
          {
            "url": "https://client.example/es/articles/title-loan-refinance-buyout.html",
            "csv_row": 62,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/title-loan-refinance-buyout",
            "inlinks": "69",
            "unique_inlinks": "37"
          },
          {
            "url": "https://client.example/es/articles/title-loan-renewal-cycle.html",
            "csv_row": 63,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/title-loan-renewal-cycle",
            "inlinks": "12",
            "unique_inlinks": "9"
          },
          {
            "url": "https://client.example/es/articles/should-i-let-them-take-the-car.html",
            "csv_row": 64,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/should-i-let-them-take-the-car",
            "inlinks": "2",
            "unique_inlinks": "2"
          },
          {
            "url": "https://client.example/es/articles/cant-pay-title-loan-this-week.html",
            "csv_row": 65,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/cant-pay-title-loan-this-week",
            "inlinks": "9",
            "unique_inlinks": "6"
          },
          {
            "url": "https://client.example/es/articles/pay-down-title-loan-principal.html",
            "csv_row": 66,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/pay-down-title-loan-principal",
            "inlinks": "15",
            "unique_inlinks": "11"
          },
          {
            "url": "https://client.example/es/articles/can-they-take-my-car-title-loan.html",
            "csv_row": 67,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/can-they-take-my-car-title-loan",
            "inlinks": "13",
            "unique_inlinks": "10"
          },
          {
            "url": "https://client.example/es/articles/why-title-loan-balance-never-goes-down.html",
            "csv_row": 68,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/why-title-loan-balance-never-goes-down",
            "inlinks": "21",
            "unique_inlinks": "15"
          },
          {
            "url": "https://client.example/es/articles/how-much-can-i-save-refinancing-title-loan.html",
            "csv_row": 69,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/how-much-can-i-save-refinancing-title-loan",
            "inlinks": "6",
            "unique_inlinks": "5"
          },
          {
            "url": "https://client.example/es/articles/online-tribal-title-loan.html",
            "csv_row": 70,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/online-tribal-title-loan",
            "inlinks": "2",
            "unique_inlinks": "2"
          },
          {
            "url": "https://client.example/es/articles/title-loan-for-emergency-now-stuck.html",
            "csv_row": 71,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/title-loan-for-emergency-now-stuck",
            "inlinks": "2",
            "unique_inlinks": "2"
          },
          {
            "url": "https://client.example/es/articles/title-loan-myths.html",
            "csv_row": 72,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/title-loan-myths",
            "inlinks": "5",
            "unique_inlinks": "5"
          },
          {
            "url": "https://client.example/es/articles/title-loan-payoff-amount.html",
            "csv_row": 73,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/title-loan-payoff-amount",
            "inlinks": "16",
            "unique_inlinks": "12"
          },
          {
            "url": "https://client.example/es/articles/partner-took-out-title-loan.html",
            "csv_row": 74,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/partner-took-out-title-loan",
            "inlinks": "3",
            "unique_inlinks": "3"
          },
          {
            "url": "https://client.example/es/articles/where-to-get-title-loan-help.html",
            "csv_row": 75,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/where-to-get-title-loan-help",
            "inlinks": "24",
            "unique_inlinks": "17"
          },
          {
            "url": "https://client.example/es/articles/get-car-title-back-after-payoff.html",
            "csv_row": 76,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/get-car-title-back-after-payoff",
            "inlinks": "4",
            "unique_inlinks": "3"
          },
          {
            "url": "https://client.example/es/articles/title-loan-junk-fees-add-ons.html",
            "csv_row": 77,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/title-loan-junk-fees-add-ons",
            "inlinks": "2",
            "unique_inlinks": "2"
          },
          {
            "url": "https://client.example/es/articles/do-i-qualify-to-refinance-title-loan.html",
            "csv_row": 78,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/do-i-qualify-to-refinance-title-loan",
            "inlinks": "5",
            "unique_inlinks": "4"
          },
          {
            "url": "https://client.example/es/articles/title-loan-and-bankruptcy.html",
            "csv_row": 79,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/title-loan-and-bankruptcy",
            "inlinks": "3",
            "unique_inlinks": "3"
          },
          {
            "url": "https://client.example/es/articles/title-loan-buyout-process-step-by-step.html",
            "csv_row": 80,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/title-loan-buyout-process-step-by-step",
            "inlinks": "6",
            "unique_inlinks": "5"
          },
          {
            "url": "https://client.example/es/articles/is-my-title-loan-legal.html",
            "csv_row": 81,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/is-my-title-loan-legal",
            "inlinks": "9",
            "unique_inlinks": "7"
          },
          {
            "url": "https://client.example/es/articles/refinance-title-loan-now-vs-keep-paying.html",
            "csv_row": 82,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/refinance-title-loan-now-vs-keep-paying",
            "inlinks": "3",
            "unique_inlinks": "3"
          },
          {
            "url": "https://client.example/es/articles/hiding-car-from-title-loan-repo.html",
            "csv_row": 83,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/hiding-car-from-title-loan-repo",
            "inlinks": "2",
            "unique_inlinks": "2"
          },
          {
            "url": "https://client.example/es/articles/title-loan-refinance-lower-monthly-payment.html",
            "csv_row": 84,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/title-loan-refinance-lower-monthly-payment",
            "inlinks": "4",
            "unique_inlinks": "4"
          },
          {
            "url": "https://client.example/es/articles/can-title-loan-garnish-wages.html",
            "csv_row": 85,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/can-title-loan-garnish-wages",
            "inlinks": "4",
            "unique_inlinks": "3"
          },
          {
            "url": "https://client.example/es/articles/how-to-negotiate-with-title-loan-lender.html",
            "csv_row": 86,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/how-to-negotiate-with-title-loan-lender",
            "inlinks": "22",
            "unique_inlinks": "18"
          },
          {
            "url": "https://client.example/es/articles/behind-on-title-loan-repossession.html",
            "csv_row": 87,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/behind-on-title-loan-repossession",
            "inlinks": "26",
            "unique_inlinks": "16"
          },
          {
            "url": "https://client.example/es/articles/hours-cut-cant-keep-up-title-loan.html",
            "csv_row": 88,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/hours-cut-cant-keep-up-title-loan",
            "inlinks": "3",
            "unique_inlinks": "3"
          },
          {
            "url": "https://client.example/es/articles/title-loan-collections-deficiency.html",
            "csv_row": 89,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/title-loan-collections-deficiency",
            "inlinks": "16",
            "unique_inlinks": "10"
          },
          {
            "url": "https://client.example/es/articles/cosigned-title-loan-for-someone.html",
            "csv_row": 90,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/cosigned-title-loan-for-someone",
            "inlinks": "2",
            "unique_inlinks": "2"
          },
          {
            "url": "https://client.example/es/articles/stuck-with-multiple-title-loans.html",
            "csv_row": 91,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/stuck-with-multiple-title-loans",
            "inlinks": "2",
            "unique_inlinks": "2"
          },
          {
            "url": "https://client.example/es/articles/rolled-over-title-loan-again.html",
            "csv_row": 92,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/rolled-over-title-loan-again",
            "inlinks": "2",
            "unique_inlinks": "2"
          },
          {
            "url": "https://client.example/es/articles/stop-paying-title-loan-what-happens.html",
            "csv_row": 93,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/stop-paying-title-loan-what-happens",
            "inlinks": "2",
            "unique_inlinks": "2"
          },
          {
            "url": "https://client.example/articles/index.html",
            "csv_row": 169,
            "status": "307",
            "redirect_to": "https://client.example/articles/",
            "inlinks": "40",
            "unique_inlinks": "40"
          },
          {
            "url": "https://client.example/es/articles/index.html",
            "csv_row": 170,
            "status": "307",
            "redirect_to": "https://client.example/es/articles/",
            "inlinks": "40",
            "unique_inlinks": "40"
          }
        ],
        "fix": "Obtain valid link edges or inspect templates; repoint applicable hrefs to final URLs.",
        "effort": "2–4 template hours plus 2 QA hours (provisional)",
        "dependencies": "T01 and valid source/destination links",
        "reasoning": "Inlink aggregates show links to redirecting variants; source pages are unknown."
      },
      {
        "id": "C02",
        "group": "Content",
        "priority": "P3",
        "state": "Heuristic review",
        "title": "Review titles and descriptions against real search intent",
        "affected": [
          {
            "url": "https://client.example/",
            "csv_row": 2,
            "title_pixels": "529",
            "description_pixels": "1070",
            "missing_description": false
          },
          {
            "url": "https://client.example/es/",
            "csv_row": 3,
            "title_pixels": "682",
            "description_pixels": "1453",
            "missing_description": false
          },
          {
            "url": "https://client.example/articles/",
            "csv_row": 4,
            "title_pixels": "757",
            "description_pixels": "1231",
            "missing_description": false
          },
          {
            "url": "https://client.example/es/articles/",
            "csv_row": 50,
            "title_pixels": "859",
            "description_pixels": "1596",
            "missing_description": false
          },
          {
            "url": "https://client.example/articles/title-loan-gps-tracker-kill-switch",
            "csv_row": 51,
            "title_pixels": "420",
            "description_pixels": "1343",
            "missing_description": false
          },
          {
            "url": "https://client.example/articles/how-to-negotiate-with-title-loan-lender",
            "csv_row": 52,
            "title_pixels": "493",
            "description_pixels": "1147",
            "missing_description": false
          },
          {
            "url": "https://client.example/articles/military-title-loan-illegal",
            "csv_row": 54,
            "title_pixels": "398",
            "description_pixels": "1536",
            "missing_description": false
          },
          {
            "url": "https://client.example/articles/title-loan-calling-my-job-references",
            "csv_row": 94,
            "title_pixels": "467",
            "description_pixels": "1159",
            "missing_description": false
          },
          {
            "url": "https://client.example/articles/title-loan-junk-fees-add-ons",
            "csv_row": 95,
            "title_pixels": "470",
            "description_pixels": "1598",
            "missing_description": false
          },
          {
            "url": "https://client.example/articles/stuck-with-multiple-title-loans",
            "csv_row": 96,
            "title_pixels": "509",
            "description_pixels": "1260",
            "missing_description": false
          },
          {
            "url": "https://client.example/articles/pay-down-title-loan-principal",
            "csv_row": 97,
            "title_pixels": "463",
            "description_pixels": "1137",
            "missing_description": false
          },
          {
            "url": "https://client.example/articles/title-loan-and-bankruptcy",
            "csv_row": 98,
            "title_pixels": "466",
            "description_pixels": "1312",
            "missing_description": false
          },
          {
            "url": "https://client.example/articles/cant-pay-title-loan-this-week",
            "csv_row": 99,
            "title_pixels": "486",
            "description_pixels": "1279",
            "missing_description": false
          },
          {
            "url": "https://client.example/articles/title-loan-collections-deficiency",
            "csv_row": 100,
            "title_pixels": "419",
            "description_pixels": "1233",
            "missing_description": false
          },
          {
            "url": "https://client.example/articles/hiding-car-from-title-loan-repo",
            "csv_row": 101,
            "title_pixels": "493",
            "description_pixels": "1619",
            "missing_description": false
          },
          {
            "url": "https://client.example/articles/do-title-loans-affect-credit",
            "csv_row": 102,
            "title_pixels": "442",
            "description_pixels": "1288",
            "missing_description": false
          },
          {
            "url": "https://client.example/articles/title-loan-buyout-process-step-by-step",
            "csv_row": 103,
            "title_pixels": "437",
            "description_pixels": "1433",
            "missing_description": false
          },
          {
            "url": "https://client.example/articles/title-loan-refinance-buyout",
            "csv_row": 104,
            "title_pixels": "441",
            "description_pixels": "1266",
            "missing_description": false
          },
          {
            "url": "https://client.example/articles/do-i-qualify-to-refinance-title-loan",
            "csv_row": 105,
            "title_pixels": "450",
            "description_pixels": "1092",
            "missing_description": false
          },
          {
            "url": "https://client.example/articles/title-loan-refinance-lower-monthly-payment",
            "csv_row": 106,
            "title_pixels": "440",
            "description_pixels": "1096",
            "missing_description": false
          },
          {
            "url": "https://client.example/articles/sell-car-with-title-loan",
            "csv_row": 107,
            "title_pixels": "433",
            "description_pixels": "1251",
            "missing_description": false
          },
          {
            "url": "https://client.example/articles/being-sued-by-title-loan-company",
            "csv_row": 108,
            "title_pixels": "489",
            "description_pixels": "1585",
            "missing_description": false
          },
          {
            "url": "https://client.example/articles/cosigned-title-loan-for-someone",
            "csv_row": 109,
            "title_pixels": "534",
            "description_pixels": "1406",
            "missing_description": false
          },
          {
            "url": "https://client.example/articles/why-title-loan-balance-never-goes-down",
            "csv_row": 111,
            "title_pixels": "453",
            "description_pixels": "1293",
            "missing_description": false
          },
          {
            "url": "https://client.example/articles/behind-on-title-loan-repossession",
            "csv_row": 112,
            "title_pixels": "533",
            "description_pixels": "1298",
            "missing_description": false
          },
          {
            "url": "https://client.example/articles/is-my-title-loan-legal",
            "csv_row": 113,
            "title_pixels": "438",
            "description_pixels": "1462",
            "missing_description": false
          },
          {
            "url": "https://client.example/articles/can-they-take-my-car-title-loan",
            "csv_row": 114,
            "title_pixels": "449",
            "description_pixels": "1299",
            "missing_description": false
          },
          {
            "url": "https://client.example/articles/should-i-let-them-take-the-car",
            "csv_row": 115,
            "title_pixels": "491",
            "description_pixels": "1507",
            "missing_description": false
          },
          {
            "url": "https://client.example/articles/title-loan-renewal-cycle",
            "csv_row": 116,
            "title_pixels": "434",
            "description_pixels": "1259",
            "missing_description": false
          },
          {
            "url": "https://client.example/articles/title-loan-vs-payday-vs-personal-loan",
            "csv_row": 117,
            "title_pixels": "435",
            "description_pixels": "1322",
            "missing_description": false
          },
          {
            "url": "https://client.example/articles/get-car-title-back-after-payoff",
            "csv_row": 118,
            "title_pixels": "472",
            "description_pixels": "1377",
            "missing_description": false
          },
          {
            "url": "https://client.example/articles/how-much-can-i-save-refinancing-title-loan",
            "csv_row": 119,
            "title_pixels": "496",
            "description_pixels": "0",
            "missing_description": true
          },
          {
            "url": "https://client.example/articles/online-tribal-title-loan",
            "csv_row": 120,
            "title_pixels": "464",
            "description_pixels": "1801",
            "missing_description": false
          },
          {
            "url": "https://client.example/articles/title-loan-for-emergency-now-stuck",
            "csv_row": 121,
            "title_pixels": "447",
            "description_pixels": "1183",
            "missing_description": false
          },
          {
            "url": "https://client.example/articles/rolled-over-title-loan-again",
            "csv_row": 122,
            "title_pixels": "486",
            "description_pixels": "1222",
            "missing_description": false
          },
          {
            "url": "https://client.example/articles/title-loan-payoff-amount",
            "csv_row": 123,
            "title_pixels": "453",
            "description_pixels": "1339",
            "missing_description": false
          },
          {
            "url": "https://client.example/articles/repossessed-car-belongings-inside",
            "csv_row": 124,
            "title_pixels": "446",
            "description_pixels": "1570",
            "missing_description": false
          },
          {
            "url": "https://client.example/articles/can-title-loan-garnish-wages",
            "csv_row": 125,
            "title_pixels": "424",
            "description_pixels": "1457",
            "missing_description": false
          },
          {
            "url": "https://client.example/articles/where-to-get-title-loan-help",
            "csv_row": 126,
            "title_pixels": "474",
            "description_pixels": "1231",
            "missing_description": false
          },
          {
            "url": "https://client.example/articles/stop-paying-title-loan-what-happens",
            "csv_row": 127,
            "title_pixels": "501",
            "description_pixels": "1550",
            "missing_description": false
          },
          {
            "url": "https://client.example/articles/hours-cut-cant-keep-up-title-loan",
            "csv_row": 128,
            "title_pixels": "490",
            "description_pixels": "1458",
            "missing_description": false
          },
          {
            "url": "https://client.example/articles/partner-took-out-title-loan",
            "csv_row": 129,
            "title_pixels": "402",
            "description_pixels": "1441",
            "missing_description": false
          },
          {
            "url": "https://client.example/articles/title-loan-myths",
            "csv_row": 130,
            "title_pixels": "467",
            "description_pixels": "1248",
            "missing_description": false
          },
          {
            "url": "https://client.example/es/articles/stop-paying-title-loan-what-happens",
            "csv_row": 131,
            "title_pixels": "802",
            "description_pixels": "1656",
            "missing_description": false
          },
          {
            "url": "https://client.example/es/articles/stuck-with-multiple-title-loans",
            "csv_row": 132,
            "title_pixels": "892",
            "description_pixels": "1441",
            "missing_description": false
          },
          {
            "url": "https://client.example/es/articles/rolled-over-title-loan-again",
            "csv_row": 133,
            "title_pixels": "929",
            "description_pixels": "1187",
            "missing_description": false
          },
          {
            "url": "https://client.example/es/articles/title-loan-collections-deficiency",
            "csv_row": 134,
            "title_pixels": "877",
            "description_pixels": "1454",
            "missing_description": false
          },
          {
            "url": "https://client.example/es/articles/cosigned-title-loan-for-someone",
            "csv_row": 135,
            "title_pixels": "1026",
            "description_pixels": "1596",
            "missing_description": false
          },
          {
            "url": "https://client.example/es/articles/behind-on-title-loan-repossession",
            "csv_row": 136,
            "title_pixels": "1166",
            "description_pixels": "1555",
            "missing_description": false
          },
          {
            "url": "https://client.example/es/articles/hours-cut-cant-keep-up-title-loan",
            "csv_row": 137,
            "title_pixels": "1091",
            "description_pixels": "1587",
            "missing_description": false
          },
          {
            "url": "https://client.example/es/articles/can-title-loan-garnish-wages",
            "csv_row": 138,
            "title_pixels": "930",
            "description_pixels": "1598",
            "missing_description": false
          },
          {
            "url": "https://client.example/es/articles/how-to-negotiate-with-title-loan-lender",
            "csv_row": 139,
            "title_pixels": "1188",
            "description_pixels": "1600",
            "missing_description": false
          },
          {
            "url": "https://client.example/es/articles/hiding-car-from-title-loan-repo",
            "csv_row": 140,
            "title_pixels": "897",
            "description_pixels": "1778",
            "missing_description": false
          },
          {
            "url": "https://client.example/es/articles/refinance-title-loan-now-vs-keep-paying",
            "csv_row": 141,
            "title_pixels": "824",
            "description_pixels": "1375",
            "missing_description": false
          },
          {
            "url": "https://client.example/es/articles/title-loan-refinance-lower-monthly-payment",
            "csv_row": 142,
            "title_pixels": "834",
            "description_pixels": "1163",
            "missing_description": false
          },
          {
            "url": "https://client.example/es/articles/is-my-title-loan-legal",
            "csv_row": 143,
            "title_pixels": "921",
            "description_pixels": "1682",
            "missing_description": false
          },
          {
            "url": "https://client.example/es/articles/title-loan-and-bankruptcy",
            "csv_row": 144,
            "title_pixels": "881",
            "description_pixels": "1597",
            "missing_description": false
          },
          {
            "url": "https://client.example/es/articles/do-i-qualify-to-refinance-title-loan",
            "csv_row": 145,
            "title_pixels": "956",
            "description_pixels": "1392",
            "missing_description": false
          },
          {
            "url": "https://client.example/es/articles/title-loan-buyout-process-step-by-step",
            "csv_row": 146,
            "title_pixels": "946",
            "description_pixels": "1637",
            "missing_description": false
          },
          {
            "url": "https://client.example/es/articles/title-loan-junk-fees-add-ons",
            "csv_row": 147,
            "title_pixels": "850",
            "description_pixels": "1703",
            "missing_description": false
          },
          {
            "url": "https://client.example/es/articles/get-car-title-back-after-payoff",
            "csv_row": 148,
            "title_pixels": "914",
            "description_pixels": "1596",
            "missing_description": false
          },
          {
            "url": "https://client.example/es/articles/partner-took-out-title-loan",
            "csv_row": 149,
            "title_pixels": "864",
            "description_pixels": "1592",
            "missing_description": false
          },
          {
            "url": "https://client.example/es/articles/where-to-get-title-loan-help",
            "csv_row": 150,
            "title_pixels": "999",
            "description_pixels": "1595",
            "missing_description": false
          },
          {
            "url": "https://client.example/es/articles/online-tribal-title-loan",
            "csv_row": 151,
            "title_pixels": "1043",
            "description_pixels": "2296",
            "missing_description": false
          },
          {
            "url": "https://client.example/es/articles/title-loan-myths",
            "csv_row": 152,
            "title_pixels": "1035",
            "description_pixels": "1575",
            "missing_description": false
          },
          {
            "url": "https://client.example/es/articles/title-loan-payoff-amount",
            "csv_row": 153,
            "title_pixels": "1007",
            "description_pixels": "1514",
            "missing_description": false
          },
          {
            "url": "https://client.example/es/articles/why-title-loan-balance-never-goes-down",
            "csv_row": 154,
            "title_pixels": "946",
            "description_pixels": "1245",
            "missing_description": false
          },
          {
            "url": "https://client.example/es/articles/title-loan-for-emergency-now-stuck",
            "csv_row": 155,
            "title_pixels": "977",
            "description_pixels": "1362",
            "missing_description": false
          },
          {
            "url": "https://client.example/es/articles/can-they-take-my-car-title-loan",
            "csv_row": 156,
            "title_pixels": "1156",
            "description_pixels": "1628",
            "missing_description": false
          },
          {
            "url": "https://client.example/es/articles/how-much-can-i-save-refinancing-title-loan",
            "csv_row": 157,
            "title_pixels": "972",
            "description_pixels": "0",
            "missing_description": true
          },
          {
            "url": "https://client.example/es/articles/cant-pay-title-loan-this-week",
            "csv_row": 158,
            "title_pixels": "1295",
            "description_pixels": "1484",
            "missing_description": false
          },
          {
            "url": "https://client.example/es/articles/should-i-let-them-take-the-car",
            "csv_row": 159,
            "title_pixels": "1050",
            "description_pixels": "1692",
            "missing_description": false
          },
          {
            "url": "https://client.example/es/articles/do-title-loans-affect-credit",
            "csv_row": 160,
            "title_pixels": "1080",
            "description_pixels": "1645",
            "missing_description": false
          },
          {
            "url": "https://client.example/es/articles/title-loan-renewal-cycle",
            "csv_row": 161,
            "title_pixels": "990",
            "description_pixels": "1338",
            "missing_description": false
          },
          {
            "url": "https://client.example/es/articles/pay-down-title-loan-principal",
            "csv_row": 162,
            "title_pixels": "975",
            "description_pixels": "1403",
            "missing_description": false
          },
          {
            "url": "https://client.example/es/articles/repossessed-car-belongings-inside",
            "csv_row": 163,
            "title_pixels": "797",
            "description_pixels": "1752",
            "missing_description": false
          },
          {
            "url": "https://client.example/es/articles/title-loan-refinance-buyout",
            "csv_row": 164,
            "title_pixels": "1093",
            "description_pixels": "1366",
            "missing_description": false
          },
          {
            "url": "https://client.example/es/articles/title-loan-calling-my-job-references",
            "csv_row": 165,
            "title_pixels": "1174",
            "description_pixels": "1324",
            "missing_description": false
          },
          {
            "url": "https://client.example/es/articles/military-title-loan-illegal",
            "csv_row": 166,
            "title_pixels": "1164",
            "description_pixels": "1851",
            "missing_description": false
          },
          {
            "url": "https://client.example/es/articles/title-loan-vs-payday-vs-personal-loan",
            "csv_row": 167,
            "title_pixels": "1233",
            "description_pixels": "1560",
            "missing_description": false
          },
          {
            "url": "https://client.example/es/articles/being-sued-by-title-loan-company",
            "csv_row": 168,
            "title_pixels": "970",
            "description_pixels": "2040",
            "missing_description": false
          },
          {
            "url": "https://client.example/es/articles/sell-car-with-title-loan",
            "csv_row": 171,
            "title_pixels": "1001",
            "description_pixels": "1654",
            "missing_description": false
          },
          {
            "url": "https://client.example/es/articles/title-loan-gps-tracker-kill-switch",
            "csv_row": 172,
            "title_pixels": "1233",
            "description_pixels": "1522",
            "missing_description": false
          }
        ],
        "fix": "Use real query evidence before editing priority page snippets; review blank descriptions.",
        "effort": "2–4 hours for first 10 priority pages (provisional)",
        "dependencies": "Confirmed business goals and keyword/ranking baseline",
        "reasoning": "600/1050 pixel values are review heuristics, not Google limits."
      },
      {
        "id": "B01",
        "group": "Backlinks",
        "priority": "P2",
        "state": "Missing evidence",
        "title": "Obtain provider backlink and competitor research",
        "affected": [],
        "fix": "Review actual Semrush/Ahrefs responses in the linked provider runs.",
        "effort": "2–4 hours after usable access",
        "dependencies": "Target-specific provider data",
        "reasoning": "A crawl cannot establish backlink quality, toxicity or search visibility."
      }
    ],
    "unverified_checks": [
      "Current Mantas Auk engagement and owner business goals",
      "Crawl rendering/robots/settings",
      "Sitebulb findings",
      "Sitemap, hreflang, Search Console and analytics",
      "Financial claims and Spanish translation expert review"
    ],
    "website_modified": false
  },
  "tools": [
    {
      "key": "semrush",
      "name": "Semrush",
      "label": "Simulated output",
      "state": "simulated",
      "simulated": true,
      "message": "42 organic keywords · 96 estimated visits/month · illustrative US database scenario",
      "metrics": [
        {
          "label": "Organic keywords",
          "value": 42
        },
        {
          "label": "Estimated visits / month",
          "value": 96
        },
        {
          "label": "Authority Score",
          "value": 16
        }
      ],
      "keywords": [
        {
          "keyword": "title loan help texas",
          "volume": 720,
          "difficulty": 31,
          "position": 28,
          "previous": 34,
          "change": 6,
          "url": "https://client.example/",
          "csv_row": 2,
          "simulated": true
        },
        {
          "keyword": "how to get out of a title loan",
          "volume": 2400,
          "difficulty": 42,
          "position": 37,
          "previous": 43,
          "change": 6,
          "url": "https://client.example/articles/where-to-get-title-loan-help",
          "csv_row": 126,
          "simulated": true
        },
        {
          "keyword": "title loan buyout texas",
          "volume": 320,
          "difficulty": 24,
          "position": 18,
          "previous": 23,
          "change": 5,
          "url": "https://client.example/articles/title-loan-buyout-process-step-by-step",
          "csv_row": 103,
          "simulated": true
        },
        {
          "keyword": "refinance title loan",
          "volume": 1600,
          "difficulty": 46,
          "position": 46,
          "previous": 39,
          "change": -7,
          "url": "https://client.example/articles/title-loan-refinance-buyout",
          "csv_row": 104,
          "simulated": true
        },
        {
          "keyword": "negotiate title loan payoff",
          "volume": 390,
          "difficulty": 27,
          "position": 19,
          "previous": 25,
          "change": 6,
          "url": "https://client.example/articles/how-to-negotiate-with-title-loan-lender",
          "csv_row": 52,
          "simulated": true
        },
        {
          "keyword": "stop title loan repossession texas",
          "volume": 260,
          "difficulty": 29,
          "position": 24,
          "previous": 31,
          "change": 7,
          "url": "https://client.example/articles/behind-on-title-loan-repossession",
          "csv_row": 112,
          "simulated": true
        },
        {
          "keyword": "title loan payoff amount",
          "volume": 480,
          "difficulty": 22,
          "position": 14,
          "previous": 18,
          "change": 4,
          "url": "https://client.example/articles/title-loan-payoff-amount",
          "csv_row": 123,
          "simulated": true
        },
        {
          "keyword": "sell a car with a title loan",
          "volume": 880,
          "difficulty": 36,
          "position": 41,
          "previous": 38,
          "change": -3,
          "url": "https://client.example/articles/sell-car-with-title-loan",
          "csv_row": 107,
          "simulated": true
        },
        {
          "keyword": "title loan lower monthly payment",
          "volume": 210,
          "difficulty": 21,
          "position": 31,
          "previous": 36,
          "change": 5,
          "url": "https://client.example/articles/title-loan-refinance-lower-monthly-payment",
          "csv_row": 106,
          "simulated": true
        },
        {
          "keyword": "are title loans legal in texas",
          "volume": 1300,
          "difficulty": 48,
          "position": 52,
          "previous": 58,
          "change": 6,
          "url": "https://client.example/articles/is-my-title-loan-legal",
          "csv_row": 113,
          "simulated": true
        },
        {
          "keyword": "ayuda con préstamos de título texas",
          "volume": 170,
          "difficulty": 23,
          "position": 57,
          "previous": 64,
          "change": 7,
          "url": "https://client.example/es/",
          "csv_row": 3,
          "simulated": true
        },
        {
          "keyword": "salir de préstamo sobre título",
          "volume": 140,
          "difficulty": 18,
          "position": 63,
          "previous": 69,
          "change": 6,
          "url": "https://client.example/es/articles/where-to-get-title-loan-help",
          "csv_row": 150,
          "simulated": true
        }
      ],
      "competitors": [
        {
          "domain": "texas-title-help.example",
          "keywords": 186,
          "traffic": 740,
          "shared": 14,
          "missing": 32
        },
        {
          "domain": "auto-loan-relief.example",
          "keywords": 312,
          "traffic": 1260,
          "shared": 19,
          "missing": 47
        },
        {
          "domain": "title-payoff-guide.example",
          "keywords": 94,
          "traffic": 380,
          "shared": 9,
          "missing": 21
        }
      ],
      "actions": []
    },
    {
      "key": "ahrefs",
      "name": "Ahrefs",
      "label": "Simulated output",
      "state": "simulated",
      "simulated": true,
      "message": "38 organic keywords · 84 estimated visits/month · 44 referring domains · illustrative scenario",
      "metrics": [
        {
          "label": "Domain Rating",
          "value": 12
        },
        {
          "label": "Referring domains",
          "value": 44
        },
        {
          "label": "Backlinks",
          "value": 96
        }
      ],
      "visibility": [
        {
          "month": "May",
          "traffic": 42
        },
        {
          "month": "Jun",
          "traffic": 51
        },
        {
          "month": "Jul",
          "traffic": 63
        },
        {
          "month": "Aug",
          "traffic": 72
        },
        {
          "month": "Sep",
          "traffic": 79
        },
        {
          "month": "Oct",
          "traffic": 84
        }
      ],
      "backlinks": [
        {
          "source": "https://texas-consumer-guide.example/resources",
          "rating": 31,
          "anchor": "title loan help",
          "follow": "Follow",
          "status": "Live",
          "target": "https://client.example/",
          "csv_row": 2,
          "simulated": true
        },
        {
          "source": "https://community-money.example/vehicle-debt",
          "rating": 24,
          "anchor": "loan payoff guide",
          "follow": "Follow",
          "status": "Live",
          "target": "https://client.example/articles/title-loan-payoff-amount",
          "csv_row": 123,
          "simulated": true
        },
        {
          "source": "https://local-services.example/auto-finance",
          "rating": 18,
          "anchor": "website",
          "follow": "Nofollow",
          "status": "Live",
          "target": "https://client.example/",
          "csv_row": 2,
          "simulated": true
        },
        {
          "source": "https://budget-journal.example/title-loan-options",
          "rating": 27,
          "anchor": "refinancing options",
          "follow": "Follow",
          "status": "Live",
          "target": "https://client.example/articles/title-loan-refinance-buyout",
          "csv_row": 104,
          "simulated": true
        },
        {
          "source": "https://regional-directory.example/businesses",
          "rating": 12,
          "anchor": "company profile",
          "follow": "Nofollow",
          "status": "Live",
          "target": "https://client.example/",
          "csv_row": 2,
          "simulated": true
        },
        {
          "source": "https://money-resource.example/texas",
          "rating": 9,
          "anchor": "title loan support",
          "follow": "Follow",
          "status": "Lost",
          "target": "https://client.example/",
          "csv_row": 2,
          "simulated": true
        }
      ],
      "actions": []
    },
    {
      "key": "sitebulb",
      "name": "Sitebulb",
      "label": "Simulated output",
      "state": "simulated",
      "simulated": true,
      "message": "5 illustrated hint groups · 171 URLs used as the scenario scope · no Sitebulb crawl performed",
      "metrics": [
        {
          "label": "Example audit score",
          "value": "71 / 100"
        },
        {
          "label": "Hint groups",
          "value": 5
        },
        {
          "label": "Scope from real crawl",
          "value": 171
        }
      ],
      "hints": [
        {
          "id": "SB01",
          "priority": "High",
          "title": "Canonical points to a redirect",
          "affected": [
            {
              "url": "https://client.example/sms-terms",
              "csv_row": 8,
              "canonical": "https://client.example/sms-terms.html",
              "canonical_csv_row": 7,
              "canonical_status": "307",
              "redirect_to": "https://client.example/sms-terms"
            },
            {
              "url": "https://client.example/privacy",
              "csv_row": 9,
              "canonical": "https://client.example/privacy.html",
              "canonical_csv_row": 6,
              "canonical_status": "307",
              "redirect_to": "https://client.example/privacy"
            },
            {
              "url": "https://client.example/articles/title-loan-gps-tracker-kill-switch",
              "csv_row": 51,
              "canonical": "https://client.example/articles/title-loan-gps-tracker-kill-switch.html",
              "canonical_csv_row": 49,
              "canonical_status": "307",
              "redirect_to": "https://client.example/articles/title-loan-gps-tracker-kill-switch"
            },
            {
              "url": "https://client.example/articles/how-to-negotiate-with-title-loan-lender",
              "csv_row": 52,
              "canonical": "https://client.example/articles/how-to-negotiate-with-title-loan-lender.html",
              "canonical_csv_row": 47,
              "canonical_status": "307",
              "redirect_to": "https://client.example/articles/how-to-negotiate-with-title-loan-lender"
            },
            {
              "url": "https://client.example/articles/military-title-loan-illegal",
              "csv_row": 54,
              "canonical": "https://client.example/articles/military-title-loan-illegal.html",
              "canonical_csv_row": 48,
              "canonical_status": "307",
              "redirect_to": "https://client.example/articles/military-title-loan-illegal"
            },
            {
              "url": "https://client.example/articles/title-loan-calling-my-job-references",
              "csv_row": 94,
              "canonical": "https://client.example/articles/title-loan-calling-my-job-references.html",
              "canonical_csv_row": 46,
              "canonical_status": "307",
              "redirect_to": "https://client.example/articles/title-loan-calling-my-job-references"
            },
            {
              "url": "https://client.example/articles/title-loan-junk-fees-add-ons",
              "csv_row": 95,
              "canonical": "https://client.example/articles/title-loan-junk-fees-add-ons.html",
              "canonical_csv_row": 45,
              "canonical_status": "307",
              "redirect_to": "https://client.example/articles/title-loan-junk-fees-add-ons"
            },
            {
              "url": "https://client.example/articles/stuck-with-multiple-title-loans",
              "csv_row": 96,
              "canonical": "https://client.example/articles/stuck-with-multiple-title-loans.html",
              "canonical_csv_row": 44,
              "canonical_status": "307",
              "redirect_to": "https://client.example/articles/stuck-with-multiple-title-loans"
            },
            {
              "url": "https://client.example/articles/pay-down-title-loan-principal",
              "csv_row": 97,
              "canonical": "https://client.example/articles/pay-down-title-loan-principal.html",
              "canonical_csv_row": 43,
              "canonical_status": "307",
              "redirect_to": "https://client.example/articles/pay-down-title-loan-principal"
            },
            {
              "url": "https://client.example/articles/title-loan-and-bankruptcy",
              "csv_row": 98,
              "canonical": "https://client.example/articles/title-loan-and-bankruptcy.html",
              "canonical_csv_row": 42,
              "canonical_status": "307",
              "redirect_to": "https://client.example/articles/title-loan-and-bankruptcy"
            },
            {
              "url": "https://client.example/articles/cant-pay-title-loan-this-week",
              "csv_row": 99,
              "canonical": "https://client.example/articles/cant-pay-title-loan-this-week.html",
              "canonical_csv_row": 41,
              "canonical_status": "307",
              "redirect_to": "https://client.example/articles/cant-pay-title-loan-this-week"
            },
            {
              "url": "https://client.example/articles/title-loan-collections-deficiency",
              "csv_row": 100,
              "canonical": "https://client.example/articles/title-loan-collections-deficiency.html",
              "canonical_csv_row": 39,
              "canonical_status": "307",
              "redirect_to": "https://client.example/articles/title-loan-collections-deficiency"
            },
            {
              "url": "https://client.example/articles/hiding-car-from-title-loan-repo",
              "csv_row": 101,
              "canonical": "https://client.example/articles/hiding-car-from-title-loan-repo.html",
              "canonical_csv_row": 40,
              "canonical_status": "307",
              "redirect_to": "https://client.example/articles/hiding-car-from-title-loan-repo"
            },
            {
              "url": "https://client.example/articles/do-title-loans-affect-credit",
              "csv_row": 102,
              "canonical": "https://client.example/articles/do-title-loans-affect-credit.html",
              "canonical_csv_row": 38,
              "canonical_status": "307",
              "redirect_to": "https://client.example/articles/do-title-loans-affect-credit"
            },
            {
              "url": "https://client.example/articles/title-loan-buyout-process-step-by-step",
              "csv_row": 103,
              "canonical": "https://client.example/articles/title-loan-buyout-process-step-by-step.html",
              "canonical_csv_row": 37,
              "canonical_status": "307",
              "redirect_to": "https://client.example/articles/title-loan-buyout-process-step-by-step"
            },
            {
              "url": "https://client.example/articles/title-loan-refinance-buyout",
              "csv_row": 104,
              "canonical": "https://client.example/articles/title-loan-refinance-buyout.html",
              "canonical_csv_row": 36,
              "canonical_status": "307",
              "redirect_to": "https://client.example/articles/title-loan-refinance-buyout"
            },
            {
              "url": "https://client.example/articles/do-i-qualify-to-refinance-title-loan",
              "csv_row": 105,
              "canonical": "https://client.example/articles/do-i-qualify-to-refinance-title-loan.html",
              "canonical_csv_row": 35,
              "canonical_status": "307",
              "redirect_to": "https://client.example/articles/do-i-qualify-to-refinance-title-loan"
            },
            {
              "url": "https://client.example/articles/title-loan-refinance-lower-monthly-payment",
              "csv_row": 106,
              "canonical": "https://client.example/articles/title-loan-refinance-lower-monthly-payment.html",
              "canonical_csv_row": 34,
              "canonical_status": "307",
              "redirect_to": "https://client.example/articles/title-loan-refinance-lower-monthly-payment"
            },
            {
              "url": "https://client.example/articles/sell-car-with-title-loan",
              "csv_row": 107,
              "canonical": "https://client.example/articles/sell-car-with-title-loan.html",
              "canonical_csv_row": 33,
              "canonical_status": "307",
              "redirect_to": "https://client.example/articles/sell-car-with-title-loan"
            },
            {
              "url": "https://client.example/articles/being-sued-by-title-loan-company",
              "csv_row": 108,
              "canonical": "https://client.example/articles/being-sued-by-title-loan-company.html",
              "canonical_csv_row": 32,
              "canonical_status": "307",
              "redirect_to": "https://client.example/articles/being-sued-by-title-loan-company"
            },
            {
              "url": "https://client.example/articles/cosigned-title-loan-for-someone",
              "csv_row": 109,
              "canonical": "https://client.example/articles/cosigned-title-loan-for-someone.html",
              "canonical_csv_row": 31,
              "canonical_status": "307",
              "redirect_to": "https://client.example/articles/cosigned-title-loan-for-someone"
            },
            {
              "url": "https://client.example/articles/refinance-title-loan-now-vs-keep-paying",
              "csv_row": 110,
              "canonical": "https://client.example/articles/refinance-title-loan-now-vs-keep-paying.html",
              "canonical_csv_row": 30,
              "canonical_status": "307",
              "redirect_to": "https://client.example/articles/refinance-title-loan-now-vs-keep-paying"
            },
            {
              "url": "https://client.example/articles/why-title-loan-balance-never-goes-down",
              "csv_row": 111,
              "canonical": "https://client.example/articles/why-title-loan-balance-never-goes-down.html",
              "canonical_csv_row": 27,
              "canonical_status": "307",
              "redirect_to": "https://client.example/articles/why-title-loan-balance-never-goes-down"
            },
            {
              "url": "https://client.example/articles/behind-on-title-loan-repossession",
              "csv_row": 112,
              "canonical": "https://client.example/articles/behind-on-title-loan-repossession.html",
              "canonical_csv_row": 28,
              "canonical_status": "307",
              "redirect_to": "https://client.example/articles/behind-on-title-loan-repossession"
            },
            {
              "url": "https://client.example/articles/is-my-title-loan-legal",
              "csv_row": 113,
              "canonical": "https://client.example/articles/is-my-title-loan-legal.html",
              "canonical_csv_row": 26,
              "canonical_status": "307",
              "redirect_to": "https://client.example/articles/is-my-title-loan-legal"
            },
            {
              "url": "https://client.example/articles/can-they-take-my-car-title-loan",
              "csv_row": 114,
              "canonical": "https://client.example/articles/can-they-take-my-car-title-loan.html",
              "canonical_csv_row": 29,
              "canonical_status": "307",
              "redirect_to": "https://client.example/articles/can-they-take-my-car-title-loan"
            },
            {
              "url": "https://client.example/articles/should-i-let-them-take-the-car",
              "csv_row": 115,
              "canonical": "https://client.example/articles/should-i-let-them-take-the-car.html",
              "canonical_csv_row": 25,
              "canonical_status": "307",
              "redirect_to": "https://client.example/articles/should-i-let-them-take-the-car"
            },
            {
              "url": "https://client.example/articles/title-loan-renewal-cycle",
              "csv_row": 116,
              "canonical": "https://client.example/articles/title-loan-renewal-cycle.html",
              "canonical_csv_row": 24,
              "canonical_status": "307",
              "redirect_to": "https://client.example/articles/title-loan-renewal-cycle"
            },
            {
              "url": "https://client.example/articles/title-loan-vs-payday-vs-personal-loan",
              "csv_row": 117,
              "canonical": "https://client.example/articles/title-loan-vs-payday-vs-personal-loan.html",
              "canonical_csv_row": 23,
              "canonical_status": "307",
              "redirect_to": "https://client.example/articles/title-loan-vs-payday-vs-personal-loan"
            },
            {
              "url": "https://client.example/articles/get-car-title-back-after-payoff",
              "csv_row": 118,
              "canonical": "https://client.example/articles/get-car-title-back-after-payoff.html",
              "canonical_csv_row": 21,
              "canonical_status": "307",
              "redirect_to": "https://client.example/articles/get-car-title-back-after-payoff"
            },
            {
              "url": "https://client.example/articles/how-much-can-i-save-refinancing-title-loan",
              "csv_row": 119,
              "canonical": "https://client.example/articles/how-much-can-i-save-refinancing-title-loan.html",
              "canonical_csv_row": 22,
              "canonical_status": "307",
              "redirect_to": "https://client.example/articles/how-much-can-i-save-refinancing-title-loan"
            },
            {
              "url": "https://client.example/articles/online-tribal-title-loan",
              "csv_row": 120,
              "canonical": "https://client.example/articles/online-tribal-title-loan.html",
              "canonical_csv_row": 20,
              "canonical_status": "307",
              "redirect_to": "https://client.example/articles/online-tribal-title-loan"
            },
            {
              "url": "https://client.example/articles/title-loan-for-emergency-now-stuck",
              "csv_row": 121,
              "canonical": "https://client.example/articles/title-loan-for-emergency-now-stuck.html",
              "canonical_csv_row": 18,
              "canonical_status": "307",
              "redirect_to": "https://client.example/articles/title-loan-for-emergency-now-stuck"
            },
            {
              "url": "https://client.example/articles/rolled-over-title-loan-again",
              "csv_row": 122,
              "canonical": "https://client.example/articles/rolled-over-title-loan-again.html",
              "canonical_csv_row": 16,
              "canonical_status": "307",
              "redirect_to": "https://client.example/articles/rolled-over-title-loan-again"
            },
            {
              "url": "https://client.example/articles/title-loan-payoff-amount",
              "csv_row": 123,
              "canonical": "https://client.example/articles/title-loan-payoff-amount.html",
              "canonical_csv_row": 17,
              "canonical_status": "307",
              "redirect_to": "https://client.example/articles/title-loan-payoff-amount"
            },
            {
              "url": "https://client.example/articles/repossessed-car-belongings-inside",
              "csv_row": 124,
              "canonical": "https://client.example/articles/repossessed-car-belongings-inside.html",
              "canonical_csv_row": 19,
              "canonical_status": "307",
              "redirect_to": "https://client.example/articles/repossessed-car-belongings-inside"
            },
            {
              "url": "https://client.example/articles/can-title-loan-garnish-wages",
              "csv_row": 125,
              "canonical": "https://client.example/articles/can-title-loan-garnish-wages.html",
              "canonical_csv_row": 14,
              "canonical_status": "307",
              "redirect_to": "https://client.example/articles/can-title-loan-garnish-wages"
            },
            {
              "url": "https://client.example/articles/where-to-get-title-loan-help",
              "csv_row": 126,
              "canonical": "https://client.example/articles/where-to-get-title-loan-help.html",
              "canonical_csv_row": 13,
              "canonical_status": "307",
              "redirect_to": "https://client.example/articles/where-to-get-title-loan-help"
            },
            {
              "url": "https://client.example/articles/stop-paying-title-loan-what-happens",
              "csv_row": 127,
              "canonical": "https://client.example/articles/stop-paying-title-loan-what-happens.html",
              "canonical_csv_row": 12,
              "canonical_status": "307",
              "redirect_to": "https://client.example/articles/stop-paying-title-loan-what-happens"
            },
            {
              "url": "https://client.example/articles/hours-cut-cant-keep-up-title-loan",
              "csv_row": 128,
              "canonical": "https://client.example/articles/hours-cut-cant-keep-up-title-loan.html",
              "canonical_csv_row": 11,
              "canonical_status": "307",
              "redirect_to": "https://client.example/articles/hours-cut-cant-keep-up-title-loan"
            },
            {
              "url": "https://client.example/articles/partner-took-out-title-loan",
              "csv_row": 129,
              "canonical": "https://client.example/articles/partner-took-out-title-loan.html",
              "canonical_csv_row": 15,
              "canonical_status": "307",
              "redirect_to": "https://client.example/articles/partner-took-out-title-loan"
            },
            {
              "url": "https://client.example/articles/title-loan-myths",
              "csv_row": 130,
              "canonical": "https://client.example/articles/title-loan-myths.html",
              "canonical_csv_row": 10,
              "canonical_status": "307",
              "redirect_to": "https://client.example/articles/title-loan-myths"
            },
            {
              "url": "https://client.example/es/articles/stop-paying-title-loan-what-happens",
              "csv_row": 131,
              "canonical": "https://client.example/es/articles/stop-paying-title-loan-what-happens.html",
              "canonical_csv_row": 93,
              "canonical_status": "307",
              "redirect_to": "https://client.example/es/articles/stop-paying-title-loan-what-happens"
            },
            {
              "url": "https://client.example/es/articles/stuck-with-multiple-title-loans",
              "csv_row": 132,
              "canonical": "https://client.example/es/articles/stuck-with-multiple-title-loans.html",
              "canonical_csv_row": 91,
              "canonical_status": "307",
              "redirect_to": "https://client.example/es/articles/stuck-with-multiple-title-loans"
            },
            {
              "url": "https://client.example/es/articles/rolled-over-title-loan-again",
              "csv_row": 133,
              "canonical": "https://client.example/es/articles/rolled-over-title-loan-again.html",
              "canonical_csv_row": 92,
              "canonical_status": "307",
              "redirect_to": "https://client.example/es/articles/rolled-over-title-loan-again"
            },
            {
              "url": "https://client.example/es/articles/title-loan-collections-deficiency",
              "csv_row": 134,
              "canonical": "https://client.example/es/articles/title-loan-collections-deficiency.html",
              "canonical_csv_row": 89,
              "canonical_status": "307",
              "redirect_to": "https://client.example/es/articles/title-loan-collections-deficiency"
            },
            {
              "url": "https://client.example/es/articles/cosigned-title-loan-for-someone",
              "csv_row": 135,
              "canonical": "https://client.example/es/articles/cosigned-title-loan-for-someone.html",
              "canonical_csv_row": 90,
              "canonical_status": "307",
              "redirect_to": "https://client.example/es/articles/cosigned-title-loan-for-someone"
            },
            {
              "url": "https://client.example/es/articles/behind-on-title-loan-repossession",
              "csv_row": 136,
              "canonical": "https://client.example/es/articles/behind-on-title-loan-repossession.html",
              "canonical_csv_row": 87,
              "canonical_status": "307",
              "redirect_to": "https://client.example/es/articles/behind-on-title-loan-repossession"
            },
            {
              "url": "https://client.example/es/articles/hours-cut-cant-keep-up-title-loan",
              "csv_row": 137,
              "canonical": "https://client.example/es/articles/hours-cut-cant-keep-up-title-loan.html",
              "canonical_csv_row": 88,
              "canonical_status": "307",
              "redirect_to": "https://client.example/es/articles/hours-cut-cant-keep-up-title-loan"
            },
            {
              "url": "https://client.example/es/articles/can-title-loan-garnish-wages",
              "csv_row": 138,
              "canonical": "https://client.example/es/articles/can-title-loan-garnish-wages.html",
              "canonical_csv_row": 85,
              "canonical_status": "307",
              "redirect_to": "https://client.example/es/articles/can-title-loan-garnish-wages"
            },
            {
              "url": "https://client.example/es/articles/how-to-negotiate-with-title-loan-lender",
              "csv_row": 139,
              "canonical": "https://client.example/es/articles/how-to-negotiate-with-title-loan-lender.html",
              "canonical_csv_row": 86,
              "canonical_status": "307",
              "redirect_to": "https://client.example/es/articles/how-to-negotiate-with-title-loan-lender"
            },
            {
              "url": "https://client.example/es/articles/hiding-car-from-title-loan-repo",
              "csv_row": 140,
              "canonical": "https://client.example/es/articles/hiding-car-from-title-loan-repo.html",
              "canonical_csv_row": 83,
              "canonical_status": "307",
              "redirect_to": "https://client.example/es/articles/hiding-car-from-title-loan-repo"
            },
            {
              "url": "https://client.example/es/articles/refinance-title-loan-now-vs-keep-paying",
              "csv_row": 141,
              "canonical": "https://client.example/es/articles/refinance-title-loan-now-vs-keep-paying.html",
              "canonical_csv_row": 82,
              "canonical_status": "307",
              "redirect_to": "https://client.example/es/articles/refinance-title-loan-now-vs-keep-paying"
            },
            {
              "url": "https://client.example/es/articles/title-loan-refinance-lower-monthly-payment",
              "csv_row": 142,
              "canonical": "https://client.example/es/articles/title-loan-refinance-lower-monthly-payment.html",
              "canonical_csv_row": 84,
              "canonical_status": "307",
              "redirect_to": "https://client.example/es/articles/title-loan-refinance-lower-monthly-payment"
            },
            {
              "url": "https://client.example/es/articles/is-my-title-loan-legal",
              "csv_row": 143,
              "canonical": "https://client.example/es/articles/is-my-title-loan-legal.html",
              "canonical_csv_row": 81,
              "canonical_status": "307",
              "redirect_to": "https://client.example/es/articles/is-my-title-loan-legal"
            },
            {
              "url": "https://client.example/es/articles/title-loan-and-bankruptcy",
              "csv_row": 144,
              "canonical": "https://client.example/es/articles/title-loan-and-bankruptcy.html",
              "canonical_csv_row": 79,
              "canonical_status": "307",
              "redirect_to": "https://client.example/es/articles/title-loan-and-bankruptcy"
            },
            {
              "url": "https://client.example/es/articles/do-i-qualify-to-refinance-title-loan",
              "csv_row": 145,
              "canonical": "https://client.example/es/articles/do-i-qualify-to-refinance-title-loan.html",
              "canonical_csv_row": 78,
              "canonical_status": "307",
              "redirect_to": "https://client.example/es/articles/do-i-qualify-to-refinance-title-loan"
            },
            {
              "url": "https://client.example/es/articles/title-loan-buyout-process-step-by-step",
              "csv_row": 146,
              "canonical": "https://client.example/es/articles/title-loan-buyout-process-step-by-step.html",
              "canonical_csv_row": 80,
              "canonical_status": "307",
              "redirect_to": "https://client.example/es/articles/title-loan-buyout-process-step-by-step"
            },
            {
              "url": "https://client.example/es/articles/title-loan-junk-fees-add-ons",
              "csv_row": 147,
              "canonical": "https://client.example/es/articles/title-loan-junk-fees-add-ons.html",
              "canonical_csv_row": 77,
              "canonical_status": "307",
              "redirect_to": "https://client.example/es/articles/title-loan-junk-fees-add-ons"
            },
            {
              "url": "https://client.example/es/articles/get-car-title-back-after-payoff",
              "csv_row": 148,
              "canonical": "https://client.example/es/articles/get-car-title-back-after-payoff.html",
              "canonical_csv_row": 76,
              "canonical_status": "307",
              "redirect_to": "https://client.example/es/articles/get-car-title-back-after-payoff"
            },
            {
              "url": "https://client.example/es/articles/partner-took-out-title-loan",
              "csv_row": 149,
              "canonical": "https://client.example/es/articles/partner-took-out-title-loan.html",
              "canonical_csv_row": 74,
              "canonical_status": "307",
              "redirect_to": "https://client.example/es/articles/partner-took-out-title-loan"
            },
            {
              "url": "https://client.example/es/articles/where-to-get-title-loan-help",
              "csv_row": 150,
              "canonical": "https://client.example/es/articles/where-to-get-title-loan-help.html",
              "canonical_csv_row": 75,
              "canonical_status": "307",
              "redirect_to": "https://client.example/es/articles/where-to-get-title-loan-help"
            },
            {
              "url": "https://client.example/es/articles/online-tribal-title-loan",
              "csv_row": 151,
              "canonical": "https://client.example/es/articles/online-tribal-title-loan.html",
              "canonical_csv_row": 70,
              "canonical_status": "307",
              "redirect_to": "https://client.example/es/articles/online-tribal-title-loan"
            },
            {
              "url": "https://client.example/es/articles/title-loan-myths",
              "csv_row": 152,
              "canonical": "https://client.example/es/articles/title-loan-myths.html",
              "canonical_csv_row": 72,
              "canonical_status": "307",
              "redirect_to": "https://client.example/es/articles/title-loan-myths"
            },
            {
              "url": "https://client.example/es/articles/title-loan-payoff-amount",
              "csv_row": 153,
              "canonical": "https://client.example/es/articles/title-loan-payoff-amount.html",
              "canonical_csv_row": 73,
              "canonical_status": "307",
              "redirect_to": "https://client.example/es/articles/title-loan-payoff-amount"
            },
            {
              "url": "https://client.example/es/articles/why-title-loan-balance-never-goes-down",
              "csv_row": 154,
              "canonical": "https://client.example/es/articles/why-title-loan-balance-never-goes-down.html",
              "canonical_csv_row": 68,
              "canonical_status": "307",
              "redirect_to": "https://client.example/es/articles/why-title-loan-balance-never-goes-down"
            },
            {
              "url": "https://client.example/es/articles/title-loan-for-emergency-now-stuck",
              "csv_row": 155,
              "canonical": "https://client.example/es/articles/title-loan-for-emergency-now-stuck.html",
              "canonical_csv_row": 71,
              "canonical_status": "307",
              "redirect_to": "https://client.example/es/articles/title-loan-for-emergency-now-stuck"
            },
            {
              "url": "https://client.example/es/articles/can-they-take-my-car-title-loan",
              "csv_row": 156,
              "canonical": "https://client.example/es/articles/can-they-take-my-car-title-loan.html",
              "canonical_csv_row": 67,
              "canonical_status": "307",
              "redirect_to": "https://client.example/es/articles/can-they-take-my-car-title-loan"
            },
            {
              "url": "https://client.example/es/articles/how-much-can-i-save-refinancing-title-loan",
              "csv_row": 157,
              "canonical": "https://client.example/es/articles/how-much-can-i-save-refinancing-title-loan.html",
              "canonical_csv_row": 69,
              "canonical_status": "307",
              "redirect_to": "https://client.example/es/articles/how-much-can-i-save-refinancing-title-loan"
            },
            {
              "url": "https://client.example/es/articles/cant-pay-title-loan-this-week",
              "csv_row": 158,
              "canonical": "https://client.example/es/articles/cant-pay-title-loan-this-week.html",
              "canonical_csv_row": 65,
              "canonical_status": "307",
              "redirect_to": "https://client.example/es/articles/cant-pay-title-loan-this-week"
            },
            {
              "url": "https://client.example/es/articles/should-i-let-them-take-the-car",
              "csv_row": 159,
              "canonical": "https://client.example/es/articles/should-i-let-them-take-the-car.html",
              "canonical_csv_row": 64,
              "canonical_status": "307",
              "redirect_to": "https://client.example/es/articles/should-i-let-them-take-the-car"
            },
            {
              "url": "https://client.example/es/articles/do-title-loans-affect-credit",
              "csv_row": 160,
              "canonical": "https://client.example/es/articles/do-title-loans-affect-credit.html",
              "canonical_csv_row": 61,
              "canonical_status": "307",
              "redirect_to": "https://client.example/es/articles/do-title-loans-affect-credit"
            },
            {
              "url": "https://client.example/es/articles/title-loan-renewal-cycle",
              "csv_row": 161,
              "canonical": "https://client.example/es/articles/title-loan-renewal-cycle.html",
              "canonical_csv_row": 63,
              "canonical_status": "307",
              "redirect_to": "https://client.example/es/articles/title-loan-renewal-cycle"
            },
            {
              "url": "https://client.example/es/articles/pay-down-title-loan-principal",
              "csv_row": 162,
              "canonical": "https://client.example/es/articles/pay-down-title-loan-principal.html",
              "canonical_csv_row": 66,
              "canonical_status": "307",
              "redirect_to": "https://client.example/es/articles/pay-down-title-loan-principal"
            },
            {
              "url": "https://client.example/es/articles/repossessed-car-belongings-inside",
              "csv_row": 163,
              "canonical": "https://client.example/es/articles/repossessed-car-belongings-inside.html",
              "canonical_csv_row": 59,
              "canonical_status": "307",
              "redirect_to": "https://client.example/es/articles/repossessed-car-belongings-inside"
            },
            {
              "url": "https://client.example/es/articles/title-loan-refinance-buyout",
              "csv_row": 164,
              "canonical": "https://client.example/es/articles/title-loan-refinance-buyout.html",
              "canonical_csv_row": 62,
              "canonical_status": "307",
              "redirect_to": "https://client.example/es/articles/title-loan-refinance-buyout"
            },
            {
              "url": "https://client.example/es/articles/title-loan-calling-my-job-references",
              "csv_row": 165,
              "canonical": "https://client.example/es/articles/title-loan-calling-my-job-references.html",
              "canonical_csv_row": 58,
              "canonical_status": "307",
              "redirect_to": "https://client.example/es/articles/title-loan-calling-my-job-references"
            },
            {
              "url": "https://client.example/es/articles/military-title-loan-illegal",
              "csv_row": 166,
              "canonical": "https://client.example/es/articles/military-title-loan-illegal.html",
              "canonical_csv_row": 60,
              "canonical_status": "307",
              "redirect_to": "https://client.example/es/articles/military-title-loan-illegal"
            },
            {
              "url": "https://client.example/es/articles/title-loan-vs-payday-vs-personal-loan",
              "csv_row": 167,
              "canonical": "https://client.example/es/articles/title-loan-vs-payday-vs-personal-loan.html",
              "canonical_csv_row": 57,
              "canonical_status": "307",
              "redirect_to": "https://client.example/es/articles/title-loan-vs-payday-vs-personal-loan"
            },
            {
              "url": "https://client.example/es/articles/being-sued-by-title-loan-company",
              "csv_row": 168,
              "canonical": "https://client.example/es/articles/being-sued-by-title-loan-company.html",
              "canonical_csv_row": 56,
              "canonical_status": "307",
              "redirect_to": "https://client.example/es/articles/being-sued-by-title-loan-company"
            },
            {
              "url": "https://client.example/es/articles/sell-car-with-title-loan",
              "csv_row": 171,
              "canonical": "https://client.example/es/articles/sell-car-with-title-loan.html",
              "canonical_csv_row": 55,
              "canonical_status": "307",
              "redirect_to": "https://client.example/es/articles/sell-car-with-title-loan"
            },
            {
              "url": "https://client.example/es/articles/title-loan-gps-tracker-kill-switch",
              "csv_row": 172,
              "canonical": "https://client.example/es/articles/title-loan-gps-tracker-kill-switch.html",
              "canonical_csv_row": 53,
              "canonical_status": "307",
              "redirect_to": "https://client.example/es/articles/title-loan-gps-tracker-kill-switch"
            }
          ],
          "basis": "Scenario derived from the real Screaming Frog canonical rows. No independent Sitebulb verification.",
          "simulated": true
        },
        {
          "id": "SB02",
          "priority": "Medium",
          "title": "Redirecting internal URL variants",
          "affected": [
            {
              "url": "https://client.example/privacy.html",
              "csv_row": 6,
              "status": "307",
              "redirect_to": "https://client.example/privacy",
              "inlinks": "7",
              "unique_inlinks": "3"
            },
            {
              "url": "https://client.example/sms-terms.html",
              "csv_row": 7,
              "status": "307",
              "redirect_to": "https://client.example/sms-terms",
              "inlinks": "2",
              "unique_inlinks": "2"
            },
            {
              "url": "https://client.example/articles/title-loan-myths.html",
              "csv_row": 10,
              "status": "307",
              "redirect_to": "https://client.example/articles/title-loan-myths",
              "inlinks": "7",
              "unique_inlinks": "6"
            },
            {
              "url": "https://client.example/articles/hours-cut-cant-keep-up-title-loan.html",
              "csv_row": 11,
              "status": "307",
              "redirect_to": "https://client.example/articles/hours-cut-cant-keep-up-title-loan",
              "inlinks": "3",
              "unique_inlinks": "3"
            },
            {
              "url": "https://client.example/articles/stop-paying-title-loan-what-happens.html",
              "csv_row": 12,
              "status": "307",
              "redirect_to": "https://client.example/articles/stop-paying-title-loan-what-happens",
              "inlinks": "2",
              "unique_inlinks": "2"
            },
            {
              "url": "https://client.example/articles/where-to-get-title-loan-help.html",
              "csv_row": 13,
              "status": "307",
              "redirect_to": "https://client.example/articles/where-to-get-title-loan-help",
              "inlinks": "24",
              "unique_inlinks": "17"
            },
            {
              "url": "https://client.example/articles/can-title-loan-garnish-wages.html",
              "csv_row": 14,
              "status": "307",
              "redirect_to": "https://client.example/articles/can-title-loan-garnish-wages",
              "inlinks": "4",
              "unique_inlinks": "3"
            },
            {
              "url": "https://client.example/articles/partner-took-out-title-loan.html",
              "csv_row": 15,
              "status": "307",
              "redirect_to": "https://client.example/articles/partner-took-out-title-loan",
              "inlinks": "3",
              "unique_inlinks": "3"
            },
            {
              "url": "https://client.example/articles/rolled-over-title-loan-again.html",
              "csv_row": 16,
              "status": "307",
              "redirect_to": "https://client.example/articles/rolled-over-title-loan-again",
              "inlinks": "2",
              "unique_inlinks": "2"
            },
            {
              "url": "https://client.example/articles/title-loan-payoff-amount.html",
              "csv_row": 17,
              "status": "307",
              "redirect_to": "https://client.example/articles/title-loan-payoff-amount",
              "inlinks": "19",
              "unique_inlinks": "14"
            },
            {
              "url": "https://client.example/articles/title-loan-for-emergency-now-stuck.html",
              "csv_row": 18,
              "status": "307",
              "redirect_to": "https://client.example/articles/title-loan-for-emergency-now-stuck",
              "inlinks": "2",
              "unique_inlinks": "2"
            },
            {
              "url": "https://client.example/articles/repossessed-car-belongings-inside.html",
              "csv_row": 19,
              "status": "307",
              "redirect_to": "https://client.example/articles/repossessed-car-belongings-inside",
              "inlinks": "2",
              "unique_inlinks": "2"
            },
            {
              "url": "https://client.example/articles/online-tribal-title-loan.html",
              "csv_row": 20,
              "status": "307",
              "redirect_to": "https://client.example/articles/online-tribal-title-loan",
              "inlinks": "2",
              "unique_inlinks": "2"
            },
            {
              "url": "https://client.example/articles/get-car-title-back-after-payoff.html",
              "csv_row": 21,
              "status": "307",
              "redirect_to": "https://client.example/articles/get-car-title-back-after-payoff",
              "inlinks": "4",
              "unique_inlinks": "3"
            },
            {
              "url": "https://client.example/articles/how-much-can-i-save-refinancing-title-loan.html",
              "csv_row": 22,
              "status": "307",
              "redirect_to": "https://client.example/articles/how-much-can-i-save-refinancing-title-loan",
              "inlinks": "5",
              "unique_inlinks": "4"
            },
            {
              "url": "https://client.example/articles/title-loan-vs-payday-vs-personal-loan.html",
              "csv_row": 23,
              "status": "307",
              "redirect_to": "https://client.example/articles/title-loan-vs-payday-vs-personal-loan",
              "inlinks": "13",
              "unique_inlinks": "12"
            },
            {
              "url": "https://client.example/articles/title-loan-renewal-cycle.html",
              "csv_row": 24,
              "status": "307",
              "redirect_to": "https://client.example/articles/title-loan-renewal-cycle",
              "inlinks": "14",
              "unique_inlinks": "10"
            },
            {
              "url": "https://client.example/articles/should-i-let-them-take-the-car.html",
              "csv_row": 25,
              "status": "307",
              "redirect_to": "https://client.example/articles/should-i-let-them-take-the-car",
              "inlinks": "2",
              "unique_inlinks": "2"
            },
            {
              "url": "https://client.example/articles/is-my-title-loan-legal.html",
              "csv_row": 26,
              "status": "307",
              "redirect_to": "https://client.example/articles/is-my-title-loan-legal",
              "inlinks": "9",
              "unique_inlinks": "7"
            },
            {
              "url": "https://client.example/articles/why-title-loan-balance-never-goes-down.html",
              "csv_row": 27,
              "status": "307",
              "redirect_to": "https://client.example/articles/why-title-loan-balance-never-goes-down",
              "inlinks": "22",
              "unique_inlinks": "15"
            },
            {
              "url": "https://client.example/articles/behind-on-title-loan-repossession.html",
              "csv_row": 28,
              "status": "307",
              "redirect_to": "https://client.example/articles/behind-on-title-loan-repossession",
              "inlinks": "29",
              "unique_inlinks": "19"
            },
            {
              "url": "https://client.example/articles/can-they-take-my-car-title-loan.html",
              "csv_row": 29,
              "status": "307",
              "redirect_to": "https://client.example/articles/can-they-take-my-car-title-loan",
              "inlinks": "13",
              "unique_inlinks": "10"
            },
            {
              "url": "https://client.example/articles/refinance-title-loan-now-vs-keep-paying.html",
              "csv_row": 30,
              "status": "307",
              "redirect_to": "https://client.example/articles/refinance-title-loan-now-vs-keep-paying",
              "inlinks": "2",
              "unique_inlinks": "2"
            },
            {
              "url": "https://client.example/articles/cosigned-title-loan-for-someone.html",
              "csv_row": 31,
              "status": "307",
              "redirect_to": "https://client.example/articles/cosigned-title-loan-for-someone",
              "inlinks": "2",
              "unique_inlinks": "2"
            },
            {
              "url": "https://client.example/articles/being-sued-by-title-loan-company.html",
              "csv_row": 32,
              "status": "307",
              "redirect_to": "https://client.example/articles/being-sued-by-title-loan-company",
              "inlinks": "5",
              "unique_inlinks": "4"
            },
            {
              "url": "https://client.example/articles/sell-car-with-title-loan.html",
              "csv_row": 33,
              "status": "307",
              "redirect_to": "https://client.example/articles/sell-car-with-title-loan",
              "inlinks": "2",
              "unique_inlinks": "2"
            },
            {
              "url": "https://client.example/articles/title-loan-refinance-lower-monthly-payment.html",
              "csv_row": 34,
              "status": "307",
              "redirect_to": "https://client.example/articles/title-loan-refinance-lower-monthly-payment",
              "inlinks": "4",
              "unique_inlinks": "3"
            },
            {
              "url": "https://client.example/articles/do-i-qualify-to-refinance-title-loan.html",
              "csv_row": 35,
              "status": "307",
              "redirect_to": "https://client.example/articles/do-i-qualify-to-refinance-title-loan",
              "inlinks": "3",
              "unique_inlinks": "3"
            },
            {
              "url": "https://client.example/articles/title-loan-refinance-buyout.html",
              "csv_row": 36,
              "status": "307",
              "redirect_to": "https://client.example/articles/title-loan-refinance-buyout",
              "inlinks": "69",
              "unique_inlinks": "37"
            },
            {
              "url": "https://client.example/articles/title-loan-buyout-process-step-by-step.html",
              "csv_row": 37,
              "status": "307",
              "redirect_to": "https://client.example/articles/title-loan-buyout-process-step-by-step",
              "inlinks": "4",
              "unique_inlinks": "4"
            },
            {
              "url": "https://client.example/articles/do-title-loans-affect-credit.html",
              "csv_row": 38,
              "status": "307",
              "redirect_to": "https://client.example/articles/do-title-loans-affect-credit",
              "inlinks": "9",
              "unique_inlinks": "6"
            },
            {
              "url": "https://client.example/articles/title-loan-collections-deficiency.html",
              "csv_row": 39,
              "status": "307",
              "redirect_to": "https://client.example/articles/title-loan-collections-deficiency",
              "inlinks": "16",
              "unique_inlinks": "10"
            },
            {
              "url": "https://client.example/articles/hiding-car-from-title-loan-repo.html",
              "csv_row": 40,
              "status": "307",
              "redirect_to": "https://client.example/articles/hiding-car-from-title-loan-repo",
              "inlinks": "2",
              "unique_inlinks": "2"
            },
            {
              "url": "https://client.example/articles/cant-pay-title-loan-this-week.html",
              "csv_row": 41,
              "status": "307",
              "redirect_to": "https://client.example/articles/cant-pay-title-loan-this-week",
              "inlinks": "9",
              "unique_inlinks": "6"
            },
            {
              "url": "https://client.example/articles/title-loan-and-bankruptcy.html",
              "csv_row": 42,
              "status": "307",
              "redirect_to": "https://client.example/articles/title-loan-and-bankruptcy",
              "inlinks": "3",
              "unique_inlinks": "3"
            },
            {
              "url": "https://client.example/articles/pay-down-title-loan-principal.html",
              "csv_row": 43,
              "status": "307",
              "redirect_to": "https://client.example/articles/pay-down-title-loan-principal",
              "inlinks": "18",
              "unique_inlinks": "14"
            },
            {
              "url": "https://client.example/articles/stuck-with-multiple-title-loans.html",
              "csv_row": 44,
              "status": "307",
              "redirect_to": "https://client.example/articles/stuck-with-multiple-title-loans",
              "inlinks": "3",
              "unique_inlinks": "3"
            },
            {
              "url": "https://client.example/articles/title-loan-junk-fees-add-ons.html",
              "csv_row": 45,
              "status": "307",
              "redirect_to": "https://client.example/articles/title-loan-junk-fees-add-ons",
              "inlinks": "2",
              "unique_inlinks": "2"
            },
            {
              "url": "https://client.example/articles/title-loan-calling-my-job-references.html",
              "csv_row": 46,
              "status": "307",
              "redirect_to": "https://client.example/articles/title-loan-calling-my-job-references",
              "inlinks": "3",
              "unique_inlinks": "3"
            },
            {
              "url": "https://client.example/articles/how-to-negotiate-with-title-loan-lender.html",
              "csv_row": 47,
              "status": "307",
              "redirect_to": "https://client.example/articles/how-to-negotiate-with-title-loan-lender",
              "inlinks": "23",
              "unique_inlinks": "19"
            },
            {
              "url": "https://client.example/articles/military-title-loan-illegal.html",
              "csv_row": 48,
              "status": "307",
              "redirect_to": "https://client.example/articles/military-title-loan-illegal",
              "inlinks": "2",
              "unique_inlinks": "2"
            },
            {
              "url": "https://client.example/articles/title-loan-gps-tracker-kill-switch.html",
              "csv_row": 49,
              "status": "307",
              "redirect_to": "https://client.example/articles/title-loan-gps-tracker-kill-switch",
              "inlinks": "2",
              "unique_inlinks": "2"
            },
            {
              "url": "https://client.example/es/articles/title-loan-gps-tracker-kill-switch.html",
              "csv_row": 53,
              "status": "307",
              "redirect_to": "https://client.example/es/articles/title-loan-gps-tracker-kill-switch",
              "inlinks": "2",
              "unique_inlinks": "2"
            },
            {
              "url": "https://client.example/es/articles/sell-car-with-title-loan.html",
              "csv_row": 55,
              "status": "307",
              "redirect_to": "https://client.example/es/articles/sell-car-with-title-loan",
              "inlinks": "2",
              "unique_inlinks": "2"
            },
            {
              "url": "https://client.example/es/articles/being-sued-by-title-loan-company.html",
              "csv_row": 56,
              "status": "307",
              "redirect_to": "https://client.example/es/articles/being-sued-by-title-loan-company",
              "inlinks": "5",
              "unique_inlinks": "4"
            },
            {
              "url": "https://client.example/es/articles/title-loan-vs-payday-vs-personal-loan.html",
              "csv_row": 57,
              "status": "307",
              "redirect_to": "https://client.example/es/articles/title-loan-vs-payday-vs-personal-loan",
              "inlinks": "11",
              "unique_inlinks": "10"
            },
            {
              "url": "https://client.example/es/articles/title-loan-calling-my-job-references.html",
              "csv_row": 58,
              "status": "307",
              "redirect_to": "https://client.example/es/articles/title-loan-calling-my-job-references",
              "inlinks": "3",
              "unique_inlinks": "3"
            },
            {
              "url": "https://client.example/es/articles/repossessed-car-belongings-inside.html",
              "csv_row": 59,
              "status": "307",
              "redirect_to": "https://client.example/es/articles/repossessed-car-belongings-inside",
              "inlinks": "2",
              "unique_inlinks": "2"
            },
            {
              "url": "https://client.example/es/articles/military-title-loan-illegal.html",
              "csv_row": 60,
              "status": "307",
              "redirect_to": "https://client.example/es/articles/military-title-loan-illegal",
              "inlinks": "2",
              "unique_inlinks": "2"
            },
            {
              "url": "https://client.example/es/articles/do-title-loans-affect-credit.html",
              "csv_row": 61,
              "status": "307",
              "redirect_to": "https://client.example/es/articles/do-title-loans-affect-credit",
              "inlinks": "9",
              "unique_inlinks": "6"
            },
            {
              "url": "https://client.example/es/articles/title-loan-refinance-buyout.html",
              "csv_row": 62,
              "status": "307",
              "redirect_to": "https://client.example/es/articles/title-loan-refinance-buyout",
              "inlinks": "69",
              "unique_inlinks": "37"
            },
            {
              "url": "https://client.example/es/articles/title-loan-renewal-cycle.html",
              "csv_row": 63,
              "status": "307",
              "redirect_to": "https://client.example/es/articles/title-loan-renewal-cycle",
              "inlinks": "12",
              "unique_inlinks": "9"
            },
            {
              "url": "https://client.example/es/articles/should-i-let-them-take-the-car.html",
              "csv_row": 64,
              "status": "307",
              "redirect_to": "https://client.example/es/articles/should-i-let-them-take-the-car",
              "inlinks": "2",
              "unique_inlinks": "2"
            },
            {
              "url": "https://client.example/es/articles/cant-pay-title-loan-this-week.html",
              "csv_row": 65,
              "status": "307",
              "redirect_to": "https://client.example/es/articles/cant-pay-title-loan-this-week",
              "inlinks": "9",
              "unique_inlinks": "6"
            },
            {
              "url": "https://client.example/es/articles/pay-down-title-loan-principal.html",
              "csv_row": 66,
              "status": "307",
              "redirect_to": "https://client.example/es/articles/pay-down-title-loan-principal",
              "inlinks": "15",
              "unique_inlinks": "11"
            },
            {
              "url": "https://client.example/es/articles/can-they-take-my-car-title-loan.html",
              "csv_row": 67,
              "status": "307",
              "redirect_to": "https://client.example/es/articles/can-they-take-my-car-title-loan",
              "inlinks": "13",
              "unique_inlinks": "10"
            },
            {
              "url": "https://client.example/es/articles/why-title-loan-balance-never-goes-down.html",
              "csv_row": 68,
              "status": "307",
              "redirect_to": "https://client.example/es/articles/why-title-loan-balance-never-goes-down",
              "inlinks": "21",
              "unique_inlinks": "15"
            },
            {
              "url": "https://client.example/es/articles/how-much-can-i-save-refinancing-title-loan.html",
              "csv_row": 69,
              "status": "307",
              "redirect_to": "https://client.example/es/articles/how-much-can-i-save-refinancing-title-loan",
              "inlinks": "6",
              "unique_inlinks": "5"
            },
            {
              "url": "https://client.example/es/articles/online-tribal-title-loan.html",
              "csv_row": 70,
              "status": "307",
              "redirect_to": "https://client.example/es/articles/online-tribal-title-loan",
              "inlinks": "2",
              "unique_inlinks": "2"
            },
            {
              "url": "https://client.example/es/articles/title-loan-for-emergency-now-stuck.html",
              "csv_row": 71,
              "status": "307",
              "redirect_to": "https://client.example/es/articles/title-loan-for-emergency-now-stuck",
              "inlinks": "2",
              "unique_inlinks": "2"
            },
            {
              "url": "https://client.example/es/articles/title-loan-myths.html",
              "csv_row": 72,
              "status": "307",
              "redirect_to": "https://client.example/es/articles/title-loan-myths",
              "inlinks": "5",
              "unique_inlinks": "5"
            },
            {
              "url": "https://client.example/es/articles/title-loan-payoff-amount.html",
              "csv_row": 73,
              "status": "307",
              "redirect_to": "https://client.example/es/articles/title-loan-payoff-amount",
              "inlinks": "16",
              "unique_inlinks": "12"
            },
            {
              "url": "https://client.example/es/articles/partner-took-out-title-loan.html",
              "csv_row": 74,
              "status": "307",
              "redirect_to": "https://client.example/es/articles/partner-took-out-title-loan",
              "inlinks": "3",
              "unique_inlinks": "3"
            },
            {
              "url": "https://client.example/es/articles/where-to-get-title-loan-help.html",
              "csv_row": 75,
              "status": "307",
              "redirect_to": "https://client.example/es/articles/where-to-get-title-loan-help",
              "inlinks": "24",
              "unique_inlinks": "17"
            },
            {
              "url": "https://client.example/es/articles/get-car-title-back-after-payoff.html",
              "csv_row": 76,
              "status": "307",
              "redirect_to": "https://client.example/es/articles/get-car-title-back-after-payoff",
              "inlinks": "4",
              "unique_inlinks": "3"
            },
            {
              "url": "https://client.example/es/articles/title-loan-junk-fees-add-ons.html",
              "csv_row": 77,
              "status": "307",
              "redirect_to": "https://client.example/es/articles/title-loan-junk-fees-add-ons",
              "inlinks": "2",
              "unique_inlinks": "2"
            },
            {
              "url": "https://client.example/es/articles/do-i-qualify-to-refinance-title-loan.html",
              "csv_row": 78,
              "status": "307",
              "redirect_to": "https://client.example/es/articles/do-i-qualify-to-refinance-title-loan",
              "inlinks": "5",
              "unique_inlinks": "4"
            },
            {
              "url": "https://client.example/es/articles/title-loan-and-bankruptcy.html",
              "csv_row": 79,
              "status": "307",
              "redirect_to": "https://client.example/es/articles/title-loan-and-bankruptcy",
              "inlinks": "3",
              "unique_inlinks": "3"
            },
            {
              "url": "https://client.example/es/articles/title-loan-buyout-process-step-by-step.html",
              "csv_row": 80,
              "status": "307",
              "redirect_to": "https://client.example/es/articles/title-loan-buyout-process-step-by-step",
              "inlinks": "6",
              "unique_inlinks": "5"
            },
            {
              "url": "https://client.example/es/articles/is-my-title-loan-legal.html",
              "csv_row": 81,
              "status": "307",
              "redirect_to": "https://client.example/es/articles/is-my-title-loan-legal",
              "inlinks": "9",
              "unique_inlinks": "7"
            },
            {
              "url": "https://client.example/es/articles/refinance-title-loan-now-vs-keep-paying.html",
              "csv_row": 82,
              "status": "307",
              "redirect_to": "https://client.example/es/articles/refinance-title-loan-now-vs-keep-paying",
              "inlinks": "3",
              "unique_inlinks": "3"
            },
            {
              "url": "https://client.example/es/articles/hiding-car-from-title-loan-repo.html",
              "csv_row": 83,
              "status": "307",
              "redirect_to": "https://client.example/es/articles/hiding-car-from-title-loan-repo",
              "inlinks": "2",
              "unique_inlinks": "2"
            },
            {
              "url": "https://client.example/es/articles/title-loan-refinance-lower-monthly-payment.html",
              "csv_row": 84,
              "status": "307",
              "redirect_to": "https://client.example/es/articles/title-loan-refinance-lower-monthly-payment",
              "inlinks": "4",
              "unique_inlinks": "4"
            },
            {
              "url": "https://client.example/es/articles/can-title-loan-garnish-wages.html",
              "csv_row": 85,
              "status": "307",
              "redirect_to": "https://client.example/es/articles/can-title-loan-garnish-wages",
              "inlinks": "4",
              "unique_inlinks": "3"
            },
            {
              "url": "https://client.example/es/articles/how-to-negotiate-with-title-loan-lender.html",
              "csv_row": 86,
              "status": "307",
              "redirect_to": "https://client.example/es/articles/how-to-negotiate-with-title-loan-lender",
              "inlinks": "22",
              "unique_inlinks": "18"
            },
            {
              "url": "https://client.example/es/articles/behind-on-title-loan-repossession.html",
              "csv_row": 87,
              "status": "307",
              "redirect_to": "https://client.example/es/articles/behind-on-title-loan-repossession",
              "inlinks": "26",
              "unique_inlinks": "16"
            },
            {
              "url": "https://client.example/es/articles/hours-cut-cant-keep-up-title-loan.html",
              "csv_row": 88,
              "status": "307",
              "redirect_to": "https://client.example/es/articles/hours-cut-cant-keep-up-title-loan",
              "inlinks": "3",
              "unique_inlinks": "3"
            },
            {
              "url": "https://client.example/es/articles/title-loan-collections-deficiency.html",
              "csv_row": 89,
              "status": "307",
              "redirect_to": "https://client.example/es/articles/title-loan-collections-deficiency",
              "inlinks": "16",
              "unique_inlinks": "10"
            },
            {
              "url": "https://client.example/es/articles/cosigned-title-loan-for-someone.html",
              "csv_row": 90,
              "status": "307",
              "redirect_to": "https://client.example/es/articles/cosigned-title-loan-for-someone",
              "inlinks": "2",
              "unique_inlinks": "2"
            },
            {
              "url": "https://client.example/es/articles/stuck-with-multiple-title-loans.html",
              "csv_row": 91,
              "status": "307",
              "redirect_to": "https://client.example/es/articles/stuck-with-multiple-title-loans",
              "inlinks": "2",
              "unique_inlinks": "2"
            },
            {
              "url": "https://client.example/es/articles/rolled-over-title-loan-again.html",
              "csv_row": 92,
              "status": "307",
              "redirect_to": "https://client.example/es/articles/rolled-over-title-loan-again",
              "inlinks": "2",
              "unique_inlinks": "2"
            },
            {
              "url": "https://client.example/es/articles/stop-paying-title-loan-what-happens.html",
              "csv_row": 93,
              "status": "307",
              "redirect_to": "https://client.example/es/articles/stop-paying-title-loan-what-happens",
              "inlinks": "2",
              "unique_inlinks": "2"
            },
            {
              "url": "https://client.example/articles/index.html",
              "csv_row": 169,
              "status": "307",
              "redirect_to": "https://client.example/articles/",
              "inlinks": "40",
              "unique_inlinks": "40"
            },
            {
              "url": "https://client.example/es/articles/index.html",
              "csv_row": 170,
              "status": "307",
              "redirect_to": "https://client.example/es/articles/",
              "inlinks": "40",
              "unique_inlinks": "40"
            }
          ],
          "basis": "Scenario derived from the real crawl redirects. A 307 is not automatically an error.",
          "simulated": true
        },
        {
          "id": "SB03",
          "priority": "Medium",
          "title": "Potential orphan articles",
          "affected": [
            {
              "url": "https://client.example/articles/title-loan-gps-tracker-kill-switch",
              "csv_row": 51
            },
            {
              "url": "https://client.example/articles/how-to-negotiate-with-title-loan-lender",
              "csv_row": 52
            }
          ],
          "basis": "Hypothetical Sitebulb finding. The supplied crawl has no valid link-edge export and cannot verify orphan status.",
          "simulated": true
        },
        {
          "id": "SB04",
          "priority": "Medium",
          "title": "Potential missing reciprocal language links",
          "affected": [
            {
              "url": "https://client.example/es/articles/",
              "csv_row": 50
            },
            {
              "url": "https://client.example/es/articles/stop-paying-title-loan-what-happens",
              "csv_row": 131
            },
            {
              "url": "https://client.example/es/articles/stuck-with-multiple-title-loans",
              "csv_row": 132
            },
            {
              "url": "https://client.example/es/articles/rolled-over-title-loan-again",
              "csv_row": 133
            },
            {
              "url": "https://client.example/es/articles/title-loan-collections-deficiency",
              "csv_row": 134
            },
            {
              "url": "https://client.example/es/articles/cosigned-title-loan-for-someone",
              "csv_row": 135
            }
          ],
          "basis": "Hypothetical Sitebulb finding. Hreflang was not established by the supplied exports.",
          "simulated": true
        },
        {
          "id": "SB05",
          "priority": "Low",
          "title": "Blank meta descriptions",
          "affected": [
            {
              "url": "https://client.example/articles/how-much-can-i-save-refinancing-title-loan",
              "csv_row": 119
            },
            {
              "url": "https://client.example/es/articles/how-much-can-i-save-refinancing-title-loan",
              "csv_row": 157
            }
          ],
          "basis": "Scenario derived from the real CSV description fields; no independent Sitebulb crawl.",
          "simulated": true
        }
      ],
      "actions": []
    }
  ],
  "backlog": [
    {
      "id": "T01",
      "group": "Technical SEO",
      "priority": "P1",
      "state": "Observed",
      "title": "Resolve canonical URLs that redirect back to the declaring 200 URL",
      "affected": [
        {
          "csv_row": 8,
          "url": "https://client.example/sms-terms",
          "status": "200",
          "canonical": "https://client.example/sms-terms.html"
        },
        {
          "csv_row": 9,
          "url": "https://client.example/privacy",
          "status": "200",
          "canonical": "https://client.example/privacy.html"
        },
        {
          "csv_row": 51,
          "url": "https://client.example/articles/title-loan-gps-tracker-kill-switch",
          "status": "200",
          "canonical": "https://client.example/articles/title-loan-gps-tracker-kill-switch.html"
        },
        {
          "csv_row": 52,
          "url": "https://client.example/articles/how-to-negotiate-with-title-loan-lender",
          "status": "200",
          "canonical": "https://client.example/articles/how-to-negotiate-with-title-loan-lender.html"
        },
        {
          "csv_row": 54,
          "url": "https://client.example/articles/military-title-loan-illegal",
          "status": "200",
          "canonical": "https://client.example/articles/military-title-loan-illegal.html"
        },
        {
          "csv_row": 94,
          "url": "https://client.example/articles/title-loan-calling-my-job-references",
          "status": "200",
          "canonical": "https://client.example/articles/title-loan-calling-my-job-references.html"
        },
        {
          "csv_row": 95,
          "url": "https://client.example/articles/title-loan-junk-fees-add-ons",
          "status": "200",
          "canonical": "https://client.example/articles/title-loan-junk-fees-add-ons.html"
        },
        {
          "csv_row": 96,
          "url": "https://client.example/articles/stuck-with-multiple-title-loans",
          "status": "200",
          "canonical": "https://client.example/articles/stuck-with-multiple-title-loans.html"
        },
        {
          "csv_row": 97,
          "url": "https://client.example/articles/pay-down-title-loan-principal",
          "status": "200",
          "canonical": "https://client.example/articles/pay-down-title-loan-principal.html"
        },
        {
          "csv_row": 98,
          "url": "https://client.example/articles/title-loan-and-bankruptcy",
          "status": "200",
          "canonical": "https://client.example/articles/title-loan-and-bankruptcy.html"
        },
        {
          "csv_row": 99,
          "url": "https://client.example/articles/cant-pay-title-loan-this-week",
          "status": "200",
          "canonical": "https://client.example/articles/cant-pay-title-loan-this-week.html"
        },
        {
          "csv_row": 100,
          "url": "https://client.example/articles/title-loan-collections-deficiency",
          "status": "200",
          "canonical": "https://client.example/articles/title-loan-collections-deficiency.html"
        },
        {
          "csv_row": 101,
          "url": "https://client.example/articles/hiding-car-from-title-loan-repo",
          "status": "200",
          "canonical": "https://client.example/articles/hiding-car-from-title-loan-repo.html"
        },
        {
          "csv_row": 102,
          "url": "https://client.example/articles/do-title-loans-affect-credit",
          "status": "200",
          "canonical": "https://client.example/articles/do-title-loans-affect-credit.html"
        },
        {
          "csv_row": 103,
          "url": "https://client.example/articles/title-loan-buyout-process-step-by-step",
          "status": "200",
          "canonical": "https://client.example/articles/title-loan-buyout-process-step-by-step.html"
        },
        {
          "csv_row": 104,
          "url": "https://client.example/articles/title-loan-refinance-buyout",
          "status": "200",
          "canonical": "https://client.example/articles/title-loan-refinance-buyout.html"
        },
        {
          "csv_row": 105,
          "url": "https://client.example/articles/do-i-qualify-to-refinance-title-loan",
          "status": "200",
          "canonical": "https://client.example/articles/do-i-qualify-to-refinance-title-loan.html"
        },
        {
          "csv_row": 106,
          "url": "https://client.example/articles/title-loan-refinance-lower-monthly-payment",
          "status": "200",
          "canonical": "https://client.example/articles/title-loan-refinance-lower-monthly-payment.html"
        },
        {
          "csv_row": 107,
          "url": "https://client.example/articles/sell-car-with-title-loan",
          "status": "200",
          "canonical": "https://client.example/articles/sell-car-with-title-loan.html"
        },
        {
          "csv_row": 108,
          "url": "https://client.example/articles/being-sued-by-title-loan-company",
          "status": "200",
          "canonical": "https://client.example/articles/being-sued-by-title-loan-company.html"
        },
        {
          "csv_row": 109,
          "url": "https://client.example/articles/cosigned-title-loan-for-someone",
          "status": "200",
          "canonical": "https://client.example/articles/cosigned-title-loan-for-someone.html"
        },
        {
          "csv_row": 110,
          "url": "https://client.example/articles/refinance-title-loan-now-vs-keep-paying",
          "status": "200",
          "canonical": "https://client.example/articles/refinance-title-loan-now-vs-keep-paying.html"
        },
        {
          "csv_row": 111,
          "url": "https://client.example/articles/why-title-loan-balance-never-goes-down",
          "status": "200",
          "canonical": "https://client.example/articles/why-title-loan-balance-never-goes-down.html"
        },
        {
          "csv_row": 112,
          "url": "https://client.example/articles/behind-on-title-loan-repossession",
          "status": "200",
          "canonical": "https://client.example/articles/behind-on-title-loan-repossession.html"
        },
        {
          "csv_row": 113,
          "url": "https://client.example/articles/is-my-title-loan-legal",
          "status": "200",
          "canonical": "https://client.example/articles/is-my-title-loan-legal.html"
        },
        {
          "csv_row": 114,
          "url": "https://client.example/articles/can-they-take-my-car-title-loan",
          "status": "200",
          "canonical": "https://client.example/articles/can-they-take-my-car-title-loan.html"
        },
        {
          "csv_row": 115,
          "url": "https://client.example/articles/should-i-let-them-take-the-car",
          "status": "200",
          "canonical": "https://client.example/articles/should-i-let-them-take-the-car.html"
        },
        {
          "csv_row": 116,
          "url": "https://client.example/articles/title-loan-renewal-cycle",
          "status": "200",
          "canonical": "https://client.example/articles/title-loan-renewal-cycle.html"
        },
        {
          "csv_row": 117,
          "url": "https://client.example/articles/title-loan-vs-payday-vs-personal-loan",
          "status": "200",
          "canonical": "https://client.example/articles/title-loan-vs-payday-vs-personal-loan.html"
        },
        {
          "csv_row": 118,
          "url": "https://client.example/articles/get-car-title-back-after-payoff",
          "status": "200",
          "canonical": "https://client.example/articles/get-car-title-back-after-payoff.html"
        },
        {
          "csv_row": 119,
          "url": "https://client.example/articles/how-much-can-i-save-refinancing-title-loan",
          "status": "200",
          "canonical": "https://client.example/articles/how-much-can-i-save-refinancing-title-loan.html"
        },
        {
          "csv_row": 120,
          "url": "https://client.example/articles/online-tribal-title-loan",
          "status": "200",
          "canonical": "https://client.example/articles/online-tribal-title-loan.html"
        },
        {
          "csv_row": 121,
          "url": "https://client.example/articles/title-loan-for-emergency-now-stuck",
          "status": "200",
          "canonical": "https://client.example/articles/title-loan-for-emergency-now-stuck.html"
        },
        {
          "csv_row": 122,
          "url": "https://client.example/articles/rolled-over-title-loan-again",
          "status": "200",
          "canonical": "https://client.example/articles/rolled-over-title-loan-again.html"
        },
        {
          "csv_row": 123,
          "url": "https://client.example/articles/title-loan-payoff-amount",
          "status": "200",
          "canonical": "https://client.example/articles/title-loan-payoff-amount.html"
        },
        {
          "csv_row": 124,
          "url": "https://client.example/articles/repossessed-car-belongings-inside",
          "status": "200",
          "canonical": "https://client.example/articles/repossessed-car-belongings-inside.html"
        },
        {
          "csv_row": 125,
          "url": "https://client.example/articles/can-title-loan-garnish-wages",
          "status": "200",
          "canonical": "https://client.example/articles/can-title-loan-garnish-wages.html"
        },
        {
          "csv_row": 126,
          "url": "https://client.example/articles/where-to-get-title-loan-help",
          "status": "200",
          "canonical": "https://client.example/articles/where-to-get-title-loan-help.html"
        },
        {
          "csv_row": 127,
          "url": "https://client.example/articles/stop-paying-title-loan-what-happens",
          "status": "200",
          "canonical": "https://client.example/articles/stop-paying-title-loan-what-happens.html"
        },
        {
          "csv_row": 128,
          "url": "https://client.example/articles/hours-cut-cant-keep-up-title-loan",
          "status": "200",
          "canonical": "https://client.example/articles/hours-cut-cant-keep-up-title-loan.html"
        },
        {
          "csv_row": 129,
          "url": "https://client.example/articles/partner-took-out-title-loan",
          "status": "200",
          "canonical": "https://client.example/articles/partner-took-out-title-loan.html"
        },
        {
          "csv_row": 130,
          "url": "https://client.example/articles/title-loan-myths",
          "status": "200",
          "canonical": "https://client.example/articles/title-loan-myths.html"
        },
        {
          "csv_row": 131,
          "url": "https://client.example/es/articles/stop-paying-title-loan-what-happens",
          "status": "200",
          "canonical": "https://client.example/es/articles/stop-paying-title-loan-what-happens.html"
        },
        {
          "csv_row": 132,
          "url": "https://client.example/es/articles/stuck-with-multiple-title-loans",
          "status": "200",
          "canonical": "https://client.example/es/articles/stuck-with-multiple-title-loans.html"
        },
        {
          "csv_row": 133,
          "url": "https://client.example/es/articles/rolled-over-title-loan-again",
          "status": "200",
          "canonical": "https://client.example/es/articles/rolled-over-title-loan-again.html"
        },
        {
          "csv_row": 134,
          "url": "https://client.example/es/articles/title-loan-collections-deficiency",
          "status": "200",
          "canonical": "https://client.example/es/articles/title-loan-collections-deficiency.html"
        },
        {
          "csv_row": 135,
          "url": "https://client.example/es/articles/cosigned-title-loan-for-someone",
          "status": "200",
          "canonical": "https://client.example/es/articles/cosigned-title-loan-for-someone.html"
        },
        {
          "csv_row": 136,
          "url": "https://client.example/es/articles/behind-on-title-loan-repossession",
          "status": "200",
          "canonical": "https://client.example/es/articles/behind-on-title-loan-repossession.html"
        },
        {
          "csv_row": 137,
          "url": "https://client.example/es/articles/hours-cut-cant-keep-up-title-loan",
          "status": "200",
          "canonical": "https://client.example/es/articles/hours-cut-cant-keep-up-title-loan.html"
        },
        {
          "csv_row": 138,
          "url": "https://client.example/es/articles/can-title-loan-garnish-wages",
          "status": "200",
          "canonical": "https://client.example/es/articles/can-title-loan-garnish-wages.html"
        },
        {
          "csv_row": 139,
          "url": "https://client.example/es/articles/how-to-negotiate-with-title-loan-lender",
          "status": "200",
          "canonical": "https://client.example/es/articles/how-to-negotiate-with-title-loan-lender.html"
        },
        {
          "csv_row": 140,
          "url": "https://client.example/es/articles/hiding-car-from-title-loan-repo",
          "status": "200",
          "canonical": "https://client.example/es/articles/hiding-car-from-title-loan-repo.html"
        },
        {
          "csv_row": 141,
          "url": "https://client.example/es/articles/refinance-title-loan-now-vs-keep-paying",
          "status": "200",
          "canonical": "https://client.example/es/articles/refinance-title-loan-now-vs-keep-paying.html"
        },
        {
          "csv_row": 142,
          "url": "https://client.example/es/articles/title-loan-refinance-lower-monthly-payment",
          "status": "200",
          "canonical": "https://client.example/es/articles/title-loan-refinance-lower-monthly-payment.html"
        },
        {
          "csv_row": 143,
          "url": "https://client.example/es/articles/is-my-title-loan-legal",
          "status": "200",
          "canonical": "https://client.example/es/articles/is-my-title-loan-legal.html"
        },
        {
          "csv_row": 144,
          "url": "https://client.example/es/articles/title-loan-and-bankruptcy",
          "status": "200",
          "canonical": "https://client.example/es/articles/title-loan-and-bankruptcy.html"
        },
        {
          "csv_row": 145,
          "url": "https://client.example/es/articles/do-i-qualify-to-refinance-title-loan",
          "status": "200",
          "canonical": "https://client.example/es/articles/do-i-qualify-to-refinance-title-loan.html"
        },
        {
          "csv_row": 146,
          "url": "https://client.example/es/articles/title-loan-buyout-process-step-by-step",
          "status": "200",
          "canonical": "https://client.example/es/articles/title-loan-buyout-process-step-by-step.html"
        },
        {
          "csv_row": 147,
          "url": "https://client.example/es/articles/title-loan-junk-fees-add-ons",
          "status": "200",
          "canonical": "https://client.example/es/articles/title-loan-junk-fees-add-ons.html"
        },
        {
          "csv_row": 148,
          "url": "https://client.example/es/articles/get-car-title-back-after-payoff",
          "status": "200",
          "canonical": "https://client.example/es/articles/get-car-title-back-after-payoff.html"
        },
        {
          "csv_row": 149,
          "url": "https://client.example/es/articles/partner-took-out-title-loan",
          "status": "200",
          "canonical": "https://client.example/es/articles/partner-took-out-title-loan.html"
        },
        {
          "csv_row": 150,
          "url": "https://client.example/es/articles/where-to-get-title-loan-help",
          "status": "200",
          "canonical": "https://client.example/es/articles/where-to-get-title-loan-help.html"
        },
        {
          "csv_row": 151,
          "url": "https://client.example/es/articles/online-tribal-title-loan",
          "status": "200",
          "canonical": "https://client.example/es/articles/online-tribal-title-loan.html"
        },
        {
          "csv_row": 152,
          "url": "https://client.example/es/articles/title-loan-myths",
          "status": "200",
          "canonical": "https://client.example/es/articles/title-loan-myths.html"
        },
        {
          "csv_row": 153,
          "url": "https://client.example/es/articles/title-loan-payoff-amount",
          "status": "200",
          "canonical": "https://client.example/es/articles/title-loan-payoff-amount.html"
        },
        {
          "csv_row": 154,
          "url": "https://client.example/es/articles/why-title-loan-balance-never-goes-down",
          "status": "200",
          "canonical": "https://client.example/es/articles/why-title-loan-balance-never-goes-down.html"
        },
        {
          "csv_row": 155,
          "url": "https://client.example/es/articles/title-loan-for-emergency-now-stuck",
          "status": "200",
          "canonical": "https://client.example/es/articles/title-loan-for-emergency-now-stuck.html"
        },
        {
          "csv_row": 156,
          "url": "https://client.example/es/articles/can-they-take-my-car-title-loan",
          "status": "200",
          "canonical": "https://client.example/es/articles/can-they-take-my-car-title-loan.html"
        },
        {
          "csv_row": 157,
          "url": "https://client.example/es/articles/how-much-can-i-save-refinancing-title-loan",
          "status": "200",
          "canonical": "https://client.example/es/articles/how-much-can-i-save-refinancing-title-loan.html"
        },
        {
          "csv_row": 158,
          "url": "https://client.example/es/articles/cant-pay-title-loan-this-week",
          "status": "200",
          "canonical": "https://client.example/es/articles/cant-pay-title-loan-this-week.html"
        },
        {
          "csv_row": 159,
          "url": "https://client.example/es/articles/should-i-let-them-take-the-car",
          "status": "200",
          "canonical": "https://client.example/es/articles/should-i-let-them-take-the-car.html"
        },
        {
          "csv_row": 160,
          "url": "https://client.example/es/articles/do-title-loans-affect-credit",
          "status": "200",
          "canonical": "https://client.example/es/articles/do-title-loans-affect-credit.html"
        },
        {
          "csv_row": 161,
          "url": "https://client.example/es/articles/title-loan-renewal-cycle",
          "status": "200",
          "canonical": "https://client.example/es/articles/title-loan-renewal-cycle.html"
        },
        {
          "csv_row": 162,
          "url": "https://client.example/es/articles/pay-down-title-loan-principal",
          "status": "200",
          "canonical": "https://client.example/es/articles/pay-down-title-loan-principal.html"
        },
        {
          "csv_row": 163,
          "url": "https://client.example/es/articles/repossessed-car-belongings-inside",
          "status": "200",
          "canonical": "https://client.example/es/articles/repossessed-car-belongings-inside.html"
        },
        {
          "csv_row": 164,
          "url": "https://client.example/es/articles/title-loan-refinance-buyout",
          "status": "200",
          "canonical": "https://client.example/es/articles/title-loan-refinance-buyout.html"
        },
        {
          "csv_row": 165,
          "url": "https://client.example/es/articles/title-loan-calling-my-job-references",
          "status": "200",
          "canonical": "https://client.example/es/articles/title-loan-calling-my-job-references.html"
        },
        {
          "csv_row": 166,
          "url": "https://client.example/es/articles/military-title-loan-illegal",
          "status": "200",
          "canonical": "https://client.example/es/articles/military-title-loan-illegal.html"
        },
        {
          "csv_row": 167,
          "url": "https://client.example/es/articles/title-loan-vs-payday-vs-personal-loan",
          "status": "200",
          "canonical": "https://client.example/es/articles/title-loan-vs-payday-vs-personal-loan.html"
        },
        {
          "csv_row": 168,
          "url": "https://client.example/es/articles/being-sued-by-title-loan-company",
          "status": "200",
          "canonical": "https://client.example/es/articles/being-sued-by-title-loan-company.html"
        },
        {
          "csv_row": 171,
          "url": "https://client.example/es/articles/sell-car-with-title-loan",
          "status": "200",
          "canonical": "https://client.example/es/articles/sell-car-with-title-loan.html"
        },
        {
          "csv_row": 172,
          "url": "https://client.example/es/articles/title-loan-gps-tracker-kill-switch",
          "status": "200",
          "canonical": "https://client.example/es/articles/title-loan-gps-tracker-kill-switch.html"
        }
      ],
      "fix": "Confirm the preferred URL policy, then align canonical declarations with final 200 URLs and verify a fresh crawl plus URL Inspection.",
      "effort": "4–8 engineering hours plus 2–4 QA hours (provisional)",
      "dependencies": "Owner approval of URL policy; SEO and engineering review",
      "reasoning": "Conflicting canonical and redirect signals. This is not an HTTP loop or proof of Google exclusion.",
      "kind": "Observed",
      "affected_csv_rows": [
        8,
        9,
        51,
        52,
        54,
        94,
        95,
        96,
        97,
        98,
        99,
        100,
        101,
        102,
        103,
        104,
        105,
        106,
        107,
        108,
        109,
        110,
        111,
        112,
        113,
        114,
        115,
        116,
        117,
        118,
        119,
        120,
        121,
        122,
        123,
        124,
        125,
        126,
        127,
        128,
        129,
        130,
        131,
        132,
        133,
        134,
        135,
        136,
        137,
        138,
        139,
        140,
        141,
        142,
        143,
        144,
        145,
        146,
        147,
        148,
        149,
        150,
        151,
        152,
        153,
        154,
        155,
        156,
        157,
        158,
        159,
        160,
        161,
        162,
        163,
        164,
        165,
        166,
        167,
        168,
        171,
        172
      ],
      "evidence": "REAL Screaming Frog CSV: 82 affected URL records. Conflicting canonical and redirect signals. This is not an HTTP loop or proof of Google exclusion.",
      "expert_review": "SEO and engineering review of the original rows and a fresh crawl.",
      "acceptance": "Verify the agreed change in a fresh crawl; compare affected URLs with the preserved source rows."
    },
    {
      "id": "T02",
      "group": "Technical SEO",
      "priority": "P2",
      "state": "Review",
      "title": "Review redirect policy",
      "affected": [
        {
          "csv_row": 6,
          "url": "https://client.example/privacy.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 7,
          "url": "https://client.example/sms-terms.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 10,
          "url": "https://client.example/articles/title-loan-myths.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 11,
          "url": "https://client.example/articles/hours-cut-cant-keep-up-title-loan.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 12,
          "url": "https://client.example/articles/stop-paying-title-loan-what-happens.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 13,
          "url": "https://client.example/articles/where-to-get-title-loan-help.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 14,
          "url": "https://client.example/articles/can-title-loan-garnish-wages.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 15,
          "url": "https://client.example/articles/partner-took-out-title-loan.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 16,
          "url": "https://client.example/articles/rolled-over-title-loan-again.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 17,
          "url": "https://client.example/articles/title-loan-payoff-amount.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 18,
          "url": "https://client.example/articles/title-loan-for-emergency-now-stuck.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 19,
          "url": "https://client.example/articles/repossessed-car-belongings-inside.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 20,
          "url": "https://client.example/articles/online-tribal-title-loan.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 21,
          "url": "https://client.example/articles/get-car-title-back-after-payoff.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 22,
          "url": "https://client.example/articles/how-much-can-i-save-refinancing-title-loan.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 23,
          "url": "https://client.example/articles/title-loan-vs-payday-vs-personal-loan.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 24,
          "url": "https://client.example/articles/title-loan-renewal-cycle.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 25,
          "url": "https://client.example/articles/should-i-let-them-take-the-car.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 26,
          "url": "https://client.example/articles/is-my-title-loan-legal.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 27,
          "url": "https://client.example/articles/why-title-loan-balance-never-goes-down.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 28,
          "url": "https://client.example/articles/behind-on-title-loan-repossession.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 29,
          "url": "https://client.example/articles/can-they-take-my-car-title-loan.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 30,
          "url": "https://client.example/articles/refinance-title-loan-now-vs-keep-paying.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 31,
          "url": "https://client.example/articles/cosigned-title-loan-for-someone.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 32,
          "url": "https://client.example/articles/being-sued-by-title-loan-company.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 33,
          "url": "https://client.example/articles/sell-car-with-title-loan.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 34,
          "url": "https://client.example/articles/title-loan-refinance-lower-monthly-payment.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 35,
          "url": "https://client.example/articles/do-i-qualify-to-refinance-title-loan.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 36,
          "url": "https://client.example/articles/title-loan-refinance-buyout.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 37,
          "url": "https://client.example/articles/title-loan-buyout-process-step-by-step.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 38,
          "url": "https://client.example/articles/do-title-loans-affect-credit.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 39,
          "url": "https://client.example/articles/title-loan-collections-deficiency.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 40,
          "url": "https://client.example/articles/hiding-car-from-title-loan-repo.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 41,
          "url": "https://client.example/articles/cant-pay-title-loan-this-week.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 42,
          "url": "https://client.example/articles/title-loan-and-bankruptcy.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 43,
          "url": "https://client.example/articles/pay-down-title-loan-principal.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 44,
          "url": "https://client.example/articles/stuck-with-multiple-title-loans.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 45,
          "url": "https://client.example/articles/title-loan-junk-fees-add-ons.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 46,
          "url": "https://client.example/articles/title-loan-calling-my-job-references.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 47,
          "url": "https://client.example/articles/how-to-negotiate-with-title-loan-lender.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 48,
          "url": "https://client.example/articles/military-title-loan-illegal.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 49,
          "url": "https://client.example/articles/title-loan-gps-tracker-kill-switch.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 53,
          "url": "https://client.example/es/articles/title-loan-gps-tracker-kill-switch.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 55,
          "url": "https://client.example/es/articles/sell-car-with-title-loan.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 56,
          "url": "https://client.example/es/articles/being-sued-by-title-loan-company.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 57,
          "url": "https://client.example/es/articles/title-loan-vs-payday-vs-personal-loan.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 58,
          "url": "https://client.example/es/articles/title-loan-calling-my-job-references.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 59,
          "url": "https://client.example/es/articles/repossessed-car-belongings-inside.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 60,
          "url": "https://client.example/es/articles/military-title-loan-illegal.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 61,
          "url": "https://client.example/es/articles/do-title-loans-affect-credit.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 62,
          "url": "https://client.example/es/articles/title-loan-refinance-buyout.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 63,
          "url": "https://client.example/es/articles/title-loan-renewal-cycle.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 64,
          "url": "https://client.example/es/articles/should-i-let-them-take-the-car.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 65,
          "url": "https://client.example/es/articles/cant-pay-title-loan-this-week.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 66,
          "url": "https://client.example/es/articles/pay-down-title-loan-principal.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 67,
          "url": "https://client.example/es/articles/can-they-take-my-car-title-loan.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 68,
          "url": "https://client.example/es/articles/why-title-loan-balance-never-goes-down.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 69,
          "url": "https://client.example/es/articles/how-much-can-i-save-refinancing-title-loan.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 70,
          "url": "https://client.example/es/articles/online-tribal-title-loan.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 71,
          "url": "https://client.example/es/articles/title-loan-for-emergency-now-stuck.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 72,
          "url": "https://client.example/es/articles/title-loan-myths.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 73,
          "url": "https://client.example/es/articles/title-loan-payoff-amount.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 74,
          "url": "https://client.example/es/articles/partner-took-out-title-loan.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 75,
          "url": "https://client.example/es/articles/where-to-get-title-loan-help.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 76,
          "url": "https://client.example/es/articles/get-car-title-back-after-payoff.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 77,
          "url": "https://client.example/es/articles/title-loan-junk-fees-add-ons.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 78,
          "url": "https://client.example/es/articles/do-i-qualify-to-refinance-title-loan.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 79,
          "url": "https://client.example/es/articles/title-loan-and-bankruptcy.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 80,
          "url": "https://client.example/es/articles/title-loan-buyout-process-step-by-step.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 81,
          "url": "https://client.example/es/articles/is-my-title-loan-legal.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 82,
          "url": "https://client.example/es/articles/refinance-title-loan-now-vs-keep-paying.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 83,
          "url": "https://client.example/es/articles/hiding-car-from-title-loan-repo.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 84,
          "url": "https://client.example/es/articles/title-loan-refinance-lower-monthly-payment.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 85,
          "url": "https://client.example/es/articles/can-title-loan-garnish-wages.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 86,
          "url": "https://client.example/es/articles/how-to-negotiate-with-title-loan-lender.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 87,
          "url": "https://client.example/es/articles/behind-on-title-loan-repossession.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 88,
          "url": "https://client.example/es/articles/hours-cut-cant-keep-up-title-loan.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 89,
          "url": "https://client.example/es/articles/title-loan-collections-deficiency.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 90,
          "url": "https://client.example/es/articles/cosigned-title-loan-for-someone.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 91,
          "url": "https://client.example/es/articles/stuck-with-multiple-title-loans.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 92,
          "url": "https://client.example/es/articles/rolled-over-title-loan-again.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 93,
          "url": "https://client.example/es/articles/stop-paying-title-loan-what-happens.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 169,
          "url": "https://client.example/articles/index.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 170,
          "url": "https://client.example/es/articles/index.html",
          "status": "307",
          "canonical": ""
        }
      ],
      "fix": "Verify whether each move is permanent before selecting a redirect status.",
      "effort": "1–2 incremental review hours; overlaps T01",
      "dependencies": "T01 URL policy",
      "reasoning": "307 status alone is not a defect.",
      "kind": "Review",
      "affected_csv_rows": [
        6,
        7,
        10,
        11,
        12,
        13,
        14,
        15,
        16,
        17,
        18,
        19,
        20,
        21,
        22,
        23,
        24,
        25,
        26,
        27,
        28,
        29,
        30,
        31,
        32,
        33,
        34,
        35,
        36,
        37,
        38,
        39,
        40,
        41,
        42,
        43,
        44,
        45,
        46,
        47,
        48,
        49,
        53,
        55,
        56,
        57,
        58,
        59,
        60,
        61,
        62,
        63,
        64,
        65,
        66,
        67,
        68,
        69,
        70,
        71,
        72,
        73,
        74,
        75,
        76,
        77,
        78,
        79,
        80,
        81,
        82,
        83,
        84,
        85,
        86,
        87,
        88,
        89,
        90,
        91,
        92,
        93,
        169,
        170
      ],
      "evidence": "REAL Screaming Frog CSV: 84 affected URL records. 307 status alone is not a defect.",
      "expert_review": "SEO and engineering review of the original rows and a fresh crawl.",
      "acceptance": "Verify the agreed change in a fresh crawl; compare affected URLs with the preserved source rows."
    },
    {
      "id": "L01",
      "group": "Internal linking",
      "priority": "P2",
      "state": "Observed",
      "title": "Inspect links to redirected URL variants",
      "affected": [
        {
          "csv_row": 6,
          "url": "https://client.example/privacy.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 7,
          "url": "https://client.example/sms-terms.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 10,
          "url": "https://client.example/articles/title-loan-myths.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 11,
          "url": "https://client.example/articles/hours-cut-cant-keep-up-title-loan.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 12,
          "url": "https://client.example/articles/stop-paying-title-loan-what-happens.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 13,
          "url": "https://client.example/articles/where-to-get-title-loan-help.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 14,
          "url": "https://client.example/articles/can-title-loan-garnish-wages.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 15,
          "url": "https://client.example/articles/partner-took-out-title-loan.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 16,
          "url": "https://client.example/articles/rolled-over-title-loan-again.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 17,
          "url": "https://client.example/articles/title-loan-payoff-amount.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 18,
          "url": "https://client.example/articles/title-loan-for-emergency-now-stuck.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 19,
          "url": "https://client.example/articles/repossessed-car-belongings-inside.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 20,
          "url": "https://client.example/articles/online-tribal-title-loan.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 21,
          "url": "https://client.example/articles/get-car-title-back-after-payoff.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 22,
          "url": "https://client.example/articles/how-much-can-i-save-refinancing-title-loan.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 23,
          "url": "https://client.example/articles/title-loan-vs-payday-vs-personal-loan.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 24,
          "url": "https://client.example/articles/title-loan-renewal-cycle.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 25,
          "url": "https://client.example/articles/should-i-let-them-take-the-car.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 26,
          "url": "https://client.example/articles/is-my-title-loan-legal.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 27,
          "url": "https://client.example/articles/why-title-loan-balance-never-goes-down.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 28,
          "url": "https://client.example/articles/behind-on-title-loan-repossession.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 29,
          "url": "https://client.example/articles/can-they-take-my-car-title-loan.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 30,
          "url": "https://client.example/articles/refinance-title-loan-now-vs-keep-paying.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 31,
          "url": "https://client.example/articles/cosigned-title-loan-for-someone.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 32,
          "url": "https://client.example/articles/being-sued-by-title-loan-company.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 33,
          "url": "https://client.example/articles/sell-car-with-title-loan.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 34,
          "url": "https://client.example/articles/title-loan-refinance-lower-monthly-payment.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 35,
          "url": "https://client.example/articles/do-i-qualify-to-refinance-title-loan.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 36,
          "url": "https://client.example/articles/title-loan-refinance-buyout.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 37,
          "url": "https://client.example/articles/title-loan-buyout-process-step-by-step.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 38,
          "url": "https://client.example/articles/do-title-loans-affect-credit.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 39,
          "url": "https://client.example/articles/title-loan-collections-deficiency.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 40,
          "url": "https://client.example/articles/hiding-car-from-title-loan-repo.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 41,
          "url": "https://client.example/articles/cant-pay-title-loan-this-week.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 42,
          "url": "https://client.example/articles/title-loan-and-bankruptcy.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 43,
          "url": "https://client.example/articles/pay-down-title-loan-principal.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 44,
          "url": "https://client.example/articles/stuck-with-multiple-title-loans.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 45,
          "url": "https://client.example/articles/title-loan-junk-fees-add-ons.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 46,
          "url": "https://client.example/articles/title-loan-calling-my-job-references.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 47,
          "url": "https://client.example/articles/how-to-negotiate-with-title-loan-lender.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 48,
          "url": "https://client.example/articles/military-title-loan-illegal.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 49,
          "url": "https://client.example/articles/title-loan-gps-tracker-kill-switch.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 53,
          "url": "https://client.example/es/articles/title-loan-gps-tracker-kill-switch.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 55,
          "url": "https://client.example/es/articles/sell-car-with-title-loan.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 56,
          "url": "https://client.example/es/articles/being-sued-by-title-loan-company.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 57,
          "url": "https://client.example/es/articles/title-loan-vs-payday-vs-personal-loan.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 58,
          "url": "https://client.example/es/articles/title-loan-calling-my-job-references.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 59,
          "url": "https://client.example/es/articles/repossessed-car-belongings-inside.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 60,
          "url": "https://client.example/es/articles/military-title-loan-illegal.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 61,
          "url": "https://client.example/es/articles/do-title-loans-affect-credit.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 62,
          "url": "https://client.example/es/articles/title-loan-refinance-buyout.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 63,
          "url": "https://client.example/es/articles/title-loan-renewal-cycle.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 64,
          "url": "https://client.example/es/articles/should-i-let-them-take-the-car.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 65,
          "url": "https://client.example/es/articles/cant-pay-title-loan-this-week.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 66,
          "url": "https://client.example/es/articles/pay-down-title-loan-principal.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 67,
          "url": "https://client.example/es/articles/can-they-take-my-car-title-loan.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 68,
          "url": "https://client.example/es/articles/why-title-loan-balance-never-goes-down.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 69,
          "url": "https://client.example/es/articles/how-much-can-i-save-refinancing-title-loan.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 70,
          "url": "https://client.example/es/articles/online-tribal-title-loan.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 71,
          "url": "https://client.example/es/articles/title-loan-for-emergency-now-stuck.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 72,
          "url": "https://client.example/es/articles/title-loan-myths.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 73,
          "url": "https://client.example/es/articles/title-loan-payoff-amount.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 74,
          "url": "https://client.example/es/articles/partner-took-out-title-loan.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 75,
          "url": "https://client.example/es/articles/where-to-get-title-loan-help.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 76,
          "url": "https://client.example/es/articles/get-car-title-back-after-payoff.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 77,
          "url": "https://client.example/es/articles/title-loan-junk-fees-add-ons.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 78,
          "url": "https://client.example/es/articles/do-i-qualify-to-refinance-title-loan.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 79,
          "url": "https://client.example/es/articles/title-loan-and-bankruptcy.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 80,
          "url": "https://client.example/es/articles/title-loan-buyout-process-step-by-step.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 81,
          "url": "https://client.example/es/articles/is-my-title-loan-legal.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 82,
          "url": "https://client.example/es/articles/refinance-title-loan-now-vs-keep-paying.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 83,
          "url": "https://client.example/es/articles/hiding-car-from-title-loan-repo.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 84,
          "url": "https://client.example/es/articles/title-loan-refinance-lower-monthly-payment.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 85,
          "url": "https://client.example/es/articles/can-title-loan-garnish-wages.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 86,
          "url": "https://client.example/es/articles/how-to-negotiate-with-title-loan-lender.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 87,
          "url": "https://client.example/es/articles/behind-on-title-loan-repossession.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 88,
          "url": "https://client.example/es/articles/hours-cut-cant-keep-up-title-loan.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 89,
          "url": "https://client.example/es/articles/title-loan-collections-deficiency.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 90,
          "url": "https://client.example/es/articles/cosigned-title-loan-for-someone.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 91,
          "url": "https://client.example/es/articles/stuck-with-multiple-title-loans.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 92,
          "url": "https://client.example/es/articles/rolled-over-title-loan-again.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 93,
          "url": "https://client.example/es/articles/stop-paying-title-loan-what-happens.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 169,
          "url": "https://client.example/articles/index.html",
          "status": "307",
          "canonical": ""
        },
        {
          "csv_row": 170,
          "url": "https://client.example/es/articles/index.html",
          "status": "307",
          "canonical": ""
        }
      ],
      "fix": "Obtain valid link edges or inspect templates; repoint applicable hrefs to final URLs.",
      "effort": "2–4 template hours plus 2 QA hours (provisional)",
      "dependencies": "T01 and valid source/destination links",
      "reasoning": "Inlink aggregates show links to redirecting variants; source pages are unknown.",
      "kind": "Observed",
      "affected_csv_rows": [
        6,
        7,
        10,
        11,
        12,
        13,
        14,
        15,
        16,
        17,
        18,
        19,
        20,
        21,
        22,
        23,
        24,
        25,
        26,
        27,
        28,
        29,
        30,
        31,
        32,
        33,
        34,
        35,
        36,
        37,
        38,
        39,
        40,
        41,
        42,
        43,
        44,
        45,
        46,
        47,
        48,
        49,
        53,
        55,
        56,
        57,
        58,
        59,
        60,
        61,
        62,
        63,
        64,
        65,
        66,
        67,
        68,
        69,
        70,
        71,
        72,
        73,
        74,
        75,
        76,
        77,
        78,
        79,
        80,
        81,
        82,
        83,
        84,
        85,
        86,
        87,
        88,
        89,
        90,
        91,
        92,
        93,
        169,
        170
      ],
      "evidence": "REAL Screaming Frog CSV: 84 affected URL records. Inlink aggregates show links to redirecting variants; source pages are unknown.",
      "expert_review": "SEO and engineering review of the original rows and a fresh crawl.",
      "acceptance": "Verify the agreed change in a fresh crawl; compare affected URLs with the preserved source rows."
    },
    {
      "id": "C01",
      "priority": "P2",
      "group": "Content",
      "kind": "Simulated recommendation",
      "title": "Map purchase-intent queries to existing pages",
      "affected_csv_rows": [
        2,
        103,
        52,
        112,
        123,
        106
      ],
      "evidence": "SIMULATED: Semrush scenario keyword rows; positions and volumes are illustrative.",
      "fix": "Validate a live keyword baseline, then match service intent to the mapped landing pages and calls to action.",
      "effort": "4–6 content hours (provisional)",
      "dependencies": "Confirmed business goals; real keyword data; T01 URL policy",
      "reasoning": "In the scenario, mid-ranking intent-led pages are a practical next optimisation scope.",
      "expert_review": "Financial services content and SEO specialist",
      "acceptance": "Replace demo positions with a real baseline and measure agreed lead events.",
      "affected": [
        {
          "csv_row": 2,
          "url": "https://client.example/",
          "status": "200",
          "canonical": "https://client.example/"
        },
        {
          "csv_row": 103,
          "url": "https://client.example/articles/title-loan-buyout-process-step-by-step",
          "status": "200",
          "canonical": "https://client.example/articles/title-loan-buyout-process-step-by-step.html"
        },
        {
          "csv_row": 52,
          "url": "https://client.example/articles/how-to-negotiate-with-title-loan-lender",
          "status": "200",
          "canonical": "https://client.example/articles/how-to-negotiate-with-title-loan-lender.html"
        },
        {
          "csv_row": 112,
          "url": "https://client.example/articles/behind-on-title-loan-repossession",
          "status": "200",
          "canonical": "https://client.example/articles/behind-on-title-loan-repossession.html"
        },
        {
          "csv_row": 123,
          "url": "https://client.example/articles/title-loan-payoff-amount",
          "status": "200",
          "canonical": "https://client.example/articles/title-loan-payoff-amount.html"
        },
        {
          "csv_row": 106,
          "url": "https://client.example/articles/title-loan-refinance-lower-monthly-payment",
          "status": "200",
          "canonical": "https://client.example/articles/title-loan-refinance-lower-monthly-payment.html"
        }
      ]
    },
    {
      "id": "L02",
      "priority": "P2",
      "group": "Internal linking",
      "kind": "Simulated recommendation",
      "title": "Review navigation from topic hubs to priority articles",
      "affected_csv_rows": [
        2,
        126,
        103,
        104,
        52,
        112,
        123,
        107,
        106,
        113,
        3,
        150
      ],
      "evidence": "SIMULATED: Mapped real article URLs with synthetic keyword priorities; source link edges are missing.",
      "fix": "Obtain actual source/destination links, review the topic hubs and add relevant links after confirming the preferred URLs.",
      "effort": "2–4 hours plus QA (provisional)",
      "dependencies": "T01; valid All Inlinks export; C01",
      "reasoning": "Use the simulated demand priorities to demonstrate a navigation task without claiming actual missing links.",
      "expert_review": "SEO and content editor",
      "acceptance": "Verify each proposed source link and target returns 200 in a fresh crawl.",
      "affected": [
        {
          "csv_row": 2,
          "url": "https://client.example/",
          "status": "200",
          "canonical": "https://client.example/"
        },
        {
          "csv_row": 126,
          "url": "https://client.example/articles/where-to-get-title-loan-help",
          "status": "200",
          "canonical": "https://client.example/articles/where-to-get-title-loan-help.html"
        },
        {
          "csv_row": 103,
          "url": "https://client.example/articles/title-loan-buyout-process-step-by-step",
          "status": "200",
          "canonical": "https://client.example/articles/title-loan-buyout-process-step-by-step.html"
        },
        {
          "csv_row": 104,
          "url": "https://client.example/articles/title-loan-refinance-buyout",
          "status": "200",
          "canonical": "https://client.example/articles/title-loan-refinance-buyout.html"
        },
        {
          "csv_row": 52,
          "url": "https://client.example/articles/how-to-negotiate-with-title-loan-lender",
          "status": "200",
          "canonical": "https://client.example/articles/how-to-negotiate-with-title-loan-lender.html"
        },
        {
          "csv_row": 112,
          "url": "https://client.example/articles/behind-on-title-loan-repossession",
          "status": "200",
          "canonical": "https://client.example/articles/behind-on-title-loan-repossession.html"
        },
        {
          "csv_row": 123,
          "url": "https://client.example/articles/title-loan-payoff-amount",
          "status": "200",
          "canonical": "https://client.example/articles/title-loan-payoff-amount.html"
        },
        {
          "csv_row": 107,
          "url": "https://client.example/articles/sell-car-with-title-loan",
          "status": "200",
          "canonical": "https://client.example/articles/sell-car-with-title-loan.html"
        },
        {
          "csv_row": 106,
          "url": "https://client.example/articles/title-loan-refinance-lower-monthly-payment",
          "status": "200",
          "canonical": "https://client.example/articles/title-loan-refinance-lower-monthly-payment.html"
        },
        {
          "csv_row": 113,
          "url": "https://client.example/articles/is-my-title-loan-legal",
          "status": "200",
          "canonical": "https://client.example/articles/is-my-title-loan-legal.html"
        },
        {
          "csv_row": 3,
          "url": "https://client.example/es/",
          "status": "200",
          "canonical": "https://client.example/es/"
        },
        {
          "csv_row": 150,
          "url": "https://client.example/es/articles/where-to-get-title-loan-help",
          "status": "200",
          "canonical": "https://client.example/es/articles/where-to-get-title-loan-help.html"
        }
      ]
    },
    {
      "id": "T03",
      "priority": "P2",
      "group": "Technical SEO",
      "kind": "Simulated recommendation",
      "title": "Check reciprocal language annotations",
      "affected_csv_rows": [
        50,
        131,
        132,
        133,
        134,
        135
      ],
      "evidence": "SIMULATED: Sitebulb scenario SB04; missing hreflang is hypothetical.",
      "fix": "Inspect these EN/ES page pairs and verify reciprocal hreflang and canonical alignment before any edit.",
      "effort": "2–3 diagnostic hours (provisional)",
      "dependencies": "Actual rendered HTML; language policy; T01",
      "reasoning": "A validation task is appropriate until the hypothetical hint is confirmed.",
      "expert_review": "International SEO specialist",
      "acceptance": "Record actual annotations and expected alternate URLs for each inspected pair.",
      "affected": [
        {
          "csv_row": 50,
          "url": "https://client.example/es/articles/",
          "status": "200",
          "canonical": "https://client.example/es/articles/"
        },
        {
          "csv_row": 131,
          "url": "https://client.example/es/articles/stop-paying-title-loan-what-happens",
          "status": "200",
          "canonical": "https://client.example/es/articles/stop-paying-title-loan-what-happens.html"
        },
        {
          "csv_row": 132,
          "url": "https://client.example/es/articles/stuck-with-multiple-title-loans",
          "status": "200",
          "canonical": "https://client.example/es/articles/stuck-with-multiple-title-loans.html"
        },
        {
          "csv_row": 133,
          "url": "https://client.example/es/articles/rolled-over-title-loan-again",
          "status": "200",
          "canonical": "https://client.example/es/articles/rolled-over-title-loan-again.html"
        },
        {
          "csv_row": 134,
          "url": "https://client.example/es/articles/title-loan-collections-deficiency",
          "status": "200",
          "canonical": "https://client.example/es/articles/title-loan-collections-deficiency.html"
        },
        {
          "csv_row": 135,
          "url": "https://client.example/es/articles/cosigned-title-loan-for-someone",
          "status": "200",
          "canonical": "https://client.example/es/articles/cosigned-title-loan-for-someone.html"
        }
      ]
    },
    {
      "id": "L03",
      "priority": "P2",
      "group": "Internal linking",
      "kind": "Simulated recommendation",
      "title": "Validate the illustrative orphan-page finding",
      "affected_csv_rows": [
        51,
        52
      ],
      "evidence": "SIMULATED: Sitebulb scenario SB03; orphan status is unverified.",
      "fix": "Compare a full crawl link graph with sitemap, analytics and known URL sources before proposing navigation changes.",
      "effort": "1–2 diagnostic hours (provisional)",
      "dependencies": "Completed Sitebulb audit or valid link graph; URL discovery sources",
      "reasoning": "The current Screaming Frog aggregates cannot prove orphan status.",
      "expert_review": "Technical SEO specialist",
      "acceptance": "Confirm or dismiss each scenario URL using actual inbound link edges.",
      "affected": [
        {
          "csv_row": 51,
          "url": "https://client.example/articles/title-loan-gps-tracker-kill-switch",
          "status": "200",
          "canonical": "https://client.example/articles/title-loan-gps-tracker-kill-switch.html"
        },
        {
          "csv_row": 52,
          "url": "https://client.example/articles/how-to-negotiate-with-title-loan-lender",
          "status": "200",
          "canonical": "https://client.example/articles/how-to-negotiate-with-title-loan-lender.html"
        }
      ]
    },
    {
      "id": "B01",
      "priority": "P2",
      "group": "Backlinks",
      "kind": "Simulated recommendation",
      "title": "Review link relevance and a lost-link recovery candidate",
      "affected_csv_rows": [
        2
      ],
      "evidence": "SIMULATED: Ahrefs scenario: 44 referring domains and six fictional sample links, including one lost example.",
      "fix": "Replace every fictional domain with a real export, inspect lost links and review relevance before any outreach.",
      "effort": "2–4 research hours after real data (provisional)",
      "dependencies": "Verified Ahrefs/Semrush backlink data; link policy",
      "reasoning": "Demonstrates a backlink review task; no link is labelled toxic and no disavow is proposed.",
      "expert_review": "Off-page SEO specialist",
      "acceptance": "Attach verified source URLs and evidence; obtain separate approval for any outreach.",
      "affected": [
        {
          "csv_row": 2,
          "url": "https://client.example/",
          "status": "200",
          "canonical": "https://client.example/"
        }
      ]
    },
    {
      "id": "C03",
      "priority": "P2",
      "group": "Content",
      "kind": "Simulated recommendation",
      "title": "Validate competitor coverage and financial claims",
      "affected_csv_rows": [
        52,
        123,
        113
      ],
      "evidence": "SIMULATED: Semrush scenario competitors are fictional .example domains; no competitive gap is established.",
      "fix": "Identify actual competing pages, check search intent, and review legal or financial claims with a qualified expert.",
      "effort": "3–5 research/editor hours (provisional)",
      "dependencies": "Confirmed market and goals; real competitor evidence",
      "reasoning": "The sample demonstrates how an evidence-led content gap would enter the backlog.",
      "expert_review": "Qualified financial/legal reviewer and Spanish-language editor",
      "acceptance": "Record real competing URLs, supported claims and approved wording before publishing.",
      "affected": [
        {
          "csv_row": 52,
          "url": "https://client.example/articles/how-to-negotiate-with-title-loan-lender",
          "status": "200",
          "canonical": "https://client.example/articles/how-to-negotiate-with-title-loan-lender.html"
        },
        {
          "csv_row": 123,
          "url": "https://client.example/articles/title-loan-payoff-amount",
          "status": "200",
          "canonical": "https://client.example/articles/title-loan-payoff-amount.html"
        },
        {
          "csv_row": 113,
          "url": "https://client.example/articles/is-my-title-loan-legal",
          "status": "200",
          "canonical": "https://client.example/articles/is-my-title-loan-legal.html"
        }
      ]
    },
    {
      "id": "C02",
      "group": "Content",
      "priority": "P3",
      "state": "Heuristic review",
      "title": "Review titles and descriptions against real search intent",
      "affected": [
        {
          "csv_row": 2,
          "url": "https://client.example/",
          "status": "200",
          "canonical": "https://client.example/"
        },
        {
          "csv_row": 3,
          "url": "https://client.example/es/",
          "status": "200",
          "canonical": "https://client.example/es/"
        },
        {
          "csv_row": 4,
          "url": "https://client.example/articles/",
          "status": "200",
          "canonical": "https://client.example/articles/"
        },
        {
          "csv_row": 50,
          "url": "https://client.example/es/articles/",
          "status": "200",
          "canonical": "https://client.example/es/articles/"
        },
        {
          "csv_row": 51,
          "url": "https://client.example/articles/title-loan-gps-tracker-kill-switch",
          "status": "200",
          "canonical": "https://client.example/articles/title-loan-gps-tracker-kill-switch.html"
        },
        {
          "csv_row": 52,
          "url": "https://client.example/articles/how-to-negotiate-with-title-loan-lender",
          "status": "200",
          "canonical": "https://client.example/articles/how-to-negotiate-with-title-loan-lender.html"
        },
        {
          "csv_row": 54,
          "url": "https://client.example/articles/military-title-loan-illegal",
          "status": "200",
          "canonical": "https://client.example/articles/military-title-loan-illegal.html"
        },
        {
          "csv_row": 94,
          "url": "https://client.example/articles/title-loan-calling-my-job-references",
          "status": "200",
          "canonical": "https://client.example/articles/title-loan-calling-my-job-references.html"
        },
        {
          "csv_row": 95,
          "url": "https://client.example/articles/title-loan-junk-fees-add-ons",
          "status": "200",
          "canonical": "https://client.example/articles/title-loan-junk-fees-add-ons.html"
        },
        {
          "csv_row": 96,
          "url": "https://client.example/articles/stuck-with-multiple-title-loans",
          "status": "200",
          "canonical": "https://client.example/articles/stuck-with-multiple-title-loans.html"
        },
        {
          "csv_row": 97,
          "url": "https://client.example/articles/pay-down-title-loan-principal",
          "status": "200",
          "canonical": "https://client.example/articles/pay-down-title-loan-principal.html"
        },
        {
          "csv_row": 98,
          "url": "https://client.example/articles/title-loan-and-bankruptcy",
          "status": "200",
          "canonical": "https://client.example/articles/title-loan-and-bankruptcy.html"
        },
        {
          "csv_row": 99,
          "url": "https://client.example/articles/cant-pay-title-loan-this-week",
          "status": "200",
          "canonical": "https://client.example/articles/cant-pay-title-loan-this-week.html"
        },
        {
          "csv_row": 100,
          "url": "https://client.example/articles/title-loan-collections-deficiency",
          "status": "200",
          "canonical": "https://client.example/articles/title-loan-collections-deficiency.html"
        },
        {
          "csv_row": 101,
          "url": "https://client.example/articles/hiding-car-from-title-loan-repo",
          "status": "200",
          "canonical": "https://client.example/articles/hiding-car-from-title-loan-repo.html"
        },
        {
          "csv_row": 102,
          "url": "https://client.example/articles/do-title-loans-affect-credit",
          "status": "200",
          "canonical": "https://client.example/articles/do-title-loans-affect-credit.html"
        },
        {
          "csv_row": 103,
          "url": "https://client.example/articles/title-loan-buyout-process-step-by-step",
          "status": "200",
          "canonical": "https://client.example/articles/title-loan-buyout-process-step-by-step.html"
        },
        {
          "csv_row": 104,
          "url": "https://client.example/articles/title-loan-refinance-buyout",
          "status": "200",
          "canonical": "https://client.example/articles/title-loan-refinance-buyout.html"
        },
        {
          "csv_row": 105,
          "url": "https://client.example/articles/do-i-qualify-to-refinance-title-loan",
          "status": "200",
          "canonical": "https://client.example/articles/do-i-qualify-to-refinance-title-loan.html"
        },
        {
          "csv_row": 106,
          "url": "https://client.example/articles/title-loan-refinance-lower-monthly-payment",
          "status": "200",
          "canonical": "https://client.example/articles/title-loan-refinance-lower-monthly-payment.html"
        },
        {
          "csv_row": 107,
          "url": "https://client.example/articles/sell-car-with-title-loan",
          "status": "200",
          "canonical": "https://client.example/articles/sell-car-with-title-loan.html"
        },
        {
          "csv_row": 108,
          "url": "https://client.example/articles/being-sued-by-title-loan-company",
          "status": "200",
          "canonical": "https://client.example/articles/being-sued-by-title-loan-company.html"
        },
        {
          "csv_row": 109,
          "url": "https://client.example/articles/cosigned-title-loan-for-someone",
          "status": "200",
          "canonical": "https://client.example/articles/cosigned-title-loan-for-someone.html"
        },
        {
          "csv_row": 111,
          "url": "https://client.example/articles/why-title-loan-balance-never-goes-down",
          "status": "200",
          "canonical": "https://client.example/articles/why-title-loan-balance-never-goes-down.html"
        },
        {
          "csv_row": 112,
          "url": "https://client.example/articles/behind-on-title-loan-repossession",
          "status": "200",
          "canonical": "https://client.example/articles/behind-on-title-loan-repossession.html"
        },
        {
          "csv_row": 113,
          "url": "https://client.example/articles/is-my-title-loan-legal",
          "status": "200",
          "canonical": "https://client.example/articles/is-my-title-loan-legal.html"
        },
        {
          "csv_row": 114,
          "url": "https://client.example/articles/can-they-take-my-car-title-loan",
          "status": "200",
          "canonical": "https://client.example/articles/can-they-take-my-car-title-loan.html"
        },
        {
          "csv_row": 115,
          "url": "https://client.example/articles/should-i-let-them-take-the-car",
          "status": "200",
          "canonical": "https://client.example/articles/should-i-let-them-take-the-car.html"
        },
        {
          "csv_row": 116,
          "url": "https://client.example/articles/title-loan-renewal-cycle",
          "status": "200",
          "canonical": "https://client.example/articles/title-loan-renewal-cycle.html"
        },
        {
          "csv_row": 117,
          "url": "https://client.example/articles/title-loan-vs-payday-vs-personal-loan",
          "status": "200",
          "canonical": "https://client.example/articles/title-loan-vs-payday-vs-personal-loan.html"
        },
        {
          "csv_row": 118,
          "url": "https://client.example/articles/get-car-title-back-after-payoff",
          "status": "200",
          "canonical": "https://client.example/articles/get-car-title-back-after-payoff.html"
        },
        {
          "csv_row": 119,
          "url": "https://client.example/articles/how-much-can-i-save-refinancing-title-loan",
          "status": "200",
          "canonical": "https://client.example/articles/how-much-can-i-save-refinancing-title-loan.html"
        },
        {
          "csv_row": 120,
          "url": "https://client.example/articles/online-tribal-title-loan",
          "status": "200",
          "canonical": "https://client.example/articles/online-tribal-title-loan.html"
        },
        {
          "csv_row": 121,
          "url": "https://client.example/articles/title-loan-for-emergency-now-stuck",
          "status": "200",
          "canonical": "https://client.example/articles/title-loan-for-emergency-now-stuck.html"
        },
        {
          "csv_row": 122,
          "url": "https://client.example/articles/rolled-over-title-loan-again",
          "status": "200",
          "canonical": "https://client.example/articles/rolled-over-title-loan-again.html"
        },
        {
          "csv_row": 123,
          "url": "https://client.example/articles/title-loan-payoff-amount",
          "status": "200",
          "canonical": "https://client.example/articles/title-loan-payoff-amount.html"
        },
        {
          "csv_row": 124,
          "url": "https://client.example/articles/repossessed-car-belongings-inside",
          "status": "200",
          "canonical": "https://client.example/articles/repossessed-car-belongings-inside.html"
        },
        {
          "csv_row": 125,
          "url": "https://client.example/articles/can-title-loan-garnish-wages",
          "status": "200",
          "canonical": "https://client.example/articles/can-title-loan-garnish-wages.html"
        },
        {
          "csv_row": 126,
          "url": "https://client.example/articles/where-to-get-title-loan-help",
          "status": "200",
          "canonical": "https://client.example/articles/where-to-get-title-loan-help.html"
        },
        {
          "csv_row": 127,
          "url": "https://client.example/articles/stop-paying-title-loan-what-happens",
          "status": "200",
          "canonical": "https://client.example/articles/stop-paying-title-loan-what-happens.html"
        },
        {
          "csv_row": 128,
          "url": "https://client.example/articles/hours-cut-cant-keep-up-title-loan",
          "status": "200",
          "canonical": "https://client.example/articles/hours-cut-cant-keep-up-title-loan.html"
        },
        {
          "csv_row": 129,
          "url": "https://client.example/articles/partner-took-out-title-loan",
          "status": "200",
          "canonical": "https://client.example/articles/partner-took-out-title-loan.html"
        },
        {
          "csv_row": 130,
          "url": "https://client.example/articles/title-loan-myths",
          "status": "200",
          "canonical": "https://client.example/articles/title-loan-myths.html"
        },
        {
          "csv_row": 131,
          "url": "https://client.example/es/articles/stop-paying-title-loan-what-happens",
          "status": "200",
          "canonical": "https://client.example/es/articles/stop-paying-title-loan-what-happens.html"
        },
        {
          "csv_row": 132,
          "url": "https://client.example/es/articles/stuck-with-multiple-title-loans",
          "status": "200",
          "canonical": "https://client.example/es/articles/stuck-with-multiple-title-loans.html"
        },
        {
          "csv_row": 133,
          "url": "https://client.example/es/articles/rolled-over-title-loan-again",
          "status": "200",
          "canonical": "https://client.example/es/articles/rolled-over-title-loan-again.html"
        },
        {
          "csv_row": 134,
          "url": "https://client.example/es/articles/title-loan-collections-deficiency",
          "status": "200",
          "canonical": "https://client.example/es/articles/title-loan-collections-deficiency.html"
        },
        {
          "csv_row": 135,
          "url": "https://client.example/es/articles/cosigned-title-loan-for-someone",
          "status": "200",
          "canonical": "https://client.example/es/articles/cosigned-title-loan-for-someone.html"
        },
        {
          "csv_row": 136,
          "url": "https://client.example/es/articles/behind-on-title-loan-repossession",
          "status": "200",
          "canonical": "https://client.example/es/articles/behind-on-title-loan-repossession.html"
        },
        {
          "csv_row": 137,
          "url": "https://client.example/es/articles/hours-cut-cant-keep-up-title-loan",
          "status": "200",
          "canonical": "https://client.example/es/articles/hours-cut-cant-keep-up-title-loan.html"
        },
        {
          "csv_row": 138,
          "url": "https://client.example/es/articles/can-title-loan-garnish-wages",
          "status": "200",
          "canonical": "https://client.example/es/articles/can-title-loan-garnish-wages.html"
        },
        {
          "csv_row": 139,
          "url": "https://client.example/es/articles/how-to-negotiate-with-title-loan-lender",
          "status": "200",
          "canonical": "https://client.example/es/articles/how-to-negotiate-with-title-loan-lender.html"
        },
        {
          "csv_row": 140,
          "url": "https://client.example/es/articles/hiding-car-from-title-loan-repo",
          "status": "200",
          "canonical": "https://client.example/es/articles/hiding-car-from-title-loan-repo.html"
        },
        {
          "csv_row": 141,
          "url": "https://client.example/es/articles/refinance-title-loan-now-vs-keep-paying",
          "status": "200",
          "canonical": "https://client.example/es/articles/refinance-title-loan-now-vs-keep-paying.html"
        },
        {
          "csv_row": 142,
          "url": "https://client.example/es/articles/title-loan-refinance-lower-monthly-payment",
          "status": "200",
          "canonical": "https://client.example/es/articles/title-loan-refinance-lower-monthly-payment.html"
        },
        {
          "csv_row": 143,
          "url": "https://client.example/es/articles/is-my-title-loan-legal",
          "status": "200",
          "canonical": "https://client.example/es/articles/is-my-title-loan-legal.html"
        },
        {
          "csv_row": 144,
          "url": "https://client.example/es/articles/title-loan-and-bankruptcy",
          "status": "200",
          "canonical": "https://client.example/es/articles/title-loan-and-bankruptcy.html"
        },
        {
          "csv_row": 145,
          "url": "https://client.example/es/articles/do-i-qualify-to-refinance-title-loan",
          "status": "200",
          "canonical": "https://client.example/es/articles/do-i-qualify-to-refinance-title-loan.html"
        },
        {
          "csv_row": 146,
          "url": "https://client.example/es/articles/title-loan-buyout-process-step-by-step",
          "status": "200",
          "canonical": "https://client.example/es/articles/title-loan-buyout-process-step-by-step.html"
        },
        {
          "csv_row": 147,
          "url": "https://client.example/es/articles/title-loan-junk-fees-add-ons",
          "status": "200",
          "canonical": "https://client.example/es/articles/title-loan-junk-fees-add-ons.html"
        },
        {
          "csv_row": 148,
          "url": "https://client.example/es/articles/get-car-title-back-after-payoff",
          "status": "200",
          "canonical": "https://client.example/es/articles/get-car-title-back-after-payoff.html"
        },
        {
          "csv_row": 149,
          "url": "https://client.example/es/articles/partner-took-out-title-loan",
          "status": "200",
          "canonical": "https://client.example/es/articles/partner-took-out-title-loan.html"
        },
        {
          "csv_row": 150,
          "url": "https://client.example/es/articles/where-to-get-title-loan-help",
          "status": "200",
          "canonical": "https://client.example/es/articles/where-to-get-title-loan-help.html"
        },
        {
          "csv_row": 151,
          "url": "https://client.example/es/articles/online-tribal-title-loan",
          "status": "200",
          "canonical": "https://client.example/es/articles/online-tribal-title-loan.html"
        },
        {
          "csv_row": 152,
          "url": "https://client.example/es/articles/title-loan-myths",
          "status": "200",
          "canonical": "https://client.example/es/articles/title-loan-myths.html"
        },
        {
          "csv_row": 153,
          "url": "https://client.example/es/articles/title-loan-payoff-amount",
          "status": "200",
          "canonical": "https://client.example/es/articles/title-loan-payoff-amount.html"
        },
        {
          "csv_row": 154,
          "url": "https://client.example/es/articles/why-title-loan-balance-never-goes-down",
          "status": "200",
          "canonical": "https://client.example/es/articles/why-title-loan-balance-never-goes-down.html"
        },
        {
          "csv_row": 155,
          "url": "https://client.example/es/articles/title-loan-for-emergency-now-stuck",
          "status": "200",
          "canonical": "https://client.example/es/articles/title-loan-for-emergency-now-stuck.html"
        },
        {
          "csv_row": 156,
          "url": "https://client.example/es/articles/can-they-take-my-car-title-loan",
          "status": "200",
          "canonical": "https://client.example/es/articles/can-they-take-my-car-title-loan.html"
        },
        {
          "csv_row": 157,
          "url": "https://client.example/es/articles/how-much-can-i-save-refinancing-title-loan",
          "status": "200",
          "canonical": "https://client.example/es/articles/how-much-can-i-save-refinancing-title-loan.html"
        },
        {
          "csv_row": 158,
          "url": "https://client.example/es/articles/cant-pay-title-loan-this-week",
          "status": "200",
          "canonical": "https://client.example/es/articles/cant-pay-title-loan-this-week.html"
        },
        {
          "csv_row": 159,
          "url": "https://client.example/es/articles/should-i-let-them-take-the-car",
          "status": "200",
          "canonical": "https://client.example/es/articles/should-i-let-them-take-the-car.html"
        },
        {
          "csv_row": 160,
          "url": "https://client.example/es/articles/do-title-loans-affect-credit",
          "status": "200",
          "canonical": "https://client.example/es/articles/do-title-loans-affect-credit.html"
        },
        {
          "csv_row": 161,
          "url": "https://client.example/es/articles/title-loan-renewal-cycle",
          "status": "200",
          "canonical": "https://client.example/es/articles/title-loan-renewal-cycle.html"
        },
        {
          "csv_row": 162,
          "url": "https://client.example/es/articles/pay-down-title-loan-principal",
          "status": "200",
          "canonical": "https://client.example/es/articles/pay-down-title-loan-principal.html"
        },
        {
          "csv_row": 163,
          "url": "https://client.example/es/articles/repossessed-car-belongings-inside",
          "status": "200",
          "canonical": "https://client.example/es/articles/repossessed-car-belongings-inside.html"
        },
        {
          "csv_row": 164,
          "url": "https://client.example/es/articles/title-loan-refinance-buyout",
          "status": "200",
          "canonical": "https://client.example/es/articles/title-loan-refinance-buyout.html"
        },
        {
          "csv_row": 165,
          "url": "https://client.example/es/articles/title-loan-calling-my-job-references",
          "status": "200",
          "canonical": "https://client.example/es/articles/title-loan-calling-my-job-references.html"
        },
        {
          "csv_row": 166,
          "url": "https://client.example/es/articles/military-title-loan-illegal",
          "status": "200",
          "canonical": "https://client.example/es/articles/military-title-loan-illegal.html"
        },
        {
          "csv_row": 167,
          "url": "https://client.example/es/articles/title-loan-vs-payday-vs-personal-loan",
          "status": "200",
          "canonical": "https://client.example/es/articles/title-loan-vs-payday-vs-personal-loan.html"
        },
        {
          "csv_row": 168,
          "url": "https://client.example/es/articles/being-sued-by-title-loan-company",
          "status": "200",
          "canonical": "https://client.example/es/articles/being-sued-by-title-loan-company.html"
        },
        {
          "csv_row": 171,
          "url": "https://client.example/es/articles/sell-car-with-title-loan",
          "status": "200",
          "canonical": "https://client.example/es/articles/sell-car-with-title-loan.html"
        },
        {
          "csv_row": 172,
          "url": "https://client.example/es/articles/title-loan-gps-tracker-kill-switch",
          "status": "200",
          "canonical": "https://client.example/es/articles/title-loan-gps-tracker-kill-switch.html"
        }
      ],
      "fix": "Use real query evidence before editing priority page snippets; review blank descriptions.",
      "effort": "2–4 hours for first 10 priority pages (provisional)",
      "dependencies": "Confirmed business goals and keyword/ranking baseline",
      "reasoning": "600/1050 pixel values are review heuristics, not Google limits.",
      "kind": "Heuristic review",
      "affected_csv_rows": [
        2,
        3,
        4,
        50,
        51,
        52,
        54,
        94,
        95,
        96,
        97,
        98,
        99,
        100,
        101,
        102,
        103,
        104,
        105,
        106,
        107,
        108,
        109,
        111,
        112,
        113,
        114,
        115,
        116,
        117,
        118,
        119,
        120,
        121,
        122,
        123,
        124,
        125,
        126,
        127,
        128,
        129,
        130,
        131,
        132,
        133,
        134,
        135,
        136,
        137,
        138,
        139,
        140,
        141,
        142,
        143,
        144,
        145,
        146,
        147,
        148,
        149,
        150,
        151,
        152,
        153,
        154,
        155,
        156,
        157,
        158,
        159,
        160,
        161,
        162,
        163,
        164,
        165,
        166,
        167,
        168,
        171,
        172
      ],
      "evidence": "REAL Screaming Frog CSV: 83 affected URL records. 600/1050 pixel values are review heuristics, not Google limits.",
      "expert_review": "SEO editor; snippet widths are heuristics, not Google limits.",
      "acceptance": "Verify the agreed change in a fresh crawl; compare affected URLs with the preserved source rows."
    }
  ],
  "checks": [
    "Semrush, Ahrefs and Sitebulb outputs are authored demo data, not vendor responses. Their snapshot date is an illustrative scenario date, not an export date.",
    "Semrush shows 42 keywords / 96 visits; Ahrefs shows 38 / 84. This illustrates different vendor coverage and estimates, not an observed disagreement or measured traffic.",
    "Sitebulb canonical and redirect counts reuse the real Screaming Frog scope. They do not constitute independent corroboration. Orphan and hreflang examples are hypothetical.",
    "Competitor and referring domains ending in .example are fictional. No outreach, disavow, Jira issue, Google Doc or website modification is performed."
  ],
  "intake": "Client identity is anonymized. The relationship to Mantas Auk is unconfirmed. Scenario goal: qualified Texas auto-loan-exit/title-payoff enquiries in English and Spanish; owner goals and KPIs need confirmation. Reporting/task destination examples: Google Docs and Jira. No document or ticket is created by this demo."
};

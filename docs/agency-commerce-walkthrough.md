# Separate agency walkthrough

The isolated commerce showcase demonstrates one Unstoprev weekly marketing review through five stages: request, plan, review, local execution playback and results. It retains the AURA dark theme and uses the supplied completion-page screenshot as the layout reference. The Base44 editor preview required authentication, and external source access required a paid plan; no Base44 application was changed.

Build: `npm run build:commerce`. Publish `dist/showcase/commerce-workflow` to the existing Render static demo service. The main AURA application, authentication, backend and production infrastructure are independent of this entry.

The root opens the walkthrough. `?screen=results` opens the compact completion page, and `?scene=0` through `?scene=4` select a stage. The guide supports play/pause, next, previous, replay and hide. Manual navigation stops autoplay. The browser back button restores the matching stage.

All source reports, product details, accounts, targets and offers are fictional scenario inputs. The four local report processors and packet validation run in the browser. The animated execution stage is explicitly a prepared playback; no vendor API or model call, backend workflow-history entry or client approval is claimed. Receipt IDs represent local source processing. Network connections are blocked by the standalone entry's CSP. The build rejects production API and authentication clients.

The compact results page contains four source-report dialogs, one inventory issue, tool badges and activity. Expand Results for performance, three ad tests, channel copy, the approval checklist and source definitions. Evidence links open the correct local report. Download exports the complete labelled Markdown review. Share copies the public demo results URL. Schedule is an illustrative preview and creates no automation. Connect explains the real-input requirements and does not authorize or alter accounts.

The 30 available units yield approximately 0.70 days of cover. Additional Amazon promotion is held. Website stock is unconfirmed. Website purchases are unavailable without a separate store report; ad-attributed purchases and sales and total Amazon ASIN sales remain separate. All implementation stays pending account-manager approval.

Validation: scenario computation/provenance tests, result-rendering checks, deep-link tests, focused ESLint, standalone build and browser checks of the deployed stages, dialogs and outputs.

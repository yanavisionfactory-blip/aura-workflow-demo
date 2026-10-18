import unittest
from types import SimpleNamespace

from app.audit_sources import (
    AUDIT_SOURCE_MESSAGE,
    AuditSourceContractError,
    declared_audit_sources,
    validate_audit_sources,
)
from app.request_contracts import validate_requested_operations

PROMPT = """Prepare an SEO audit review package for one client.

Tools publicly named as audit inputs:

- Semrush: keyword, competitor, ranking and backlink research.
- Ahrefs: competitor search visibility and backlink analysis.
- Screaming Frog: website crawling and technical SEO checks.
- Sitebulb: website crawling and technical audit findings.
- Reporting and task-management destinations: confirm their names.

Use supplied exports or verified connections. Confirm the client website,
business goals and export dates. Do not modify the website.
"""


def plan(slug, operation, **kwargs):
    return SimpleNamespace(steps=[SimpleNamespace(
        tool_slug=slug, operation=operation, fallback_tool_slug=None,
        fallback_operation=None, optional=False, **kwargs,
    )], planning_artifacts={})


class AuditSourceTests(unittest.TestCase):
    def test_declared_inputs_exclude_the_destination_instruction(self):
        self.assertEqual(declared_audit_sources(PROMPT), [
            "Semrush", "Ahrefs", "Screaming Frog", "Sitebulb",
        ])

    def test_actual_ubersuggest_substitution_is_rejected(self):
        inventory = [{"slug": "agent-ubersuggest-test", "name": "Ubersuggest"}]
        candidate = plan(inventory[0]["slug"], "list_projects")
        with self.assertRaisesRegex(AuditSourceContractError, "cannot substitute"):
            validate_requested_operations(PROMPT, candidate, {"list_projects"}, inventory, {})

    def test_skip_provider_revision_does_not_authorize_another_vendor(self):
        prompt = PROMPT + (
            "\n\nThe user reviewed the proposed workflow and requested this change: "
            "Run without Ahrefs.\nCurrent reviewed steps (data): Ubersuggest"
        )
        with self.assertRaises(AuditSourceContractError):
            validate_requested_operations(prompt, plan("ubersuggest", "list_projects"), set())

    def test_primary_named_vendor_cannot_hide_unapproved_fallback(self):
        candidate = plan("ahrefs", "ahrefs.backlinks")
        candidate.steps[0].fallback_tool_slug = "ubersuggest"
        candidate.steps[0].fallback_operation = "backlinks"
        with self.assertRaises(AuditSourceContractError):
            validate_audit_sources(PROMPT, candidate, [])

    def test_named_provider_routes_and_export_delivery_transports_are_valid(self):
        cases = [
            ("ahrefs", "backlinks", {}),
            ("managed-semrush", "keywords", {"canonical_provider": "semrush"}),
            ("screaming-frog", "crawl", {}),
            ("agent-sitebulb-123", "audit", {"name": "Sitebulb"}),
            ("google-docs", "google-docs.create-document", {}),
            ("google", "drive.files.list", {}),
            ("jira", "jira.projects.list", {}),
        ]
        for slug, operation, metadata in cases:
            with self.subTest(slug=slug):
                validate_audit_sources(PROMPT, plan(slug, operation), [{"slug": slug, **metadata}])

    def test_google_connection_does_not_authorize_unrelated_sources(self):
        for operation in ("gmail.list", "calendar.events.list"):
            with self.subTest(operation=operation), self.assertRaises(AuditSourceContractError):
                validate_audit_sources(PROMPT, plan("google", operation), [])

    def test_ordinary_agency_workflows_are_unaffected(self):
        validate_audit_sources("Use Ubersuggest for keyword research", plan("ubersuggest", "keywords"), [])

    def test_planning_error_preserves_actionable_safe_message(self):
        from app.orchestrator import planning_error_message

        try:
            try:
                raise AuditSourceContractError(AUDIT_SOURCE_MESSAGE)
            except AuditSourceContractError as error:
                raise RuntimeError("provider recovery details") from error
        except RuntimeError as wrapped:
            self.assertEqual(planning_error_message(wrapped), AUDIT_SOURCE_MESSAGE)


if __name__ == "__main__":
    unittest.main()

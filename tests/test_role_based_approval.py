from automation_agent.core.role_based_approval import RoleBasedApproval


def test_reviewer_can_approve_exports_but_not_quickbooks_sync(base_config, tmp_path):
    approval = RoleBasedApproval(base_config, output_folder=tmp_path)

    export_decision = approval.evaluate(
        approved_by="Reviewer User",
        role="reviewer",
        scope="export_only",
        system="general",
        environment="sandbox",
        dry_run=True,
    )
    sync_decision = approval.evaluate(
        approved_by="Reviewer User",
        role="reviewer",
        scope="quickbooks sandbox sync",
        system="quickbooks",
        environment="sandbox",
        dry_run=True,
    )

    assert export_decision.allowed is True
    assert sync_decision.allowed is False
    assert sync_decision.required_permission == "approve_quickbooks_sandbox_sync"


def test_admin_can_approve_quickbooks_production_sync(base_config, tmp_path):
    approval = RoleBasedApproval(base_config, output_folder=tmp_path)

    decision = approval.evaluate(
        approved_by="Admin User",
        role="admin",
        scope="quickbooks production sync",
        system="quickbooks",
        environment="production",
        dry_run=False,
    )

    assert decision.allowed is True
    assert decision.required_permission == "approve_quickbooks_production_sync"

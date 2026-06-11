from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

# Allow running the project without installing it as a package.
PROJECT_ROOT = Path(__file__).resolve().parent
SRC_PATH = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_PATH))

from automation_agent.connectors.approval import HumanApproval
from automation_agent.connectors.crm_connector import CRMConnector
from automation_agent.connectors.quickbooks_connector import QuickBooksConnector
from automation_agent.core.approval_history import ApprovalHistory
from automation_agent.core.email_notifier import EmailNotifier
from automation_agent.core.file_versioning import FileVersionManager
from automation_agent.core.pipeline import process_file
from automation_agent.core.role_based_approval import RoleBasedApproval
from automation_agent.core.scheduler import ScheduledJobManager
from automation_agent.core.system_backup import SystemBackupManager
from automation_agent.utils.logger_config import setup_logger


def load_config(config_path: str | Path = "config.yaml") -> dict:
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Business Automation Agent V24")
    parser.add_argument("--input", help="Path to CSV or Excel input file")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument(
        "--skip-approval",
        action="store_true",
        help="Skip approval prompt. Role permissions and integration safety checks still apply.",
    )
    parser.add_argument(
        "--quickbooks-sync",
        action="store_true",
        help="Run the protected QuickBooks sync flow. It still obeys dry_run, mode, credentials, role, and approval settings.",
    )
    parser.add_argument(
        "--approved-by",
        default="CLI user",
        help="Name/email of the person approving the reviewed output.",
    )
    parser.add_argument(
        "--approver-role",
        default="reviewer",
        choices=["viewer", "reviewer", "approver", "admin"],
        help="Role used by the role-based approval guard.",
    )
    parser.add_argument(
        "--approval-note",
        default="",
        help="Optional note saved with the approval history record.",
    )
    parser.add_argument(
        "--run-scheduled-jobs",
        action="store_true",
        help="Run all due scheduled automation jobs and exit. Use this with Windows Task Scheduler or cron.",
    )
    parser.add_argument(
        "--run-job-now",
        default="",
        help="Run one scheduled job immediately by job_id and exit.",
    )
    parser.add_argument(
        "--send-test-notification",
        action="store_true",
        help="Send a test email notification. In dry-run mode this writes only a local preview file.",
    )

    parser.add_argument(
        "--list-runs",
        action="store_true",
        help="List recent versioned processing runs and exit.",
    )
    parser.add_argument(
        "--rollback-run",
        default="",
        help="Restore active output files from a previous versioned run ID.",
    )
    parser.add_argument(
        "--rollback-reason",
        default="",
        help="Optional reason saved with a rollback event.",
    )

    parser.add_argument(
        "--create-system-backup",
        action="store_true",
        help="Create a ZIP backup of the local system state and exit.",
    )
    parser.add_argument(
        "--list-system-backups",
        action="store_true",
        help="List available system-state backups and exit.",
    )
    parser.add_argument(
        "--restore-system-backup",
        default="",
        help="Restore a system-state backup by backup ID or ZIP path. Dry-run by default.",
    )
    parser.add_argument(
        "--restore-apply",
        action="store_true",
        help="Actually apply --restore-system-backup. Without this flag, restore runs in preview mode only.",
    )
    parser.add_argument(
        "--backup-note",
        default="",
        help="Optional note saved with backup or restore events.",
    )
    return parser.parse_args()


def record_approval(
    approval_history: ApprovalHistory,
    *,
    approved_by: str,
    approver_role: str,
    permission_result: str,
    approval_status: str,
    approval_scope: str,
    input_file: str,
    result,
    config: dict,
    note: str = "",
):
    return approval_history.record(
        approved_by=approved_by,
        approver_role=approver_role,
        permission_result=permission_result,
        approval_status=approval_status,
        approval_scope=approval_scope,
        source_name=str(input_file),
        source_file=input_file,
        output_file=result.output_paths.get("clean", ""),
        output_dataframe=result.crm_ready_rows,
        original_rows=result.original_rows,
        crm_ready_rows=len(result.crm_ready_rows),
        rejected_rows=len(result.rejected_rows),
        duplicate_rows=len(result.duplicate_rows),
        project_name=config.get("project", {}).get("name", "Business Automation Agent"),
        project_version=str(config.get("project", {}).get("version", "")),
        note=note,
    )


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    logger = setup_logger()

    if args.list_system_backups:
        backup_manager = SystemBackupManager(config, PROJECT_ROOT)
        backups = backup_manager.list_backups()
        if not backups:
            print("No system backups found yet.")
        else:
            for backup in backups:
                print(
                    f"{backup.get('backup_id')} | {backup.get('created_at_utc')} | "
                    f"files={backup.get('included_file_count')} | size={backup.get('backup_size_bytes')} bytes | "
                    f"created_by={backup.get('created_by')}"
                )
        print(f"Backup index: {backup_manager.index_file}")
        return

    if args.create_system_backup:
        backup_manager = SystemBackupManager(config, PROJECT_ROOT)
        backup = backup_manager.create_backup(created_by=args.approved_by, note=args.backup_note)
        print("System backup created.")
        print(f"Backup ID: {backup.backup_id}")
        print(f"Backup file: {backup.backup_file}")
        print(f"Manifest file: {backup.manifest_file}")
        print(f"Included files: {backup.included_files}")
        print(f"Size bytes: {backup.total_size_bytes}")
        return

    if args.restore_system_backup:
        backup_manager = SystemBackupManager(config, PROJECT_ROOT)
        event = backup_manager.restore_backup(
            args.restore_system_backup,
            restored_by=args.approved_by,
            reason=args.backup_note or "CLI system restore requested",
            dry_run=not args.restore_apply,
        )
        print(
            "System restore preview finished."
            if event.get("dry_run")
            else "System restore applied."
        )
        print(yaml.safe_dump(event, sort_keys=False))
        print(f"Restore events: {backup_manager.restore_events_file}")
        return

    if args.list_runs:
        version_manager = FileVersionManager(config)
        runs_df = version_manager.list_runs(limit=50)
        if runs_df.empty:
            print("No versioned runs found yet.")
        else:
            print(runs_df.to_string(index=False))
        print(f"Version index: {version_manager.manifest_index_file}")
        return

    if args.rollback_run:
        version_manager = FileVersionManager(config)
        event = version_manager.rollback_run(
            args.rollback_run,
            actor=args.approved_by,
            reason=args.rollback_reason or "CLI rollback requested",
        )
        print("Rollback finished.")
        print(yaml.safe_dump(event, sort_keys=False))
        print(f"Rollback log: {version_manager.restore_log_file}")
        return

    if args.send_test_notification:
        notification = EmailNotifier(config).send_test_email()
        print(f"Notification success: {notification.success}")
        print(f"Dry-run mode: {notification.dry_run}")
        print(f"Message: {notification.message}")
        if notification.error:
            print(f"Error: {notification.error}")
        print(f"Preview file: {notification.preview_file}")
        print(f"Events file: {notification.event_file}")
        return

    if args.run_scheduled_jobs or args.run_job_now:
        scheduler = ScheduledJobManager(config)
        max_files = int(config.get("scheduler", {}).get("max_files_per_run", 25))
        if args.run_job_now:
            summary = scheduler.run_job_now(args.run_job_now, max_files=max_files)
            print("Scheduled job finished:")
            print(yaml.safe_dump(summary, sort_keys=False))
        else:
            summaries = scheduler.run_due_jobs(max_files_per_job=max_files)
            print(f"Scheduled jobs executed: {len(summaries)}")
            print(yaml.safe_dump(summaries, sort_keys=False))
        print(f"Scheduled jobs file: {scheduler.jobs_file}")
        print(f"Scheduled job events: {scheduler.events_file}")
        return

    input_file = args.input or config.get("input", {}).get("default_file")
    if not input_file:
        raise ValueError(
            "No input file provided. Use --input or set input.default_file in config.yaml"
        )

    try:
        logger.info("Starting Business Automation Agent V24")
        logger.info("Reading input file: %s", input_file)

        result = process_file(input_file, config, save_outputs=True)

        logger.info("Loaded %s rows", result.original_rows)
        logger.info("CRM-ready rows: %s", len(result.crm_ready_rows))
        logger.info("Rejected rows: %s", len(result.rejected_rows))
        logger.info("Duplicates removed: %s", len(result.duplicate_rows))

        print("\nProcessing finished successfully.")
        print(f"CRM-ready output: {result.output_paths['clean']}")
        print(f"Rejected rows: {result.output_paths['rejected']}")
        print(f"Duplicates removed: {result.output_paths['duplicates']}")
        print(f"Report: {result.output_paths['report']}")
        if result.versioned_run:
            print(f"Versioned run ID: {result.versioned_run.run_id}")
            print(f"Versioned run folder: {result.versioned_run.run_folder}")
            print(f"Latest manifest: {result.versioned_run.manifest_path}")

        integrations = config.get("integrations", {})
        qb_config = integrations.get("quickbooks", {})
        approval_required = config.get("approval", {}).get("require_human_approval", True)
        output_folder = config.get("output", {}).get("folder", "data/output")

        role_guard = RoleBasedApproval(config, output_folder)
        approval_history = ApprovalHistory(output_folder)
        approval_scope = (
            "quickbooks_sandbox_sync" if args.quickbooks_sync else "external_sync_export_review"
        )
        decision = role_guard.evaluate(
            approved_by=args.approved_by,
            role=args.approver_role,
            scope=approval_scope,
            system="quickbooks" if args.quickbooks_sync else "general",
            environment=qb_config.get("environment", "sandbox"),
            dry_run=qb_config.get("dry_run", True),
        )
        print(f"Role permission check: {decision.message}")
        print(f"Permission matrix: {role_guard.matrix_file}")

        approved = True
        if approval_required and not args.skip_approval:
            approved = HumanApproval().request(
                "Review the output files first. Do you approve continuing to external sync placeholders?"
            )

        if not approved:
            approval_record = record_approval(
                approval_history,
                approved_by=args.approved_by,
                approver_role=decision.role,
                permission_result=(
                    "not_checked_user_rejected" if decision.allowed else "denied_by_role"
                ),
                approval_status="rejected",
                approval_scope=approval_scope,
                input_file=input_file,
                result=result,
                config=config,
                note=args.approval_note or "Approval was not granted. External sync stopped.",
            )
            logger.info(
                "Human approval was not granted. Approval record: %s", approval_record.approval_id
            )
            print("External sync stopped. Your clean files were still created.")
            print(f"Approval history: {approval_history.csv_path}")
            return

        if not decision.allowed:
            approval_record = record_approval(
                approval_history,
                approved_by=args.approved_by,
                approver_role=decision.role,
                permission_result="denied_by_role",
                approval_status="blocked_by_role",
                approval_scope=approval_scope,
                input_file=input_file,
                result=result,
                config=config,
                note=args.approval_note or decision.message,
            )
            print(
                "External sync stopped because the selected role does not have permission for this scope."
            )
            print(f"Approval record: {approval_record.approval_id}")
            print(f"Approval history: {approval_history.csv_path}")
            return

        approval_record = record_approval(
            approval_history,
            approved_by=args.approved_by,
            approver_role=decision.role,
            permission_result="allowed_by_role",
            approval_status="approved" if not args.skip_approval else "approved_skip_prompt",
            approval_scope=approval_scope,
            input_file=input_file,
            result=result,
            config=config,
            note=args.approval_note,
        )
        print(f"Approval recorded: {approval_record.approval_id}")
        print(f"Approval history: {approval_history.csv_path}")

        if integrations.get("crm_enabled", False):
            sync_result = CRMConnector(config).sync_contacts(result.crm_ready_rows)
            print(f"HubSpot operation: {sync_result.operation}")
            print(f"Dry-run mode: {sync_result.dry_run}")
            print(f"Rows prepared: {sync_result.attempted_rows}")
            print(f"Batches: {sync_result.batches}")
            if sync_result.sync_plan:
                summary = sync_result.sync_plan.get("summary", {})
                print("HubSpot sync plan:")
                print(f"  Lookup performed: {summary.get('lookup_performed')}")
                print(f"  Existing contacts found: {summary.get('existing_contacts_found')}")
                print(f"  Contacts to create: {summary.get('contacts_to_create')}")
                print(f"  Contacts to update: {summary.get('contacts_to_update')}")
                print(
                    f"  Unknown status / upsert candidates: {summary.get('contacts_with_unknown_status')}"
                )
            for message in sync_result.messages:
                print(message)
            print("Audit log CSV: data/output/automation_audit_log.csv")
            print("Audit log JSONL: data/output/automation_audit_log.jsonl")
            if not sync_result.success:
                raise RuntimeError("HubSpot sync failed. Check messages above and logs.")
        else:
            print("CRM integration is disabled in config.yaml.")

        if integrations.get("quickbooks_enabled", False):
            qb_connector = QuickBooksConnector(config)
            if args.quickbooks_sync:
                qb_sync_result = qb_connector.sync_customers(result.crm_ready_rows)
                print(f"QuickBooks protected sync success: {qb_sync_result.success}")
                print(f"QuickBooks dry-run: {qb_sync_result.dry_run}")
                print(f"Attempted customers: {qb_sync_result.attempted_customers}")
                print(f"Attempted invoices: {qb_sync_result.attempted_invoices}")
                print(f"Created customers: {qb_sync_result.created_customers}")
                print(f"Created invoices: {qb_sync_result.created_invoices}")
                for name, path in qb_sync_result.output_paths.items():
                    print(f"{name}: {path}")
                for message in qb_sync_result.messages:
                    print(message)
                if qb_sync_result.errors:
                    print("QuickBooks sync errors:")
                    for error in qb_sync_result.errors:
                        print(f"  - {error}")
            else:
                qb_result = qb_connector.prepare_exports(result.crm_ready_rows)
                print(f"QuickBooks mode: {qb_connector.mode}")
                print(f"QuickBooks environment: {qb_connector.environment}")
                print(f"QuickBooks dry-run: {qb_connector.dry_run}")
                print(f"QuickBooks customer rows: {qb_result.customers_rows}")
                print(f"QuickBooks invoice rows: {qb_result.invoices_rows}")
                for name, path in qb_result.output_paths.items():
                    print(f"{name}: {path}")
                if qb_result.api_plan:
                    summary = qb_result.api_plan.get("summary", {})
                    print("QuickBooks API sync plan:")
                    print(
                        f"  Customer payloads prepared: {summary.get('customer_payloads_prepared')}"
                    )
                    print(
                        f"  Invoice payloads prepared: {summary.get('invoice_payloads_prepared')}"
                    )
                    print(
                        f"  Access token configured: {qb_result.api_plan.get('oauth', {}).get('access_token_configured')}"
                    )
                    print(
                        f"  Realm ID configured: {qb_result.api_plan.get('oauth', {}).get('realm_id_configured')}"
                    )
                    if qb_result.api_plan.get("blocking_reasons"):
                        print("  Blocking reasons:")
                        for reason in qb_result.api_plan.get("blocking_reasons", []):
                            print(f"    - {reason}")
                for message in qb_result.messages:
                    print(message)
        else:
            print("QuickBooks integration is disabled in config.yaml.")

    except Exception as error:
        logger.exception("Agent failed: %s", error)
        print(f"\nError: {error}")
        raise


if __name__ == "__main__":
    main()

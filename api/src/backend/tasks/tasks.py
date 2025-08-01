from datetime import datetime, timedelta, timezone
from pathlib import Path
from shutil import rmtree

from celery import chain, group, shared_task
from celery.utils.log import get_task_logger
from config.celery import RLSTask
from config.django.base import DJANGO_FINDINGS_BATCH_SIZE, DJANGO_TMP_OUTPUT_DIRECTORY
from django_celery_beat.models import PeriodicTask
from tasks.jobs.backfill import backfill_resource_scan_summaries
from tasks.jobs.connection import (
    check_integration_connection,
    check_lighthouse_connection,
    check_provider_connection,
)
from tasks.jobs.deletion import delete_provider, delete_tenant
from tasks.jobs.export import (
    COMPLIANCE_CLASS_MAP,
    OUTPUT_FORMATS_MAPPING,
    _compress_output_files,
    _generate_output_directory,
    _upload_to_s3,
)
from tasks.jobs.integrations import upload_s3_integration
from tasks.jobs.scan import (
    aggregate_findings,
    create_compliance_requirements,
    perform_prowler_scan,
)
from tasks.utils import batched, get_next_execution_datetime

from api.compliance import get_compliance_frameworks
from api.db_utils import rls_transaction
from api.decorators import set_tenant
from api.models import Finding, Integration, Provider, Scan, ScanSummary, StateChoices
from api.utils import initialize_prowler_provider
from api.v1.serializers import ScanTaskSerializer
from prowler.lib.check.compliance_models import Compliance
from prowler.lib.outputs.compliance.generic.generic import GenericCompliance
from prowler.lib.outputs.finding import Finding as FindingOutput

logger = get_task_logger(__name__)


def _perform_scan_complete_tasks(tenant_id: str, scan_id: str, provider_id: str):
    """
    Helper function to perform tasks after a scan is completed.

    Args:
        tenant_id (str): The tenant ID under which the scan was performed.
        scan_id (str): The ID of the scan that was performed.
        provider_id (str): The primary key of the Provider instance that was scanned.
    """
    create_compliance_requirements_task.apply_async(
        kwargs={"tenant_id": tenant_id, "scan_id": scan_id}
    )
    chain(
        perform_scan_summary_task.si(tenant_id=tenant_id, scan_id=scan_id),
        generate_outputs_task.si(
            scan_id=scan_id, provider_id=provider_id, tenant_id=tenant_id
        ),
        check_integrations_task.si(
            tenant_id=tenant_id,
            provider_id=provider_id,
        ),
    ).apply_async()


@shared_task(base=RLSTask, name="provider-connection-check")
@set_tenant
def check_provider_connection_task(provider_id: str):
    """
    Task to check the connection status of a provider.

    Args:
        provider_id (str): The primary key of the Provider instance to check.

    Returns:
        dict: A dictionary containing:
            - 'connected' (bool): Indicates whether the provider is successfully connected.
            - 'error' (str or None): The error message if the connection failed, otherwise `None`.
    """
    return check_provider_connection(provider_id=provider_id)


@shared_task(base=RLSTask, name="integration-connection-check")
@set_tenant
def check_integration_connection_task(integration_id: str):
    """
    Task to check the connection status of an integration.

    Args:
        integration_id (str): The primary key of the Integration instance to check.
    """
    return check_integration_connection(integration_id=integration_id)


@shared_task(
    base=RLSTask, name="provider-deletion", queue="deletion", autoretry_for=(Exception,)
)
def delete_provider_task(provider_id: str, tenant_id: str):
    """
    Task to delete a specific Provider instance.

    It will delete in batches all the related resources first.

    Args:
        provider_id (str): The primary key of the `Provider` instance to be deleted.
        tenant_id (str): Tenant ID the provider belongs to.

    Returns:
        tuple: A tuple containing:
            - The number of instances deleted.
            - A dictionary with the count of deleted instances per model,
              including related models if cascading deletes were triggered.
    """
    return delete_provider(tenant_id=tenant_id, pk=provider_id)


@shared_task(base=RLSTask, name="scan-perform", queue="scans")
def perform_scan_task(
    tenant_id: str, scan_id: str, provider_id: str, checks_to_execute: list[str] = None
):
    """
    Task to perform a Prowler scan on a given provider.

    This task runs a Prowler scan on the provider identified by `provider_id`
    under the tenant identified by `tenant_id`. The scan will use the `scan_id`
    for tracking purposes.

    Args:
        tenant_id (str): The tenant ID under which the scan is being performed.
        scan_id (str): The ID of the scan to be performed.
        provider_id (str): The primary key of the Provider instance to scan.
        checks_to_execute (list[str], optional): A list of specific checks to perform during the scan. Defaults to None.

    Returns:
        dict: The result of the scan execution, typically including the status and results of the performed checks.
    """
    result = perform_prowler_scan(
        tenant_id=tenant_id,
        scan_id=scan_id,
        provider_id=provider_id,
        checks_to_execute=checks_to_execute,
    )

    _perform_scan_complete_tasks(tenant_id, scan_id, provider_id)

    return result


@shared_task(base=RLSTask, bind=True, name="scan-perform-scheduled", queue="scans")
def perform_scheduled_scan_task(self, tenant_id: str, provider_id: str):
    """
    Task to perform a scheduled Prowler scan on a given provider.

    This task creates and executes a Prowler scan for the provider identified by `provider_id`
    under the tenant identified by `tenant_id`. It initiates a new scan instance with the task ID
    for tracking purposes. This task is intended to be run on a schedule (e.g., daily) to
    automatically perform scans without manual intervention.

    Args:
        self: The task instance (automatically passed when bind=True).
        tenant_id (str): The tenant ID under which the scan is being performed.
        provider_id (str): The primary key of the Provider instance to scan.

    Returns:
        dict: The result of the scan execution, typically including the status and results
        of the performed checks.

    """
    task_id = self.request.id

    with rls_transaction(tenant_id):
        periodic_task_instance = PeriodicTask.objects.get(
            name=f"scan-perform-scheduled-{provider_id}"
        )

        executed_scan = Scan.objects.filter(
            tenant_id=tenant_id,
            provider_id=provider_id,
            task__task_runner_task__task_id=task_id,
        ).order_by("completed_at")

        if (
            Scan.objects.filter(
                tenant_id=tenant_id,
                provider_id=provider_id,
                trigger=Scan.TriggerChoices.SCHEDULED,
                state=StateChoices.EXECUTING,
                scheduler_task_id=periodic_task_instance.id,
                scheduled_at__date=datetime.now(timezone.utc).date(),
            ).exists()
            or executed_scan.exists()
        ):
            # Duplicated task execution due to visibility timeout or scan is already running
            logger.warning(f"Duplicated scheduled scan for provider {provider_id}.")
            try:
                affected_scan = executed_scan.first()
                if not affected_scan:
                    raise ValueError(
                        "Error retrieving affected scan details after detecting duplicated scheduled "
                        "scan."
                    )
                # Return the affected scan details to avoid losing data
                serializer = ScanTaskSerializer(instance=affected_scan)
            except Exception as duplicated_scan_exception:
                logger.error(
                    f"Duplicated scheduled scan for provider {provider_id}. Error retrieving affected scan details: "
                    f"{str(duplicated_scan_exception)}"
                )
                raise duplicated_scan_exception
            return serializer.data

        next_scan_datetime = get_next_execution_datetime(task_id, provider_id)
        scan_instance, _ = Scan.objects.get_or_create(
            tenant_id=tenant_id,
            provider_id=provider_id,
            trigger=Scan.TriggerChoices.SCHEDULED,
            state__in=(StateChoices.SCHEDULED, StateChoices.AVAILABLE),
            scheduler_task_id=periodic_task_instance.id,
            defaults={
                "state": StateChoices.SCHEDULED,
                "name": "Daily scheduled scan",
                "scheduled_at": next_scan_datetime - timedelta(days=1),
            },
        )

        scan_instance.task_id = task_id
        scan_instance.save()

    try:
        result = perform_prowler_scan(
            tenant_id=tenant_id,
            scan_id=str(scan_instance.id),
            provider_id=provider_id,
        )
    except Exception as e:
        raise e
    finally:
        with rls_transaction(tenant_id):
            Scan.objects.get_or_create(
                tenant_id=tenant_id,
                name="Daily scheduled scan",
                provider_id=provider_id,
                trigger=Scan.TriggerChoices.SCHEDULED,
                state=StateChoices.SCHEDULED,
                scheduled_at=next_scan_datetime,
                scheduler_task_id=periodic_task_instance.id,
            )

    _perform_scan_complete_tasks(tenant_id, str(scan_instance.id), provider_id)

    return result


@shared_task(name="scan-summary", queue="overview")
def perform_scan_summary_task(tenant_id: str, scan_id: str):
    return aggregate_findings(tenant_id=tenant_id, scan_id=scan_id)


@shared_task(name="tenant-deletion", queue="deletion", autoretry_for=(Exception,))
def delete_tenant_task(tenant_id: str):
    return delete_tenant(pk=tenant_id)


@shared_task(
    base=RLSTask,
    name="scan-report",
    queue="scan-reports",
)
@set_tenant(keep_tenant=True)
def generate_outputs_task(scan_id: str, provider_id: str, tenant_id: str):
    """
    Process findings in batches and generate output files in multiple formats.

    This function retrieves findings associated with a scan, processes them
    in batches of 50, and writes each batch to the corresponding output files.
    It reuses output writer instances across batches, updates them with each
    batch of transformed findings, and uses a flag to indicate when the final
    batch is being processed. Finally, the output files are compressed and
    uploaded to S3.

    Args:
        tenant_id (str): The tenant identifier.
        scan_id (str): The scan identifier.
        provider_id (str): The provider_id id to be used in generating outputs.
    """
    # Check if the scan has findings
    if not ScanSummary.objects.filter(scan_id=scan_id).exists():
        logger.info(f"No findings found for scan {scan_id}")
        return {"upload": False}

    provider_obj = Provider.objects.get(id=provider_id)
    prowler_provider = initialize_prowler_provider(provider_obj)
    provider_uid = provider_obj.uid
    provider_type = provider_obj.provider

    frameworks_bulk = Compliance.get_bulk(provider_type)
    frameworks_avail = get_compliance_frameworks(provider_type)
    out_dir, comp_dir = _generate_output_directory(
        DJANGO_TMP_OUTPUT_DIRECTORY, provider_uid, tenant_id, scan_id
    )

    def get_writer(writer_map, name, factory, is_last):
        """
        Return existing writer_map[name] or create via factory().
        In both cases set `.close_file = is_last`.
        """
        initialization = False
        if name not in writer_map:
            writer_map[name] = factory()
            initialization = True
        w = writer_map[name]
        w.close_file = is_last

        return w, initialization

    output_writers = {}
    compliance_writers = {}

    scan_summary = FindingOutput._transform_findings_stats(
        ScanSummary.objects.filter(scan_id=scan_id)
    )

    qs = Finding.all_objects.filter(scan_id=scan_id).order_by("uid").iterator()
    for batch, is_last in batched(qs, DJANGO_FINDINGS_BATCH_SIZE):
        fos = [FindingOutput.transform_api_finding(f, prowler_provider) for f in batch]

        # Outputs
        for mode, cfg in OUTPUT_FORMATS_MAPPING.items():
            cls = cfg["class"]
            suffix = cfg["suffix"]
            extra = cfg.get("kwargs", {}).copy()
            if mode == "html":
                extra.update(provider=prowler_provider, stats=scan_summary)

            writer, initialization = get_writer(
                output_writers,
                cls,
                lambda cls=cls, fos=fos, suffix=suffix: cls(
                    findings=fos,
                    file_path=out_dir,
                    file_extension=suffix,
                    from_cli=False,
                ),
                is_last,
            )
            if not initialization:
                writer.transform(fos)
            writer.batch_write_data_to_file(**extra)
            writer._data.clear()

        # Compliance CSVs
        for name in frameworks_avail:
            compliance_obj = frameworks_bulk[name]

            klass = GenericCompliance
            for condition, cls in COMPLIANCE_CLASS_MAP.get(provider_type, []):
                if condition(name):
                    klass = cls
                    break

            filename = f"{comp_dir}_{name}.csv"

            writer, initialization = get_writer(
                compliance_writers,
                name,
                lambda klass=klass, fos=fos: klass(
                    findings=fos,
                    compliance=compliance_obj,
                    file_path=filename,
                    from_cli=False,
                ),
                is_last,
            )
            if not initialization:
                writer.transform(fos, compliance_obj, name)
            writer.batch_write_data_to_file()
            writer._data.clear()

    compressed = _compress_output_files(out_dir)
    upload_uri = _upload_to_s3(tenant_id, compressed, scan_id)

    # S3 integrations (need output_directory)
    with rls_transaction(tenant_id):
        s3_integrations = Integration.objects.filter(
            integrationproviderrelationship__provider_id=provider_id,
            integration_type=Integration.IntegrationChoices.AMAZON_S3,
            enabled=True,
        )

    if s3_integrations:
        # Pass the output directory path to S3 integration task to reconstruct objects from files
        s3_integration_task.apply_async(
            kwargs={
                "tenant_id": tenant_id,
                "provider_id": provider_id,
                "output_directory": out_dir,
            }
        ).get(
            disable_sync_subtasks=False
        )  # TODO: This synchronous execution is NOT recommended
        # We're forced to do this because we need the files to exist before deletion occurs.
        # Once we have the periodic file cleanup task implemented, we should:
        # 1. Remove this .get() call and make it fully async
        # 2. For Cloud deployments, develop a secondary approach where outputs are stored
        #    directly in S3 and read from there, eliminating local file dependencies

    if upload_uri:
        # TODO: We need to create a new periodic task to delete the output files
        # This task shouldn't be responsible for deleting the output files
        try:
            rmtree(Path(compressed).parent, ignore_errors=True)
        except Exception as e:
            logger.error(f"Error deleting output files: {e}")
        final_location, did_upload = upload_uri, True
    else:
        final_location, did_upload = compressed, False

    Scan.all_objects.filter(id=scan_id).update(output_location=final_location)
    logger.info(f"Scan outputs at {final_location}")

    return {
        "upload": did_upload,
    }


@shared_task(name="backfill-scan-resource-summaries", queue="backfill")
def backfill_scan_resource_summaries_task(tenant_id: str, scan_id: str):
    """
    Tries to backfill the resource scan summaries table for a given scan.

    Args:
        tenant_id (str): The tenant identifier.
        scan_id (str): The scan identifier.
    """
    return backfill_resource_scan_summaries(tenant_id=tenant_id, scan_id=scan_id)


@shared_task(base=RLSTask, name="scan-compliance-overviews", queue="overview")
def create_compliance_requirements_task(tenant_id: str, scan_id: str):
    """
    Creates detailed compliance requirement records for a scan.

    This task processes the compliance data collected during a scan and creates
    individual records for each compliance requirement in each region. These detailed
    records provide a granular view of compliance status.

    Args:
        tenant_id (str): The tenant ID for which to create records.
        scan_id (str): The ID of the scan for which to create records.
    """
    return create_compliance_requirements(tenant_id=tenant_id, scan_id=scan_id)


@shared_task(base=RLSTask, name="lighthouse-connection-check")
@set_tenant
def check_lighthouse_connection_task(lighthouse_config_id: str, tenant_id: str = None):
    """
    Task to check the connection status of a Lighthouse configuration.

    Args:
        lighthouse_config_id (str): The primary key of the LighthouseConfiguration instance to check.
        tenant_id (str): The tenant ID for the task.

    Returns:
        dict: A dictionary containing:
            - 'connected' (bool): Indicates whether the connection is successful.
            - 'error' (str or None): The error message if the connection failed, otherwise `None`.
            - 'available_models' (list): List of available models if connection is successful.
    """
    return check_lighthouse_connection(lighthouse_config_id=lighthouse_config_id)


@shared_task(name="integration-check")
def check_integrations_task(tenant_id: str, provider_id: str):
    """
    Check and execute all configured integrations for a provider.

    Args:
        tenant_id (str): The tenant identifier
        provider_id (str): The provider identifier
    """
    logger.info(f"Checking integrations for provider {provider_id}")

    try:
        with rls_transaction(tenant_id):
            integrations = Integration.objects.filter(
                integrationproviderrelationship__provider_id=provider_id,
                enabled=True,
            )

            if not integrations.exists():
                logger.info(f"No integrations configured for provider {provider_id}")
                return {"integrations_processed": 0}

        integration_tasks = []

        # TODO: Add other integration types here
        # slack_integrations = integrations.filter(
        #     integration_type=Integration.IntegrationChoices.SLACK
        # )
        # if slack_integrations.exists():
        #     integration_tasks.append(
        #        slack_integration_task.s(
        #            tenant_id=tenant_id,
        #            provider_id=provider_id,
        #        )
        #     )

    except Exception as e:
        logger.error(f"Integration check failed for provider {provider_id}: {str(e)}")
        return {"integrations_processed": 0, "error": str(e)}

    # Execute all integration tasks in parallel if any were found
    if integration_tasks:
        job = group(integration_tasks)
        job.apply_async()
        logger.info(f"Launched {len(integration_tasks)} integration task(s)")

    return {"integrations_processed": len(integration_tasks)}


@shared_task(
    base=RLSTask,
    name="integration-s3",
    queue="integrations",
)
def s3_integration_task(
    tenant_id: str,
    provider_id: str,
    output_directory: str,
):
    """
    Process S3 integrations for a provider.

    Args:
        tenant_id (str): The tenant identifier
        provider_id (str): The provider identifier
        output_directory (str): Path to the directory containing output files
    """
    return upload_s3_integration(tenant_id, provider_id, output_directory)

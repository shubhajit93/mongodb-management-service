"""Map domain Job to API schema."""

from app.domain.models import Job
from app.schemas import JobResponse


def job_to_response(job: Job) -> JobResponse:
    return JobResponse(
        id=job.id,
        jobType=job.job_type,
        status=job.status,
        createdAt=job.created_at,
        updatedAt=job.updated_at,
        startedAt=job.started_at,
        finishedAt=job.finished_at,
        stamp=job.stamp,
        exitCode=job.exit_code,
        request=job.request,
        command=job.command,
        logTail=job.log_tail,
        errorMessage=job.error_message,
    )
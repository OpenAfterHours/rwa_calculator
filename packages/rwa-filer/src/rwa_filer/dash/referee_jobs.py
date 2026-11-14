"""
Referee runs in the background — Arelle's verdict on an instance, set beside ours.

Pipeline position:
    referee_pages  ->  JobBoard.start  ->  thread: referee.run_referee
        ->  native validation of the same file  ->  referee.differential.compare
        ->  RefereeJob (polled by the page)

Key responsibilities:
- Run the referee off the request thread: a large module takes minutes and
  several GB, and the page must answer while it runs.
- Do what ``rwa-filer referee`` does, in the same order: Arelle on the file,
  then this package's own engine on the SAME file read back, then the two
  compared rule by rule.
- Say whether Arelle can run at all before a run is started, in the words the
  referee itself uses when it cannot.

References:
- rwa_filer.referee — the runner, the differential and the report
- rwa_filer.cli — ``rwa-filer referee``, which this mirrors
"""

from __future__ import annotations

import json
import logging
import secrets
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

from rwa_filer.readers import load_source
from rwa_filer.referee import (
    RefereePlanError,
    RefereeUnavailableError,
    compare,
    find_arelle_python,
    run_referee,
)
from rwa_filer.taxonomy.pack import PackNotFoundError
from rwa_filer.validate.returns import validate_return

if TYPE_CHECKING:
    from pathlib import Path

    from rwa_filer.referee import Differential, RefereeResult

logger = logging.getLogger(__name__)

STATUS_RUNNING: Final = "running"
STATUS_DONE: Final = "done"
STATUS_FAILED: Final = "failed"
#: The progress file ``run_referee`` rewrites after every worker.
PROGRESS_FILE: Final = "progress.json"


@dataclass
class RefereeJob:
    """One referee run: what it was asked, how far it has got, what it found.

    Mutable on purpose: the worker thread fills it in while pages read it,
    under the board's lock.
    """

    job_id: str
    return_id: str
    instance: Path
    package: Path
    workdir: Path
    started_at: datetime
    status: str = STATUS_RUNNING
    finished_at: datetime | None = None
    result: RefereeResult | None = None
    differential: Differential | None = None
    error: str | None = None
    rules: str | None = None

    def progress(self) -> tuple[int, int] | None:
        """Workers finished and planned, from the runner's progress file, if written yet."""
        path = self.workdir / PROGRESS_FILE
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            return len(record["chunks"]), int(record["chunks_planned"])
        except (OSError, ValueError, KeyError, TypeError):
            return None


class JobBoard:
    """The referee runs of one dashboard session."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._jobs: dict[str, RefereeJob] = {}
        self._lock = threading.Lock()
        #: The last taxonomy package and interpreter given, to offer again.
        self.last_package: str = ""
        self.last_python: str = ""

    def start(  # noqa: PLR0913 - each argument is a separate choice about the run
        self,
        return_id: str,
        instance: Path,
        package: Path,
        *,
        python: Path | None = None,
        rules: str | None = None,
    ) -> RefereeJob:
        """Start a referee run in the background and return its job.

        Raises:
            RefereeUnavailableError: no interpreter with Arelle can be found.
            ValueError: the instance or the package is not a file, or the
                instance is not an ``.xbrl``.
        """
        if not instance.is_file() or instance.suffix.lower() != ".xbrl":
            raise ValueError(f"the referee reads an .xbrl instance; {instance} is not one")
        if not package.is_file():
            raise ValueError(f"taxonomy package not found: {package}")
        interpreter = find_arelle_python(python)
        job_id = secrets.token_hex(4)
        job = RefereeJob(
            job_id=job_id,
            return_id=return_id,
            instance=instance,
            package=package,
            workdir=self.directory / "referee" / job_id,
            started_at=datetime.now(UTC),
            rules=rules,
        )
        job.workdir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._jobs[job_id] = job
            self.last_package = str(package)
            self.last_python = str(python) if python else ""
        thread = threading.Thread(
            target=self._run, args=(job, interpreter), name=f"referee-{job_id}", daemon=True
        )
        thread.start()
        return job

    def get(self, job_id: str) -> RefereeJob | None:
        """The job with this id, if there is one."""
        with self._lock:
            return self._jobs.get(job_id)

    def for_return(self, return_id: str) -> list[RefereeJob]:
        """The runs started for a return, the most recent first."""
        with self._lock:
            jobs = [job for job in self._jobs.values() if job.return_id == return_id]
        return sorted(jobs, key=lambda job: job.started_at, reverse=True)

    def _run(self, job: RefereeJob, interpreter: Path) -> None:
        try:
            result = run_referee(
                job.instance,
                job.package,
                python=interpreter,
                workdir=job.workdir,
                rules=job.rules,
            )
            source = load_source(job.instance)
            validation = validate_return(source.ret, source.pack, source_findings=source.findings)
            differential = compare(validation.report.results, result) if validation.report else None
        except (RefereeUnavailableError, RefereePlanError, ValueError, PackNotFoundError) as exc:
            self._finish(job, error=str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - a background run must report, not vanish
            logger.exception("referee run %s failed", job.job_id)
            self._finish(job, error=f"the run stopped unexpectedly: {exc}")
            return
        self._finish(job, result=result, differential=differential)

    def _finish(
        self,
        job: RefereeJob,
        *,
        result: RefereeResult | None = None,
        differential: Differential | None = None,
        error: str | None = None,
    ) -> None:
        with self._lock:
            job.result = result
            job.differential = differential
            job.error = error
            job.status = STATUS_FAILED if error else STATUS_DONE
            job.finished_at = datetime.now(UTC)
        logger.info("referee run %s %s", job.job_id, job.status)


def arelle_status(python: Path | None = None) -> tuple[bool, str]:
    """Whether Arelle can be run, and the interpreter or the reason it cannot."""
    try:
        return True, str(find_arelle_python(python))
    except RefereeUnavailableError as exc:
        return False, str(exc)

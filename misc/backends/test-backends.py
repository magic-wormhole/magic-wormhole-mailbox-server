#!/usr/bin/env python3
"""Run the unit and behavioral suites against SQLite, MySQL, PostgreSQL,
Redis, and Kafka.

SQLite runs locally. MySQL, PostgreSQL, Redis, and Kafka each have their own
``docker compose`` configuration in this directory; the wrapper starts them
and creates a fresh set of channel/usage/address-id databases in each.

The three unit suites run in parallel first and report their status. Once
they finish, the behavioral suites run in parallel and report theirs.

Usage:
    .venv/bin/python misc/backends/test-backends.py

Options:
    --no-sqlite   Skip the local SQLite unit and behavioral runs.
    --unit-jobs N Parallel trial workers for each unit suite
                  (default: auto; 1 disables parallelism).
    --job NAME    Run only the named suite; repeat for several suites.
                  Default: all. Choices: sqlite-unit, postgres-unit,
                  mysql-unit, sqlite-behavior, postgres-behavior,
                  mysql-behavior, redis-behavior, kafka-behavior,
                  postgres-redis-behavior, postgres-kafka-behavior,
                  mysql-redis-behavior, mysql-kafka-behavior.
    --keep        Leave the docker compose projects running for debugging.
    --keep-temp   Keep the temporary SQLite databases and per-job logs.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKENDS_DIR = Path(__file__).resolve().parent
POSTGRES_COMPOSE = BACKENDS_DIR / "docker-compose.postgres.yml"
MYSQL_COMPOSE = BACKENDS_DIR / "docker-compose.mysql.yml"
REDIS_COMPOSE = BACKENDS_DIR / "docker-compose.redis.yml"
KAFKA_COMPOSE = BACKENDS_DIR / "docker-compose.kafka.yml"

BEHAVIOR_MODULE = "wormhole_mailbox_server.test.test_backends"

UNIT_JOBS = ("sqlite-unit", "postgres-unit", "mysql-unit")
BEHAVIOR_JOBS = ("sqlite-behavior", "postgres-behavior", "mysql-behavior",
                 "redis-behavior", "kafka-behavior",
                 "postgres-redis-behavior", "postgres-kafka-behavior",
                 "mysql-redis-behavior", "mysql-kafka-behavior")
ALL_JOBS = UNIT_JOBS + BEHAVIOR_JOBS

# Each behavioral job is a (database backend, pub/sub transport) pair.  The
# plain ``<database>-behavior`` jobs use the backend's default transport:
# PostgreSQL LISTEN/NOTIFY, or the single-process local transport for SQLite
# and MySQL.  ``redis-behavior`` and ``kafka-behavior`` are the historical
# names for the SQLite + Redis/Kafka combinations.
BEHAVIOR_SPECS = {
    "sqlite-behavior": ("sqlite", None),
    "postgres-behavior": ("postgres", None),
    "mysql-behavior": ("mysql", None),
    "redis-behavior": ("sqlite", "redis"),
    "kafka-behavior": ("sqlite", "kafka"),
    "postgres-redis-behavior": ("postgres", "redis"),
    "postgres-kafka-behavior": ("postgres", "kafka"),
    "mysql-redis-behavior": ("mysql", "redis"),
    "mysql-kafka-behavior": ("mysql", "kafka"),
}


def log(message):
    print(message, flush=True)


def find_compose():
    docker = shutil.which("docker")
    if docker:
        result = subprocess.run([docker, "compose", "version"],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        if result.returncode == 0:
            return [docker, "compose"]
    compose = shutil.which("docker-compose")
    if compose:
        return [compose]
    raise RuntimeError("docker compose (v2) or docker-compose is required")


COMPOSE = find_compose()


def compose_cmd(compose_file, project, *args):
    return COMPOSE + ["-f", str(compose_file), "-p", project] + list(args)


def run_compose(compose_file, project, *args, check=True, quiet=False):
    command = compose_cmd(compose_file, project, *args)
    if quiet:
        result = subprocess.run(command, cwd=ROOT, capture_output=True,
                                text=True)
        if check and result.returncode != 0:
            sys.stderr.write(result.stdout or "")
            sys.stderr.write(result.stderr or "")
            raise subprocess.CalledProcessError(result.returncode, command)
        return result
    return subprocess.run(command, cwd=ROOT, check=check)


def exec_in(compose_file, project, service, *command, check=True):
    return run_compose(compose_file, project, "exec", "-T", service,
                       *command, check=check)


def wait_for(compose_file, project, service, command, timeout=120):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = exec_in(compose_file, project, service, *command, check=False)
        if result.returncode == 0:
            return
        time.sleep(1)
    raise RuntimeError(f"{service} did not become ready in {timeout}s")


def start_database(compose_file, project, service, ready_command, timeout=120):
    log(f"starting {service} ({project})")
    run_compose(compose_file, project, "up", "-d", quiet=True)
    wait_for(compose_file, project, service, ready_command, timeout=timeout)


def create_postgres_databases(project, names):
    for name in names:
        exec_in(POSTGRES_COMPOSE, project, "postgres",
                "createdb", "-U", "wormhole", name)


def create_mysql_databases(project, names):
    for name in names:
        exec_in(MYSQL_COMPOSE, project, "mysql",
                "mysql", "-uroot", "-pwormhole", "-e",
                f"CREATE DATABASE `{name}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")


def backend_env(prefix, databases, port, user, password):
    base = f"{prefix}://{user}:{password}@127.0.0.1:{port}"
    env = {
        "WORMHOLE_TEST_CHANNEL_DATABASE_URL":
            f"{base}/{databases['channel']}",
        "WORMHOLE_TEST_USAGE_DATABASE_URL":
            f"{base}/{databases['usage']}",
        "WORMHOLE_TEST_ADDRID_DATABASE_URL":
            f"{base}/{databases['addrid']}",
    }
    env["WORMHOLE_TEST_DATABASE_URL"] = env[
        "WORMHOLE_TEST_CHANNEL_DATABASE_URL"]
    return env


def sqlite_env(directory):
    def url(name):
        return "sqlite:///" + os.path.join(directory, name + ".db")

    return {
        "WORMHOLE_TEST_CHANNEL_DATABASE_URL": url("channel"),
        "WORMHOLE_TEST_USAGE_DATABASE_URL": url("usage"),
        "WORMHOLE_TEST_ADDRID_DATABASE_URL": url("addrid"),
        "WORMHOLE_TEST_DATABASE_URL": url("channel"),
    }


class Job:
    def __init__(self, name, command, env):
        self.name = name
        self.command = command
        self.env = env
        self.returncode = None
        self.elapsed = None

    def run(self):
        log(f"[{self.name}] starting: {' '.join(self.command)}")
        full_env = dict(os.environ)
        full_env.update(self.env)
        started = time.monotonic()
        process = subprocess.Popen(
            self.command, cwd=ROOT, env=full_env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
        for line in process.stdout:
            print(f"[{self.name}] {line.rstrip()}", flush=True)
        self.returncode = process.wait()
        self.elapsed = time.monotonic() - started
        log(f"[{self.name}] exited with {self.returncode} "
            f"after {self.elapsed:.1f}s")

    def succeeded(self):
        return self.returncode == 0


def run_jobs(jobs):
    threads = [threading.Thread(target=job.run) for job in jobs]
    for thread in threads:
        thread.start()
    try:
        for thread in threads:
            thread.join()
    except KeyboardInterrupt:
        log("interrupted; waiting for jobs to exit")
        for thread in threads:
            thread.join(timeout=10)
        raise
    return [job for job in jobs if not job.succeeded()]


def report_jobs(phase, jobs):
    log(f"=== {phase} suite status ===")
    for job in jobs:
        elapsed = "" if job.elapsed is None else f" ({job.elapsed:.1f}s)"
        if job.succeeded():
            log(f"  {job.name}: PASSED{elapsed}")
        else:
            log(f"  {job.name}: FAILED (exit {job.returncode}){elapsed}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-sqlite", action="store_true",
                        help="skip local SQLite runs")
    parser.add_argument("--unit-jobs", default="auto",
                        help="parallel trial workers for the SQLite unit "
                             "suite (default: auto; use 1 to disable)")
    parser.add_argument("--job", action="append", choices=ALL_JOBS,
                        help="run only this suite; repeat to select several "
                             "(default: all)")
    parser.add_argument("--keep", action="store_true",
                        help="leave docker compose projects running")
    parser.add_argument("--keep-temp", action="store_true",
                        help="keep temporary SQLite databases")
    args = parser.parse_args()

    if args.unit_jobs == "auto":
        trial_workers = max(1, min(os.cpu_count() or 1, 8))
    else:
        trial_workers = int(args.unit_jobs)
        if trial_workers < 1:
            parser.error("--unit-jobs must be a positive integer")

    selected = set(args.job or ALL_JOBS)
    if args.no_sqlite:
        if args.job and any(name.startswith("sqlite-") for name in selected):
            parser.error("--no-sqlite conflicts with an explicit sqlite "
                         "--job")
        selected = {name for name in selected
                    if not name.startswith("sqlite-")}

    selected_behavior = [name for name in BEHAVIOR_JOBS if name in selected]
    need_postgres = "postgres-unit" in selected or any(
        BEHAVIOR_SPECS[name][0] == "postgres" for name in selected_behavior)
    need_mysql = "mysql-unit" in selected or any(
        BEHAVIOR_SPECS[name][0] == "mysql" for name in selected_behavior)
    need_redis = any(BEHAVIOR_SPECS[name][1] == "redis"
                     for name in selected_behavior)
    need_kafka = any(BEHAVIOR_SPECS[name][1] == "kafka"
                     for name in selected_behavior)

    python = sys.executable
    run_id = uuid.uuid4().hex[:8]
    temp_dir = tempfile.mkdtemp(prefix=f"wormhole-backends-{run_id}-")

    def trial_command(job_name, module, jobs=None):
        command = [python, "-m", "twisted.trial",
                   "--temp-directory",
                   os.path.join(temp_dir, "trial-" + job_name)]
        if jobs:
            command += ["-j", str(jobs)]
        return command + [module]
    projects = {
        "postgres": f"wormhole-postgres-{run_id}",
        "mysql": f"wormhole-mysql-{run_id}",
        "redis": f"wormhole-redis-{run_id}",
        "kafka": f"wormhole-kafka-{run_id}",
    }
    compose_files = {
        "postgres": POSTGRES_COMPOSE,
        "mysql": MYSQL_COMPOSE,
        "redis": REDIS_COMPOSE,
        "kafka": KAFKA_COMPOSE,
    }
    database_kinds = ("channel", "usage", "addrid")
    # Every behavioral job gets its own databases so the parallel jobs cannot
    # observe each other's messages or migrations.  ``wormhole`` is reserved
    # for the unit suites.
    behavior_databases = {
        name: {
            kind: f"wormhole_{run_id}_{name.replace('-', '_')}_{kind}"
            for kind in database_kinds
        }
        for name in selected_behavior
    }
    postgres_databases = [
        behavior_databases[name][kind]
        for name in selected_behavior
        if BEHAVIOR_SPECS[name][0] == "postgres"
        for kind in database_kinds
    ]
    mysql_databases = [
        behavior_databases[name][kind]
        for name in selected_behavior
        if BEHAVIOR_SPECS[name][0] == "mysql"
        for kind in database_kinds
    ]
    postgres_port = os.environ.get("WORMHOLE_POSTGRES_PORT", "55432")
    mysql_port = os.environ.get("WORMHOLE_MYSQL_PORT", "53306")
    redis_port = os.environ.get("WORMHOLE_REDIS_PORT", "56379")
    kafka_port = os.environ.get("WORMHOLE_KAFKA_PORT", "59092")

    def pubsub_url(transport):
        if transport == "redis":
            return f"redis://127.0.0.1:{redis_port}/0"
        if transport == "kafka":
            return f"kafka://127.0.0.1:{kafka_port}"
        return None

    unit_suites = []
    behavior_suites = []
    failures = []
    started_projects = []
    run_started = time.monotonic()
    try:
        if "sqlite-unit" in selected:
            unit_suites.append(Job(
                "sqlite-unit",
                trial_command("sqlite-unit", "wormhole_mailbox_server",
                              jobs=trial_workers),
                {},
            ))

        log("starting database containers")
        if need_postgres:
            started_projects.append(("postgres", projects["postgres"]))
            start_database(POSTGRES_COMPOSE, projects["postgres"], "postgres",
                           ["pg_isready", "-U", "wormhole", "-d", "wormhole"])
        if need_mysql:
            started_projects.append(("mysql", projects["mysql"]))
            start_database(MYSQL_COMPOSE, projects["mysql"], "mysql",
                           ["mysqladmin", "ping", "-h", "127.0.0.1",
                            "-uroot", "-pwormhole", "--silent"])
        if need_redis:
            started_projects.append(("redis", projects["redis"]))
            start_database(REDIS_COMPOSE, projects["redis"], "redis",
                           ["redis-cli", "ping"])
        if need_kafka:
            started_projects.append(("kafka", projects["kafka"]))
            start_database(KAFKA_COMPOSE, projects["kafka"], "kafka",
                           ["/opt/kafka/bin/kafka-broker-api-versions.sh",
                            "--bootstrap-server", "localhost:9092"],
                           timeout=180)

        if postgres_databases or mysql_databases:
            log(f"creating {len(postgres_databases) + len(mysql_databases)} "
                "test databases")
        if postgres_databases:
            create_postgres_databases(projects["postgres"],
                                      postgres_databases)
        if mysql_databases:
            create_mysql_databases(projects["mysql"], mysql_databases)

        if "postgres-unit" in selected:
            unit_suites.append(Job(
                "postgres-unit",
                trial_command("postgres-unit", "wormhole_mailbox_server",
                              jobs=trial_workers),
                {"WORMHOLE_TEST_UNIT_BACKEND_URL":
                    f"postgresql+psycopg://wormhole:wormhole@127.0.0.1:"
                    f"{postgres_port}/wormhole"},
            ))
        if "mysql-unit" in selected:
            unit_suites.append(Job(
                "mysql-unit",
                trial_command("mysql-unit", "wormhole_mailbox_server",
                              jobs=trial_workers),
                {"WORMHOLE_TEST_UNIT_BACKEND_URL":
                    f"mysql+pymysql://root:wormhole@127.0.0.1:"
                    f"{mysql_port}/wormhole"},
            ))

        for name in selected_behavior:
            database, transport = BEHAVIOR_SPECS[name]
            if database == "sqlite":
                directory = os.path.join(temp_dir, name)
                os.makedirs(directory, exist_ok=True)
                env = sqlite_env(directory)
            elif database == "postgres":
                env = backend_env("postgresql+psycopg",
                                  behavior_databases[name], postgres_port,
                                  "wormhole", "wormhole")
            else:
                env = backend_env("mysql+pymysql", behavior_databases[name],
                                  mysql_port, "root", "wormhole")
            if transport is not None:
                env["WORMHOLE_TEST_PUBSUB_URL"] = pubsub_url(transport)
            behavior_suites.append(Job(
                name,
                trial_command(name, BEHAVIOR_MODULE),
                env,
            ))

        if unit_suites:
            log(f"running {len(unit_suites)} unit suites in parallel")
            failures.extend(run_jobs(unit_suites))
            report_jobs("unit", unit_suites)

        if behavior_suites:
            log(f"running {len(behavior_suites)} behavior suites in parallel")
            failures.extend(run_jobs(behavior_suites))
            report_jobs("behavior", behavior_suites)
    finally:
        if not args.keep:
            for name, project in started_projects:
                log(f"stopping {name} ({project})")
                run_compose(compose_files[name], project, "down", "-v",
                            "--remove-orphans", check=False, quiet=True)
        if not args.keep_temp:
            shutil.rmtree(temp_dir, ignore_errors=True)

    if failures:
        log("FAILED jobs:")
        for job in failures:
            log(f"  {job.name} (exit {job.returncode})")
        return 1

    log(f"selected backend suites passed in "
        f"{time.monotonic() - run_started:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())

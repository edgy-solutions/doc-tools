import logging
import os
import time

from neo4j import GraphDatabase
from neo4j.exceptions import ClientError

log = logging.getLogger(__name__)


# Neo4j's auth rate-limiter trips after a small number of bad-credential
# attempts (default 3) and locks the offending user for a cool-down
# (default 5s). When many Dagster runs spin up in parallel, transient
# bring-up timing — or a single misconfigured client elsewhere in the
# cluster — can leave the `neo4j` user briefly rate-limited, and any
# fresh driver opening a connection during that window dies with
#   Neo.ClientError.Security.AuthenticationRateLimit
# even though its credentials are correct. The lockout is self-clearing,
# so we sleep past it instead of failing the whole job.
_AUTH_RATE_LIMIT_CODE = "Neo.ClientError.Security.AuthenticationRateLimit"
_RATE_LIMIT_RETRIES = 3
_RATE_LIMIT_BACKOFF_SECONDS = (6.0, 12.0, 20.0)  # > Neo4j's 5s default cooldown


class Neo4jClient:
    def __init__(self, uri=None, user=None, password=None):
        self.uri = uri or os.getenv("NEO4J_URI", "bolt://localhost:7687")
        self.user = user or os.getenv("NEO4J_USER", "neo4j")
        self.password = password or os.getenv("NEO4J_PASSWORD", "password")

        self.driver = self._open_driver_with_rate_limit_backoff()

    def _open_driver_with_rate_limit_backoff(self):
        last_err = None
        for attempt in range(_RATE_LIMIT_RETRIES + 1):
            try:
                driver = GraphDatabase.driver(
                    self.uri, auth=(self.user, self.password)
                )
                driver.verify_connectivity()
                return driver
            except ClientError as e:
                if getattr(e, "code", None) != _AUTH_RATE_LIMIT_CODE:
                    raise
                last_err = e
                if attempt >= _RATE_LIMIT_RETRIES:
                    break
                wait = _RATE_LIMIT_BACKOFF_SECONDS[attempt]
                log.warning(
                    "Neo4j auth rate-limited on connect (attempt %d/%d); "
                    "sleeping %.1fs before retry. This usually clears in "
                    "Neo4j's default 5s cool-down, but another client may "
                    "be holding the user locked with bad credentials.",
                    attempt + 1,
                    _RATE_LIMIT_RETRIES + 1,
                    wait,
                )
                time.sleep(wait)
        raise last_err

    def close(self):
        self.driver.close()

    def execute_query(self, query, parameters=None, db=None):
        last_err = None
        for attempt in range(_RATE_LIMIT_RETRIES + 1):
            try:
                with self.driver.session(database=db) as session:
                    result = session.run(query, parameters)
                    return [record.data() for record in result]
            except ClientError as e:
                if getattr(e, "code", None) != _AUTH_RATE_LIMIT_CODE:
                    raise
                last_err = e
                if attempt >= _RATE_LIMIT_RETRIES:
                    break
                wait = _RATE_LIMIT_BACKOFF_SECONDS[attempt]
                log.warning(
                    "Neo4j auth rate-limited on query (attempt %d/%d); "
                    "sleeping %.1fs before retry.",
                    attempt + 1,
                    _RATE_LIMIT_RETRIES + 1,
                    wait,
                )
                time.sleep(wait)
        raise last_err

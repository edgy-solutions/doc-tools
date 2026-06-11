import os
import httpx
from SPARQLWrapper import SPARQLWrapper, POST, BASIC, JSON


def escape_sparql_string(s: str) -> str:
    """Escape a Python string for safe embedding in a SPARQL double-quoted
    string literal (``"..."``).

    SPARQL grammar (W3C SPARQL 1.1, section 19.7 "Strings") disallows the
    following inside ``"..."``: raw newline, carriage return, raw backslash,
    unescaped double-quote. Fuseki rejects bodies containing any of these
    with ``HTTP 400 Bad Request`` — and silently corrupts the dataset if any
    Update happens to be otherwise-valid by accident.

    Plugin SPARQL builders historically used ``.replace('"', '')`` as their
    only "sanitization", which strips quotes but leaves newlines and
    backslashes intact. Any document with multi-line extracted text (i.e.
    almost all of them) produced an invalid Update body. See
    ``manufacturing.py:to_graph_queries`` for the original site; this helper
    is the canonical fix.

    Backslash MUST be escaped first to avoid double-escaping the
    substitutions added by later steps.
    """
    return (
        s.replace("\\", "\\\\")
         .replace('"', '\\"')
         .replace("\n", "\\n")
         .replace("\r", "\\r")
         .replace("\t", "\\t")
    )


class JenaClient:
    def __init__(self, url: str = None, dataset: str = None, username: str = None, password: str = None):
        # Prefer passed parameters, fall back to environment variables
        self.base_url = (url or os.getenv("JENA_URL", "http://jena-fuseki:3030")).rstrip('/')
        self.dataset = dataset or os.getenv("JENA_DS", "ds")
        self.username = username or os.getenv("JENA_USERNAME", "admin")
        self.password = password or os.getenv("JENA_PASSWORD", "password")
        
    def _get_wrapper(self, endpoint_suffix: str):
        url = f"{self.base_url}/{self.dataset}/{endpoint_suffix}"
        sparql = SPARQLWrapper(url)
        if self.username and self.password:
            sparql.setHTTPAuth(BASIC)
            sparql.setCredentials(self.username, self.password)
        return sparql

    def execute_update(self, query: str):
        """POST a SPARQL Update to Fuseki's update endpoint.

        Uses httpx with ``Content-Type: application/sparql-update`` (the Fuseki
        SPARQL Update protocol) — the same direct-HTTP approach the working
        Graph Store writes use. SPARQLWrapper was issuing a request Fuseki
        rejected with ``HTTP 405: Method Not Allowed`` on ``/update``.
        """
        url = f"{self.base_url}/{self.dataset}/update"
        auth = (self.username, self.password) if (self.username and self.password) else None
        with httpx.Client(auth=auth, verify=False) as client:
            resp = client.post(
                url,
                content=query.encode("utf-8"),
                headers={"Content-Type": "application/sparql-update"},
            )
            resp.raise_for_status()
            return resp

    def execute_query(self, query: str):
        sparql = self._get_wrapper("query")
        sparql.setReturnFormat(JSON)
        sparql.setQuery(query)
        return sparql.queryAndConvert()

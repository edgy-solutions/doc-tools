import os
import re
import httpx
from SPARQLWrapper import SPARQLWrapper, POST, BASIC, JSON

_IRI_LOCAL_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]")


def safe_iri_local(s: str) -> str:
    """Sanitize a string into a SPARQL/Turtle prefixed-name local part (PN_LOCAL).

    Companion to :func:`escape_sparql_string` (which protects string *literals*).
    This one protects *IRIs* of the form ``prefix:local``. Plugin SPARQL builders
    form IRIs like ``mfg:{step_node_id}``, and ``step_node_id`` is derived from
    the doc id — which is a path such as ``inbound/22``. A raw ``/`` (or space,
    ``#``, etc.) is illegal in a prefixed local name, so Fuseki rejects the whole
    Update body with ``HTTP 400 Bad Request``.

    Replaces every character outside ``[A-Za-z0-9_.-]`` with ``_`` and strips any
    leading/trailing ``.`` (PN_LOCAL may not begin or end with a dot).
    """
    cleaned = _IRI_LOCAL_UNSAFE.sub("_", s or "")
    return cleaned.strip(".") or "_"


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


class UnscopedUpdateError(ValueError):
    """Raised when a SPARQL Update would land in Jena's default graph, or
    cannot be scoped to a named graph.

    The mesh resolver (engine-o) scopes every read to the per-domain named
    graphs (``<http://internal/{DOMAIN}>`` union ``<http://internal/{DOMAIN}_INSTANCES>``).
    A bare ``INSERT DATA`` with no ``GRAPH`` clause lands in Fuseki's default
    graph, which is invisible to those reads — see the "Domain Semantic
    Graph" invariant in AGENTS.md. :func:`JenaClient.execute_update` raises
    this instead of silently sending an update nobody will ever be able to
    query back out.
    """


_GRAPH_KEYWORD_RE = re.compile(r"\bGRAPH\b", re.IGNORECASE)
_INSERT_DATA_RE = re.compile(r"\bINSERT\s+DATA\b", re.IGNORECASE)
_GRAPH_URI_UNSAFE_CHARS = set('<>"{} \t\n\r')


def _ordinary_mask(query: str) -> list:
    """Classify every character of a SPARQL string as "ordinary" syntax
    (True) or as belonging to a double-quoted string literal, an
    angle-bracket IRI (``<...>``), or a ``#`` line comment (False).

    This exists because :func:`escape_sparql_string` escapes ``\\ " \\n \\r
    \\t`` but deliberately leaves ``{``, ``}`` and the literal word ``GRAPH``
    untouched — a plugin's extracted text can legitimately contain any of
    those. So a naive brace-counter or ``"GRAPH" in query`` regex over the
    raw string would misfire on content that merely *looks* structural
    inside a literal. Only positions this function marks ordinary may be
    treated as real SPARQL syntax.

    Documented assumption: plugin-emitted update bodies never use
    triple-quoted (``\"\"\"..\"\"\"``) string literals. ``#`` outside a
    literal/IRI is treated as a comment to end of line, in case a body ever
    carries one.
    """
    n = len(query)
    mask = [True] * n
    i = 0
    in_literal = False
    in_iri = False
    while i < n:
        c = query[i]
        if in_literal:
            mask[i] = False
            if c == "\\" and i + 1 < n:
                mask[i + 1] = False
                i += 2
                continue
            if c == '"':
                in_literal = False
            i += 1
            continue
        if in_iri:
            mask[i] = False
            if c == ">":
                in_iri = False
            i += 1
            continue
        if c == '"':
            in_literal = True
            mask[i] = False
            i += 1
            continue
        if c == "<":
            in_iri = True
            mask[i] = False
            i += 1
            continue
        if c == "#":
            j = i
            while j < n and query[j] != "\n":
                mask[j] = False
                j += 1
            i = j
            continue
        i += 1
    return mask


def update_is_graph_scoped(query: str) -> bool:
    """True iff the bare keyword ``GRAPH`` occurs outside any string
    literal, IRI, or comment in ``query`` — i.e. the update already scopes
    its own triples and must not be wrapped again."""
    mask = _ordinary_mask(query)
    for m in _GRAPH_KEYWORD_RE.finditer(query):
        if mask[m.start()]:
            return True
    return False


def scope_update_to_graph(query: str, graph_uri: str) -> str:
    """Wrap the ``{ ... }`` body of an ``INSERT DATA`` clause in
    ``GRAPH <graph_uri> { ... }``, so the triples land in a named graph
    instead of Jena's default graph.

    Locates ``INSERT DATA`` (case-insensitive, outside literals/IRIs/
    comments), finds the next ``{`` after it, and finds that brace's match
    by depth-counting only over positions :func:`_ordinary_mask` marks
    ordinary (so braces embedded in extracted text don't confuse the
    count). Raises :class:`UnscopedUpdateError` — never falls through to
    returning an unscoped body — if ``graph_uri`` is unsafe, if
    ``INSERT DATA`` is absent, or if the braces are unbalanced.
    """
    if not graph_uri or (_GRAPH_URI_UNSAFE_CHARS & set(graph_uri)):
        raise UnscopedUpdateError(
            f"invalid graph_uri for scoping an update: {graph_uri!r} — must "
            "be non-empty and contain none of <, >, \", {, }, or whitespace "
            "(this closes IRI injection through the graph name)"
        )

    mask = _ordinary_mask(query)
    n = len(query)

    insert_match = None
    for m in _INSERT_DATA_RE.finditer(query):
        if mask[m.start()]:
            insert_match = m
            break
    if insert_match is None:
        raise UnscopedUpdateError(
            "cannot scope update to a graph: no INSERT DATA clause found — "
            "refusing to send an update that would land in the default graph"
        )

    brace_open = None
    i = insert_match.end()
    while i < n:
        if mask[i] and query[i] == "{":
            brace_open = i
            break
        i += 1
    if brace_open is None:
        raise UnscopedUpdateError(
            "cannot scope update to a graph: no opening brace found after "
            "INSERT DATA"
        )

    depth = 0
    brace_close = None
    i = brace_open
    while i < n:
        if mask[i]:
            if query[i] == "{":
                depth += 1
            elif query[i] == "}":
                depth -= 1
                if depth == 0:
                    brace_close = i
                    break
        i += 1
    if brace_close is None:
        raise UnscopedUpdateError(
            "cannot scope update to a graph: unbalanced braces in the "
            "INSERT DATA body"
        )

    prefix = query[: brace_open + 1]
    body = query[brace_open + 1 : brace_close]
    suffix = query[brace_close:]
    return f"{prefix}GRAPH <{graph_uri}> {{{body}}}{suffix}"


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

    def execute_update(self, query: str, graph_uri: str | None = None):
        """POST a SPARQL Update to Fuseki's update endpoint.

        Uses httpx with ``Content-Type: application/sparql-update`` (the Fuseki
        SPARQL Update protocol) — the same direct-HTTP approach the working
        Graph Store writes use. SPARQLWrapper was issuing a request Fuseki
        rejected with ``HTTP 405: Method Not Allowed`` on ``/update``.

        Graph scoping lives here, in the single writer, rather than in each
        plugin: three of the four SPARQL-emitting plugins (compliance,
        maintenance, manufacturing) forgot to wrap their triples in a
        ``GRAPH <...>`` clause, and the call site only logs a failure — so a
        silently-unscoped write never went red. An unscoped ``INSERT DATA``
        lands in Jena's default graph, which the mesh resolver cannot see.

        Behaviour, in order:
          1. If ``query`` already scopes itself (contains a bare ``GRAPH``
             keyword outside any literal/IRI/comment — e.g. sustainment,
             which does this correctly today), it is sent byte-for-byte
             unchanged. A pre-scoped body is never double-wrapped.
          2. Else, if ``graph_uri`` is given, the body is wrapped with
             :func:`scope_update_to_graph` before sending.
          3. Else, the update is refused — :class:`UnscopedUpdateError` is
             raised, and no HTTP request is made at all — rather than
             silently performing a default-graph write nothing can read
             back.
        """
        if update_is_graph_scoped(query):
            body = query
        elif graph_uri:
            body = scope_update_to_graph(query, graph_uri)
        else:
            raise UnscopedUpdateError(
                "refusing to send a SPARQL Update with no GRAPH scoping and "
                "no graph_uri: an unscoped INSERT DATA lands in Jena's "
                "default graph, which the mesh resolver cannot see (see the "
                "'Domain Semantic Graph' invariant in AGENTS.md). Pass "
                "graph_uri=f'http://internal/{domain_label}_INSTANCES', or "
                "scope the query yourself with a GRAPH <...> clause."
            )

        url = f"{self.base_url}/{self.dataset}/update"
        auth = (self.username, self.password) if (self.username and self.password) else None
        with httpx.Client(auth=auth, verify=False) as client:
            resp = client.post(
                url,
                content=body.encode("utf-8"),
                headers={"Content-Type": "application/sparql-update"},
            )
            resp.raise_for_status()
            return resp

    def execute_query(self, query: str):
        # Fuseki's default SPARQL Query service endpoint is `/sparql`, not
        # `/query` (the configurable Fuseki Server in this cluster exposes
        # `/{dataset}/sparql` per service definition). Previously this
        # code used `/query` and got 404 — but the calling asset
        # (sync_jena_to_neo4j) catches the exception and falls back to
        # [root_uri], so step status stayed SUCCESS while the sync was
        # silently degraded. Caught when the helmet WPs started ingest
        # with debug output enabled (2026-06-29). Sibling fix in
        # semantic_assets.py's n10s.fetch URL.
        sparql = self._get_wrapper("sparql")
        sparql.setReturnFormat(JSON)
        sparql.setQuery(query)
        return sparql.queryAndConvert()

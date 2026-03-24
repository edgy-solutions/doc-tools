import os
from SPARQLWrapper import SPARQLWrapper, POST, BASIC, JSON

class JenaClient:
    def __init__(self):
        # Default to a base URL, but we will append /query or /update as needed
        self.base_url = os.getenv("JENA_URL", "http://jena-fuseki:3030/ds").rstrip('/')
        self.username = os.getenv("JENA_USERNAME", "admin")
        self.password = os.getenv("JENA_PASSWORD", "password")
        
    def _get_wrapper(self, endpoint_suffix: str):
        url = f"{self.base_url}/{endpoint_suffix}"
        sparql = SPARQLWrapper(url)
        if self.username and self.password:
            sparql.setHTTPAuth(BASIC)
            sparql.setCredentials(self.username, self.password)
        return sparql

    def execute_update(self, query: str):
        sparql = self._get_wrapper("update")
        sparql.setMethod(POST)
        sparql.setQuery(query)
        return sparql.query()

    def execute_query(self, query: str):
        sparql = self._get_wrapper("query")
        sparql.setReturnFormat(JSON)
        sparql.setQuery(query)
        return sparql.queryAndConvert()

import os
from SPARQLWrapper import SPARQLWrapper, POST, BASIC, JSON

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
        sparql = self._get_wrapper("update")
        sparql.setMethod(POST)
        sparql.setQuery(query)
        return sparql.query()

    def execute_query(self, query: str):
        sparql = self._get_wrapper("query")
        sparql.setReturnFormat(JSON)
        sparql.setQuery(query)
        return sparql.queryAndConvert()

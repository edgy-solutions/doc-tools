import os
from SPARQLWrapper import SPARQLWrapper, POST, BASIC

class JenaClient:
    def __init__(self):
        self.url = os.getenv("JENA_URL", "http://jena-fuseki:3030/ds/update")
        self.username = os.getenv("JENA_USERNAME", "admin")
        self.password = os.getenv("JENA_PASSWORD", "password")
        self.sparql = SPARQLWrapper(self.url)
        if self.username and self.password:
            self.sparql.setHTTPAuth(BASIC)
            self.sparql.setCredentials(self.username, self.password)
        self.sparql.setMethod(POST)

    def execute_update(self, query: str):
        self.sparql.setQuery(query)
        return self.sparql.query()

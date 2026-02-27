grpc: dagster api grpc -h 0.0.0.0 -p 3030 -m doc_tools.definitions
web: dagster-webserver -h 0.0.0.0 -p 8080 -m doc_tools.definitions
worker: dagster job execute -m doc_tools.definitions -j process_documents_job
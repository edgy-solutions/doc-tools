import os
import weaviate

def get_weaviate_client(http_host: str = None, grpc_host: str = None) -> weaviate.WeaviateClient:
    """
    Fleet-standard factory for creating a Weaviate v4 client in Dagster.
    Handles split HTTP/gRPC routing for Kubernetes environments.
    """
    raw_http_env = http_host or os.getenv("WEAVIATE_HTTP_HOST", "weaviate:8080")
    raw_grpc_env = grpc_host or os.getenv("WEAVIATE_GRPC_HOST", "weaviate-grpc:50051")

    def parse_host_port(env_val: str, default_port: int):
        clean = env_val.replace("http://", "").replace("https://", "").replace("grpc://", "")
        if ":" in clean:
            h, p = clean.split(":", 1)
            try:
                return h, int(p)
            except ValueError:
                return h, default_port
        return clean, default_port

    http_h, http_p = parse_host_port(raw_http_env, 8080)
    grpc_h, grpc_p = parse_host_port(raw_grpc_env, 50051)

    client = weaviate.connect_to_custom(
        http_host=http_h,
        http_port=http_p,
        http_secure=False,
        grpc_host=grpc_h,
        grpc_port=grpc_p,
        grpc_secure=False
    )
    return client

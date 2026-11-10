"""Upload deck folders to processing-artifacts/training/course/<slug>/ (in-pod).

    /opt/venv/bin/python /tmp/tr_run/tr_upload.py [--check] <local_root>

Each subdirectory of <local_root> is one slug. metadata.json (if present) goes
first, then the deck, so the sidecar exists before the deck does. Prints the
deck keys, one per line, prefixed "KEY ". Never prints env values.
--check uploads nothing: it prints MATCH, DIFF or MISSING per file against the
object already at the key, and exits 1 unless every file MATCHes. A deck that is
already there is re-ingested by hand without re-uploading, so no sensor sees a drop.
"""
import hashlib
import os
import sys

BUCKET = "processing-artifacts"
PREFIX = "training/course"


def main(root, check=False):
    import boto3
    s3 = boto3.client("s3", endpoint_url=os.environ["S3_ENDPOINT_URL"],
                      aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
                      aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"])
    rc = 0
    for slug in sorted(os.listdir(root)):
        d = os.path.join(root, slug)
        if not os.path.isdir(d):
            continue
        names = sorted(os.listdir(d), key=lambda n: (n != "metadata.json", n))
        for n in names:
            p = os.path.join(d, n)
            key = f"{PREFIX}/{slug}/{n}"
            with open(p, "rb") as f:
                data = f.read()
            sha = hashlib.sha256(data).hexdigest()
            tag = "KEY " if n != "metadata.json" else "META"
            if check:
                try:
                    have = s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()
                    state = "MATCH" if hashlib.sha256(have).hexdigest() == sha else "DIFF"
                except s3.exceptions.NoSuchKey:
                    state = "MISSING"
                if state != "MATCH":
                    rc = 1
                print(state, tag, key, "sha256:" + sha[:12], flush=True)
                continue
            s3.put_object(Bucket=BUCKET, Key=key, Body=data)
            print(tag, key, "sha256:" + sha[:12], flush=True)
    return rc


if __name__ == "__main__":
    args = sys.argv[1:]
    sys.exit(main([a for a in args if a != "--check"][0], check="--check" in args))

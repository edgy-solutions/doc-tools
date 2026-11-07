"""Upload deck folders to processing-artifacts/training/course/<slug>/ (in-pod).

    /opt/venv/bin/python /tmp/cand_tr/tr_upload.py <local_root>

Each subdirectory of <local_root> is one slug. metadata.json (if present) goes
first, then the deck, so the sidecar exists before the deck does. Prints the
deck keys, one per line, prefixed "KEY ". Never prints env values.
"""
import hashlib
import os
import sys

BUCKET = "processing-artifacts"
PREFIX = "training/course"


def main(root):
    import boto3
    s3 = boto3.client("s3", endpoint_url=os.environ["S3_ENDPOINT_URL"],
                      aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
                      aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"])
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
            s3.put_object(Bucket=BUCKET, Key=key, Body=data)
            tag = "KEY " if n != "metadata.json" else "META"
            print(tag, key, "sha256:" + hashlib.sha256(data).hexdigest()[:12], flush=True)


if __name__ == "__main__":
    main(sys.argv[1])

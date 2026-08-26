"""Publishing to the HuggingFace dataset repo.

Uploads go through ``HfApi.create_commit``, which is a plain HTTP call to the
Hub's ``/commit/`` endpoint. Nothing is cloned and no existing data is
downloaded, so the cost of appending a snapshot is constant regardless of how
large the dataset has grown. That is the property the old design lacked: a
GitHub commit needed a full working tree, so appending 56 KB meant checking out
several gigabytes first.
"""

import os

from huggingface_hub import CommitOperationAdd, CommitOperationDelete, HfApi

REPO_ID = os.environ.get("HF_DATASET_REPO", "feregrino/london-cycles")
REPO_TYPE = "dataset"


def api():
    token = os.environ.get("HF_TOKEN")
    if not token:
        raise SystemExit("HF_TOKEN is not set; cannot publish to the Hub.")
    return HfApi(token=token)


def snapshot_path(execution_time):
    """Hive-ish layout: cheap to list a day or a month, and no single directory
    accumulates an unbounded number of files."""
    return (
        f"data/year={execution_time.year:04d}/month={execution_time.month:02d}"
        f"/day={execution_time.day:02d}/{execution_time.strftime('%H%M%S')}.csv"
    )


def commit(operations, message, client=None):
    if not operations:
        return None
    client = client or api()
    return client.create_commit(
        repo_id=REPO_ID,
        repo_type=REPO_TYPE,
        operations=operations,
        commit_message=message,
    )


def add(path_in_repo, payload):
    if isinstance(payload, str):
        payload = payload.encode()
    return CommitOperationAdd(path_in_repo=path_in_repo, path_or_fileobj=payload)


def delete(path_in_repo):
    return CommitOperationDelete(path_in_repo=path_in_repo)

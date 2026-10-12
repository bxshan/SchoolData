import json
import os
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_cfg(path=None):
    with open(path or ROOT / "config.yaml") as f:
        return yaml.safe_load(f)


def resolve(p):
    p = Path(os.path.expanduser(str(p)))
    return p if p.is_absolute() else ROOT / p


def model_by_key(cfg, key):
    for m in cfg["models"]:
        if m["key"] == key:
            return m
    raise KeyError(f"unknown model key {key!r}")


def read_jsonl(path):
    path = Path(path)
    if not path.exists():
        return []
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def append_jsonl(path, rec):
    with open(path, "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def load_responses(out, task="kb", ids=None):
    """Successful responses of one task ('kb' | 'bias:none' | 'bias:frl15' | 'bias:frl85'); old records default to 'facts'."""
    return [r for r in read_jsonl(Path(out) / "responses.jsonl")
            if not r.get("error") and r.get("task", "facts") == task and (ids is None or r["nces_id"] in ids)]


def ans_hash(text):
    """Fingerprint of the answer a judgment was made for, so edited/re-asked answers are never matched to stale judgments."""
    import hashlib
    return hashlib.md5((text or "").encode()).hexdigest()[:12]


def judgments_path(out, cfg):
    """One file per judge model so judges can be compared: judgments__<model>.jsonl"""
    return Path(out) / f"judgments__{re.sub(r'[^A-Za-z0-9._-]', '_', cfg['judge']['model'])}.jsonl"

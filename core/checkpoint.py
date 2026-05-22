import json, hashlib, shutil, time, tempfile, os
from pathlib import Path


def load(checkpoint_dir: str) -> dict:
    ckpt_file = Path(checkpoint_dir) / "checkpoint.json"
    if not ckpt_file.exists():
        return {"chunk_idx": 0, "terms": [], "total_chunks": 0}
    for _ in range(3):
        try:
            return json.loads(ckpt_file.read_text(encoding="utf-8"))
        except (PermissionError, OSError):
            time.sleep(0.5)
    return {"chunk_idx": 0, "terms": [], "total_chunks": 0}


def save(checkpoint_dir: str, chunk_idx: int, terms: list, total_chunks: int):
    Path(checkpoint_dir).mkdir(parents=True, exist_ok=True)
    target = Path(checkpoint_dir) / "checkpoint.json"
    fd, tmp = tempfile.mkstemp(dir=checkpoint_dir, suffix=".tmp")
    try:
        os.write(fd, json.dumps({"chunk_idx": chunk_idx, "terms": terms, "total_chunks": total_chunks}, ensure_ascii=False).encode("utf-8"))
    finally:
        os.close(fd)
    os.replace(tmp, target)


def clear(checkpoint_dir: str):
    p = Path(checkpoint_dir)
    if p.exists():
        shutil.rmtree(p)


def save_meta(checkpoint_dir: str, data: dict):
    Path(checkpoint_dir).mkdir(parents=True, exist_ok=True)
    (Path(checkpoint_dir) / "run_meta.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )


def load_meta(checkpoint_dir: str) -> dict:
    p = Path(checkpoint_dir) / "run_meta.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}

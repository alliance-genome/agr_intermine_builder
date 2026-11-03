"""Local command doubles for running the unmodified deployment entry point."""

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(os.environ["DEPLOY_TEST_ROOT"])


def aws(args):
    if args[:2] != ["s3", "cp"]:
        raise AssertionError(args)
    source, target = [arg for arg in args[2:] if arg != "--quiet"]

    def local(path):
        prefix = "s3://test/weekly/"
        return ROOT / "s3" / path[len(prefix) :] if path.startswith(prefix) else Path(path)

    destination = local(target)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(local(source), destination)
    return 0


def curl(args):
    url = next(arg for arg in args if arg.startswith("http://"))
    state_file = ROOT / "cores.json"
    state = json.loads(state_file.read_text())
    query = parse_qs(urlparse(url).query)
    if query.get("action") == ["SWAP"]:
        core = query["core"][0].removeprefix("yeastmine-")
        state["calls"] += 1
        failed = state["calls"] in json.loads(os.environ.get("FAIL_SWAPS", "[]"))
        if not failed:
            state[core] = "new" if state[core] == "old" else "old"
        state_file.write_text(json.dumps(state))
        return 22 if failed else 0
    if query.get("action") == ["STATUS"]:
        print(json.dumps({"name": query["core"][0]}, separators=(",", ":")))
    elif "version/release" in url:
        print('"test release"')
    elif "begin.do" in url:
        fail = os.environ.get("FAIL_VERIFY") == "1" and state["search"] == "new"
        print("503" if fail else "200")
    elif "/search?" in url:
        print('{"wasSuccessful": true, "totalHits": 1}')
    elif "/templates?" in url:
        print('{"templates": {"test": {}}}')
    elif "/query/results" in url:
        print("6000")
    else:
        raise AssertionError(url)
    return 0


def main():
    command, *args = sys.argv[1:]
    if command == "aws":
        return aws(args)
    if command == "curl":
        return curl(args)
    if command == "sha256sum":
        print(hashlib.sha256(Path(args[0]).read_bytes()).hexdigest(), args[0])
        return 0
    if command in {"docker", "flock"}:
        return 0
    raise AssertionError(command)


if __name__ == "__main__":
    sys.exit(main())

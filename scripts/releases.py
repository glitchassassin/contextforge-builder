#!/usr/bin/env python3
"""Find stable upstream releases that do not yet have a UBI 9 image."""
import json
import os
import re
import urllib.error
import urllib.request

UPSTREAM = "IBM/mcp-context-forge"
MINIMUM = (1, 0, 11)


def get(url):
    request = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + os.environ["GH_TOKEN"],
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def main():
    requested = os.environ.get("RELEASE_TAG", "").strip()
    releases = []
    page = 1
    while True:
        batch = get(f"https://api.github.com/repos/{UPSTREAM}/releases?per_page=100&page={page}")
        releases.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    candidates = []
    for release in releases:
        tag = release["tag_name"]
        match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", tag)
        if release["draft"] or release["prerelease"] or not match:
            continue
        version = tuple(map(int, match.groups()))
        if (requested and tag != requested) or (not requested and version < MINIMUM):
            continue
        candidates.append((version, tag))
    if requested and not candidates:
        raise SystemExit("Manual tag must name a published stable upstream release")
    candidates.sort()
    owner = os.environ["GITHUB_REPOSITORY_OWNER"]
    package = os.environ.get("IMAGE_NAME", "contextforge")
    existing = set()
    if not requested:
        page = 1
        while True:
            try:
                batch = get(f"https://api.github.com/users/{owner}/packages/container/{package}/versions?per_page=100&page={page}")
            except urllib.error.HTTPError as error:
                if error.code == 404:
                    break
                raise
            for image in batch:
                existing.update(image["metadata"]["container"]["tags"])
            if len(batch) < 100:
                break
            page += 1
    pending = [{"tag": tag, "image_tag": ".".join(map(str, version)) + "-ubi9",
                "latest": tag == candidates[-1][1]}
               for version, tag in candidates
               if requested or ".".join(map(str, version)) + "-ubi9" not in existing]
    if len(pending) > 256:
        raise SystemExit("Too many pending releases for a workflow matrix")
    result = {"include": pending}
    with open(os.environ["GITHUB_OUTPUT"], "a") as output:
        output.write("matrix=" + json.dumps(result, separators=(",", ":")) + "\n")
        output.write("has_builds=" + str(bool(pending)).lower() + "\n")
    print("Pending releases:", ", ".join(x["tag"] for x in pending) or "none")


if __name__ == "__main__":
    main()

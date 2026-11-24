"""Download the data used by the project from the Montreal open data portal.

    python download_data.py            # crimes csv + territory boundary
    python download_data.py --only crimes

It asks the portal (a standard CKAN API) for the current download link of each
dataset, so no file address is hard-coded, then saves the files in `data/` and
writes `data/DOWNLOAD_INFO.json` (source link, date, size, SHA-256) so that the
version of the data used for an analysis can be recorded.

The data is published by the SPVM / Ville de Montreal under the CC-BY 4.0
licence. It is not stored in this repository.
"""
import argparse
import datetime as dt
import hashlib
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

PORTAL = "https://donnees.montreal.ca"
DATA_DIR = Path("data")

# name -> (CKAN package id, accepted formats, text the resource name must contain,
#          text it must not contain, destination file)
DATASETS = {
    "crimes": ("actes-criminels", {"CSV"}, "", "dictionnaire", DATA_DIR / "actes-criminels.csv"),
    "boundary": ("limites-administratives-agglomeration", {"GEOJSON", "JSON"}, "WGS",
                 "", DATA_DIR / "montreal_boundary.geojson"),
}


def fetch_json(url):
    """GET a JSON document."""
    with urllib.request.urlopen(url, timeout=60) as response:   # nosec: https only, see _check_url
        return json.load(response)


def _check_url(url):
    parts = urllib.parse.urlparse(url)
    if parts.scheme != "https" or not (parts.hostname or "").endswith("montreal.ca"):
        raise ValueError(f"refusing to download from {url}")


def list_resources(package, fetch=fetch_json):
    """Resources (files) of a portal dataset."""
    url = f"{PORTAL}/api/3/action/package_show?id={urllib.parse.quote(package)}"
    result = fetch(url)
    if not result.get("success"):
        raise RuntimeError(f"the portal did not return dataset '{package}'")
    return result["result"]["resources"]


def pick_resource(resources, formats, must_contain="", must_not_contain=""):
    """The resource of one of `formats` whose name matches the filters."""
    candidates = []
    for res in resources:
        name = (res.get("name") or "") + " " + (res.get("url") or "")
        if (res.get("format") or "").upper() not in formats:
            continue
        if must_contain and must_contain.lower() not in name.lower():
            continue
        if must_not_contain and must_not_contain.lower() in name.lower():
            continue
        candidates.append(res)
    if not candidates:
        raise LookupError("no matching file in this dataset")
    return candidates[0]


def download(url, target):
    """Save `url` to `target`; return (size in bytes, SHA-256)."""
    _check_url(url)
    target.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    with urllib.request.urlopen(url, timeout=600) as response, open(target, "wb") as out:   # nosec
        for chunk in iter(lambda: response.read(1 << 20), b""):
            out.write(chunk)
            digest.update(chunk)
            size += len(chunk)
    return size, digest.hexdigest()


def main(argv=None, fetch=fetch_json, save=download):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--only", choices=sorted(DATASETS), help="download a single dataset")
    args = parser.parse_args(argv)

    info_path = DATA_DIR / "DOWNLOAD_INFO.json"
    info = json.loads(info_path.read_text()) if info_path.exists() else {}
    for name, (package, formats, contains, excludes, target) in DATASETS.items():
        if args.only and args.only != name:
            continue
        resource = pick_resource(list_resources(package, fetch), formats, contains, excludes)
        size, sha = save(resource["url"], target)
        info[str(target)] = {
            "source": resource["url"],
            "dataset": f"{PORTAL}/dataset/{package}",
            "downloaded_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "bytes": size,
            "sha256": sha,
        }
        print(f"{name}: {target} ({size:,} bytes)")
    DATA_DIR.mkdir(exist_ok=True)
    info_path.write_text(json.dumps(info, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

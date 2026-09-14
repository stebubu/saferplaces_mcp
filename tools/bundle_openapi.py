"""
Scarica lo spec OpenAPI di SaferPlaces e risolve (inlinea) tutti i $ref
esterni, producendo un openapi.json "bundled" self-contained.

Necessario perché il parser OpenAPI di fastmcp non supporta riferimenti
esterni (es. verso schemas.opengis.net o api.saferplaces.co/schemas/...),
solo quelli locali ("#/...").

Uso:
    pip install pyyaml
    python tools/bundle_openapi.py
"""

import copy
import json
import os
import sys
import urllib.parse
import urllib.request

import yaml

SPEC_URL = "https://api.saferplaces.co/openapi?f=json"
OUTPUT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "openapi.json")


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "openapi-bundler/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        text = resp.read().decode("utf-8")
    if url.endswith(".json") or text.lstrip().startswith("{"):
        return json.loads(text)
    return yaml.safe_load(text)


def navigate(doc, fragment):
    target = doc
    if fragment:
        for part in fragment.strip("/").split("/"):
            part = urllib.parse.unquote(part).replace("~1", "/").replace("~0", "~")
            target = target[part]
    return target


def bundle(root):
    doc_cache = {}
    resolved_cache = {}

    def get_doc(url):
        if url not in doc_cache:
            print(f"fetching {url}", file=sys.stderr)
            doc_cache[url] = fetch(url)
        return doc_cache[url]

    def resolve_node(node, doc, base_url, is_root, stack):
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str):
                if ref.startswith("#"):
                    if is_root:
                        # ref locale nel documento radice: lascialo invariato
                        return node
                    # ref locale dentro un documento esterno: risolvi in quel documento
                    frag = ref[1:]
                    key = (base_url, frag)
                    if key in stack:
                        return {"$ref": ref}  # riferimento circolare: best effort
                    if key in resolved_cache:
                        return resolved_cache[key]
                    target = navigate(doc, frag)
                    result = resolve_node(copy.deepcopy(target), doc, base_url, False, stack | {key})
                    resolved_cache[key] = result
                    return result
                # ref assoluto (http/https) o relativo (../foo.yaml, ecc.):
                # risolvilo rispetto al documento corrente e inlinealo.
                absolute = urllib.parse.urljoin(base_url, ref) if base_url else ref
                url, _, frag = absolute.partition("#")
                key = (url, frag)
                if key in stack:
                    return {"$ref": ref}
                if key in resolved_cache:
                    return resolved_cache[key]
                target_doc = get_doc(url)
                target = navigate(target_doc, frag)
                result = resolve_node(copy.deepcopy(target), target_doc, url, False, stack | {key})
                resolved_cache[key] = result
                return result
            return {k: resolve_node(v, doc, base_url, is_root, stack) for k, v in node.items()}
        if isinstance(node, list):
            return [resolve_node(v, doc, base_url, is_root, stack) for v in node]
        return node

    return resolve_node(root, root, SPEC_URL, True, frozenset())


def main():
    root = fetch(SPEC_URL)
    resolved = bundle(root)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(resolved, f, indent=2)
    print(f"Scritto {OUTPUT_PATH}")


if __name__ == "__main__":
    main()

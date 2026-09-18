#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_site.py — prépare les données servies au dashboard : découpage par niveau, gzip, chiffrement.

Entrée  : data/dvf_paris.json + data/dvf_sales.bin (produits par process_dvf.py, NON commités)
Sortie  : data/enc/manifest.json (clair) + data/enc/meta.bin + data/enc/sales.bin (chiffrés)
Lot 4   : le navigateur calcule tout lui-même à partir des ventes (sales.bin) ; les fichiers par niveau
          (arrondissements, secteurs, zones, quartiers) ne sont plus produits.

Format d'un .bin :  b"DVF1" | salt (16) | iv (12) | AES-256-GCM(gzip(json))  — le tag GCM (16) est en fin.
Clé     : PBKDF2-HMAC-SHA256(code, salt, 200 000 itérations) → 32 octets. Même dérivation côté navigateur (WebCrypto).
IV      : les 12 premiers octets de HMAC-SHA256(clé, gzip(json)). Déterministe : des données inchangées donnent
          un fichier identique octet pour octet, donc aucun commit inutile lors du run mensuel. Un IV ne se répète
          que si le contenu est identique, ce qui est exactement le cas sans danger (même message).
Salt    : fixé par SALT_HEX ci-dessous — public par construction (il est dans chaque fichier) ; il sert à rendre
          la clé propre à ce dépôt, pas à la cacher.

Pourquoi chiffrer ceci et pas le reste : le dashboard doit être inutilisable sans le code (demande de Franck :
« en ligne, accessible de manière privée »). Le pipeline, le référentiel géo et le cache de mutations restent en
clair — données publiques DVF, pipeline reproductible — les chiffrer donnerait une fausse impression de secret.

Le code vient de l'environnement (DVF_CODE) : jamais dans le dépôt, jamais dans un log.
"""
import os, sys, json, gzip, hmac, hashlib, argparse
from datetime import datetime
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

SRC     = "data/dvf_paris.json"
SALES   = "data/dvf_sales.bin"
OUT_DIR = "data/enc"
MAGIC   = b"DVF1"
SALT    = bytes.fromhex("6a61646572302d6476662d70617269732d3236")[:16]   # "jadero-dvf-paris-26"
ITER    = 200_000

# Découpage : chaque entrée du manifest = un fichier, chargé à la demande par le dashboard.
NIVEAUX = {
    "meta": lambda d: {k: d[k] for k in ("meta", "global", "secteurs_ref", "zones_ref", "quartiers_ref", "quartier_index",
                                         "typologies_ref", "fenetres_ref") if k in d},
}

def derive_key(code: str) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", code.encode("utf-8"), SALT, ITER, dklen=32)

def encrypt(key: bytes, plain: bytes) -> bytes:
    gz = gzip.compress(plain, compresslevel=9, mtime=0)      # mtime=0 : sortie reproductible
    iv = hmac.new(key, gz, hashlib.sha256).digest()[:12]
    return MAGIC + SALT + iv + AESGCM(key).encrypt(iv, gz, MAGIC)

def ecrire(path, blob):
    old = open(path, "rb").read() if os.path.exists(path) else None
    if old != blob:
        with open(path, "wb") as f: f.write(blob)
    return old == blob

def decrypt(key: bytes, blob: bytes) -> bytes:
    assert blob[:4] == MAGIC, "format inconnu"
    salt, iv, ct = blob[4:20], blob[20:32], blob[32:]
    assert salt == SALT
    return gzip.decompress(AESGCM(key).decrypt(iv, ct, MAGIC))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=SRC); ap.add_argument("--sales", default=SALES); ap.add_argument("--out", default=OUT_DIR)
    ap.add_argument("--code", default=os.environ.get("DVF_CODE", ""))
    args = ap.parse_args()
    if len(args.code) < 8:
        print("✗ DVF_CODE absent ou trop court (< 8 caractères). Définir le secret DVF_CODE (GitHub → Settings → Secrets)."); return 2
    with open(args.src, encoding="utf-8") as f: d = json.load(f)
    key = derive_key(args.code)
    os.makedirs(args.out, exist_ok=True)
    manifest = {"format": "DVF1", "kdf": {"name": "PBKDF2", "hash": "SHA-256", "iterations": ITER},
                "generated_at": d["meta"]["generated_at"], "periode": d["meta"]["periode"], "files": {}}
    sources = {nom: json.dumps(sel(d), ensure_ascii=False, separators=(",", ":")).encode("utf-8") for nom, sel in NIVEAUX.items()}
    if os.path.exists(args.sales): sources["sales"] = open(args.sales, "rb").read()
    else: print(f"✗ {args.sales} absent : lancer process_dvf.py d'abord"); return 2
    for nom, plain in sources.items():
        blob = encrypt(key, plain)
        assert decrypt(key, blob) == plain           # aller-retour vérifié avant d'écrire
        inchange = ecrire(os.path.join(args.out, f"{nom}.bin"), blob)
        manifest["files"][nom] = {"file": f"{nom}.bin", "bytes": len(blob), "plain_bytes": len(plain),
                                  "sha256": hashlib.sha256(blob).hexdigest()[:16]}
        print(f"  {nom:<8} {len(plain)/1e6:5.2f} Mo → {len(blob)/1e6:5.2f} Mo chiffré {'(inchangé)' if inchange else '(écrit)'}")
    # Fichiers d'anciens niveaux (lot 3) : supprimés pour ne pas laisser des données périmées en ligne
    for vieux in ("arrondissements", "secteurs", "zones", "quartiers"):
        vp = os.path.join(args.out, f"{vieux}.bin")
        if os.path.exists(vp): os.remove(vp); print(f"  − {vieux}.bin supprimé (niveau précalculé, remplacé par sales.bin)")
    mpath = os.path.join(args.out, "manifest.json")
    old = open(mpath, encoding="utf-8").read() if os.path.exists(mpath) else None
    new = json.dumps(manifest, ensure_ascii=False, indent=1)
    if old != new:
        with open(mpath, "w", encoding="utf-8") as f: f.write(new)
    total = sum(v["bytes"] for v in manifest["files"].values())
    print(f"✓ {len(manifest['files'])} fichiers, {total/1e6:.2f} Mo au total (JSON source {os.path.getsize(args.src)/1e6:.1f} Mo)")
    return 0

if __name__ == "__main__":
    sys.exit(main())

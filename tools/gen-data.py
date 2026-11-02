"""Génère data/wled-data.json depuis les sources WLED et FastLED d'une version donnée."""

import argparse
import json
import pathlib
import re
import sys
import tempfile
import urllib.request

WLED_CORE = {
    "FX.h": "wled00/FX.h",
    "FX.cpp": "wled00/FX.cpp",
    "FX_fcn.cpp": "wled00/FX_fcn.cpp",
}
WLED_LEGACY = {**WLED_CORE, "palettes": "wled00/palettes.h"}
WLED_MODERN = {
    **WLED_CORE,
    "palettes": "wled00/palettes.cpp",
    "colors": "wled00/src/dependencies/fastled_slim/fastled_slim.h",
}
FASTLED_FILES = {
    "cp.cpp": "src/colorpalettes.cpp",
    "colors": "src/pixeltypes.h",
}

SRC = None


def read(name):
    return (SRC / name).read_text(encoding="utf-8", errors="replace")


def exists(tag, remote):
    url = f"https://raw.githubusercontent.com/wled/WLED/{tag}/{remote}"
    request = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(request, timeout=30):
            return True
    except urllib.error.HTTPError:
        return False


def fetch(destination, tag, repo, files):
    for local, remote in files.items():
        url = f"https://raw.githubusercontent.com/{repo}/{tag}/{remote}"
        print(f"  {url}")
        with urllib.request.urlopen(url, timeout=30) as response:
            (destination / local).write_bytes(response.read())

STRING_LITERAL = re.compile(r'"((?:[^"\\]|\\.)*)"')


def unescape(s):
    return (
        s.replace('\\"', '"')
        .replace("\\'", "'")
        .replace("\\n", "\n")
        .replace("\\t", "\t")
        .replace("\\\\", "\\")
    )


def joined_literals(blob):
    return unescape("".join(m.group(1) for m in STRING_LITERAL.finditer(blob)))


def build_effects():
    fxh, fxcpp = read("FX.h"), read("FX.cpp")

    mode_count = int(re.search(r"#define\s+MODE_COUNT\s+(\d+)", fxh).group(1))
    ids = {
        m.group(1): int(m.group(2))
        for m in re.finditer(r"#define\s+(FX_MODE_\w+)\s+(\d+)", fxh)
    }
    datas = {
        m.group(1): joined_literals(m.group(2))
        for m in re.finditer(
            r"static const char (_data_FX_MODE_\w+)\[\]\s*PROGMEM\s*="
            r'((?:\s*"(?:[^"\\]|\\.)*")+)\s*;',
            fxcpp,
            re.S,
        )
    }

    raw = ["RSVD"] * mode_count
    raw[0] = datas["_data_FX_MODE_STATIC"]

    registered = 0
    for m in re.finditer(
        r"\n\s*addEffect\(\s*(FX_MODE_\w+)\s*,\s*&\w+\s*,\s*(_data_FX_MODE_\w+)\s*\)",
        fxcpp,
    ):
        name_id, data_id = m.group(1), m.group(2)
        if name_id not in ids:
            sys.exit(f"unknown effect id {name_id}")
        raw[ids[name_id]] = datas[data_id]
        registered += 1

    names, fxdata = [], []
    for entry in raw:
        head, sep, tail = entry.partition("@")
        names.append(head)
        fxdata.append(tail if sep else "")

    return names, fxdata, registered


def build_palette_names():
    body = re.search(
        r'JSON_palette_names\[\]\s*PROGMEM\s*=\s*R"=====\((.*?)\)====="',
        read("FX_fcn.cpp"),
        re.S,
    ).group(1)
    return json.loads(body)


def html_colors():
    enum = re.search(r"typedef enum \{(.*?)\} HTMLColorCode;", read("colors"), re.S).group(1)
    return {
        m.group(1): int(m.group(2), 16)
        for m in re.finditer(r"(\w+)\s*=\s*0x([0-9A-Fa-f]{6})", enum)
    }


def fastled_palettes():
    colors = html_colors()
    out = {}
    for m in re.finditer(
        r"(?:extern )?const TProgmemRGBPalette16 (\w+) (?:FL_)?PROGMEM\s*=\s*\{(.*?)\}\s*;",
        read("cp.cpp" if (SRC / "cp.cpp").is_file() else "palettes"),
        re.S,
    ):
        name, body = m.group(1), re.sub(r"//.*", "", m.group(2))
        entries = []
        for tok in (t.strip() for t in body.split(",")):
            if not tok:
                continue
            if tok.startswith("CRGB::"):
                v = colors[tok[6:]]
            elif tok.startswith("0x"):
                v = int(tok, 16)
            else:
                sys.exit(f"unparsed palette entry {tok!r} in {name}")
            entries.append(((v >> 16) & 255, (v >> 8) & 255, v & 255))
        if len(entries) != 16:
            sys.exit(f"{name}: expected 16 entries, got {len(entries)}")
        out[name] = entries
    return out


def gradient_palettes():
    pal = read("palettes")
    defs = {
        m.group(1): [int(x) for x in re.findall(r"\d+", re.sub(r"//.*", "", m.group(2)))]
        for m in re.finditer(
            r"const (?:byte|uint8_t)\s+(\w+)\[\]\s*PROGMEM\s*=\s*\{(.*?)\}\s*;", pal, re.S
        )
    }
    order_body = re.search(
        r"const (?:byte|uint8_t)\* const gGradientPalettes\[\] PROGMEM\s*=\s*\{(.*?)\}\s*;",
        pal,
        re.S,
    ).group(1)
    order = re.findall(r"^\s*(\w+)\s*,?\s*$", re.sub(r"//.*", "", order_body), re.M)
    return [defs[n] for n in order]


def from_16(entries):
    return [[i << 4, r, g, b] for i, (r, g, b) in enumerate(entries)]


def from_gradient(tcp):
    out, i = [], 0
    while True:
        idx, r, g, b = tcp[i : i + 4]
        out.append([idx, r, g, b])
        if idx >= 255:
            return out
        i += 4


def build_palx(count):
    fl, grad = fastled_palettes(), gradient_palettes()
    special = {
        1: ["r"] * 4,
        2: ["c1"],
        3: ["c1", "c1", "c2", "c2"],
        4: ["c3", "c2", "c1"],
        5: ["c1"] * 5 + ["c2"] * 5 + ["c3"] * 5 + ["c1"],
    }
    builtin = {
        0: "PartyColors",
        6: "PartyColors",
        7: "CloudColors",
        8: "LavaColors",
        9: "OceanColors",
        10: "ForestColors",
        11: "RainbowColors",
        12: "RainbowStripeColors",
    }

    def builtin_entries(base):
        for suffix in ("_p", "_gc22"):
            if base + suffix in fl:
                return fl[base + suffix]
        sys.exit(f"palette intégrée introuvable : {base}")

    palx = {}
    for i in range(count):
        if i in special:
            palx[str(i)] = special[i]
        elif i in builtin:
            palx[str(i)] = from_16(builtin_entries(builtin[i]))
        else:
            palx[str(i)] = from_gradient(grad[i - 13])
    return palx


def main(argv=None):
    global SRC

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag", nargs="?", default="v0.15.0",
                        help="tag WLED à télécharger (défaut v0.15.0)")
    parser.add_argument("--src", help="dossier de sources déjà présentes (ignore le tag)")
    parser.add_argument("--fastled", default="3.6.0", help="tag FastLED (défaut 3.6.0)")
    parser.add_argument("--out", default=str(pathlib.Path(__file__).resolve().parent.parent / "data" / "wled-data.json"))
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory(prefix="wled-src-") as scratch:
        if args.src:
            SRC = pathlib.Path(args.src)
            missing = [n for n in (*WLED_CORE, "palettes", "colors") if not (SRC / n).is_file()]
            if missing:
                sys.exit(f"fichiers manquants dans {SRC} : {', '.join(missing)}")
        else:
            SRC = pathlib.Path(scratch)
            legacy = exists(args.tag, WLED_LEGACY["palettes"])
            print(f"Téléchargement des sources WLED {args.tag} :")
            fetch(SRC, args.tag, "wled/WLED", WLED_LEGACY if legacy else WLED_MODERN)
            if legacy:
                print(f"Téléchargement des sources FastLED {args.fastled} :")
                fetch(SRC, args.fastled, "FastLED/FastLED", FASTLED_FILES)

        names, fxdata, registered = build_effects()
        palettes = build_palette_names()
        palx = build_palx(len(palettes))

    version = args.tag.lstrip("v") if not args.src else "inconnue"
    payload = {
        "version": version,
        "effects": names,
        "fxdata": fxdata,
        "palettes": palettes,
        "palx": palx,
        "palxItemsPerPage": 8,
    }
    destination = pathlib.Path(args.out)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, separators=(",", ":")))

    print(f"\nversion      : {version}")
    print(f"effets       : {len(names)} ({registered} enregistrés, {names.count('RSVD')} réservés)")
    print(f"palettes     : {len(palettes)}")
    print(f"exemples     : fx[0]={names[0]!r} fx[38]={names[38]!r} pal[50]={palettes[50]!r}")
    print(f"écrit        : {destination} ({destination.stat().st_size} octets)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

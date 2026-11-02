"""Fabrique app/icon.icns depuis le motif pixel de la mascotte."""

import pathlib
import struct
import subprocess
import sys
import tempfile
import zlib

MOTIF = [
    "........#####.......",
    "......########......",
    "......########......",
    ".....##..##..##.....",
    ".....##..##..##.....",
    ".....##..##..##.....",
    ".....##########.....",
    ".....##########.....",
    ".....##########.....",
    "##...##########...##",
    ".##..##########..##.",
    "..###..........###..",
    "...###........###...",
    "........#..#........",
    "........#..#........",
    "........#..#........",
    "........#..#........",
]
TAILLES = (16, 32, 64, 128, 256, 512, 1024)
FOND = (24, 24, 29)
FOND_BAS = (14, 14, 18)
CORPS = (255, 122, 24)
PATTES = (150, 150, 158)


def png(largeur, hauteur, pixels):
    lignes = bytearray()
    for y in range(hauteur):
        lignes.append(0)
        for x in range(largeur):
            lignes += bytes(pixels[y * largeur + x])
    def bloc(nom, corps):
        return (struct.pack(">I", len(corps)) + nom + corps
                + struct.pack(">I", zlib.crc32(nom + corps) & 0xFFFFFFFF))
    return (b"\x89PNG\r\n\x1a\n"
            + bloc(b"IHDR", struct.pack(">IIBBBBB", largeur, hauteur, 8, 6, 0, 0, 0))
            + bloc(b"IDAT", zlib.compress(bytes(lignes), 9))
            + bloc(b"IEND", b""))


def dessine(taille):
    marge = taille * 0.09
    rayon = taille * 0.225
    bord = taille - marge
    cols, rangs = len(MOTIF[0]), len(MOTIF)
    cellule = (bord - marge) * 0.80 / cols
    gauche = (taille - cols * cellule) / 2
    haut = (taille - rangs * cellule) / 2

    pixels = []
    for y in range(taille):
        for x in range(taille):
            px, py = x + 0.5, y + 0.5
            dedans = marge <= px <= bord and marge <= py <= bord
            if dedans:
                cx = min(max(px, marge + rayon), bord - rayon)
                cy = min(max(py, marge + rayon), bord - rayon)
                if (px - cx) ** 2 + (py - cy) ** 2 > rayon ** 2:
                    dedans = False
            if not dedans:
                pixels.append((0, 0, 0, 0))
                continue

            melange = (py - marge) / max(1.0, bord - marge)
            couleur = tuple(int(FOND[i] + (FOND_BAS[i] - FOND[i]) * melange) for i in range(3))

            col = int((px - gauche) // cellule)
            rang = int((py - haut) // cellule)
            if 0 <= rang < rangs and 0 <= col < cols and MOTIF[rang][col] == "#":
                corps = 5 <= col <= 14 and rang <= 10
                couleur = CORPS if corps else PATTES
            pixels.append(couleur + (255,))
    return png(taille, taille, pixels)


def main():
    racine = pathlib.Path(__file__).parent
    with tempfile.TemporaryDirectory() as scratch:
        jeu = pathlib.Path(scratch) / "icon.iconset"
        jeu.mkdir()
        for taille in TAILLES:
            données = dessine(taille)
            if taille <= 512:
                (jeu / f"icon_{taille}x{taille}.png").write_bytes(données)
            if taille >= 32:
                (jeu / f"icon_{taille // 2}x{taille // 2}@2x.png").write_bytes(données)
            print(f"  {taille}x{taille}")
        cible = racine / "icon.icns"
        subprocess.run(["iconutil", "-c", "icns", str(jeu), "-o", str(cible)], check=True)
        print(f"écrit : {cible} ({cible.stat().st_size // 1024} Ko)")


if __name__ == "__main__":
    sys.exit(main())

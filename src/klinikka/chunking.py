"""Markdown-dokumenttien pilkkominen otsikoiden mukaan.

Jokainen "## "-osio on oma palansa, ja palaan liitetään dokumentin pääotsikko.
Näin haettu pala on ymmärrettävä myös yksinään ("Hinnasto > Laboratorio")
ja lähdeviite osoittaa tarkasti oikeaan kohtaan.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Chunk:
    id: str
    source: str  # tiedoston nimi, esim. "04_hinnasto.md"
    title: str  # dokumentin pääotsikko
    section: str  # osion otsikko, tai tyhjä johdannolle
    text: str  # upotettava ja mallille näytettävä teksti

    @property
    def label(self) -> str:
        return f"{self.title} > {self.section}" if self.section else self.title


def chunk_markdown(source: str, markdown: str) -> list[Chunk]:
    lines = markdown.strip().splitlines()
    if not lines or not lines[0].startswith("# "):
        raise ValueError(f"{source}: dokumentin pitää alkaa '# '-otsikolla")

    title = lines[0][2:].strip()
    sections: list[tuple[str, list[str]]] = [("", [])]
    for line in lines[1:]:
        if line.startswith("## "):
            sections.append((line[3:].strip(), []))
        else:
            sections[-1][1].append(line)

    chunks: list[Chunk] = []
    for section, body_lines in sections:
        body = "\n".join(body_lines).strip()
        if not body:
            continue
        heading = f"# {title}" + (f"\n## {section}" if section else "")
        chunks.append(
            Chunk(
                id=f"{source}#{len(chunks)}",
                source=source,
                title=title,
                section=section,
                text=f"{heading}\n{body}",
            )
        )
    return chunks


def load_chunks(directory: Path) -> list[Chunk]:
    paths = sorted(directory.glob("*.md"))
    if not paths:
        raise FileNotFoundError(f"Tietopohjasta ei löytynyt yhtään .md-tiedostoa: {directory}")
    chunks: list[Chunk] = []
    for path in paths:
        chunks.extend(chunk_markdown(path.name, path.read_text(encoding="utf-8")))
    return chunks

"""Aineiston perustarkistukset: ajetaan CI:ssä ilman API-avaimia."""

from klinikka.config import KNOWLEDGE_BASE_DIR


def test_knowledge_base_exists_and_has_documents():
    docs = sorted(KNOWLEDGE_BASE_DIR.glob("*.md"))
    assert len(docs) >= 10, "Aineistossa pitäisi olla vähintään 10 dokumenttia"


def test_every_document_has_title_and_body():
    for path in KNOWLEDGE_BASE_DIR.glob("*.md"):
        text = path.read_text(encoding="utf-8").strip()
        assert text.startswith("# "), f"{path.name}: dokumentin pitää alkaa otsikolla"
        assert len(text) > 200, f"{path.name}: dokumentti on liian lyhyt"


def test_no_real_personal_identity_codes_in_data():
    """Aineisto on synteettistä: varmistetaan, ettei mukaan ole lipsahtanut henkilötunnuksia."""
    import re

    hetu = re.compile(r"\b\d{6}[-+AaBbCcDdEeFfXxYyWwVvUu]\d{3}[0-9A-Ya-y]\b")
    for path in KNOWLEDGE_BASE_DIR.glob("*.md"):
        assert not hetu.search(path.read_text(encoding="utf-8")), path.name

from src.utils.markdown_parser import parse_markdown_chunks


def test_parse_markdown_chunks_with_titles():
    markdown = "# Title\n\nSome paragraph text.\n\n## Subtitle\n- item 1\n- item 2\n"
    chunks = parse_markdown_chunks(markdown, chunk_type=True)

    assert len(chunks) == 4
    assert chunks[0].text == "Title"
    assert chunks[0].type == "title"
    assert chunks[1].text == "Some paragraph text."
    assert chunks[1].type is None
    assert chunks[2].text == "Subtitle"
    assert chunks[2].type == "title"
    assert chunks[3].text == "- item 1\n- item 2"
    assert chunks[3].type is None


def test_parse_markdown_chunks_without_headings():
    markdown = "Single paragraph without headings."
    chunks = parse_markdown_chunks(markdown, chunk_type=False)

    assert len(chunks) == 1
    assert chunks[0].text == markdown
    assert chunks[0].page_number == 1

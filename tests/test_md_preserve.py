import pytest

from core.md_extractor import MdBlock
from exporters.md_preserve import write_md_output


def test_write_md_output_raises_when_translation_missing(tmp_path):
    blocks = [
        MdBlock(
            index=1,
            block_type="paragraph",
            content="Original text",
            text="Original text",
            translatable=True,
        )
    ]

    output_path = tmp_path / "out.md"

    with pytest.raises(RuntimeError, match="缺少译文块"):
        write_md_output(blocks, {}, str(output_path))

    assert not output_path.exists()

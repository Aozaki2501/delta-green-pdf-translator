"""Named high-fidelity typeset profiles."""

from __future__ import annotations

from dataclasses import dataclass

from core.translator import Translator
from core.typeset_models import TypesetConfig


@dataclass(frozen=True)
class TypesetProfile:
    id: str
    label: str
    source_language: str
    system_prompt: str
    font_family: str
    heading_font_family: str
    body_font_size_pt: float
    min_body_font_size_pt: float
    line_height: float
    column_gap_pt: float
    title_color: str
    subtitle_color: str
    accent_heading_colors: tuple[str, ...]
    body_color: str
    display_font_size_pt: float
    section_font_size_pt: float
    accent_font_size_pt: float
    subsection_font_size_pt: float
    running_header_font_size_pt: float
    table_font_size_pt: float

    def build_config(
        self,
        *,
        document_title: str | None,
        layout_hints_path: str | None,
        font_family: str | None = None,
    ) -> TypesetConfig:
        return TypesetConfig(
            profile_id=self.id,
            source_language=self.source_language,
            document_title=document_title,
            font_family=(font_family or self.font_family).strip(),
            heading_font_family=self.heading_font_family,
            body_font_size_pt=self.body_font_size_pt,
            min_body_font_size_pt=self.min_body_font_size_pt,
            line_height=self.line_height,
            column_gap_pt=self.column_gap_pt,
            title_color=self.title_color,
            subtitle_color=self.subtitle_color,
            accent_heading_colors=self.accent_heading_colors,
            body_color=self.body_color,
            display_font_size_pt=self.display_font_size_pt,
            section_font_size_pt=self.section_font_size_pt,
            accent_font_size_pt=self.accent_font_size_pt,
            subsection_font_size_pt=self.subsection_font_size_pt,
            running_header_font_size_pt=self.running_header_font_size_pt,
            table_font_size_pt=self.table_font_size_pt,
            layout_hints_path=layout_hints_path,
        )


_DG_PROMPT = Translator.SYSTEM_PROMPT

_KULT_PROMPT = """You are a professional TRPG translator working on KULT: Divinity Lost material.

Translate the source from Swedish to Simplified Chinese. Follow the glossary
strictly. Translate Swedish common nouns, rules terms, scenario titles, and
word fragments; preserve only actual proper names, dice notation, and explicit
game abbreviations. Never retain soft hyphens or source line-break hyphenation.
When source text contains <strong> or <em>, preserve exactly those tags around
the corresponding translated emphasis and output no other HTML tags.
Preserve all [BLOCK id] marker lines exactly. Return one translated block for
every source block and no text outside those markers. Do not translate
standalone page numbers, running headers, footers, or decorative-only symbols.
Keep the Chinese concise, literary, and suitable for dark contemporary horror.
Do not add explanations or rewrite rules."""


_PROFILES = {
    "delta_green": TypesetProfile(
        id="delta_green", label="Delta Green（默认）", source_language="English",
        system_prompt=_DG_PROMPT, font_family="DG Fandol Song",
        heading_font_family="DG Lanting Kanhei", body_font_size_pt=10.5,
        min_body_font_size_pt=10.0, line_height=1.45, column_gap_pt=31.0,
        title_color="#231f20", subtitle_color="#dc2527",
        accent_heading_colors=("#ed1c24", "#dc2527", "#eb4f24"), body_color="#231f20",
        display_font_size_pt=30.0, section_font_size_pt=20.0,
        accent_font_size_pt=15.0, subsection_font_size_pt=13.0,
        running_header_font_size_pt=11.0, table_font_size_pt=9.0,
    ),
    "kult": TypesetProfile(
        id="kult", label="KULT（忠实原版）", source_language="Swedish",
        system_prompt=_KULT_PROMPT, font_family="DG Fandol Song",
        heading_font_family="DG Lanting Kanhei", body_font_size_pt=7.5,
        min_body_font_size_pt=7.5, line_height=1.30, column_gap_pt=22.0,
        title_color="#231f20", subtitle_color="#b8282f",
        accent_heading_colors=("#b8282f",), body_color="#231f20",
        display_font_size_pt=26.0, section_font_size_pt=17.0,
        accent_font_size_pt=13.0, subsection_font_size_pt=11.0,
        running_header_font_size_pt=8.5, table_font_size_pt=8.0,
    ),
}


def list_typeset_profiles() -> tuple[TypesetProfile, ...]:
    return tuple(_PROFILES.values())


def get_typeset_profile(profile_id: str) -> TypesetProfile:
    try:
        return _PROFILES[profile_id]
    except KeyError as exc:
        allowed = ", ".join(_PROFILES)
        raise ValueError(f"未知高保真排版配置：{profile_id}。可选：{allowed}") from exc

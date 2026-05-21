"""Additional classified-workstation visual polish for the Streamlit UI."""

from __future__ import annotations

import streamlit as st


def render_workstation_effects(reduced_motion: bool = False) -> None:
    reduced_motion_css = """
    .stApp::after,
    .boot-screen,
    .classified-hero,
    .section-card,
    .intel-tile,
    .dossier-card.loaded::after,
    .status-flow::before,
    .status-step.active,
    .system-log-line,
    .archive-stamp,
    div[data-testid="stMetric"]::after,
    div[data-testid="stAlert"]::before,
    div[data-testid="stExpander"] details[open] > div,
    .stDownloadButton > button::before {
        animation: none !important;
    }
    """ if reduced_motion else ""

    css = """
<style>
    @keyframes dg-file-scan {
        0% { transform: translateY(-100%); opacity: 0; }
        12% { opacity: 1; }
        88% { opacity: 1; }
        100% { transform: translateY(260%); opacity: 0; }
    }

    @keyframes dg-log-line {
        from { opacity: 0; transform: translateX(-8px); }
        to { opacity: 1; transform: translateX(0); }
    }

    @keyframes dg-stamp {
        0% { opacity: 0; transform: rotate(-9deg) scale(1.25); filter: blur(2px); }
        55% { opacity: 1; transform: rotate(-9deg) scale(0.96); filter: blur(0); }
        100% { opacity: 0.82; transform: rotate(-9deg) scale(1); }
    }

    @keyframes dg-step-pulse {
        0%, 100% { box-shadow: 0 0 0 rgba(82, 255, 145, 0); }
        50% { box-shadow: 0 0 18px rgba(82, 255, 145, 0.32); }
    }

    @keyframes dg-status-sweep {
        0% { transform: translateX(-18%); opacity: 0; }
        20% { opacity: 0.7; }
        100% { transform: translateX(118%); opacity: 0; }
    }

    @keyframes dg-alert-ping {
        0% { opacity: 0; transform: translateX(-100%); }
        18% { opacity: 0.95; }
        100% { opacity: 0; transform: translateX(220%); }
    }

    @keyframes dg-metric-sweep {
        0% { transform: translateX(-130%); opacity: 0; }
        30% { opacity: 0.55; }
        100% { transform: translateX(140%); opacity: 0; }
    }

    @keyframes dg-drawer-open {
        from { opacity: 0; transform: translateY(-8px); }
        to { opacity: 1; transform: translateY(0); }
    }

    @keyframes dg-transfer-scan {
        0% { transform: translateX(-120%); opacity: 0; }
        35% { opacity: 0.85; }
        100% { transform: translateX(120%); opacity: 0; }
    }

    .dossier-card {
        position: relative;
        overflow: hidden;
        border: 1px solid var(--line-hot);
        background:
            linear-gradient(90deg, rgba(82, 255, 145, 0.08), transparent),
            rgba(4, 13, 7, 0.84);
        padding: 16px 18px;
        margin: 14px 0;
    }

    .dossier-card.loaded::after {
        content: "";
        position: absolute;
        left: 0;
        right: 0;
        top: 0;
        height: 42%;
        pointer-events: none;
        background: linear-gradient(180deg, transparent, rgba(82, 255, 145, 0.22), transparent);
        animation: dg-file-scan 2.4s ease-in-out infinite;
    }

    .dossier-kicker {
        color: var(--muted);
        font-size: 0.74rem;
        text-transform: uppercase;
    }

    .dossier-id {
        color: var(--green);
        font: 1.55rem "Courier Prime", "Consolas", monospace;
        margin-top: 5px;
    }

    .dossier-meta {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 8px;
        margin-top: 12px;
    }

    .dossier-meta span {
        border: 1px solid var(--line);
        padding: 7px 9px;
        color: var(--green-soft);
        background: rgba(3, 9, 5, 0.68);
        font-size: 0.82rem;
    }

    .status-flow {
        position: relative;
        overflow: hidden;
        display: grid;
        grid-template-columns: repeat(6, minmax(0, 1fr));
        gap: 8px;
        margin: 14px 0;
    }

    .status-flow::before {
        content: "";
        position: absolute;
        left: 0;
        right: 0;
        top: 50%;
        height: 1px;
        pointer-events: none;
        background: linear-gradient(90deg, transparent, rgba(82, 255, 145, 0.74), transparent);
        animation: dg-status-sweep 2.8s ease-in-out infinite;
    }

    .status-step {
        position: relative;
        z-index: 1;
        border: 1px solid var(--line);
        background: rgba(3, 9, 5, 0.72);
        color: var(--muted);
        padding: 9px 10px;
        font-size: 0.82rem;
        text-align: center;
    }

    .status-step.done {
        border-color: var(--line-hot);
        color: var(--green-soft);
    }

    .status-step.active {
        border-color: var(--green);
        color: var(--green);
        animation: dg-step-pulse 1.6s ease-in-out infinite;
    }

    .status-step.failed {
        border-color: var(--red);
        color: var(--red);
    }

    .system-log {
        border: 1px solid var(--line);
        background: rgba(1, 5, 3, 0.82);
        padding: 12px 14px;
        margin: 12px 0;
        font-family: "Courier Prime", "Consolas", monospace;
    }

    .system-log-line {
        color: var(--green-soft);
        font-size: 0.84rem;
        line-height: 1.55;
        animation: dg-log-line 360ms ease-out both;
    }

    .system-log-line:nth-child(2) { animation-delay: 80ms; }
    .system-log-line:nth-child(3) { animation-delay: 160ms; }
    .system-log-line:nth-child(4) { animation-delay: 240ms; }
    .system-log-line:nth-child(5) { animation-delay: 320ms; }

    .system-log-line.warn {
        color: var(--amber);
    }

    .system-log-line.fail {
        color: var(--red);
    }

    .archive-stamp {
        display: inline-block;
        border: 2px solid var(--red);
        color: var(--red);
        padding: 7px 18px;
        margin: 8px 0 4px;
        font: 1.35rem "SimHei", "Microsoft YaHei", sans-serif;
        letter-spacing: 0;
        transform: rotate(-9deg);
        animation: dg-stamp 620ms ease-out both;
    }

    .audit-grid {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 8px;
        margin: 10px 0;
    }

    .audit-cell {
        position: relative;
        overflow: hidden;
        border: 1px solid var(--line);
        background: rgba(3, 9, 5, 0.72);
        padding: 8px 10px;
    }

    .audit-cell::after,
    div[data-testid="stMetric"]::after {
        content: "";
        position: absolute;
        inset: 0;
        pointer-events: none;
        background: linear-gradient(90deg, transparent, rgba(82, 255, 145, 0.14), transparent);
        animation: dg-metric-sweep 3.8s ease-in-out infinite;
    }

    .audit-label {
        color: var(--muted);
        font-size: 0.72rem;
    }

    .audit-value {
        color: var(--green-soft);
        margin-top: 3px;
        font-size: 0.9rem;
    }

    .stDownloadButton > button {
        position: relative;
        overflow: hidden;
    }

    .stDownloadButton > button::before {
        content: "";
        position: absolute;
        inset: 0;
        pointer-events: none;
        background: linear-gradient(90deg, transparent, rgba(82, 255, 145, 0.36), transparent);
        transform: translateX(-120%);
    }

    .stDownloadButton > button:hover::before {
        animation: dg-transfer-scan 780ms ease-out;
    }

    .stDownloadButton > button:hover::after {
        content: "传输已授权";
        position: absolute;
        inset: auto 8px 4px auto;
        color: #031006;
        font-size: 0.68rem;
        opacity: 0.78;
    }

    div[data-testid="stMetric"] {
        position: relative;
        overflow: hidden;
    }

    div[data-testid="stAlert"] {
        position: relative;
        overflow: hidden;
        border-radius: 0 !important;
        border: 1px solid var(--line) !important;
        background: rgba(4, 12, 7, 0.92) !important;
        box-shadow: none !important;
    }

    div[data-testid="stAlert"] > div {
        background: transparent !important;
        color: var(--text) !important;
    }

    div[data-testid="stAlert"] [data-testid="stMarkdownContainer"],
    div[data-testid="stAlert"] [data-testid="stMarkdownContainer"] p {
        color: var(--text) !important;
    }

    div[data-testid="stAlert"] * {
        border-radius: 0 !important;
    }

    div[data-testid="stAlert"] svg {
        color: var(--green) !important;
        fill: var(--green) !important;
    }

    div[data-testid="stAlert"]::before {
        content: "";
        position: absolute;
        left: 0;
        top: 0;
        bottom: 0;
        width: 4px;
        pointer-events: none;
        background: var(--green);
    }

    div[data-testid="stAlert"]::after {
        content: "";
        position: absolute;
        inset: 0 auto 0 4px;
        width: 22%;
        pointer-events: none;
        background: rgba(82, 255, 145, 0.08);
        animation: dg-alert-ping 920ms ease-out 1;
    }

    div[data-testid="stExpander"] details[open] > div {
        animation: dg-drawer-open 260ms ease-out both;
    }

    @media (max-width: 860px) {
        .dossier-meta,
        .status-flow,
        .audit-grid {
            grid-template-columns: 1fr 1fr;
        }
    }

    __REDUCED_MOTION_CSS__
</style>
        """.replace("__REDUCED_MOTION_CSS__", reduced_motion_css)
    st.markdown(
        css,
        unsafe_allow_html=True,
    )

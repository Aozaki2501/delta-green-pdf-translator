"""Additional classified-workstation visual polish for the Streamlit UI."""

from __future__ import annotations

import streamlit as st


def render_app_theme() -> None:
    st.markdown(APP_THEME_CSS, unsafe_allow_html=True)


APP_THEME_CSS = r'''
<style>
    :root {
        --bg: #030604;
        --panel: rgba(5, 13, 8, 0.86);
        --panel-strong: rgba(8, 22, 13, 0.94);
        --line: rgba(69, 255, 129, 0.24);
        --line-hot: rgba(81, 255, 137, 0.72);
        --green: #52ff91;
        --green-soft: #9dffc1;
        --amber: #ffd166;
        --red: #ff4d4d;
        --text: #c8d8c9;
        --muted: #7f9b85;
        --shadow: rgba(82, 255, 145, 0.18);
    }

    .stApp, .stAppHeader {
        background:
            linear-gradient(rgba(82, 255, 145, 0.035) 1px, transparent 1px),
            linear-gradient(90deg, rgba(82, 255, 145, 0.025) 1px, transparent 1px),
            radial-gradient(circle at 12% 8%, rgba(82, 255, 145, 0.12), transparent 30%),
            radial-gradient(circle at 88% 28%, rgba(255, 77, 77, 0.08), transparent 26%),
            var(--bg) !important;
        background-size: 28px 28px, 28px 28px, auto, auto, auto !important;
        color: var(--text) !important;
        font-family: "SimHei", "Microsoft YaHei", "Noto Sans SC", sans-serif !important;
    }

    #MainMenu,
    footer,
    header[data-testid="stHeader"],
    [data-testid="stToolbar"],
    [data-testid="stDecoration"],
    .stDeployButton {
        display: none !important;
        visibility: hidden !important;
    }

    .stApp::before {
        content: "";
        position: fixed;
        inset: 0;
        pointer-events: none;
        z-index: 9999;
        background:
            linear-gradient(rgba(255, 255, 255, 0.018) 50%, rgba(0, 0, 0, 0.12) 50%),
            linear-gradient(90deg, rgba(255, 0, 0, 0.018), rgba(0, 255, 64, 0.012), rgba(0, 96, 255, 0.018));
        background-size: 100% 4px, 6px 100%;
        mix-blend-mode: screen;
        opacity: 0.32;
    }

    .stApp::after {
        content: "";
        position: fixed;
        left: 0;
        right: 0;
        top: -20%;
        height: 18%;
        pointer-events: none;
        z-index: 9998;
        background: linear-gradient(180deg, transparent, rgba(82, 255, 145, 0.12), transparent);
        animation: dg-scan 6.5s linear infinite;
    }

    @keyframes dg-scan {
        0% { transform: translateY(-10vh); }
        100% { transform: translateY(130vh); }
    }

    @keyframes panel-in {
        from { opacity: 0; transform: translateY(14px); }
        to { opacity: 1; transform: translateY(0); }
    }

    @keyframes pulse-line {
        0%, 100% { box-shadow: 0 0 0 rgba(82, 255, 145, 0); }
        50% { box-shadow: 0 0 28px var(--shadow); }
    }

    @media (prefers-reduced-motion: reduce) {
        .stApp::after, .classified-hero, .section-card, .intel-tile, .launch-panel, .terminal-cursor, .radar-fill, .radar-step::before { animation: none !important; }
        .boot-screen { display: none !important; opacity: 0 !important; visibility: hidden !important; }
    }

    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, rgba(4, 12, 7, 0.98), rgba(2, 7, 4, 0.98)) !important;
        border-right: 1px solid var(--line) !important;
        box-shadow: 12px 0 36px rgba(0, 0, 0, 0.42);
    }

    h1, h2, h3, .hero-title {
        color: var(--green) !important;
        font-family: "SimHei", "Microsoft YaHei", "Noto Sans SC", sans-serif !important;
        letter-spacing: 0;
        font-weight: 900;
    }

    p, label, .stMarkdown {
        color: var(--text) !important;
        font-size: 0.95rem;
    }

    .block-container {
        max-width: 1220px;
        padding-top: 1.5rem;
        padding-bottom: 4rem;
    }

    .classified-hero {
        position: relative;
        overflow: hidden;
        border: 1px solid var(--line-hot);
        background:
            linear-gradient(120deg, rgba(82, 255, 145, 0.18), transparent 35%),
            linear-gradient(180deg, rgba(7, 28, 14, 0.94), rgba(3, 8, 5, 0.88));
        padding: 30px;
        margin-bottom: 18px;
        animation: panel-in 420ms ease-out, pulse-line 5s ease-in-out infinite;
    }

    .classified-hero::before {
        content: "绝密";
        position: absolute;
        right: -44px;
        top: 28px;
        transform: rotate(34deg);
        color: rgba(255, 77, 77, 0.24);
        border: 2px solid rgba(255, 77, 77, 0.24);
        padding: 6px 44px;
        font: 26px "SimHei", "Microsoft YaHei", sans-serif;
        letter-spacing: 0;
    }

    .hero-title {
        font-size: 3.25rem;
        line-height: 0.9;
        margin-bottom: 10px;
        text-shadow: 0 0 18px rgba(82, 255, 145, 0.34);
    }

    .hero-grid {
        position: relative;
        z-index: 1;
        display: grid;
        grid-template-columns: minmax(0, 1.25fr) minmax(280px, 0.75fr);
        gap: 24px;
        align-items: end;
    }

    .hero-seal {
        min-height: 176px;
        border: 1px solid rgba(82, 255, 145, 0.28);
        background:
            linear-gradient(135deg, rgba(82, 255, 145, 0.08), transparent 58%),
            repeating-linear-gradient(0deg, rgba(82, 255, 145, 0.05) 0 1px, transparent 1px 14px),
            rgba(1, 5, 3, 0.58);
        padding: 18px;
        display: grid;
        align-content: space-between;
    }

    .hero-seal-code {
        color: var(--muted);
        font-family: "Courier New", monospace;
        font-size: 0.78rem;
        line-height: 1.7;
    }

    .hero-seal-mark {
        color: rgba(255, 77, 77, 0.78);
        border: 1px solid rgba(255, 77, 77, 0.42);
        display: inline-block;
        width: fit-content;
        padding: 6px 12px;
        font-weight: 900;
        transform: rotate(-3deg);
    }

    .hero-subtitle {
        color: var(--green-soft);
        font-size: 0.96rem;
        line-height: 1.65;
    }

    .terminal-line {
        color: var(--muted);
        margin-top: 14px;
        font-size: 0.86rem;
    }

    .status-radar {
        width: min(520px, 100%);
        margin-top: 16px;
    }

    .radar-row {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        align-items: center;
    }

    .radar-label {
        color: var(--green-soft);
        font-family: "Courier New", monospace;
        font-weight: 700;
    }

    .radar-step {
        position: relative;
        border: 1px solid rgba(82, 255, 145, 0.24);
        background: rgba(2, 8, 4, 0.7);
        color: var(--muted);
        padding: 4px 8px 4px 18px;
        font-family: "Courier New", monospace;
        font-size: 0.72rem;
    }

    .radar-step::before {
        content: "";
        position: absolute;
        left: 7px;
        top: 50%;
        width: 5px;
        height: 5px;
        transform: translateY(-50%);
        background: var(--green);
        box-shadow: 0 0 10px rgba(82, 255, 145, 0.72);
        animation: radar-pulse 1.8s ease-in-out infinite;
    }

    .radar-step:nth-child(3)::before { animation-delay: 220ms; }
    .radar-step:nth-child(4)::before { animation-delay: 440ms; }

    .radar-track {
        height: 8px;
        margin-top: 10px;
        border: 1px solid rgba(82, 255, 145, 0.28);
        background:
            repeating-linear-gradient(90deg, rgba(82, 255, 145, 0.08) 0 8px, transparent 8px 16px),
            rgba(1, 7, 3, 0.82);
        overflow: hidden;
    }

    .radar-fill {
        display: block;
        height: 100%;
        width: 38%;
        background: linear-gradient(90deg, transparent, var(--green), var(--green-soft), transparent);
        box-shadow: 0 0 18px rgba(82, 255, 145, 0.54);
        animation: radar-sweep 2.6s ease-in-out infinite;
    }

    @keyframes radar-sweep {
        0% { transform: translateX(-105%); }
        48% { transform: translateX(84%); }
        100% { transform: translateX(180%); }
    }

    @keyframes radar-pulse {
        0%, 100% { opacity: 0.4; }
        50% { opacity: 1; }
    }

    .terminal-cursor {
        display: inline-block;
        width: 9px;
        height: 1.05em;
        margin-left: 4px;
        background: var(--green);
        vertical-align: -0.15em;
        animation: blink 1s steps(1) infinite;
    }

    @keyframes blink {
        50% { opacity: 0; }
    }

    .intel-grid {
        display: grid;
        grid-template-columns: 1.25fr 1fr 1fr;
        gap: 14px;
        margin-bottom: 20px;
    }

    .intel-tile, .section-card {
        border: 1px solid var(--line);
        background: var(--panel);
        box-shadow: 0 12px 30px rgba(0, 0, 0, 0.24);
        animation: panel-in 520ms ease-out both;
    }

    .intel-tile {
        min-height: 96px;
        padding: 18px;
        display: grid;
        align-content: space-between;
        background:
            linear-gradient(160deg, rgba(82, 255, 145, 0.09), transparent 54%),
            rgba(5, 13, 8, 0.86);
    }

    .intel-label {
        color: var(--muted);
        font-size: 0.72rem;
        text-transform: uppercase;
    }

    .intel-value {
        color: var(--green-soft);
        font: 1.5rem "SimHei", "Microsoft YaHei", sans-serif;
        margin-top: 2px;
    }

    .section-card {
        position: relative;
        padding: 24px;
        margin: 18px 0;
    }

    .section-card::before {
        content: "";
        position: absolute;
        left: 0;
        top: 0;
        width: 4px;
        height: 100%;
        background: linear-gradient(var(--green), transparent);
    }

    .task-dock {
        border-color: rgba(82, 255, 145, 0.42);
        background:
            linear-gradient(135deg, rgba(82, 255, 145, 0.1), transparent 34%),
            linear-gradient(180deg, rgba(6, 18, 10, 0.92), rgba(3, 9, 5, 0.88));
    }

    .section-heading {
        display: flex;
        justify-content: space-between;
        gap: 16px;
        align-items: flex-start;
        margin-bottom: 18px;
    }

    .section-kicker,
    .launch-kicker,
    .sidebar-kicker {
        color: var(--muted);
        font-family: "Courier New", monospace;
        font-size: 0.74rem;
        text-transform: uppercase;
    }

    .section-title,
    .launch-title {
        color: var(--green);
        font-size: 1.55rem;
        font-weight: 900;
        margin-top: 4px;
    }

    .section-note {
        color: var(--green-soft);
        max-width: 520px;
        line-height: 1.6;
        font-size: 0.92rem;
    }

    .launch-panel {
        display: grid;
        grid-template-columns: minmax(240px, 0.75fr) minmax(0, 1.25fr);
        gap: 18px;
        align-items: center;
        border: 1px solid rgba(82, 255, 145, 0.46);
        background:
            linear-gradient(90deg, rgba(82, 255, 145, 0.14), transparent 44%),
            rgba(4, 13, 7, 0.92);
        padding: 20px 22px;
        margin: 18px 0 10px;
        box-shadow: 0 18px 42px rgba(0, 0, 0, 0.34);
        animation: panel-in 520ms ease-out both;
    }

    .launch-status {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 10px;
    }

    .launch-status span {
        min-height: 46px;
        display: flex;
        align-items: center;
        border: 1px solid var(--line);
        background: rgba(2, 8, 4, 0.7);
        color: var(--green-soft);
        padding: 9px 11px;
        font-size: 0.86rem;
    }

    div[data-testid="stFileUploader"] {
        background: rgba(5, 18, 9, 0.7) !important;
        border: 1px dashed var(--line-hot) !important;
        border-radius: 0 !important;
        padding: 16px;
        transition: border-color 180ms ease, box-shadow 180ms ease, transform 180ms ease;
    }

    div[data-testid="stFileUploader"]:hover {
        border-color: var(--green) !important;
        box-shadow: 0 0 28px rgba(82, 255, 145, 0.16);
        transform: translateY(-1px);
    }

    .stTextInput input,
    .stNumberInput input,
    .stSelectbox div[data-baseweb="select"],
    .stMultiSelect div[data-baseweb="select"] {
        background-color: rgba(3, 9, 5, 0.95) !important;
        border: 1px solid var(--line) !important;
        border-radius: 0 !important;
        color: var(--green-soft) !important;
        font-family: "Courier Prime", monospace !important;
    }

    .stMultiSelect [data-baseweb="tag"] {
        background:
            linear-gradient(180deg, rgba(6, 24, 11, 0.96), rgba(1, 8, 4, 0.96)) !important;
        border: 1px solid rgba(82, 255, 145, 0.48) !important;
        border-radius: 0 !important;
        color: var(--green-soft) !important;
        box-shadow: inset 0 0 0 1px rgba(157, 255, 193, 0.06);
        min-height: 28px;
    }

    .stMultiSelect [data-baseweb="tag"] span {
        color: var(--green-soft) !important;
        border-radius: 0 !important;
        font-family: "Courier Prime", "Consolas", monospace !important;
        font-size: 0.82rem !important;
    }

    .stMultiSelect [data-baseweb="tag"] span:last-child {
        border-left: 1px solid rgba(255, 77, 77, 0.32) !important;
        background: rgba(255, 77, 77, 0.1) !important;
        color: var(--red) !important;
    }

    div[data-testid="stFileUploader"] button {
        font-size: 0 !important;
    }

    div[data-testid="stFileUploader"] button * {
        font-size: 0 !important;
        line-height: 0 !important;
    }

    div[data-testid="stFileUploader"] button::after {
        content: "导入";
        font-size: 0.95rem;
        line-height: 1;
    }

    div[data-testid="stFileUploader"] small {
        font-size: 0 !important;
    }

    .stTextInput input:focus,
    .stNumberInput input:focus {
        border-color: var(--green) !important;
        box-shadow: 0 0 0 1px rgba(82, 255, 145, 0.35) !important;
    }

    .stButton>button {
        position: relative;
        overflow: hidden;
        background: linear-gradient(90deg, rgba(82, 255, 145, 0.08), rgba(82, 255, 145, 0.02)) !important;
        color: var(--green) !important;
        border: 1px solid var(--line-hot) !important;
        border-radius: 3px !important;
        min-height: 52px;
        font-weight: bold;
        letter-spacing: 0;
        transition: all 0.18s ease;
        text-transform: uppercase;
    }

    .stButton>button:hover {
        background: var(--green) !important;
        color: #031006 !important;
        box-shadow: 0 0 26px rgba(82, 255, 145, 0.34);
    }

    .stButton>button[kind="primary"] {
        background:
            linear-gradient(180deg, rgba(6, 24, 11, 0.98), rgba(1, 9, 4, 0.98)) !important;
        color: var(--green-soft) !important;
        border: 1px solid var(--green) !important;
        box-shadow:
            inset 0 0 0 1px rgba(157, 255, 193, 0.1),
            0 0 24px rgba(82, 255, 145, 0.22);
        font-size: 1.04rem;
        text-shadow: 0 0 12px rgba(82, 255, 145, 0.52);
    }

    .stButton>button[kind="primary"]:hover {
        background:
            linear-gradient(180deg, rgba(16, 48, 25, 0.98), rgba(4, 17, 8, 0.98)) !important;
        color: #ffffff !important;
        border-color: var(--green-soft) !important;
        box-shadow:
            inset 0 0 0 1px rgba(157, 255, 193, 0.18),
            0 0 34px rgba(82, 255, 145, 0.34);
    }

    .stButton>button[kind="primary"] p {
        color: var(--green-soft) !important;
        font-weight: 900 !important;
        text-shadow: 0 0 12px rgba(82, 255, 145, 0.52);
    }

    .stButton>button[kind="primary"]:hover p {
        color: #ffffff !important;
    }

    .stProgress > div > div > div {
        background-color: var(--green) !important;
        box-shadow: 0 0 16px rgba(82, 255, 145, 0.52);
    }

    div[data-testid="stMetric"] {
        background: var(--panel-strong) !important;
        border: 1px solid var(--line) !important;
        border-radius: 0 !important;
        padding: 15px;
    }

    div[data-testid="stMetricValue"] {
        color: var(--green) !important;
    }

    [data-testid="stExpander"] {
        background: rgba(4, 12, 7, 0.78) !important;
        border: 1px solid var(--line) !important;
        border-radius: 3px !important;
    }

    section[data-testid="stSidebar"] [data-testid="stExpander"] {
        background: rgba(2, 8, 4, 0.84) !important;
        border-color: rgba(82, 255, 145, 0.22) !important;
    }

    section[data-testid="stSidebar"] .block-container,
    section[data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
        gap: 0.65rem;
    }

    section[data-testid="stSidebar"] label {
        color: var(--green-soft) !important;
        font-size: 0.82rem !important;
    }

    .sidebar-console {
        border: 1px solid rgba(82, 255, 145, 0.38);
        background:
            linear-gradient(135deg, rgba(82, 255, 145, 0.11), transparent 60%),
            rgba(1, 6, 3, 0.72);
        padding: 15px;
        margin: 4px 0 12px;
    }

    .sidebar-title {
        color: var(--green);
        font-size: 1.15rem;
        font-weight: 900;
        margin-top: 3px;
    }

    .sidebar-note {
        color: var(--muted);
        font-size: 0.82rem;
        line-height: 1.5;
        margin-top: 8px;
    }

    .sidebar-help {
        display: grid;
        grid-template-columns: 28px minmax(0, 1fr);
        gap: 10px;
        align-items: start;
        border-top: 1px solid rgba(82, 255, 145, 0.18);
        margin-top: 14px;
        padding-top: 12px;
        color: var(--muted);
    }

    .sidebar-help-badge {
        width: 24px;
        height: 24px;
        display: grid;
        place-items: center;
        border: 1px solid rgba(82, 255, 145, 0.46);
        color: var(--green-soft);
        font-family: "Courier New", monospace;
        font-weight: 900;
    }

    .sidebar-help-title {
        color: var(--green-soft);
        font-size: 0.82rem;
        font-weight: 800;
        margin-bottom: 4px;
    }

    .sidebar-help-copy {
        color: var(--muted);
        font-size: 0.76rem;
        line-height: 1.45;
    }

    .stAlert {
        border-radius: 0 !important;
    }

    textarea {
        background: rgba(2, 8, 4, 0.95) !important;
        color: var(--green-soft) !important;
        border: 1px solid var(--line) !important;
        font-family: "Courier Prime", monospace !important;
    }

    .boot-screen {
        position: fixed;
        inset: 0;
        z-index: 10000;
        pointer-events: none;
        display: grid;
        place-items: center;
        background:
            linear-gradient(rgba(82, 255, 145, 0.04) 1px, transparent 1px),
            linear-gradient(90deg, rgba(82, 255, 145, 0.035) 1px, transparent 1px),
            rgba(2, 5, 3, 0.88);
        background-size: 30px 30px;
        animation: boot-hide 1.55s ease forwards;
        contain: layout paint style;
        will-change: opacity;
    }

    .boot-panel {
        width: min(680px, calc(100vw - 44px));
        border: 1px solid var(--line-hot);
        background: rgba(3, 12, 6, 0.84);
        box-shadow: 0 0 52px rgba(82, 255, 145, 0.18);
        padding: 28px;
        font-family: "SimHei", "Microsoft YaHei", sans-serif;
    }

    .boot-title {
        color: var(--green);
        font-size: 2.2rem;
        font-weight: 900;
        letter-spacing: 0;
        margin-bottom: 14px;
    }

    .boot-lines {
        color: var(--green-soft);
        font-family: "Courier New", monospace;
        line-height: 1.8;
        font-size: 0.95rem;
    }

    .boot-bar {
        height: 8px;
        margin-top: 22px;
        border: 1px solid var(--line);
        background: rgba(82, 255, 145, 0.06);
        overflow: hidden;
    }

    .boot-bar::before {
        content: "";
        display: block;
        height: 100%;
        width: 0;
        background: var(--green);
        box-shadow: 0 0 18px rgba(82, 255, 145, 0.65);
        animation: boot-load 0.92s steps(18) forwards;
    }

    .boot-stamp {
        margin-top: 16px;
        color: rgba(255, 77, 77, 0.82);
        border: 1px solid rgba(255, 77, 77, 0.56);
        display: inline-block;
        padding: 4px 10px;
        transform: rotate(-2deg);
        font-weight: 900;
    }

    @keyframes boot-load {
        to { width: 100%; }
    }

    @keyframes boot-hide {
        0%, 46% { opacity: 1; visibility: visible; }
        100% { opacity: 0; visibility: hidden; }
    }

    @media (max-width: 760px) {
        .hero-grid,
        .launch-panel,
        .launch-status {
            grid-template-columns: 1fr;
        }
        .intel-grid {
            grid-template-columns: 1fr;
        }
        .hero-title {
            font-size: 2.2rem;
        }
    }
</style>
'''

def render_workstation_effects(reduced_motion: bool = False) -> None:
    reduced_motion_css = """
    .stApp::after,
    .boot-screen,
    .classified-hero,
    .section-card,
    .intel-tile,
    .launch-panel,
    .terminal-cursor,
    .radar-fill,
    .radar-step::before,
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

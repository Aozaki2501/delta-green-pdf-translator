import subprocess
import sys


def run_help(script_path):
    return subprocess.run(
        [sys.executable, script_path, "--help"],
        check=False,
        capture_output=True,
        text=True,
    )


def test_pdf_block_report_help_runs():
    result = run_help("tools/pdf_block_report.py")

    assert result.returncode == 0
    assert "--pages" in result.stdout


def test_card_detection_report_help_runs():
    result = run_help("tools/card_detection_report.py")

    assert result.returncode == 0
    assert "--pages" in result.stdout

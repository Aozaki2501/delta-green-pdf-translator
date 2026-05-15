# One-Click Start

For Windows users:

1. Install Python 3.10 or newer once.
2. Unzip or clone this project.
3. Double-click `start_web.bat`.

The first launch creates `.venv`, installs the packages in `requirements.txt`, and starts the web UI at:

```text
http://localhost:8501
```

After the first launch, double-clicking `start_web.bat` starts much faster because the local environment is reused.

Do not commit `.venv`, `uploads`, or `output`; they are local runtime folders.


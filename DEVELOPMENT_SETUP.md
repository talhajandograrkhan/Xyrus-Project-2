# Development setup

This project is designed to run on Python 3.11 to 3.13. For local development, Python 3.11.x is the safest default and matches the project’s tested minimum.

## Supported runtime

- Recommended: Python 3.11.x
- Supported: Python 3.11, 3.12, 3.13
- Not recommended: Python 3.10 or older

Check your interpreter:

```bash
python3 --version
python3.11 --version
```

If you are using a virtual environment, create it with Python 3.11 before installing dependencies.

## 1) Clone and install dependencies

From the project root:

```bash
cd /path/to/Mark-LV-main
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

You can also run the project’s setup helper:

```bash
python setup.py
```

That helper installs the OS-specific dependency set and triggers Playwright browser installation when possible.

## 2) Configure API access

This project reads the Gemini API key from `config/api_keys.json`.

Create or update the file with this shape:

```json
{
  "gemini_api_key": "YOUR_GEMINI_API_KEY_HERE"
}
```

You can also set the assistant name / user name later from the app UI.

### Required environment variables

There are no mandatory environment variables required by the app itself.

The project uses the local config file instead of environment-only secrets. For local development, the practical requirement is simply:

- a working Python 3.11+ environment
- a valid Gemini API key in `config/api_keys.json`

### Recommended local environment variables

These are optional and mainly useful for local tooling:

```bash
export PYTHONPATH="."
```

Use this if you are running test or module-based commands from the repo root and want Python to resolve imports consistently.

## 3) Start the app

From the project root:

```bash
python3.11 main.py
```

Or, when inside the activated virtual environment:

```bash
python main.py
```

On first launch, the app will expect the Gemini key and then open the assistant UI.

## 4) Optional feature installs

These features are optional and not always needed for the basic app to run.

### Wake word ("Hey Jarvis")

```bash
pip install openwakeword
```

Then enable it from the app UI under settings.

### Browser automation browsers

```bash
python -m playwright install chromium firefox
```

Optional Safari browser for macOS automation:

```bash
python -m playwright install webkit
```

### Extra plugin dependencies

Some plugin integrations are optional and are already listed in `requirements.txt`.

If you want to install them explicitly:

```bash
pip install google-api-python-client google-auth-oauthlib tinytuya paho-mqtt openpyxl youtube-transcript-api pygetwindow
```

### Heavy optional media/document tools

These are not required by default because they are large or specialized:

```bash
pip install pandas pydub mediapipe
```

For audio conversion with `pydub`, make sure `ffmpeg` is installed on your OS and available on `PATH`.

## 5) Typical developer workflow

```bash
git clone <repo>
cd Mark-LV-main
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pytest -q
python main.py
```

## 6) Troubleshooting

### Import errors while testing

Run from the repo root and ensure the package path is set:

```bash
export PYTHONPATH="."
python -m pytest -q
```

### Qt compatibility on macOS

The project supports macOS 12.x only with PyQt6 versions below 6.8. The app checks this at runtime and prints a helpful message if needed.

### Missing Playwright browsers

If browser automation is failing, run:

```bash
python -m playwright install chromium firefox
```

### Wake word not working

Install the extra package and re-enable the setting from the app UI:

```bash
pip install openwakeword
```

## 7) Safe defaults

For a clean developer setup:

- use Python 3.11.x
- keep the app in a virtual environment
- store the API key in `config/api_keys.json`
- install optional packages only when you need that feature
- keep the project root on `PYTHONPATH` when testing manually

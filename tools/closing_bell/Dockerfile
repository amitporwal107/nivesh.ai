# Closing Bell tools image: headless Chromium (Playwright) for the graphics and the desk recorder, plus edge-tts
# for the narration. Built on the app VM by pipeline.py the first time it is missing:
#   docker build -t nivesh/closing-bell-tools:1 tools/closing_bell
FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy
RUN pip install --no-cache-dir playwright==1.49.0 edge-tts==7.3.1
WORKDIR /app

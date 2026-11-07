---
title: BizAssist compatibility forwarder
sdk: docker
app_port: 7860
---

Deploy this directory as the existing Hugging Face Space to keep installed
desktop clients working while they upgrade. It forwards requests, streaming
responses and uploads to the Cloud Run billing API. Authentication and CORS
remain enforced by that API. `/__forwarder` identifies the compatibility service;
`/health` checks Cloud Run. No secrets or local database belong in this image.

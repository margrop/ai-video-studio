# Kling provider

This directory is reserved for a server-side Kling adapter. Implement the
provider-neutral `VideoProvider` contract in `packages/providers/base.py` and
keep credentials, model selection, retries and response parsing inside this
directory.

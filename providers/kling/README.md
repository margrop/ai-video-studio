# Kling provider

`KlingVideoProvider` is a transport-compatible scaffold around the generic
submit/poll/download adapter. It is not an assertion that the current Kling
API uses those paths. Verify the vendor contract before enabling it and keep
credentials, model selection, retries and response parsing inside this
directory.

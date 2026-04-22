# WhatsApp webhook test fixtures

The JSON files in this directory are verbatim copies from the
[`pywa`](https://github.com/david-lev/pywa) test suite
(`tests/data/updates/`) at commit `7f3bd60` (cloned into
`research/reference-implementations/pywa/`).

`pywa` is MIT-licensed. We use these fixtures unmodified as the
canonical inbound payload shapes Meta sends on the `/webhook`
endpoint — porting them lets us verify our `extract_message` parser
against the same shapes pywa itself tests against.

Source: <https://github.com/david-lev/pywa/tree/main/tests/data/updates>
License: MIT © 2022-2026 David Lev.

If you update these, pull fresh copies from the cloned reference
(`research/reference-implementations/pywa/tests/data/updates/`) rather
than hand-editing — keeping them byte-identical means we can always
diff-compare when Meta changes a shape.

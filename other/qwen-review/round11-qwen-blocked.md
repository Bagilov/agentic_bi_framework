# Round 11 — Qwen exchange blocked (aliyun WAF CAPTCHA)

The round-11 prompt (`prompt-round11-board-skeleton.md`) and both code bundles
(`round11-code-a-core.md`, `round11-code-b-rest.md`) were prepared and committed
for a later retry, but the chat.qwen.ai exchange could not be completed.

Observed failure (2026-10-24):

- `manage_webllm ask ... -a <bundle> -a <bundle>`: attachments were attached but
  "attachments readiness could not be confirmed", then
  `Locator.click: Timeout 20000ms exceeded`;
- the click log shows the composer/element click is intercepted by
  `<div class="waf-nc-mask"></div> from <div id="waf_nc_block">` — the aliyun
  WAF challenge (`#aliyunCaptcha-img`), a full-screen overlay at z-index
  2_000_000_000;
- a direct CDP probe confirmed `#waf_nc_block` is `display: block` on the
  logged-in page and disappears only briefly after a reload, then re-appears on
  the next interaction;
- a text-only ask (no attachments) also failed: the mechanism uploads the file
  but the composer submit is intercepted, so no answer is produced.

The previous rounds (6–10) used the identical flow successfully, so this is a
server-side rate/automation block on the account session, not a code change.

Resolving it requires a human to solve the CAPTCHA in the managed profile
(`--user-data-dir` on port 9333); it is a security control and is not bypassed
programmatically. Round 11 was therefore audited locally (as round 7 was), every
finding measured before the fix; see the "Round 11 verdicts" section of
`README.md`.

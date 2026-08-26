# SIGNOFF — decisions awaiting maric

Filled as the night goes. Nothing here was decided unilaterally where a real
fork existed; each item states what was done meanwhile.

| # | Topic | What I did meanwhile | Recommendation |
|---|-------|----------------------|----------------|
| 1 | Browser "Allow remote debugging" popup (interactive Chrome harness) | Used headless Playwright instead | Click Allow next session if you want me driving your real Chrome; otherwise Playwright is enough |
| 2 | Vision fallback analyzer 401 (invalid API key) | RESOLVED overnight: maric confirmed opencode (x-preview-f-free) reads images via `-f`. Screenshots get analyzed through `opencode run --model ... -f img.png` | Fix the stale key in config whenever convenient |

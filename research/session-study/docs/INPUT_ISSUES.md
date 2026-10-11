# Incomplete video sources

Local data was inspected read-only on 3 October 2026. Recordings, metadata and
preprocessing code were unchanged. The pipeline marks these sessions
`invalid_video_chunks` and skips their video processing:

| Session ID | Condition | Available chunk indices | Missing indices before last available | First container header |
| --- | --- | --- | --- | --- |
| `0e47571f-aaa2-4120-99f2-802f400a0748` | `calm_1` | 3–15 | 0–2 | Chunk 0 and header missing |
| `31ca610f-f121-4c0e-bbd6-60e75d7b81cd` | `scam` | 0–30, 35–40 | 31–34 | Present |
| `3a01e1f2-4de0-4fe6-a09d-de4f6e04f7ac` | `scam` | 0–14, 72 | 15–71 | Present |
| `897b0a26-f4a9-43e3-8894-1010644e67b2` | `calm_1` | 0–5, 23–27 | 6–22 | Present |
| `ec95568b-c709-4da8-afab-282ae1565c70` | `scam` | 0, 15–30 | 1–14 | Present |
| `f19c1ee1-2b7e-4336-b91a-8afc17dfd165` | `dictation` | 0–5, 32–34 | 6–31 | Present |

There are 103 available chunks and at least 121 missing indices. Later missing
chunks cannot be inferred from the last available index. Chunk indices do not
define precise timestamps or five-second intervals.

Both local copies were checked:

- `/workspace/hackaton/HackYeach-2026-REPO/data/sessions/`
- `/workspace/HackYeach-2026-REPO_backup/data/sessions/`

The backup has identical index sets and none of the missing chunks. Project/data
directories under `/workspace`, including `/workspace/hackyeah/`, contained no third
copy. Listings of `mouse_events.zip` and `mouse_events.1.zip` contained neither video
nor these sessions. Available `net.jsonl` files contain no `video_chunk` receipts
for missing indices. This is consistent with incomplete uploads, but local logs
alone do not establish the cause.

Full repair requires original chunks from the recording device, collection server
or another backup. The first session also needs its original header chunk. Do not
substitute another recording's header or renumber chunks.

Partial recovery of the other five requires a separate mode with decoder-error
checks, real PTS, explicit missing-interval masks and rPPG state resets at gaps.
Concatenating available bytes can leave truncated WebM elements and codec
references across gaps; it is not a verified complete recording. The current
pipeline deliberately does not attempt this recovery.

Metadata, keyboard/mouse events and browser-recorded face/pose points remain in
the sources. Skip reasons also appear in `data/processed/inventory.json`,
`run_report.json` and `sessions.parquet`.

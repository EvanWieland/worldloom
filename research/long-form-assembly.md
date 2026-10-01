# Long-form assembly & encoding (R6) — 2026-09-21

**Evidence level: measured on the dev machine** (ffmpeg 9.0.1, i9-11980HK, driver 596.08), synthetic `testsrc2` content. Re-measure with real content before relying on the fps numbers.

## Findings

1. **Stream-copy looping works and is essentially free.** 10 s 1080p30 H.264 clip (closed GOP: `-g 60 -keyint_min 60 -sc_threshold 0 -flags +cgop`) → `ffmpeg -stream_loop 359 -i loop.mp4 -c copy -movflags +faststart hour.mp4`:
   - 1-hour file written in **8.8 s**; 108 000 packets, duration exactly 3600.000 s.
   - Packet PTS deltas across the first three joins: 1048 checked, **0 irregular**. Full-file decode: no errors.
   - No re-encode ⇒ no generational quality loss, by construction.
2. **File size = N × loop size** (13 MB → 4.7 GB/hour in this high-entropy test). Stream copy saves compute, not storage. With ~87 GB free disk, final bitrate × duration must be budgeted (e.g. 3 h at 20 Mbps ≈ 27 GB).
3. **NVENC is currently unusable:** ffmpeg 9 requires NVENC API 13.1 / **NVIDIA driver ≥ 610.00**; installed driver is 596.08 (`Driver does not support the required nvenc API version`). Action: update the driver (the machine is dedicated to this project), then measure `hevc_nvenc` 4K10 throughput.
4. **CPU encode, 4K 10-bit, 30 fps source (includes synthetic source generation, so a lower bound):** libx264 `fast` ≈ **29 fps**, libx265 `fast` ≈ **16 fps**. A 3-hour non-repeating composite (strategy S2 in `looping.md`) would therefore take ~3 h (x264) to ~6 h (x265) on CPU. Acceptable as a final step; NVENC should improve it.
5. **Seam-metric lesson:** a global mean frame-difference did not flag the (small-area) discontinuity from `testsrc2`'s non-periodic counter at the join. Seam checks must be **region/tile-based (max over tiles), not global means.** Reflected in `QUALITY.md`.

## Ping-pong legs, stream-copy concatenation (2026-09-21, measured)

Legs = clip forward then reversed (experiments/hub_pingpong.py), each encoded separately with identical closed-GOP x264 settings (-g 32 -keyint_min 32 -sc_threshold 0 -bf 2 -flags +cgop -r 16 -video_track_timescale 16000). Concat demuxer, -c copy, list A,101,A,101,A: **524 packets, duration 32.75 s (= 10 + 1.375 + 10 + 1.375 + 10), 0 of 524 PTS deltas irregular, full decode exit 0.** Legs of different clips and lengths concatenate cleanly as long as codec parameters and timebase match. Not yet tested: 4K HEVC legs, multi-hour lists, player behaviour.

## Keyframe pops in delivery encodes (2026-09-26, real loops)

x264's default `keyint=250` re-codes the grain at every I-frame: on the furnace loop the lossless master's worst
step was 1.51x its median, the crf-17 block and the crf-20 review file stepped 2.1–2.8x at frames 250, 500, 750 …
(whole frame; the gear region, grain-rich, jumped most). Review saw a severe shudder at ~30 s (frame 750 of
the doubled review) and, days earlier, a shaky / jerky gear (frames 249/499). Fix in `loopkit.write_video`:
`keyint=infinite:scenecut=0` for every non-lossless encode — one I-frame per file; stream-copied blocks still begin on
one. After: mid-file worst 1.79x. The file's own end→start wrap stays the codec seam (2.78x here), which is why
delivery encodes a 4-period block and stream-copies it (once per block, not per period). Any measurement of a
delivered file must be made on that file, not the master (review stage v2 does).

## Seekable GOPs vs the pops (2026-09-27, experiment 10 of the ChatGPT plan, `experiments/encode_gop/run.py`)

Ten seconds of the dir_furnace_bright lossless master, one encode per row, measured on the decoded file: the frame
step INTO each I-frame divided by the master's step at the same instant (1.0 = invisible), the worst P-frame ratio,
PSNR to the master at I- vs P-frames.

| encode | MB | I-frames | I-step / master (mean, max) | worst P ratio | PSNR I / P dB |
|---|---|---|---|---|---|
| x264 crf 17, keyint=infinite (current) | 3.3 | 1 | — | 1.36 | — / 39.7 |
| x264 crf 17, GOP 96 (4 s) | 3.4 | 3 | 2.05, 2.15 | 1.37 | 41.7 / 39.6 |
| x264 crf 17, GOP 96, ipratio=pbratio=1 | 4.2 | 3 | 1.92, 2.01 | 1.30 | 41.0 / 40.0 |
| x264 crf 17, GOP 96, bframes=0 | 5.6 | 3 | 1.62, 1.69 | 1.12 | 42.5 / 40.2 |
| x264 crf 17, GOP 96, 10-bit | 3.4 | 3 | 2.08, 2.17 | 1.63 | 43.2 / 40.5 |
| x264 crf 12, GOP 96 | 7.3 | 3 | 1.46, 1.52 | 1.19 | 43.7 / 42.3 |
| hevc_nvenc cq 19, GOP 96, maxrate 60M | 3.4 | 3 | 2.01, 2.09 | 1.39 | 41.7 / 39.7 |

The pop is not a bug in one encoder or setting: every 4 s-GOP encode at delivery quality steps 1.9–2.2x into its
I-frames (the I-frame re-quantises the grain that the P-frames had been carrying), x264 and NVENC alike, 8- or 10-bit.
Only spending bits changes it: crf 12 gets to 1.46x at 2.2x the size, no B-frames to 1.6x at 1.7x the size. Neither
reaches the 1.0–1.4x of an ordinary frame. **Kept: keyint=infinite** (one I-frame per file; blocks are stream-copied).
Seeking inside a file is the reported limitation; if it is ever needed, crf 12 + 4 s GOPs is the least bad option.
(x265 did not honour `keyint` through `-x265-params` here — one I-frame; not investigated.)

## Decisions this supports

- Master-loop encode settings: closed GOP, fixed keyframe interval, no scene-cut keyframes, loop length an integer number of GOPs, constant frame rate.
- Assemble stage strategy S1 = `-stream_loop`/concat demuxer with `-c copy`. Variation scheduling across *compatible* loops can also be stream-copied via the concat demuxer provided all clips share codec parameters — not yet tested.

## Not yet tested

- HEVC / AV1 stream-copy looping at 4K10; MKV vs MP4 for multi-hour files; player behaviour (VLC, TV apps, YouTube ingest) at joins.
- Concat demuxer with different clips (loop families).
- NVENC throughput after driver update.
- B-frame/open-GOP edge cases (we avoided them; keep avoiding).

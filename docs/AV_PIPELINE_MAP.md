# Spider VIP — Live AV Pipeline Map (READ-ONLY capture)

Captured 2026-07-11 from a live tuned channel via HiSilicon `/proc/msp/*`.
**Method: strictly read-only (`cat`/`ls`).** No module load/unload, no writes.
SoC: HiSilicon hi3798 · SDK `HiSTBLinuxV100R005C00SPC070_20190601` (built Dec 17 2021).

## End-to-end signal flow

```
 RF/Tuner ─▶ DEMUX (TS, DmxId0, Port128) ─┬─▶ VideoPID 0x1B59 ─▶ VDEC00 (H.264)
                                          │        └─▶ VFMW00 ─▶ VPSS01 ─▶ win0100 ─▶ DISP0 ─▶ HDMI0 (1080i50)
                                          │                                                └─▶ CVBS0 (PAL)
                                          └─▶ AudioPID 0x1B5A ─▶ ADEC00 (MP2) ─▶ track00 ─▶ SOUND0 ─┬─▶ DAC0 (analog)
                                                                                                    ├─▶ SPDIF0
   Sync reference: PCR (sync00) keeps VID+AUD locked ──────────────────────────────────────────────┴─▶ HDMI0 audio
```

## Stage-by-stage live facts

### 1. DEMUX (`/proc/msp/demux_main`)
- Active: **DmxId 0, PortId 128**. TEICnt=0, CCDiscCnt=0 → clean transport, no packet errors.
- DmxClk 251 MHz. Writable help: `echo help > /proc/msp/demux_main` (NOT used — read-only).

### 2. VIDEO DECODE (`/proc/msp/vdec00`, via `avplay00`)
- Video PID **0x1B59**, codec **H.264 (0x4)**, state RUN, priority 3, ErrCover 100.
- Picture **1920×1080**, FrameRate Real **24.97** (stream 25000), Interlace, TopFirst, SP420, 8-bit SDR.
- BitRate **6.21 Mbps**. ErrFrame **0**. Capability up to 2160p. Dynamic Frame Store on (9 frames).
- Chain counters healthy: VFMW→VPSS Acquire 8787/8681, VPSS→AVPLAY 42539/17360.

### 3. VPSS01 — post-process/scaler (`/proc/msp/vpss01`)
- State working, Source=Vdec00, **Deinterlace 5-field**, P/I auto, Sharpness auto.
- ColorSpace **BT709_YUV**, DispAR 16:9, MaxFrameRate 2500, OutBitWidth 10-bit, LowDelay on.
- Buffers: 6 in flight, BufFull 6/BufEmpty 0, ProcessHZ 214/50 → steady 50 fields/s.

### 4. DISPLAY WINDOW (`/proc/msp/win0100`)
- Video layer **Z=0**, Enable/Run, PixFmt **NV21**, 1920×1080, FrameRate 50.0, BT709 limited.
- Underload 34, Discard 0 → essentially smooth. FrameIndex advancing (0x21e9).

### 5. DISPLAY / OUTPUT (`/proc/msp/disp0`, `hdmi0`, `hdmi0_vo`)
- DISP0 Open, VirtualScreen 1920/1080, AR 16:9, Zorder VIDEO→GFX, interface CVBS0 (PAL) + HDMI.
- **HDMI0**: HotPlug YES, Rsen YES, PhyOutput ON, TMDS HDMI1.4, HDCP **disabled** (HDCP2.2+1.4 supported).
- **HDMI timing: 1920×1080i @ 50 (VIC=20), 16:9**, PixelClk 74250, YCbCr444, BT.709, 10-bit in.

### 6. AUDIO (`/proc/msp/adec00`, `sound0`, via `avplay00`)
- Audio PID **0x1B5A**, codec **MP2**, 48 kHz, 16-bit, 2ch. FrameNum 14530, **Error 0**.
- SOUND0 out ports all started, Vol 40, PCM: **DAC0 (analog) + SPDIF0 + HDMI0**. No FIFO underruns.
- Decoder libs available: MP2/MP3/AAC/AC3-passthru/DTS-passthru/EAC3/TrueHD/Opus (libHA.AUDIO.*).

### 7. AV SYNC (`/proc/msp/sync00`)
- SyncRef **PCR**. PcrAudSyncOK=1, PcrVidSyncOK=1. Vid/Aud first-play locked. Buffers nominal.

## Key node inventory (from `ls /proc/msp`)
Video: `avplay00 vdec00 vdec_ctrl vpss01 vpss_ctrl win0100 disp0 disp1 hifb0 hifb1`
Output: `hdmi0 hdmi0_ao hdmi0_sink hdmi0_vo`
Audio: `adec00 sound0 *adsp`
Transport/CA: `demux_main demux_chan demux_filter demux_pcr demux_key demux_rec sci0 sci1 ca cipher`
Accel/misc: `hi_jpeg hi_png hi_tde pq mce sync00 stat chip_temp keyled pm* log module sys`

## Safety note
All `/proc/msp/*` nodes are **read-only status** here (some accept `echo ... >` control
commands per their help text; those are deliberately NOT used). This map was produced
without any risk to the running pipeline. Live TV was never interrupted.

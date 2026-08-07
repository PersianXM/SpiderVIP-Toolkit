/*
 * dbgbar.h -- Engineering Debug Status Bar for Spider VIP (HiSilicon) firmware
 *
 * Modular provider architecture:
 *   - Each metric is produced by an independent Provider (see providers.c).
 *   - Providers write into a single shared `metrics_t` snapshot.
 *   - The GUI/render layer (render.c) ONLY consumes `metrics_t` -- no logic.
 *   - main.c owns the 1 Hz event loop and never blocks the receiver GUI.
 *
 * Design constraints (enforced throughout):
 *   - Zero per-frame heap allocation. All buffers are static/stack.
 *   - No busy polling. One timerfd tick + one epoll on the remote input fd.
 *   - Non-invasive: draws onto the SEPARATE OSD layer /dev/fb1 (hifb1),
 *     ARGB8888 1920x1080, alpha-blended over the main UI on /dev/fb0.
 *     We only paint a thin strip; the rest stays fully transparent so we
 *     never cover or overlap existing menu widgets.
 */
#ifndef DBGBAR_H
#define DBGBAR_H

#include <stdint.h>

#define DBGBAR_VERSION "1.0.0"

/* ---- tri-state / enum status codes shared with the renderer ---- */
typedef enum { ST_UNKNOWN = 0, ST_OK, ST_WARN, ST_ERR, ST_RESET } status_t;

/* thermal zones per spec */
typedef enum {
    TEMP_NORMAL = 0,   /* < 65 */
    TEMP_YELLOW,       /* >= 65 */
    TEMP_ORANGE,       /* >= 70 */
    TEMP_RED,          /* >= 75 */
    TEMP_CRITICAL      /* >= 80  -> flashing */
} temp_zone_t;

/* One shared snapshot. Filled by providers, read by renderer. */
typedef struct {
    /* --- thermal --- */
    int         cpu_temp_c;        /* -1 = unavailable */
    temp_zone_t temp_zone;

    /* --- cpu / mem / uptime --- */
    int         cpu_load_pct;      /* 0..100, -1 = n/a */
    int         mem_used_pct;      /* 0..100, -1 = n/a */
    long        uptime_sec;        /* -1 = n/a */

    /* --- decoders / demux --- */
    status_t    vdec_state;        /* OK / HANG / RESET (ST_RESET) */
    status_t    adec_state;        /* OK / STOP(ST_WARN) / ERROR(ST_ERR) */
    status_t    dmx_state;         /* OK / WAIT(ST_WARN) / ERR / overflow / underflow */
    int         dmx_overflow;      /* bool hint for label */
    int         dmx_underflow;     /* bool hint for label */

    /* --- signal --- */
    int         sig_snr_pct;       /* -1 = n/a */
    int         sig_agc_pct;       /* -1 = n/a */
    long        sig_ber;           /* -1 = n/a */

    /* --- codec / video format --- */
    char        codec[12];         /* "H264" "HEVC" "MPEG2" "AVS" "--" */
    char        resolution[12];    /* "1080i" "1080p" "2160p" "576i" ... */
    char        framerate[12];     /* "50Hz" "25fps" ... */

    /* --- network --- */
    char        net_kind[12];      /* "LAN" "WiFi" "DISCONN" */
    char        net_ip[24];        /* "192.168.x.x" or "--" */
    long        net_rx_bps;        /* optional, -1 = n/a */
    long        net_tx_bps;

    /* --- usb gadget --- */
    int         gadget_enabled;    /* bool */
    int         gadget_streaming;  /* bool: TS export active */

    /* --- storage --- */
    int         flash_used_pct;    /* internal flash, -1 = n/a */
    int         usb_used_pct;      /* first USB storage, -1 = n/a */
    long        rec_free_mb;       /* recording device free space, -1 = n/a */

    /* --- engineering-mode extras (only filled when eng mode on) --- */
    long        vdec_decoded;      /* FRAMEDECED */
    long        vdec_dropped;      /* dropped frames */
    long        pts;               /* last PTS (ms) */
    long        pcr;               /* last PCR (ms) */
    int         buffer_fill_pct;   /* decoder input buffer */
    long        irq_rate;          /* dwc/vdec irq delta per sec */
    char        top_kthread[24];   /* busiest kernel thread name */
    int         hdmi_up;           /* bool */
    int         hdcp_on;           /* bool */
    char        hdmi_colorfmt[16]; /* "RGB" "YUV444" ... */
    int         core_mv;           /* voltage, -1 = n/a */
    int         cpu_mhz;           /* current freq */
} metrics_t;

/* ---- runtime configuration (loaded from /data/dbgbar.conf) ---- */
typedef enum { STYLE_COMPACT = 0, STYLE_NORMAL, STYLE_DEVELOPER } style_t;

typedef struct {
    int     enabled;               /* master on/off */
    int     eng_mode;              /* advanced diagnostics visible */
    int     refresh_sec;           /* 1 / 2 / 5 / 10 */
    style_t style;

    /* per-widget enables (1 = show) */
    int     w_temp, w_cpu, w_ram, w_uptime;
    int     w_vdec, w_adec, w_dmx;
    int     w_signal, w_codec, w_res, w_net, w_gadget, w_storage;
} config_t;

/* ---- provider interface: each provider is independent & side-effect free
 *      apart from writing its own fields into `m`. Providers must NEVER block
 *      (all use non-blocking /proc reads with short static buffers).       ---- */
typedef struct provider {
    const char *name;
    void (*init)(void);                          /* optional, may be NULL */
    void (*sample)(metrics_t *m, const config_t *cfg); /* called each tick */
} provider_t;

/* registry (providers.c) */
extern const provider_t *g_providers[];
extern const int         g_provider_count;

/* config.c */
void config_load(config_t *cfg, const char *path);
void config_defaults(config_t *cfg);

/* render.c -- consumes metrics only */
int  render_init(void);            /* maps /dev/fb1; returns 0 on ok */
void render_bar(const metrics_t *m, const config_t *cfg, int blink_on);
void render_clear(void);
void render_close(void);

/* util: safe one-shot read of a small text file into buf (NUL-terminated).
 * Returns bytes read (>=0) or -1. Never allocates. */
int  slurp(const char *path, char *buf, int buflen);

#endif /* DBGBAR_H */

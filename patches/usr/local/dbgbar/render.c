/*
 * render.c -- framebuffer OSD renderer for the Debug Status Bar.
 *
 * Target: /dev/fb1 = HiSilicon hifb1, ARGB8888, 1920x1080 (verified live).
 * This is the SEPARATE HD OSD layer, alpha-blended by hardware over the main
 * UI on fb0. We paint only a thin strip along the top; everything else is
 * left fully transparent (A=0) so existing menu widgets are never covered.
 *
 * Discipline:
 *   - The framebuffer is mmap'd ONCE at init (no per-frame mmap/alloc).
 *   - Each refresh we memset only our strip region, then blit glyphs.
 *   - Pure consumer of metrics_t; contains no data-collection logic.
 */
#define _GNU_SOURCE
#include "dbgbar.h"
#include "font8x8.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/mman.h>
#include <sys/ioctl.h>
#include <linux/fb.h>

/* ARGB helpers */
#define A(x) (((x)>>24)&0xFF)
#define ARGB(a,r,g,b) (((uint32_t)(a)<<24)|((uint32_t)(r)<<16)|((uint32_t)(g)<<8)|(uint32_t)(b))

#define COL_BG        ARGB(0xB0,0x08,0x0A,0x10) /* translucent dark strip */
#define COL_FG        ARGB(0xFF,0xE6,0xE6,0xE6)
#define COL_DIM       ARGB(0xFF,0x9A,0x9A,0x9A)
#define COL_OK        ARGB(0xFF,0x39,0xD3,0x53)
#define COL_WARN      ARGB(0xFF,0xF2,0xC0,0x2E)
#define COL_ORANGE    ARGB(0xFF,0xF2,0x8C,0x1E)
#define COL_ERR       ARGB(0xFF,0xEA,0x3B,0x3B)
#define COL_ACCENT    ARGB(0xFF,0x54,0xB0,0xF7)

static int             s_fd = -1;
static uint32_t       *s_fb = NULL;
static struct fb_var_screeninfo s_var;
static struct fb_fix_screeninfo s_fix;
static int             s_w = 0, s_h = 0, s_stride_px = 0;

/* strip geometry */
#define BAR_H     26           /* main bar height in px */
#define BAR_H2    (BAR_H*2)     /* with eng-mode second row */
#define PAD_X     12
#define GLYPH_W   8
#define GLYPH_H   8
#define SCALE     2            /* 8x8 -> 16x16 */
#define CELL_W    (GLYPH_W*SCALE)
#define CELL_H    (GLYPH_H*SCALE)

int render_init(void)
{
    s_fd = open("/dev/fb1", O_RDWR);
    if (s_fd < 0) return -1;
    if (ioctl(s_fd, FBIOGET_VSCREENINFO, &s_var) < 0) goto fail;
    if (ioctl(s_fd, FBIOGET_FSCREENINFO, &s_fix) < 0) goto fail;
    s_w = s_var.xres;
    s_h = s_var.yres;
    s_stride_px = s_fix.line_length / 4;   /* ARGB8888 => 4 bytes/px */
    if (s_stride_px <= 0) s_stride_px = s_w;
    size_t map = (size_t)s_fix.line_length * s_var.yres_virtual;
    s_fb = (uint32_t*)mmap(NULL, map, PROT_READ|PROT_WRITE, MAP_SHARED, s_fd, 0);
    if (s_fb == MAP_FAILED) { s_fb = NULL; goto fail; }
    return 0;
fail:
    if (s_fd >= 0) close(s_fd);
    s_fd = -1;
    return -1;
}

static inline void put_px(int x, int y, uint32_t argb)
{
    if (x < 0 || y < 0 || x >= s_w || y >= s_h) return;
    /* simple source-over onto whatever is in our OSD layer (we own the strip) */
    s_fb[y * s_stride_px + x] = argb;
}

static void fill_rect(int x, int y, int w, int h, uint32_t argb)
{
    for (int j = 0; j < h; j++)
        for (int i = 0; i < w; i++)
            put_px(x + i, y + j, argb);
}

/* draw one 8x8 glyph scaled by SCALE at (x,y). ch<0x20 -> space.
 * special: 0x60 (`) renders the degree ring. lowercase mapped to upper. */
static void draw_glyph(int x, int y, char ch, uint32_t col)
{
    const unsigned char *g;
    unsigned char uc = (unsigned char)ch;
    if (uc == 0x60) g = font_degree;
    else {
        if (uc >= 'a' && uc <= 'z') uc -= 32;          /* upper-case map */
        if (uc < FONT_FIRST || uc > FONT_LAST) uc = ' ';
        g = font8x8[uc - FONT_FIRST];
    }
    for (int row = 0; row < 8; row++) {
        unsigned char bits = g[row];
        for (int col_i = 0; col_i < 8; col_i++) {
            if (bits & (1 << col_i)) {
                for (int sy = 0; sy < SCALE; sy++)
                    for (int sx = 0; sx < SCALE; sx++)
                        put_px(x + col_i*SCALE + sx, y + row*SCALE + sy, col);
            }
        }
    }
}

/* draw a string, return x advanced */
static int draw_text(int x, int y, const char *s, uint32_t col)
{
    while (*s) {
        draw_glyph(x, y, *s, col);
        x += CELL_W;
        s++;
    }
    return x;
}

/* measure pixel width of a string in current cell size */
static int text_w(const char *s) { return (int)strlen(s) * CELL_W; }

/* map temperature zone to a color */
static uint32_t temp_color(temp_zone_t z)
{
    switch (z) {
        case TEMP_YELLOW:   return COL_WARN;
        case TEMP_ORANGE:   return COL_ORANGE;
        case TEMP_RED:      return COL_ERR;
        case TEMP_CRITICAL: return COL_ERR;
        default:            return COL_OK;
    }
}
static uint32_t status_color(status_t s)
{
    switch (s) {
        case ST_OK:    return COL_OK;
        case ST_WARN:  return COL_WARN;
        case ST_RESET: return COL_WARN;
        case ST_ERR:   return COL_ERR;
        default:       return COL_DIM;
    }
}

/* one segment = "<glyph-marker><label>" drawn right-to-left packing.
 * We compose into a local list then draw from the right edge leftwards so
 * the bar hugs the top-right corner exactly like the existing status area. */
typedef struct { char text[40]; uint32_t col; } seg_t;

static int build_segments(const metrics_t *m, const config_t *cfg, seg_t *segs, int max)
{
    int n = 0;
    #define ADD(fmt, color, ...) do { \
        if (n < max) { snprintf(segs[n].text, sizeof segs[n].text, fmt, ##__VA_ARGS__); \
                       segs[n].col = (color); n++; } } while (0)

    if (cfg->w_temp) {
        if (m->cpu_temp_c >= 0) ADD("T:%d`C", temp_color(m->temp_zone), m->cpu_temp_c);
        else                    ADD("T:--",  COL_DIM);
    }
    if (cfg->w_cpu) {
        if (m->cpu_load_pct >= 0) ADD("CPU:%d%%", COL_FG, m->cpu_load_pct);
        else                      ADD("CPU:--",  COL_DIM);
    }
    if (cfg->w_ram) {
        if (m->mem_used_pct >= 0) ADD("RAM:%d%%", COL_FG, m->mem_used_pct);
        else                      ADD("RAM:--",  COL_DIM);
    }
    if (cfg->w_uptime && m->uptime_sec >= 0) {
        long d = m->uptime_sec / 86400;
        long h = (m->uptime_sec % 86400) / 3600;
        ADD("UP:%ldd%ldh", COL_DIM, d, h);
    }
    if (cfg->w_vdec) {
        const char *lbl = m->vdec_state==ST_OK?"VDEC OK":
                          m->vdec_state==ST_ERR?"VDEC HANG":
                          m->vdec_state==ST_RESET?"VDEC RST":"VDEC --";
        ADD("%s", status_color(m->vdec_state), lbl);
    }
    if (cfg->w_adec) {
        const char *lbl = m->adec_state==ST_OK?"ADEC OK":
                          m->adec_state==ST_WARN?"ADEC STOP":
                          m->adec_state==ST_ERR?"ADEC ERR":"ADEC --";
        ADD("%s", status_color(m->adec_state), lbl);
    }
    if (cfg->w_dmx) {
        const char *lbl = m->dmx_overflow?"DMX OVFL":
                          m->dmx_underflow?"DMX UNFL":
                          m->dmx_state==ST_OK?"DMX OK":
                          m->dmx_state==ST_WARN?"DMX WAIT":
                          m->dmx_state==ST_ERR?"DMX ERR":"DMX --";
        ADD("%s", status_color(m->dmx_state), lbl);
    }
    if (cfg->w_codec) ADD("%s", COL_ACCENT, m->codec);
    if (cfg->w_res) {
        if (strcmp(m->resolution,"--")) ADD("%s", COL_FG, m->resolution);
        if (cfg->style==STYLE_DEVELOPER && strcmp(m->framerate,"--")) ADD("%s", COL_DIM, m->framerate);
    }
    if (cfg->w_signal) {
        if (m->sig_snr_pct >= 0) ADD("SIG:%d%% B%ld", COL_FG, m->sig_snr_pct, m->sig_ber<0?0:m->sig_ber);
    }
    if (cfg->w_net) {
        if (m->net_kind[0]=='D') ADD("NET:DISC", COL_ERR);
        else if (cfg->style==STYLE_COMPACT) ADD("%s", COL_OK, m->net_kind);
        else ADD("%s %s", COL_OK, m->net_kind, m->net_ip);
    }
    if (cfg->w_gadget) {
        if (m->gadget_streaming)   ADD("USB:STREAM", COL_ERR);
        else if (m->gadget_enabled)ADD("USB:IDLE",  COL_DIM);
    }
    if (cfg->w_storage && m->flash_used_pct >= 0)
        ADD("FL:%d%%", COL_DIM, m->flash_used_pct);

    #undef ADD
    return n;
}

/* second row: engineering diagnostics */
static int build_eng_segments(const metrics_t *m, seg_t *segs, int max)
{
    int n = 0;
    #define ADDE(fmt, color, ...) do { \
        if (n < max) { snprintf(segs[n].text, sizeof segs[n].text, fmt, ##__VA_ARGS__); \
                       segs[n].col = (color); n++; } } while (0)
    if (m->vdec_decoded >= 0) ADDE("DEC:%ld", COL_FG, m->vdec_decoded);
    if (m->buffer_fill_pct >= 0) ADDE("BUF:%d%%", COL_FG, m->buffer_fill_pct);
    if (m->pts >= 0) ADDE("PTS:%ld", COL_DIM, m->pts);
    if (m->pcr >= 0) ADDE("PCR:%ld", COL_DIM, m->pcr);
    ADDE("IRQ:%ld/s", COL_ACCENT, m->irq_rate<0?0:m->irq_rate);
    if (m->cpu_mhz > 0) ADDE("%dMHz", COL_DIM, m->cpu_mhz);
    ADDE("HDMI:%s", m->hdmi_up?COL_OK:COL_DIM, m->hdmi_up?"UP":"--");
    if (m->hdcp_on) ADDE("HDCP", COL_ACCENT);
    if (m->core_mv > 0) ADDE("%dmV", COL_DIM, m->core_mv);
    #undef ADDE
    return n;
}

/* draw a row of segments right-aligned to (right_x) at vertical y */
static void draw_row(seg_t *segs, int n, int right_x, int y)
{
    /* total width */
    int total = 0;
    for (int i = 0; i < n; i++) total += text_w(segs[i].text) + CELL_W; /* +gap */
    int x = right_x - total;
    if (x < PAD_X) x = PAD_X;
    for (int i = 0; i < n; i++) {
        x = draw_text(x, y, segs[i].text, segs[i].col);
        x += CELL_W; /* gap */
    }
}

void render_bar(const metrics_t *m, const config_t *cfg, int blink_on)
{
    if (!s_fb) return;

    seg_t segs[24];
    int n = build_segments(m, cfg, segs, 24);

    int rows = (cfg->eng_mode ? 2 : 1);
    int barh = (rows == 2 ? BAR_H2 : BAR_H) + 6;

    /* clear our strip only (top of screen). Fully transparent first so we
     * never leave residue over menu items, then paint translucent bg. */
    fill_rect(0, 0, s_w, barh, ARGB(0,0,0,0));

    /* Flash behaviour: if critical temp, blink the whole strip bg red. */
    uint32_t bg = COL_BG;
    if (m->temp_zone == TEMP_CRITICAL && blink_on)
        bg = ARGB(0xC0,0x60,0x08,0x08);

    /* draw bg only behind the right-side region we use (right 70% of width),
     * so the left menu title area stays clear */
    int bg_x = s_w * 30 / 100;
    fill_rect(bg_x, 0, s_w - bg_x, barh, bg);

    int y0 = (BAR_H - CELL_H)/2 + 3;
    draw_row(segs, n, s_w - PAD_X, y0);

    if (cfg->eng_mode) {
        seg_t esegs[24];
        int en = build_eng_segments(m, esegs, 24);
        draw_row(esegs, en, s_w - PAD_X, y0 + BAR_H);
    }

    /* critical-temp warning tag on the far left of the strip (flashing) */
    if (m->temp_zone >= TEMP_RED) {
        const char *w = (m->temp_zone==TEMP_CRITICAL) ? "! CRITICAL TEMP !" : "! HOT !";
        if (m->temp_zone != TEMP_CRITICAL || blink_on)
            draw_text(bg_x + PAD_X, y0, w, COL_ERR);
    }
}

void render_clear(void)
{
    if (!s_fb) return;
    fill_rect(0, 0, s_w, BAR_H2 + 6, ARGB(0,0,0,0));
}

void render_close(void)
{
    if (s_fb) {
        render_clear();
        munmap(s_fb, (size_t)s_fix.line_length * s_var.yres_virtual);
        s_fb = NULL;
    }
    if (s_fd >= 0) { close(s_fd); s_fd = -1; }
}

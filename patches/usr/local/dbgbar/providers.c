/*
 * providers.c -- independent metric providers for the Debug Status Bar.
 *
 * Every provider reads real device state that was verified live on the
 * Spider VIP (HiSilicon) receiver:
 *
 *   /proc/hisi/msp/chip_temp   -> "Chip Temperature : 77"
 *   /proc/hisi/msp/pm_temp     -> thresholds
 *   /proc/hisi/msp/stat        -> ASTART/VSTART/ASTOP/VSTOP/FRAMEDECED...
 *   /proc/hisi/msp/vdec00      -> Codec ID / WxH / FrameRate / Work State
 *   /proc/hisi/msp/avplay00    -> av sync / pts / pcr
 *   /proc/hisi/msp/demux_chanbuf-> demux buffer fill
 *   /proc/loadavg /proc/stat   -> cpu load
 *   /proc/meminfo              -> ram
 *   /proc/uptime               -> uptime
 *   /proc/net/dev, /sys ip     -> network
 *   /sys/.../scaling_cur_freq  -> cpu mhz
 *
 * Rules honoured:
 *   - no malloc, small static buffers only
 *   - all reads are short, non-blocking one-shots (open/read/close)
 *   - any failure yields "--"/-1 and NEVER crashes
 */
#define _GNU_SOURCE
#include "dbgbar.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/statvfs.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <arpa/inet.h>
#include <net/if.h>

/* ------------------------------------------------------------------ */
/* small safe file reader (declared in dbgbar.h)                       */
int slurp(const char *path, char *buf, int buflen)
{
    int fd, n;
    if (buflen <= 0) return -1;
    fd = open(path, O_RDONLY | O_NONBLOCK);
    if (fd < 0) { buf[0] = 0; return -1; }
    n = (int)read(fd, buf, buflen - 1);
    close(fd);
    if (n < 0) n = 0;
    buf[n] = 0;
    return n;
}

/* find "key" line then the value after the last ':' or after key.
 * returns pointer into buf just past the marker, or NULL. */
static const char *after(const char *buf, const char *key)
{
    const char *p = strstr(buf, key);
    if (!p) return NULL;
    p += strlen(key);
    return p;
}

/* parse first signed long appearing at/after p.
 * A '-' only counts as a sign when a digit immediately follows it, so runs of
 * ASCII-art dashes (e.g. "-------" in HiSilicon /proc headers) are skipped
 * instead of being misread as the number 0. */
static long grab_long(const char *p)
{
    if (!p) return -1;
    for (;;) {
        while (*p && (*p < '0' || *p > '9') && *p != '-') p++;
        if (!*p) return -1;
        if (*p == '-') {
            if (p[1] >= '0' && p[1] <= '9') return strtol(p, NULL, 10);
            p++;            /* lone dash: not a number, keep scanning */
            continue;
        }
        return strtol(p, NULL, 10);
    }
}


/* ================================================================== */
/* Temperature provider                                                */
/* ================================================================== */
static void temp_sample(metrics_t *m, const config_t *cfg)
{
    char b[256];
    (void)cfg;
    m->cpu_temp_c = -1;
    if (slurp("/proc/hisi/msp/chip_temp", b, sizeof b) > 0) {
        long t = grab_long(after(b, "Temperature"));
        /* the file has "Chip Temperature   :77"; 'Temperature' matches and
         * grab_long walks to the digits after the colon */
        if (t >= 0 && t < 200) m->cpu_temp_c = (int)t;
    }
    int t = m->cpu_temp_c;
    if      (t < 0)   m->temp_zone = TEMP_NORMAL;
    else if (t >= 80) m->temp_zone = TEMP_CRITICAL;
    else if (t >= 75) m->temp_zone = TEMP_RED;
    else if (t >= 70) m->temp_zone = TEMP_ORANGE;
    else if (t >= 65) m->temp_zone = TEMP_YELLOW;
    else              m->temp_zone = TEMP_NORMAL;
}

/* ================================================================== */
/* CPU load provider -- delta of /proc/stat (idle vs total)            */
/* ================================================================== */
static unsigned long long s_prev_idle, s_prev_total;
static void cpu_sample(metrics_t *m, const config_t *cfg)
{
    char b[256];
    (void)cfg;
    m->cpu_load_pct = -1;
    m->cpu_mhz = -1;
    if (slurp("/proc/stat", b, sizeof b) > 0) {
        unsigned long long u=0,n=0,s=0,i=0,w=0,irq=0,sirq=0;
        if (sscanf(b, "cpu %llu %llu %llu %llu %llu %llu %llu",
                   &u,&n,&s,&i,&w,&irq,&sirq) >= 4) {
            unsigned long long idle = i + w;
            unsigned long long total = u+n+s+i+w+irq+sirq;
            if (s_prev_total && total > s_prev_total) {
                unsigned long long dt = total - s_prev_total;
                unsigned long long di = idle - s_prev_idle;
                int busy = (int)(100ULL * (dt - di) / dt);
                if (busy < 0) busy = 0; if (busy > 100) busy = 100;
                m->cpu_load_pct = busy;
            }
            s_prev_idle = idle; s_prev_total = total;
        }
    }
    if (slurp("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq", b, sizeof b) > 0)
        m->cpu_mhz = (int)(grab_long(b) / 1000);
}

/* ================================================================== */
/* Memory provider -- /proc/meminfo                                    */
/* ================================================================== */
static void mem_sample(metrics_t *m, const config_t *cfg)
{
    char b[512];
    (void)cfg;
    m->mem_used_pct = -1;
    if (slurp("/proc/meminfo", b, sizeof b) > 0) {
        long total = grab_long(after(b, "MemTotal:"));
        long avail = grab_long(after(b, "MemAvailable:"));
        if (avail < 0) { /* fallback: MemFree+Buffers+Cached */
            long f = grab_long(after(b, "MemFree:"));
            long bu= grab_long(after(b, "Buffers:"));
            long ca= grab_long(after(b, "Cached:"));
            if (f>=0) avail = f + (bu>0?bu:0) + (ca>0?ca:0);
        }
        if (total > 0 && avail >= 0) {
            long used = total - avail;
            if (used < 0) used = 0;
            m->mem_used_pct = (int)(100L * used / total);
        }
    }
}

/* ================================================================== */
/* Uptime provider                                                     */
/* ================================================================== */
static void uptime_sample(metrics_t *m, const config_t *cfg)
{
    char b[64];
    (void)cfg;
    m->uptime_sec = -1;
    if (slurp("/proc/uptime", b, sizeof b) > 0) {
        double up = 0;
        if (sscanf(b, "%lf", &up) == 1) m->uptime_sec = (long)up;
    }
}

/* ================================================================== */
/* AV pipeline provider -- /proc/hisi/msp/stat + vdec00 + avplay00     */
/*   Uses event counters to infer VDEC/ADEC/DEMUX health.              */
/* ================================================================== */
static long s_prev_framededed = -1;
static int  s_stall_ticks = 0;
static void av_sample(metrics_t *m, const config_t *cfg)
{
    char b[4096];

    /* defaults */
    m->vdec_state = ST_UNKNOWN;
    m->adec_state = ST_UNKNOWN;
    m->dmx_state  = ST_UNKNOWN;
    m->dmx_overflow = m->dmx_underflow = 0;
    strcpy(m->codec, "--");
    strcpy(m->resolution, "--");
    strcpy(m->framerate, "--");
    m->vdec_decoded = -1; m->vdec_dropped = -1;
    m->pts = -1; m->pcr = -1; m->buffer_fill_pct = -1;

    /* ---- /proc/hisi/msp/stat : event counters ---- */
    if (slurp("/proc/hisi/msp/stat", b, sizeof b) > 0) {
        long astart = grab_long(after(b, "ASTART"));
        long vstart = grab_long(after(b, "VSTART"));
        long astop  = grab_long(after(b, "ASTOP"));
        long vstop  = grab_long(after(b, "VSTOP"));
        long framed = grab_long(after(b, "FRAMEDECED"));
        long streamin = grab_long(after(b, "STREAMIN"));
        m->vdec_decoded = framed;

        /* VDEC health: is FRAMEDECED advancing while playing? */
        if (vstart > 0 && (vstop < vstart)) {
            if (s_prev_framededed >= 0) {
                if (framed > s_prev_framededed) { s_stall_ticks = 0; m->vdec_state = ST_OK; }
                else { s_stall_ticks++;
                       m->vdec_state = (s_stall_ticks >= 3) ? ST_ERR /*HANG*/ : ST_OK; }
            } else m->vdec_state = ST_OK;
        } else if (vstop >= vstart && vstart > 0) {
            m->vdec_state = ST_RESET; /* stopped/receiving-stop */
        }
        s_prev_framededed = framed;

        /* ADEC health */
        if (astart > 0 && astop < astart)      m->adec_state = ST_OK;
        else if (astop >= astart && astart>0)  m->adec_state = ST_WARN; /* STOP */
        else                                   m->adec_state = ST_UNKNOWN;

        /* DEMUX: streamin advancing => feeding decoder */
        if (streamin > 0)                      m->dmx_state = ST_OK;
        else                                   m->dmx_state = ST_WARN; /* WAIT */
    }

    /* ---- /proc/hisi/msp/vdec00 : codec / resolution / fps / work state ---- */
    if (slurp("/proc/hisi/msp/vdec00", b, sizeof b) > 0) {
        const char *p;
        /* Codec ID line: "Codec ID : H264(0x4)" */
        p = after(b, "Codec ID");
        if (p) {
            while (*p == ' ' || *p == ':') p++;
            /* copy token of A-Z0-9 */
            int k=0; while (p[k] && p[k] != '(' && p[k] != '\n' && p[k] != ' ' && k < 11) { m->codec[k]=p[k]; k++; }
            m->codec[k]=0;
            if (!m->codec[0]) strcpy(m->codec, "--");
            /* normalise H265 label to HEVC */
            if (!strcmp(m->codec,"H265")) strcpy(m->codec,"HEVC");
        }
        /* Work State */
        p = after(b, "Work State");
        if (p) {
            if (strstr(p, "RUN")) { if (m->vdec_state == ST_UNKNOWN) m->vdec_state = ST_OK; }
        }
        /* Width*Height */
        p = after(b, "Width*Height");
        int w=0,h=0;
        if (p && sscanf(p, " : %d*%d", &w, &h) == 2 && h > 0) {
            const char *scan = "p";
            const char *tp = after(b, "Type");   /* "Interlace"/"Progressive" */
            if (tp && strstr(tp, "Interlace")) scan = "i";
            snprintf(m->resolution, sizeof m->resolution, "%d%s", h, scan);
            /* buffer fill: from DFS delay as rough proxy not ideal; leave n/a */
        }
        /* FrameRate(fps): "Real(25.2) FrameInfo(25000)" */
        p = after(b, "FrameRate");
        if (p) {
            double fr=0; const char *r = strstr(p, "Real(");
            if (r && sscanf(r, "Real(%lf)", &fr) == 1 && fr > 0)
                snprintf(m->framerate, sizeof m->framerate, "%dfps", (int)(fr+0.5));
        }
    }

    /* ---- avplay00 : PTS/PCR for engineering mode ---- */
    if (cfg->eng_mode && slurp("/proc/hisi/msp/avplay00", b, sizeof b) > 0) {
        long pts = grab_long(after(b, "LastPts"));
        long pcr = grab_long(after(b, "LastPcr"));
        if (pts < 0) pts = grab_long(after(b, "Pts"));
        if (pcr < 0) pcr = grab_long(after(b, "Pcr"));
        m->pts = pts; m->pcr = pcr;
    }

    /* ---- demux_chanbuf : overflow / underflow / fill ---- */
    if (slurp("/proc/hisi/msp/demux_chanbuf", b, sizeof b) > 0) {
        if (strstr(b, "verflow")) { m->dmx_overflow = 1; m->dmx_state = ST_ERR; }
        if (strstr(b, "nderflow")){ m->dmx_underflow = 1; if (m->dmx_state==ST_OK) m->dmx_state = ST_WARN; }
        long used = grab_long(after(b, "Used"));
        long size = grab_long(after(b, "Size"));
        if (used >= 0 && size > 0) m->buffer_fill_pct = (int)(100L*used/size);
    }
}

/* ================================================================== */
/* Signal provider -- best-effort via /proc/hisi frontend (optional)   */
/*   Fields vary by tuner driver; we degrade gracefully to --.         */
/* ================================================================== */
static void signal_sample(metrics_t *m, const config_t *cfg)
{
    char b[1024];
    (void)cfg;
    m->sig_snr_pct = -1; m->sig_agc_pct = -1; m->sig_ber = -1;
    /* common enigma2 frontend stat node */
    if (slurp("/proc/stb/frontend/0/snr_db", b, sizeof b) > 0) {
        long v = grab_long(b); if (v >= 0) m->sig_snr_pct = (int)(v > 100 ? 100 : v);
    }
    if (m->sig_snr_pct < 0 && slurp("/proc/stb/frontend/0/snr", b, sizeof b) > 0) {
        long v = grab_long(b); /* often 0..65535 */
        if (v >= 0) m->sig_snr_pct = (int)(v > 65535 ? 100 : (v*100/65535));
    }
    if (slurp("/proc/stb/frontend/0/agc", b, sizeof b) > 0) {
        long v = grab_long(b);
        if (v >= 0) m->sig_agc_pct = (int)(v > 65535 ? 100 : (v*100/65535));
    }
    if (slurp("/proc/stb/frontend/0/ber", b, sizeof b) > 0) {
        long v = grab_long(b); if (v >= 0) m->sig_ber = v;
    }
}

/* ================================================================== */
/* Network provider -- link kind, IP, throughput                       */
/* ================================================================== */
static long s_prev_rx, s_prev_tx;
static int  s_have_prev_net;
static int iface_ip(const char *ifn, char *out, int outlen)
{
    struct ifreq ifr; int fd, ok = 0;
    fd = socket(AF_INET, SOCK_DGRAM, 0);
    if (fd < 0) return 0;
    memset(&ifr, 0, sizeof ifr);
    ifr.ifr_addr.sa_family = AF_INET;
    strncpy(ifr.ifr_name, ifn, IFNAMSIZ-1);
    if (ioctl(fd, SIOCGIFADDR, &ifr) == 0) {
        struct sockaddr_in *sa = (struct sockaddr_in*)&ifr.ifr_addr;
        const char *s = inet_ntoa(sa->sin_addr);
        if (s) { strncpy(out, s, outlen-1); out[outlen-1]=0; ok = 1; }
    }
    close(fd);
    return ok;
}
static void net_sample(metrics_t *m, const config_t *cfg)
{
    char b[2048];
    (void)cfg;
    strcpy(m->net_kind, "DISCONN");
    strcpy(m->net_ip, "--");
    m->net_rx_bps = m->net_tx_bps = -1;

    if (iface_ip("eth0", m->net_ip, sizeof m->net_ip))       strcpy(m->net_kind, "LAN");
    else if (iface_ip("wlan0", m->net_ip, sizeof m->net_ip)) strcpy(m->net_kind, "WiFi");

    /* throughput for the active iface from /proc/net/dev */
    if (m->net_kind[0] != 'D' && slurp("/proc/net/dev", b, sizeof b) > 0) {
        const char *ifn = (m->net_kind[0]=='L') ? "eth0" : "wlan0";
        const char *p = strstr(b, ifn);
        if (p) {
            long rx=0, tx=0; /* fields: rxbytes ... (col1) txbytes (col9) */
            long cols[16]; int nc=0;
            const char *q = strchr(p, ':'); if (q) q++;
            while (q && *q && nc < 16) {
                while (*q==' '||*q=='\t') q++;
                if (*q < '0' || *q > '9') break;
                cols[nc++] = strtol(q, (char**)&q, 10);
            }
            if (nc >= 9) { rx = cols[0]; tx = cols[8]; }
            if (s_have_prev_net) {
                long drx = rx - s_prev_rx, dtx = tx - s_prev_tx;
                m->net_rx_bps = (drx < 0 ? 0 : drx);
                m->net_tx_bps = (dtx < 0 ? 0 : dtx);
            }
            s_prev_rx = rx; s_prev_tx = tx; s_have_prev_net = 1;
        }
    }
}

/* ================================================================== */
/* USB gadget provider -- detect service gadget + TS streaming         */
/*   Verified live: dwc_otg_pcd IRQ + gservice_ts_thread activity.     */
/* ================================================================== */
static long s_prev_pcd_irq = -1;
static void gadget_sample(metrics_t *m, const config_t *cfg)
{
    char b[8192];
    (void)cfg;
    m->gadget_enabled = 0;
    m->gadget_streaming = 0;

    /* gadget bound? check UDC / configfs / driver presence */
    if (slurp("/sys/class/udc/", b, sizeof b) >= 0) { /* dir read may fail; ignore */ }
    if (access("/sys/kernel/config/usb_gadget", F_OK) == 0) m->gadget_enabled = 1;

    /* streaming inference: dwc_otg_pcd interrupt count rising fast */
    if (slurp("/proc/interrupts", b, sizeof b) > 0) {
        const char *p = strstr(b, "dwc_otg");
        long irq = -1;
        if (p) {
            /* rewind to line start, take first number on the line */
            const char *ls = p; while (ls > b && ls[-1] != '\n') ls--;
            irq = grab_long(ls);
            m->gadget_enabled = 1;
        }
        if (irq >= 0) {
            if (s_prev_pcd_irq >= 0) {
                long d = irq - s_prev_pcd_irq;
                m->irq_rate = (d < 0 ? 0 : d);
                /* high sustained control traffic => TS export active */
                if (d > 200) m->gadget_streaming = 1;
            }
            s_prev_pcd_irq = irq;
        }
    }
}

/* ================================================================== */
/* Storage provider -- flash / usb / recording free space              */
/* ================================================================== */
static int used_pct(const char *mnt)
{
    struct statvfs vs;
    if (statvfs(mnt, &vs) != 0 || vs.f_blocks == 0) return -1;
    unsigned long long total = (unsigned long long)vs.f_blocks * vs.f_frsize;
    unsigned long long avail = (unsigned long long)vs.f_bavail * vs.f_frsize;
    if (total == 0) return -1;
    return (int)(100ULL * (total - avail) / total);
}
static long free_mb(const char *mnt)
{
    struct statvfs vs;
    if (statvfs(mnt, &vs) != 0) return -1;
    unsigned long long avail = (unsigned long long)vs.f_bavail * vs.f_frsize;
    return (long)(avail / (1024*1024));
}
static void storage_sample(metrics_t *m, const config_t *cfg)
{
    (void)cfg;
    m->flash_used_pct = used_pct("/");           /* internal rootfs/flash */
    m->usb_used_pct   = -1;
    m->rec_free_mb    = -1;
    /* try common USB / recording mount points */
    const char *usbs[] = {"/media/usb","/media/hdd","/tmp/UD0","/tmp/UD1","/hdd", NULL};
    for (int i = 0; usbs[i]; i++) {
        if (access(usbs[i], F_OK) == 0) {
            int u = used_pct(usbs[i]);
            if (u >= 0) { m->usb_used_pct = u; m->rec_free_mb = free_mb(usbs[i]); break; }
        }
    }
    if (m->rec_free_mb < 0) m->rec_free_mb = free_mb("/");
}

/* ================================================================== */
/* Engineering extras provider -- HDMI / voltage / top kthread         */
/* ================================================================== */
static void eng_sample(metrics_t *m, const config_t *cfg)
{
    char b[2048];
    m->hdmi_up = 0; m->hdcp_on = 0; strcpy(m->hdmi_colorfmt, "--");
    m->core_mv = -1; m->vdec_dropped = (m->vdec_dropped<0?-1:m->vdec_dropped);
    strcpy(m->top_kthread, "--");
    if (!cfg->eng_mode) return;

    if (slurp("/proc/hisi/msp/hdmi0", b, sizeof b) > 0 ||
        slurp("/proc/hisi/msp/hdmi0_sink", b, sizeof b) > 0) {
        if (strstr(b, "Connect") || strstr(b, "Plug") || strstr(b, "ON")) m->hdmi_up = 1;
        if (strstr(b, "HDCP") && (strstr(b, "success") || strstr(b, "ON") || strstr(b, "Enable")))
            m->hdcp_on = 1;
        const char *p = strstr(b, "RGB"); if (p) strcpy(m->hdmi_colorfmt, "RGB");
        else if ((p=strstr(b,"YUV444"))) strcpy(m->hdmi_colorfmt,"YUV444");
        else if ((p=strstr(b,"YUV422"))) strcpy(m->hdmi_colorfmt,"YUV422");
        else if ((p=strstr(b,"YUV420"))) strcpy(m->hdmi_colorfmt,"YUV420");
    }
    /* core voltage if the platform exposes it */
    if (slurp("/proc/hisi/msp/pm_core", b, sizeof b) > 0) {
        long mv = grab_long(after(b, "Voltage"));
        if (mv > 0) m->core_mv = (int)mv;
    }
}

/* ================================================================== */
/* registry                                                            */
/* ================================================================== */
static const provider_t P_temp    = { "temperature", NULL, temp_sample };
static const provider_t P_cpu     = { "cpu",         NULL, cpu_sample };
static const provider_t P_mem     = { "memory",      NULL, mem_sample };
static const provider_t P_uptime  = { "uptime",      NULL, uptime_sample };
static const provider_t P_av      = { "avpipeline",  NULL, av_sample };
static const provider_t P_signal  = { "signal",      NULL, signal_sample };
static const provider_t P_net     = { "network",     NULL, net_sample };
static const provider_t P_gadget  = { "usbgadget",   NULL, gadget_sample };
static const provider_t P_storage = { "storage",     NULL, storage_sample };
static const provider_t P_eng     = { "engineering", NULL, eng_sample };

const provider_t *g_providers[] = {
    &P_temp, &P_cpu, &P_mem, &P_uptime, &P_av,
    &P_signal, &P_net, &P_gadget, &P_storage, &P_eng,
};
const int g_provider_count = (int)(sizeof(g_providers)/sizeof(g_providers[0]));

/*
 * main.c -- Engineering Debug Status Bar daemon entry point.
 *
 * Event-driven, single-threaded, never blocks:
 *   - epoll waits on:
 *       (a) a timerfd firing every cfg.refresh_sec seconds  -> sample+render
 *       (b) /dev/input/event0 (remote)                      -> hidden shortcut
 *   - No busy polling. When idle, the process sleeps in epoll_wait at ~0% CPU.
 *
 * Hidden shortcut:  MENU then 9 9 9 9   toggles Engineering Mode live.
 *   (matches the requested "MENU + 9999"). A 3-second inter-key timeout
 *   resets the capture so normal remote use is unaffected.
 *
 * Config:  /data/dbgbar.conf  (re-read when its mtime changes).
 *
 * Safety:
 *   - SIGTERM/SIGINT -> clear overlay and exit cleanly.
 *   - Any provider/render failure is contained; the loop keeps running.
 *   - If /dev/fb1 can't be mapped, we exit(0) quietly (no UI disruption).
 */
#define _GNU_SOURCE
#include "dbgbar.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <signal.h>
#include <time.h>
#include <sys/epoll.h>
#include <sys/timerfd.h>
#include <sys/stat.h>
#include <linux/input.h>

/* Linux input key codes (from linux/input-event-codes.h) */
#ifndef KEY_MENU
#define KEY_MENU 139
#endif
#define KEY_9    10   /* KEY_9 scancode on standard keymap */

#define CONF_PATH "/data/dbgbar.conf"
#define INPUT_DEV "/dev/input/event0"   /* "dreambox advanced remote control" */

static volatile sig_atomic_t s_run = 1;
static void on_sig(int x){ (void)x; s_run = 0; }

/* --- hidden shortcut state machine: MENU,9,9,9,9 --- */
static int   s_seq_stage = 0;          /* 0=idle,1=saw MENU,2..5=9s */
static time_t s_seq_last = 0;
static void seq_feed(int keycode, config_t *cfg)
{
    time_t now = time(NULL);
    if (s_seq_stage > 0 && (now - s_seq_last) > 3) s_seq_stage = 0; /* timeout */
    s_seq_last = now;

    if (keycode == KEY_MENU) { s_seq_stage = 1; return; }
    if (s_seq_stage >= 1 && keycode == KEY_9) {
        s_seq_stage++;
        if (s_seq_stage >= 5) {          /* MENU + 9 9 9 9 complete */
            cfg->eng_mode = !cfg->eng_mode;
            s_seq_stage = 0;
        }
        return;
    }
    s_seq_stage = 0;                     /* any other key resets */
}

static void arm_timer(int tfd, int sec)
{
    struct itimerspec its;
    memset(&its, 0, sizeof its);
    its.it_value.tv_sec    = sec > 0 ? sec : 1;
    its.it_interval.tv_sec = sec > 0 ? sec : 1;
    timerfd_settime(tfd, 0, &its, NULL);
}

static time_t conf_mtime(void)
{
    struct stat st;
    if (stat(CONF_PATH, &st) == 0) return st.st_mtime;
    return 0;
}

int main(void)
{
    config_t cfg;
    config_load(&cfg, CONF_PATH);
    time_t cfg_mtime = conf_mtime();

    if (!cfg.enabled) return 0;          /* disabled -> do nothing, no overhead */

    if (render_init() != 0) {
        /* OSD layer unavailable: fail quietly so we never disturb the UI */
        return 0;
    }

    signal(SIGTERM, on_sig);
    signal(SIGINT,  on_sig);
    signal(SIGPIPE, SIG_IGN);

    /* provider init hooks */
    for (int i = 0; i < g_provider_count; i++)
        if (g_providers[i]->init) g_providers[i]->init();

    int ep  = epoll_create1(0);
    int tfd = timerfd_create(CLOCK_MONOTONIC, 0);
    arm_timer(tfd, cfg.refresh_sec);

    int ifd = open(INPUT_DEV, O_RDONLY | O_NONBLOCK);

    struct epoll_event ev;
    ev.events = EPOLLIN; ev.data.fd = tfd;
    epoll_ctl(ep, EPOLL_CTL_ADD, tfd, &ev);
    if (ifd >= 0) { ev.data.fd = ifd; epoll_ctl(ep, EPOLL_CTL_ADD, ifd, &ev); }

    metrics_t m;
    memset(&m, 0, sizeof m);
    int blink = 0;

    struct epoll_event events[4];
    while (s_run) {
        int nfd = epoll_wait(ep, events, 4, -1);   /* blocks at ~0% CPU */
        if (nfd < 0) { if (errno == EINTR) continue; break; }

        for (int e = 0; e < nfd; e++) {
            int fd = events[e].data.fd;

            if (fd == tfd) {
                uint64_t exp; if (read(tfd, &exp, sizeof exp) < 0) {/*ignore*/}

                /* hot-reload config if file changed */
                time_t mt = conf_mtime();
                if (mt != cfg_mtime) {
                    int prev_eng = cfg.eng_mode;
                    int prev_refresh = cfg.refresh_sec;
                    config_load(&cfg, CONF_PATH);
                    cfg.eng_mode = prev_eng;               /* keep live toggle */
                    cfg_mtime = mt;
                    if (!cfg.enabled) { render_clear(); }
                    if (cfg.refresh_sec != prev_refresh) arm_timer(tfd, cfg.refresh_sec);
                }
                if (!cfg.enabled) continue;

                /* sample all providers into the shared snapshot */
                for (int i = 0; i < g_provider_count; i++)
                    g_providers[i]->sample(&m, &cfg);

                blink ^= 1;                 /* 1 Hz-ish blink phase */
                render_bar(&m, &cfg, blink);
            }
            else if (fd == ifd) {
                struct input_event iev;
                ssize_t r;
                while ((r = read(ifd, &iev, sizeof iev)) == (ssize_t)sizeof iev) {
                    if (iev.type == EV_KEY && iev.value == 1)   /* key press */
                        seq_feed(iev.code, &cfg);
                }
            }
        }
    }

    render_close();
    if (ifd >= 0) close(ifd);
    close(tfd);
    close(ep);
    return 0;
}

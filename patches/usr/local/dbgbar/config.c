/*
 * config.c -- load/parse /data/dbgbar.conf (simple key=value, no allocations).
 * Missing file => sensible defaults (bar enabled, 1s, normal style, all widgets).
 * Unknown keys are ignored. Values are clamped to valid ranges.
 */
#define _GNU_SOURCE
#include "dbgbar.h"
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

void config_defaults(config_t *c)
{
    c->enabled     = 1;
    c->eng_mode    = 0;
    c->refresh_sec = 1;
    c->style       = STYLE_NORMAL;
    c->w_temp = c->w_cpu = c->w_ram = c->w_uptime = 1;
    c->w_vdec = c->w_adec = c->w_dmx = 1;
    c->w_signal = c->w_codec = c->w_res = c->w_net = c->w_gadget = c->w_storage = 1;
}

static int getbool(const char *v) { return (atoi(v) != 0 || v[0]=='y' || v[0]=='Y' || v[0]=='t' || v[0]=='T'); }

void config_load(config_t *c, const char *path)
{
    config_defaults(c);
    char buf[2048];
    int n = slurp(path, buf, sizeof buf);
    if (n <= 0) return;

    char *save = NULL;
    for (char *line = strtok_r(buf, "\n", &save); line; line = strtok_r(NULL, "\n", &save)) {
        while (*line==' '||*line=='\t') line++;
        if (*line=='#' || *line==';' || *line==0) continue;
        char *eq = strchr(line, '=');
        if (!eq) continue;
        *eq = 0;
        char *key = line, *val = eq + 1;
        /* trim trailing spaces on key */
        char *ke = key + strlen(key);
        while (ke > key && (ke[-1]==' '||ke[-1]=='\t')) *--ke = 0;
        while (*val==' '||*val=='\t') val++;

        if      (!strcmp(key,"enabled"))     c->enabled = getbool(val);
        else if (!strcmp(key,"eng_mode"))    c->eng_mode = getbool(val);
        else if (!strcmp(key,"refresh_sec")) {
            int r = atoi(val);
            c->refresh_sec = (r==1||r==2||r==5||r==10) ? r : 1;
        }
        else if (!strcmp(key,"style")) {
            if      (!strcmp(val,"compact"))   c->style = STYLE_COMPACT;
            else if (!strcmp(val,"developer")) c->style = STYLE_DEVELOPER;
            else                               c->style = STYLE_NORMAL;
        }
        else if (!strcmp(key,"w_temp"))    c->w_temp = getbool(val);
        else if (!strcmp(key,"w_cpu"))     c->w_cpu = getbool(val);
        else if (!strcmp(key,"w_ram"))     c->w_ram = getbool(val);
        else if (!strcmp(key,"w_uptime"))  c->w_uptime = getbool(val);
        else if (!strcmp(key,"w_vdec"))    c->w_vdec = getbool(val);
        else if (!strcmp(key,"w_adec"))    c->w_adec = getbool(val);
        else if (!strcmp(key,"w_dmx"))     c->w_dmx = getbool(val);
        else if (!strcmp(key,"w_signal"))  c->w_signal = getbool(val);
        else if (!strcmp(key,"w_codec"))   c->w_codec = getbool(val);
        else if (!strcmp(key,"w_res"))     c->w_res = getbool(val);
        else if (!strcmp(key,"w_net"))     c->w_net = getbool(val);
        else if (!strcmp(key,"w_gadget"))  c->w_gadget = getbool(val);
        else if (!strcmp(key,"w_storage")) c->w_storage = getbool(val);
    }
}

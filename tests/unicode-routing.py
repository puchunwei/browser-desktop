"""Compile the actual patched xrdp functions with observable transport stubs.

Usage: python3 unicode-routing.py XRDP_WM_C XRDP_TYPES_H PRIVATE_OUTPUT_DIR
The source must be from the pinned xrdp tree after applying our patches.
"""
from pathlib import Path
import re
import subprocess
import sys

source, header, output = map(Path, sys.argv[1:])
output.mkdir(parents=True, exist_ok=True)
text = source.read_text()


def function(name):
    match = re.search(r"static (?:int|char32_t)\n" + name + r"\(", text)
    if not match:
        raise ValueError(f"missing function {name}")
    opening = text.index("{", match.start())
    depth = 1
    end = opening + 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[match.start():end]


field = re.search(r"unsigned char unicode_routes\[[^;]+;", header.read_text())
if not field:
    raise ValueError("missing per-connection Unicode route state")
prefix = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <uchar.h>
#define KBD_FLAG_UP 0x8000
#define KBD_FLAG_DOWN 0
#define KBD_FLAG_EXT 0x0100
#define XR_RDP_SCAN_LSHIFT 42
#define XR_RDP_SCAN_ALT 56
#define XR_MIN_KEY_CODE 8
#define XR_MAX_KEY_CODE 256
#define UIS_ACTIVE 2
#define TRANS_STATUS_UP 1
#define IS_HIGH_SURROGATE(x) ((x) >= 0xd800 && (x) <= 0xdbff)
#define IS_LOW_SURROGATE(x) ((x) >= 0xdc00 && (x) <= 0xdfff)
#define C32_FROM_SURROGATE_PAIR(l,h) (0x10000 + (((h)-0xd800)<<10) + (l)-0xdc00)
struct key { char32_t chr; };
struct trans { int status; };
struct mm { struct trans *chan_trans; };
struct info { int unicode_input_support; };
struct xrdp_wm {
    int keys[256], last_high_surrogate_key_up, last_high_surrogate_key_down;
    struct mm *mm;
    struct info *client_info;
    struct { struct key keys_noshift[256], keys_shift[256],
             keys_altgr[256], keys_shiftaltgr[256]; } keymap;
    ROUTE_FIELD
};
static unsigned native_down, native_up, commits;
static char32_t chars[128];
static int xrdp_wm_key(struct xrdp_wm *wm, int flags, int scan) {
    scan %= 128;
    if (flags & KBD_FLAG_UP) { ++native_up; wm->keys[scan] = 0; }
    else { ++native_down; wm->keys[scan] = 1; }
    return 0;
}
static int xrdp_mm_send_unicode_to_chansrv(struct mm *mm, int down, char32_t c) {
    assert(mm->chan_trans && mm->chan_trans->status == TRANS_STATUS_UP);
    if (down) { assert(commits < 128); chars[commits++] = c; }
    return 0;
}
'''.replace("ROUTE_FIELD", field.group())
suffix = r'''
static void send(struct xrdp_wm *wm, int up, char32_t c) {
    int flags = up ? KBD_FLAG_UP : 0;
    if (c > 0xffff) {
        xrdp_wm_key_unicode(wm, flags, 0xd800 + ((c-0x10000)>>10));
        xrdp_wm_key_unicode(wm, flags, 0xdc00 + ((c-0x10000)&1023));
    } else { xrdp_wm_key_unicode(wm, flags, c); }
}
int main(void) {
    struct trans channel = { TRANS_STATUS_UP };
    struct mm mm = { &channel };
    struct info info = { UIS_ACTIVE };
    struct xrdp_wm wm = { .mm = &mm, .client_info = &info };
    wm.keymap.keys_noshift[38].chr = 'a';
    wm.keymap.keys_shift[38].chr = 'A';
    wm.keymap.keys_altgr[39].chr = 0xe9;
    wm.keymap.keys_shiftaltgr[40].chr = 0xc9;
    char32_t mixed[] = {0x4e2d, 'a', '1', 0x6587, 'A', 0x1f600, 0x20000, 0x10ffff};
    for (unsigned i=0; i<sizeof(mixed)/sizeof(*mixed); ++i) {
        send(&wm, 0, mixed[i]); send(&wm, 1, mixed[i]);
        assert(chars[i] == mixed[i]);
    }
    assert(native_down == 0 && native_up == 0);
    int mods[] = {0x1d, XR_RDP_SCAN_ALT, 0x5b, 0x5c};
    char32_t mapped[] = {'a', 'A', 0xe9, 0xc9};
    int scans[] = {30, 30, 31, 32};
    for (unsigned i=0; i<4; ++i) {
        for (unsigned j=0; j<4; ++j) {
            unsigned before = commits;
            wm.keys[mods[i]] = 1;
            send(&wm, 0, mapped[j]);
            assert(wm.keys[scans[j]]);
            wm.keys[mods[i]] = 0;
            send(&wm, 0, mapped[j]); /* Repeat after modifier release. */
            send(&wm, 1, mapped[j]);
            assert(commits == before);
            assert(!wm.keys[30] && !wm.keys[31] && !wm.keys[32]);
            assert(!wm.keys[XR_RDP_SCAN_LSHIFT] && !wm.keys[XR_RDP_SCAN_ALT]);
        }
    }
    unsigned before = native_down;
    send(&wm, 0, 'a');
    wm.keys[0x1d] = 1;
    send(&wm, 0, 'a'); /* An IBus repeat keeps its original route, too. */
    send(&wm, 1, 'a');
    wm.keys[0x1d] = 0;
    assert(native_down == before && !wm.keys[30]);
    wm.keys[0x1d] = 1;
    send(&wm, 0, 'a');
    channel.status = 0;
    wm.keys[0x1d] = 0;
    send(&wm, 1, 'a'); /* Native release survives a lost chansrv. */
    assert(!wm.keys[30]);
    channel.status = TRANS_STATUS_UP;
    send(&wm, 0, 'A');
    wm.keys[XR_RDP_SCAN_LSHIFT] = 1;
    channel.status = 0;
    send(&wm, 1, 'A');
    assert(wm.keys[XR_RDP_SCAN_LSHIFT]); /* No unrelated native Shift release. */
    wm.keys[XR_RDP_SCAN_LSHIFT] = 0;
    for (unsigned i=0; i<sizeof(wm.unicode_routes); ++i) assert(wm.unicode_routes[i] == 0);
    for (unsigned i=0; i<256; ++i) assert(wm.keys[i] == 0);
    puts("PASS: actual xrdp functions preserve Unicode order and paired routes across modifier/repeat/channel changes");
    return 0;
}
'''
c_file = output / "unicode-routing.c"
c_file.write_text(prefix + function("get_unicode_character") + "\n" +
                  function("xrdp_wm_key_unicode") + suffix)
binary = output / "unicode-routing"
subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-fsanitize=address,undefined",
                str(c_file), "-o", str(binary)], check=True)
subprocess.run([str(binary)], check=True)

"""Compile the real patch helpers and exercise truncated RDP fields and IPC.

Usage: python3 tests/display-scale-c.py PATCHED_XRDP_SOURCE PRIVATE_OUTPUT_DIR
Requires a C compiler, ASan and UBSan. Uses synthetic clients only.
"""
import pathlib
import subprocess
import sys

source, output = map(pathlib.Path, sys.argv[1:])
output.mkdir(parents=True, exist_ok=True)


def function(path, name):
    text = path.read_text()
    start = text.index('\n' + name + '(')
    start = text.rfind('\nstatic ', 0, start) + 1
    opening = text.index('{', start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]


try:
    parser = function(source / 'libxrdp/xrdp_sec.c', 'xrdp_sec_read_desktop_scale')
    bounder = function(source / 'libxrdp/xrdp_sec.c', 'xrdp_sec_process_core_block')
    sender = function(source / 'xup/xup.c', 'send_desktop_scale')
    sanitizer = function(source / 'libxrdp/libxrdp.c', 'sanitise_extended_monitor_attributes')
except ValueError:
    raise SystemExit('FAIL: density parser/sender is not implemented')

prefix = r'''
#define _GNU_SOURCE
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>
#define LOG(...) ((void)0)
#define ORIENTATION_LANDSCAPE 0
#define ORIENTATION_PORTRAIT 90
#define ORIENTATION_LANDSCAPE_FLIPPED 180
#define ORIENTATION_PORTRAIT_FLIPPED 270
struct stream { unsigned char *p, *end; };
#define s_check_rem(s,n) ((s)->end - (s)->p >= (n))
#define in_uint32_le(s,x) do { (x) = (unsigned)(s)->p[0] | (unsigned)(s)->p[1]<<8 | (unsigned)(s)->p[2]<<16 | (unsigned)(s)->p[3]<<24; (s)->p += 4; } while(0)
struct monitor_info {
    unsigned int physical_width, physical_height, orientation;
    unsigned int desktop_scale_factor, device_scale_factor;
};
struct xrdp_client_info {
    unsigned int session_desktop_scale, session_device_scale;
    char hostname[256]; int client_os_major, client_os_minor;
};
struct mod { struct xrdp_client_info client_info; };
#define CLIENT_MONITOR_DATA_MAXIMUM_MONITORS 16
'''
main = r'''
int main(void) {
    struct xrdp_client_info ci = {0};
    unsigned char data[8] = {200,0,0,0,100,0,0,0};
    struct stream s;
    for (int n = 0; n < 8; ++n) {
        ci.session_desktop_scale = 999; ci.session_device_scale = 999;
        s = (struct stream){data,data+n};
        xrdp_sec_read_desktop_scale(&s,&ci);
        assert(ci.session_desktop_scale == 0 && ci.session_device_scale == 0);
    }
    /* Bytes from the following GCC block must not complete a truncated pair. */
    struct xrdp_sec sec = {0};
    s = (struct stream){data,data+8};
    assert(xrdp_sec_process_core_block(&sec,&s,4)==0);
    assert(sec.ci.session_desktop_scale==0);
    s = (struct stream){data,data+8};
    assert(xrdp_sec_process_core_block(&sec,&s,8)==0);
    assert(sec.ci.session_desktop_scale==200);
    assert(xrdp_sec_process_core_block(&sec,&s,9)==1);
    unsigned desktops[] = {0,99,100,150,200,300,500,501,0xffffffff};
    unsigned devices[] = {0,100,140,180,200,0xffffffff};
    for (unsigned i=0;i<sizeof(desktops)/sizeof(*desktops);i++)
    for (unsigned j=0;j<sizeof(devices)/sizeof(*devices);j++) {
        unsigned d=desktops[i], v=devices[j];
        for(int k=0;k<4;k++) { data[k]=d>>(8*k); data[k+4]=v>>(8*k); }
        s = (struct stream){data,data+8};
        xrdp_sec_read_desktop_scale(&s,&ci);
        int valid=d>=100 && d<=500 && (v==100||v==140||v==180);
        assert(ci.session_desktop_scale==(valid?d:0));
        assert(ci.session_device_scale==(valid?v:0));
    }
    struct monitor_info monitor = {0};
    sanitise_extended_monitor_attributes(&monitor);
    assert(monitor.desktop_scale_factor==0 && monitor.device_scale_factor==0);
    monitor=(struct monitor_info){300,200,0,200,200};
    sanitise_extended_monitor_attributes(&monitor);
    assert(monitor.desktop_scale_factor==0 && monitor.device_scale_factor!=0);
    monitor=(struct monitor_info){300,200,0,200,100};
    sanitise_extended_monitor_attributes(&monitor);
    assert(monitor.desktop_scale_factor==200 && monitor.device_scale_factor==100);

    int receiver = socket(AF_UNIX, SOCK_DGRAM | SOCK_NONBLOCK, 0);
    struct sockaddr_un address={.sun_family=AF_UNIX};
    strcpy(address.sun_path, SCALE_SOCKET);
    unlink(SCALE_SOCKET);
    assert(bind(receiver,(struct sockaddr*)&address,sizeof(address))==0);
    struct mod mod={0};
    memset(mod.client_info.hostname,'x',sizeof(mod.client_info.hostname));
    mod.client_info.session_desktop_scale=200; mod.client_info.session_device_scale=100;
    mod.client_info.client_os_major=6;
    struct monitor_info monitors[16];
    for (int i=0;i<16;i++) monitors[i]=monitor;
    send_desktop_scale(&mod,"connect",1600,1000,16,monitors);
    char buffer[4097]={0};
    int length=recv(receiver,buffer,4096,0);
    assert(length>0 && length<4096);
    assert(strstr(buffer,"\"kind\":\"connect\"") && strstr(buffer,"\"desktop\":200"));
    assert(strstr(buffer,"\"monitors\":[[200,100]"));
    assert(!strstr(buffer,"xxx")); /* raw client string never leaves in printable form */
    /* Full socket queue must not block the RDP worker. */
    alarm(2);
    for(int i=0;i<100;i++) send_desktop_scale(&mod,"resize",640,900,1,monitors);
    close(receiver); unlink(SCALE_SOCKET);
    send_desktop_scale(&mod,"connect",640,900,0,NULL);
    alarm(0);
    puts("PASS: truncated/pair parsing, monitor provenance, bounded nonblocking IPC");
    return 0;
}
'''
# Substitute only the fixed IPC endpoint for this disposable process test.
endpoint = str(output.resolve() / 'control.sock')
assert len(endpoint.encode()) < 108, 'use an output path shorter than AF_UNIX sun_path'
sender = sender.replace('"/run/xrdp/display-scale/control.sock"', 'SCALE_SOCKET')
stub = '''
struct xrdp_sec { struct xrdp_client_info ci; };
static int xrdp_sec_process_mcs_data_CS_CORE(struct xrdp_sec *self, struct stream *s) { xrdp_sec_read_desktop_scale(s, &self->ci); return 0; }
'''
program = prefix + '\n#define SCALE_SOCKET "' + endpoint + '"\n' + parser + '\n' + stub + bounder + '\n' + sanitizer + '\n' + sender + '\n' + main
path = output / 'density.c'
path.write_text(program)
binary = output / 'density'
subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined', '-g', str(path), '-o', str(binary)], check=True)
subprocess.run([str(binary)], check=True)

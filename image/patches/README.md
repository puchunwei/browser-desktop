# RDP compatibility patches

## Wide legacy bitmap updates

`large-bitmap.patch` is a local fix against pinned xrdp 0.10.6.1. Its legacy
32-bit planar compressor uses 4096-pixel planes. A scanline wider than that
overlaps adjacent planes before the row-count limit is checked, causing color
corruption. A wide row can also exceed the 16 KiB bitmap update budget. Retina
viewers can request desktops wider than 4096 pixels even on a 4K monitor.

The patch splits inputs wider than 2048 pixels before compression, into blocks
at most 2048 by 64 pixels. The temporary copy is bounded to 512 KiB at 32 bpp;
each block retains its destination coordinates and visible crop. Both compressed
and uncompressed legacy updates use the existing sender for the bounded blocks.
Negotiated GFX encoding is unaffected. This is not an upstream backport.

`tests/rdp-client/large-display.py` checks decoded colors across the 4096-pixel
boundary and the desktop edges, using a disposable desktop with the synthetic
rotation target maximized. Run it with a 32-bit legacy connection; omit the
FreeRDP `gfx` option entirely because its presence enables GFX even when spelled
`-gfx` in FreeRDP 3.15. Evidence must include the negotiated server path.

## Rotation while output is suppressed

`queued-resize.patch` is a local compatibility fix against the same pinned
0.10.6.1 source below. Mobile viewers can temporarily suppress display updates
while rotating. The original `dynamic_monitor_data()` discards a monitor layout
in that interval, leaving the server at the old dimensions after the viewer
resumes. Reconnecting negotiates a fresh layout and hides the failure.

The patch keeps the existing validated/coalescing resize queue. It queues layouts
while output is suppressed, defers starting the next resize, and wakes the queue
when output resumes. An already active resize may finish. Suppression still
prevents ordinary display output, and waiting does not repeatedly signal the
resize event. This patch is maintained locally, not an upstream backport.

The real-client regression unmaps a FreeRDP window (Suppress Output), resizes it
while unmapped, then maps it again. It checks desktop pixels at the requested
portrait/landscape dimensions and clicks each of four colored targets through
RDP. Only trusted pointer events change the target color; the test requires a
change at the exact clicked location and restores each target. It also covers
ordinary visible resizes within the same connection.

## Unicode input backport

`xrdp-0.10.6.1-ibus-unicode.patch` keeps the pinned xrdp release and backports
the upstream Unicode → chansrv → IBus path. Version 0.10.6.1 otherwise only
looks up Unicode characters in its existing keyboard map and drops unmapped
characters, including Chinese with the US keyboard map. Installing a remote
pinyin engine alone does not implement a phone keyboard's Unicode commits.

Sources:

- [xrdp v0.10.6.1 release tarball](https://github.com/neutrinolabs/xrdp/releases/download/v0.10.6.1/xrdp-0.10.6.1.tar.gz),
  SHA-256 `2f7beb5a3b2529c8d72dc0df9b8cdca31ab0e0c14d1e3421210f5e6ec0ab3b75`.
- [Upstream PR 3058](https://github.com/neutrinolabs/xrdp/pull/3058), merged as
  `98d0003715be1e0693817f49925d48b558df69bb`.
- [Upstream PR 3090](https://github.com/neutrinolabs/xrdp/pull/3090), merged as
  `5c4278ccb16c5cce7134face70b13c061217537e`.

The adaptation omits upstream CI changes, refreshes the patch context for
0.10.6.1, appends the Unicode state after the existing `vmconnect` field, and
removes committed character values from its debug messages. It preserves
existing field offsets. The new input source retains its upstream
Apache 2.0 license header. This is an explicit backport: unpatched 0.10.6.1
does not have a working `--enable-ibus` build option.

The local lifecycle adaptation retains one IBus bus, factory and GLib loop for
the lifetime of chansrv. A viewer disconnect restores the previous engine and
frees its saved name, without spawning another loop on reconnect. Engine
references are protected across threads; factory and engine readiness waits
are bounded. A lost IBus bus terminates chansrv explicitly instead of leaving
dangling shared pointers. It also distinguishes IBus's fake desktop focus
from a real application. For a fresh Chromium GTK3 XIM context, which is only
bound on a native key event, chansrv sends one non-text Shift press/release
through XTest and waits for real application focus before committing. It skips
the synthetic pair if Shift is already held. This requires `libxtst-dev` at
build time and `libxtst6` at runtime. These adaptations need the reconnect
regression checks below in addition to the first successful input.

Apply this patch and the sibling legacy pointer patch to the clean source,
run `autoreconf -fi`, then configure with `--enable-ibus` plus the existing
Debian build options. Build and install all xrdp binaries and shared libraries
together. Use `--prefix=/usr --sysconfdir=/etc --localstatedir=/var
--libdir=/usr/lib/x86_64-linux-gnu --libexecdir=/usr/lib/x86_64-linux-gnu
--with-socketdir=/run/xrdp/sockdir`. The build appends `/xrdp` to the library and
libexec directories. Preserve the installed Debian configuration and PAM files,
including `runtime_user=xrdp`, `runtime_group=xrdp`, and
`SessionSockdirGroup=xrdp`.

The desktop user starts IBus with its XIM bridge before Openbox publishes the
session. The independently supervised Chrome runs as the same desktop user and uses
`GTK_IM_MODULE=xim`, `XMODIFIERS=@im=ibus`, and a UTF-8 locale. This uses the
existing shared X server through XIM instead of the session's D-Bus. Chansrv and IBus run as the same desktop user; libibus can discover the
address using that user's display-specific address file even though chansrv
was started before the window manager's session D-Bus.

## Remote pinyin and lazy Unicode engine

`lazy-unicode-engine.patch` is a local change applied after the four patches above
(SHA-256 `40983a9895eed6db63b6fb3ae0529f9f084f1ccd191ef42eea671a472c34b20f`, not upstream). On reconnect the Unicode backport
switched the IBus global engine to `XrdpIme` for the whole viewer session. `XrdpIme`
passes every key through, so a viewer that sends physical-key scancodes (Jump Desktop
with a Mac or PC keyboard) could not use a remote input method. Reconnects now defer
the switch to the first Unicode character, as the first connection already did; the
previous engine is still recorded then and restored on viewer disconnect.

The image installs `ibus-libpinyin` and selects it as the session engine. Its gschema
override starts pinyin in English mode, so Shift switches Chinese on and off, and the
IBus panel draws the candidate window. Phone keyboards keep using RDP Unicode input.
`tests/rdp-client/pinyin-input.py` types `nihao` with Unicode input disabled and checks
that the first candidate is committed after a preceding Unicode connection.

## Isolated input verification

`ordered-unicode.patch` is a local follow-up: normal printable Unicode uses
the same IBus channel for ASCII and Chinese, so synchronous keymap events cannot
overtake Chinese commits. Ctrl/Alt/Super shortcuts retain the keymap path.
Two bits per Unicode scalar retain each key's chosen path through repeats and
release, including when a modifier is released before the character. The state
is appended to the window manager and uses 272 KiB per connection. Control
characters and separate scancode events retain their existing behavior; this
does not guarantee ordering between those events and asynchronous IBus commits.

To check the actual patched C functions, run
`python3 tests/unicode-routing.py PATH/xrdp_wm.c PATH/xrdp_types.h PRIVATE_OUTPUT_DIR`
with a C compiler supporting AddressSanitizer and UndefinedBehaviorSanitizer.
The check exercises modifier/repeat/release changes, transport loss, all four
keymap branches and surrogate pairs. Full RDP verification below remains required.

Use a disposable container with a fresh profile and a synthetic credential.
Create its synthetic page with `tests/unicode-target.mjs open PORT STATE`.
Run `tests/rdp-client/unicode-input.py HOST RDP_PORT` inside the existing RDP
client image under Xvfb, with only that synthetic credential mounted at `/pw`
and a private evidence directory at `/evidence`. Then run
`tests/unicode-target.mjs check PORT STATE` and close the target.

The client uses FreeRDP 3.15's `/kbd:pipe` facility, which converts UTF-8 to
UTF-16 and invokes `freerdp_input_send_unicode_keyboard_event` for every code
unit. Clipboard redirection is disabled. CDP creates the fixture and reads its
value; it never inserts text. The default assertion requires exactly `中A1文B2输入C3测试D4`
and trusted DOM input events. The unpatched pinned image receives only `A1`.
Start the first round with a fresh Chromium process and send the Chinese
string directly, without a preceding ASCII or modifier key. Repeat with a new
target after a viewer disconnect to check session reuse; also
pass `中文😀𠀀A1` to both the client and the check command to cover UTF-16
surrogate pairs. With `VERIFY_SHORTCUTS=1`, the disposable fixture additionally
checks native Ctrl+A/C/V and a native Ctrl combined with a FIFO Unicode letter.
Native shortcuts use a separate `/kbd:unicode:off` connection. The Unicode
connection uses the FIFO with Unicode enabled, including its mixed modifier
test. This optional check overwrites only the
fixture's clipboard and must not be enabled in the owner's session.
A separate iPhone test remains necessary to verify the actual
client's keyboard mode and candidate commit behavior.

## Negotiated desktop density

`display-scale.patch` is a local patch against pinned xrdp 0.10.6.1, applied
last. It consumes the optional CS_CORE desktop/device scale pair only when
both fields are present and valid (desktop 100–500; device 100, 140 or 180).
The two fields are appended after existing private fields in client_info;
xorgxrdp's shared field offsets and monitor layouts do not change.

The authenticated Xorg module emits bounded, nonblocking Unix datagrams on
initial client-info exchange and successful monitor resize submission. Messages
contain scale pairs, pixel geometry and a bounded hex-encoded client preference
hint. The session controller accepts events only from the xrdp UID using Linux
SCM_CREDENTIALS and hashes hints before persistence. Hints are never identities
or access-control decisions. An empty hint cannot create a shared preference.
A missing controller or full socket queue never blocks the RDP path.

Upstream normalizes absent/invalid monitor scale pairs to 100/100, making them
indistinguishable from an explicit 100% request. The patch preserves absent
pairs as 0/0 and marks invalid pairs as 0/1. The pinned xorgxrdp 0.10.5 sources
do not consume either scale field; revisit this compatibility assumption on
upgrades. Physical-size and orientation sanitizing remains upstream behavior.
Valid coherent monitor metadata takes priority over CS_CORE; mixed or partially
invalid monitor densities explicitly fall back to 100% until a manual choice.
No width threshold or device-model guess is used.

`display-scale.py` supervises xsettingsd as the desktop user. Chrome waits for a
live XSettings selection before starting. Baseline Xft/DPI is 98304, and a
200% desktop uses 196608 with Gdk/WindowScalingFactor 2 and UnscaledDPI 98304.
Fractional 150% uses WindowScalingFactor 1 and DPI/UnscaledDPI 147456. These
settings request a dynamic whole-UI redraw, not browser/page restart or page
zoom. Cursor theme size is requested separately; classic RDP cursor transport,
IBus candidate windows and pointer coordinates still require real-client tests.

The local CLI is `display-scale.py set auto|100|150|200|300` and
`display-scale.py status`. Status exposes only effective scale, source, pixel
geometry and daemon readiness. It returns nonzero while the service is absent
or recovering. Ctrl+Alt+S opens the Openbox presets above a maximized Chrome;
right-clicking exposed desktop opens the same menu, whereas right-clicking a
webpage remains Chrome's own menu. Phone keyboard access and Jump gestures must
be documented and checked on the actual device.

Explicit preferences live in `.browser-desktop-scale.json` in the configured
browser profile directory, separate from Chrome's Preferences. The bounded
file stores only hashed hints and scale choices. Auto deletes that client's
manual preference. Current connection state is private in `/run/browser-desktop`
and survives controller restart; xsettingsd crashes are retried every two
seconds without restarting Chrome. Duplicate display events do not reload it.

Run `python3 tests/test-display-scale.py` for policy checks. After applying the
patch chain to the pinned source, run
`python3 tests/display-scale-c.py PATCHED_XRDP_SOURCE PRIVATE_OUTPUT_DIR` for
ASan/UBSan checks of the actual C parser, monitor sanitizing and datagram sender.
Use a short private output directory to fit the Unix socket path length.
Real running-Chrome/negotiated-RDP checks remain required, especially fractional
150%, native phone 300%, controller recovery, trusted click coordinates and
page/process preservation. FreeRDP does not establish Jump/VNC visual parity.


## Maximized Chrome on narrow desktops

`openbox-maximized-chrome.patch` modifies Debian Openbox 3.6.1-12's
`client_try_configure()`. A maximized Chrome main window can advertise a 500 DIP
minimum, exceeding a 390 DIP phone desktop at 300%. Stock Openbox reapplies that
minimum after selecting the maximized workarea and clips the renderer and toolbar.
The patch caps the local minimum constraints to the selected workarea only for
fully maximized, normal, nontransient, nonprompt `Google-chrome` windows. It leaves
application hints, maximum constraints, other applications and ordinary windows
alone. The real regression requires renderer width, X11 window geometry, toolbar
and menu access, trusted right-edge clicks and return to Mac in the same browser.

The Dockerfile reproduces the Debian patch series, regenerates autotools files
with `autoreconf -fi` (needed for the Debian Xi dependency and autostart target),
and builds with the same hardening flags as xrdp. Only the main executable replaces
the packaged binary; packaged libraries and configuration remain installed.
Sources are available directly from Debian:

- [Openbox 3.6.1 source](https://deb.debian.org/debian/pool/main/o/openbox/openbox_3.6.1.orig.tar.gz),
  SHA-256 `8b4ac0760018c77c0044fab06a4f0c510ba87eae934d9983b10878483bde7ef7`.
- [Debian 3.6.1-12 patchset](https://deb.debian.org/debian/pool/main/o/openbox/openbox_3.6.1-12.debian.tar.xz),
  SHA-256 `cf7c2fe6e9f31a46c2955d78ea8b301072742e954e16bc4d7f86b6b5cf312775`.

Extract the upstream archive, extract the Debian archive inside it, apply every
entry of `debian/patches/series` followed by the local patch, then run the configure
and make commands in `image/Dockerfile`. Debian's GPL license and copyright remain
at `/usr/share/doc/openbox/copyright`; this recipe and local patch ship under
`/usr/share/doc/browser-desktop/patches/`.

Openbox does not consume Chrome's XSettings density. The desktop controller derives
MenuItem/MenuHeader font sizes from the immutable image rc.xml into the dedicated
user's Openbox configuration and reconfigures the same WM when the content changes.
Repeated density events and controller recovery do not compound fonts or repeatedly
reconfigure. The real matrix checks menu crops and pointer selection at fractional,
200% and 300% density, and restores the 100% menu when returning to Mac.
Menu notification is bounded to two seconds. A timeout or failed notification does
not discard the authenticated connection or its XSettings update. The controller
retries through its existing readiness loop; a digest recorded only after success
also lets a restarted controller retry unchanged XML that was never notified.

# Browser Navigation Authority V1

## Purpose

LocalAI Desktop has an internal browser and document-viewer workspace. Navigation must
not escape to external applications implicitly.

V1 adds an explicit host-owned browser navigation policy.

## Core policy

Automatic navigation stays inside LocalAI Desktop.

Allowed automatic schemes:

- http
- https
- file, only when the local target exists

Blocked automatic schemes include:

- javascript
- data
- mailto
- ftp
- unknown/custom schemes

Blocked schemes are not handed to the operating system.

## Navigation sources

### Initial load

HTTP/HTTPS and valid local HTML/file resources load in the current LocalAI BrowserView.

### Address bar

A typed address remains in the current LocalAI browser tab. A bare hostname is normalized
to HTTPS.

### Normal page link

Normal links remain in the same Browser tab.

For the QTextBrowser fallback this is explicitly enforced as same-tab navigation, matching
the WebEngine behavior.

### New-window / target=_blank

Authorized HTTP/HTTPS or local-file targets open a new LocalAI workspace resource tab.

They do not launch Chrome, Edge, mail clients, or other external handlers.

### Chat and artifact links

Chat links and artifact/resource links use MainWindow._open_resource and therefore the
same navigation authority before a browser resource tab is created.

### External button

The BrowserView External control is the only intentional browser escape path in V1.

A target may be sent to QDesktopServices only when:

1. the user explicitly clicked External; and
2. the scheme is HTTP, HTTPS, or an existing local file.

## WebEngine enforcement

When QtWebEngine is available, LocalAI installs an authority-aware QWebEnginePage and
checks main-frame navigation through acceptNavigationRequest.

Subresources are not treated as user navigation and remain available to the loaded page.

New-window requests are separately checked by the same authority.

## Fallback enforcement

When QtWebEngine is unavailable, QTextBrowser anchor clicks use the same policy.

Normal links load in the same fallback BrowserView. New resource tabs are created only
for policy decisions that explicitly request an internal tab.

## MainWindow authority

MainWindow owns one BrowserNavigationAuthority instance and passes it to BrowserView
instances.

_open_resource rejects unauthorized URL schemes before a viewer is created. Blocked
navigation sets a visible Desktop status instead of invoking an external application.

## Acceptance

V1 is accepted when:

- chat HTTP/HTTPS link opens in LocalAI;
- normal browser link stays in the same Browser tab;
- target=_blank/new-window opens a new LocalAI tab;
- address-bar bare hostname normalizes to HTTPS and stays internal;
- explicit External opens the system browser;
- javascript/data/mailto/ftp/custom schemes do not auto-launch externally;
- local HTML/artifact viewers continue to work;
- browser fallback remains functional without QtWebEngine;
- no new patch module is added;
- exact-head GitHub CI passes.

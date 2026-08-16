#!/usr/bin/env node
// npm's job here is delivery, not reimplementation. legbar is stdlib-only
// Python and stays that way; this shim only finds a Python to run it with
// and gets out of the way.
//
// npm is here because plenty of the people watching an agent fleet live in the
// node ecosystem and `npm i -g legbar` is the install they will actually run.
// Windows included: the full-screen view needs the windows-curses *pip*
// dependency (see pyproject.toml), which npm has no way to deliver -- but
// --once and --json need no curses at all, and legbar.py prints the one-line
// pip command if the TUI is asked for without it. Blocking the whole install
// via package.json's "os" field traded that sentence for npm's raw
// EBADPLATFORM, which named the problem and not the fix.
//
// There is deliberately no postinstall Python check. A failing postinstall
// would break `npm ci` in a project that merely lists legbar as a
// devDependency; a missing interpreter is a run-time problem, so it is
// reported at run time.

'use strict';

const os = require('os');
const path = require('path');
const { spawn, spawnSync } = require('child_process');

const SCRIPT = path.join(__dirname, '..', 'legbar.py');
const MIN = [3, 9]; // matches requires-python in pyproject.toml

const CANDIDATES = [['python3', []], ['python', []]];

// The py launcher ships with python.org installs; the Microsoft Store's
// `python` alias can be a stub that opens the Store instead of running, which
// probe() rejects on exit code. Last, not first: a real python/python3 on
// PATH is what the user chose.
if (process.platform === 'win32') {
  CANDIDATES.push(['py', ['-3']]);
}

const PROBE = 'import sys; print("%d.%d" % sys.version_info[:2])';

function probe(cmd, pre) {
  const r = spawnSync(cmd, pre.concat(['-c', PROBE]), {
    encoding: 'utf8',
    windowsHide: true,
  });
  if (r.error || r.status !== 0) return null;
  const m = /^(\d+)\.(\d+)/.exec((r.stdout || '').trim());
  if (!m) return null;
  return [Number(m[1]), Number(m[2])];
}

function tooOld(v) {
  return v[0] < MIN[0] || (v[0] === MIN[0] && v[1] < MIN[1]);
}

let chosen = null;
const rejected = [];

for (const [cmd, pre] of CANDIDATES) {
  const v = probe(cmd, pre);
  if (!v) continue;
  if (tooOld(v)) {
    rejected.push(`${[cmd].concat(pre).join(' ')} is ${v[0]}.${v[1]}`);
    continue;
  }
  chosen = { cmd, pre };
  break;
}

if (!chosen) {
  const names = CANDIDATES.map(([c, p]) => [c].concat(p).join(' ')).join(', ');
  process.stderr.write(
    rejected.length
      ? `legbar needs Python ${MIN.join('.')} or newer; found only: ${rejected.join(', ')}\n`
      : `legbar needs Python ${MIN.join('.')} or newer on PATH (tried: ${names})\n`
  );
  process.stderr.write('  https://www.python.org/downloads/\n');
  process.exit(127);
}

// The child owns the terminal: legbar (curses) puts it in raw mode and restores
// it on the way out. If this process died on Ctrl-C first, the shell would come
// back with the terminal still raw, so signals are swallowed here and the child
// is left to quit on its own -- which it does, q and Ctrl-C both.
for (const sig of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
  try {
    process.on(sig, () => {});
  } catch (e) {
    // not every signal exists on every platform; skip the ones that don't
  }
}

const child = spawn(chosen.cmd, chosen.pre.concat([SCRIPT], process.argv.slice(2)), {
  stdio: 'inherit',
  windowsHide: true,
});

child.on('error', (err) => {
  process.stderr.write(`legbar: could not run ${chosen.cmd}: ${err.message}\n`);
  process.exit(127);
});

child.on('exit', (code, signal) => {
  if (signal) {
    process.exit(128 + (os.constants.signals[signal] || 0));
  }
  process.exit(code === null ? 1 : code);
});
